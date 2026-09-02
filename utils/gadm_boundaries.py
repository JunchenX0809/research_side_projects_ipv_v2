"""
Load GADM administrative boundaries from local GeoJSON for Earth Engine zonal stats.

GADM is not available as a standard EE catalog layer. Country GeoJSON files live under
``data/raw/gadm/{version}/`` (see ``data/raw/gadm/README.md``).

District / province codes in export tables map from GADM ``ID_2`` / ``ID_1`` (teammate
``ISO_2`` / ``ISO_1`` in ``skills/GADM_admin_areas_v1.xlsx``). Properties are normalized
to ``ADM1_NAME``, ``ADM2_NAME``, ``ADM1_CODE``, ``ADM2_CODE`` so ``utils.adam_modis_export``
works unchanged.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.repo_paths import find_repo_root

if TYPE_CHECKING:
    import ee

# Short key -> directory name under data/raw/gadm/
GADM_VERSIONS: dict[str, str] = {
    "41": "4.1",
    "40": "4.0",
    "36": "3.6",
    "28": "2.8",
}


def gadm_geojson_path(
    iso3: str,
    level: int,
    *,
    version: str = "40",
    root: Path | None = None,
) -> Path:
    """
    Path to ``gadm{version}_{ISO3}_{level}.json`` under ``data/raw/gadm/{version_dir}/``.

    ``iso3`` is GADM ``ID_0`` (e.g. ``ZWE`` for Zimbabwe), not always ISO 3166-1 alpha-3.
    """
    if version not in GADM_VERSIONS:
        raise ValueError(f"Unknown GADM version {version!r}; expected one of {list(GADM_VERSIONS)}")
    repo = root or find_repo_root()
    version_dir = GADM_VERSIONS[version]
    filename = f"gadm{version}_{iso3.upper()}_{level}.json"
    path = repo / "data" / "raw" / "gadm" / version_dir / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"GADM GeoJSON not found: {path}\n"
            f"Download from https://geodata.ucdavis.edu/gadm/gadm{version}/json/ "
            f"(see data/raw/gadm/README.md)."
        )
    return path


def load_gadm_geojson(
    iso3: str,
    level: int,
    *,
    version: str = "40",
    root: Path | None = None,
) -> dict[str, Any]:
    """Load a GADM GeoJSON ``FeatureCollection`` dict from disk."""
    path = gadm_geojson_path(iso3, level, version=version, root=root)
    data = json.loads(path.read_text(encoding="utf-8"))
    if "features" not in data or not isinstance(data["features"], list):
        raise ValueError(f"Expected GeoJSON FeatureCollection in {path}")
    return data


def _prop(props: dict[str, Any], *keys: str) -> Any:
    """First matching property (GADM 4.0 ``ID_*`` vs 3.6 shapefile ``GID_*``)."""
    for key in keys:
        if key in props and props[key] is not None:
            val = props[key]
            if isinstance(val, float) and math.isnan(val):
                continue
            return val
    return None


def _sanitize_property_value(value: Any) -> Any:
    """Earth Engine JSON rejects NaN; use null instead."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: _sanitize_property_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_property_value(v) for v in value]
    return value


def _sanitize_properties(props: dict[str, Any]) -> dict[str, Any]:
    return {k: _sanitize_property_value(v) for k, v in props.items()}


def geodesic_area_km2(geometry: dict[str, Any]) -> float:
    """Geodesic (ellipsoidal WGS84) area of a GeoJSON geometry, in km².

    Handles polygons, multipolygons, and holes. GADM geometries are lon/lat (EPSG:4326);
    this gives an accurate on-the-ground area without choosing a projection.
    """
    from pyproj import Geod
    from shapely.geometry import shape

    area_m2, _ = Geod(ellps="WGS84").geometry_area_perimeter(shape(geometry))
    return abs(area_m2) / 1e6


def adm1_id_by_name(
    iso3: str,
    *,
    version: str = "40",
    root: Path | None = None,
) -> dict[str, str]:
    """``NAME_1`` -> ``ID_1`` from the ADM1 GeoJSON (ADM2 features only carry ``NAME_1``)."""
    data = load_gadm_geojson(iso3, 1, version=version, root=root)
    out: dict[str, str] = {}
    for feat in data["features"]:
        props = feat.get("properties") or {}
        name = _prop(props, "NAME_1")
        id1 = _prop(props, "ID_1", "GID_1")
        if name is not None and id1 is not None:
            out[str(name)] = str(id1)
    return out


def normalize_gadm_level2_features(
    features: list[dict[str, Any]],
    *,
    adm1_ids: dict[str, str],
) -> list[dict[str, Any]]:
    """
    Copy features with properties aligned to GAUL-style names used in export code.

    ``ADM1_CODE`` / ``ADM2_CODE`` hold GADM ``ID_1`` / ``ID_2`` (export ``adm*_pcode``).
    """
    normalized: list[dict[str, Any]] = []
    for feat in features:
        props = dict(feat.get("properties") or {})
        name1 = _prop(props, "NAME_1")
        name2 = _prop(props, "NAME_2")
        id2 = _prop(props, "ID_2", "GID_2")
        if name1 is None or name2 is None or id2 is None:
            raise ValueError(f"GADM ADM2 feature missing NAME_1/NAME_2/ID_2: {props!r}")
        id1 = adm1_ids.get(str(name1))
        if id1 is None:
            raise KeyError(f"No ADM1 ID_1 for NAME_1={name1!r}; check ADM1 GeoJSON.")

        hasc2 = _prop(props, "HASC_2")
        new_props = _sanitize_properties(
            {
                "ADM0_NAME": _prop(props, "COUNTRY", "NAME_0"),
                "ADM0_CODE": _prop(props, "ID_0", "GID_0"),
                "ADM1_NAME": str(name1),
                "ADM1_CODE": id1,
                "ADM2_NAME": str(name2),
                "ADM2_CODE": str(id2),
                "ADM2_AREA_KM2": geodesic_area_km2(feat["geometry"]),
                "GADM_ID_1": id1,
                "GADM_ID_2": str(id2),
                "HASC_2": hasc2,
            }
        )
        normalized.append(
            {
                "type": "Feature",
                "geometry": feat["geometry"],
                "properties": new_props,
            }
        )
    return normalized


def gadm_level2_normalized_features(
    iso3: str,
    *,
    version: str = "40",
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """ADM2 GeoJSON features with export property names (no Earth Engine call)."""
    adm1_ids = adm1_id_by_name(iso3, version=version, root=root)
    data = load_gadm_geojson(iso3, 2, version=version, root=root)
    return normalize_gadm_level2_features(data["features"], adm1_ids=adm1_ids)


def gadm_level2_feature_collection(
    iso3: str,
    *,
    version: str = "40",
    root: Path | None = None,
) -> "ee.FeatureCollection":
    """
    GADM admin-2 ``ee.FeatureCollection`` with normalized property names for zonal export.

    Parameters
    ----------
    iso3:
        GADM country code (``ID_0``), e.g. ``ZWE`` for Zimbabwe.
    """
    import ee

    features = gadm_level2_normalized_features(iso3, version=version, root=root)
    return ee.FeatureCollection(features)


# ---------------------------------------------------------------------------
# ADM1 / ADM0 (countries with no GADM ADM2, e.g. Lesotho, Moldova)
# ---------------------------------------------------------------------------


def normalize_gadm_level1_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ADM1 features with export property names. ``ADM1_CODE`` holds GADM ``ID_1``.

    Unlike ADM2, ADM1 features carry their own ``ID_1`` — no name->ID lookup needed.
    No ``ADM2_*`` properties are emitted (these countries have no GADM ADM2).
    """
    normalized: list[dict[str, Any]] = []
    for feat in features:
        props = dict(feat.get("properties") or {})
        name1 = _prop(props, "NAME_1")
        id1 = _prop(props, "ID_1", "GID_1")
        if name1 is None or id1 is None:
            raise ValueError(f"GADM ADM1 feature missing NAME_1/ID_1: {props!r}")
        new_props = _sanitize_properties(
            {
                "ADM0_NAME": _prop(props, "COUNTRY", "NAME_0"),
                "ADM0_CODE": _prop(props, "ID_0", "GID_0"),
                "ADM1_NAME": str(name1),
                "ADM1_CODE": str(id1),
                "ADM1_AREA_KM2": geodesic_area_km2(feat["geometry"]),
                "GADM_ID_1": str(id1),
                "HASC_1": _prop(props, "HASC_1"),
            }
        )
        normalized.append(
            {"type": "Feature", "geometry": feat["geometry"], "properties": new_props}
        )
    return normalized


def normalize_gadm_level0_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ADM0 (national) features with export property names."""
    normalized: list[dict[str, Any]] = []
    for feat in features:
        props = dict(feat.get("properties") or {})
        new_props = _sanitize_properties(
            {
                "ADM0_NAME": _prop(props, "COUNTRY", "NAME_0"),
                "ADM0_CODE": _prop(props, "ID_0", "GID_0"),
                "ADM0_AREA_KM2": geodesic_area_km2(feat["geometry"]),
            }
        )
        normalized.append(
            {"type": "Feature", "geometry": feat["geometry"], "properties": new_props}
        )
    return normalized


def gadm_level_normalized_features(
    iso3: str,
    *,
    level: int,
    version: str = "40",
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Normalized GADM features at ``level`` (0, 1, or 2) with export property names."""
    if level == 2:
        return gadm_level2_normalized_features(iso3, version=version, root=root)
    if level == 1:
        data = load_gadm_geojson(iso3, 1, version=version, root=root)
        return normalize_gadm_level1_features(data["features"])
    if level == 0:
        data = load_gadm_geojson(iso3, 0, version=version, root=root)
        return normalize_gadm_level0_features(data["features"])
    raise ValueError(f"Unsupported admin level {level!r}; expected 0, 1, or 2.")


def gadm_level_feature_collection(
    iso3: str,
    *,
    level: int,
    version: str = "40",
    root: Path | None = None,
) -> "ee.FeatureCollection":
    """GADM ``ee.FeatureCollection`` at ``level`` (0/1/2) with normalized property names."""
    import ee

    return ee.FeatureCollection(
        gadm_level_normalized_features(iso3, level=level, version=version, root=root)
    )
