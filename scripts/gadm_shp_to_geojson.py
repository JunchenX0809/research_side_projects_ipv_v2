#!/usr/bin/env python3
"""
Convert GADM shapefiles to GeoJSON for ``utils.gadm_boundaries`` (Earth Engine).

GADM 3.6 on the UC Davis mirror is shapefile/RDS only — no ``json/`` folder like 4.0.
If you downloaded ``gadm36_{ISO3}_shp.zip``, run this to build ``gadm36_{ISO3}_{level}.json``.

Example (Zimbabwe, from existing shp folder)::

    python scripts/gadm_shp_to_geojson.py --iso3 ZWE --version 36 \\
        --shp-dir data/raw/gadm/3.6/gadm36_ZWE_shp

Batch (all ADM2 countries under ``data/raw/gadm/3.6/``)::

    python scripts/gadm_shp_to_geojson.py --version 36 --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.gadm_boundaries import GADM_VERSIONS, _sanitize_properties
from utils.repo_paths import find_repo_root


def _rename_gadm36_props(props: dict) -> dict:
    """Map 3.6 shapefile ``GID_*`` fields to 4.0-style ``ID_*`` for shared loaders."""
    out = dict(props)
    for level in ("0", "1", "2"):
        gid = out.pop(f"GID_{level}", None)
        if gid is not None and f"ID_{level}" not in out:
            out[f"ID_{level}"] = gid
    if "NAME_0" in out and "COUNTRY" not in out:
        out["COUNTRY"] = out["NAME_0"]
    return out


def shp_to_geojson(shp_path: Path, out_path: Path) -> int:
    import geopandas as gpd

    gdf = gpd.read_file(shp_path)
    features = []
    for _, row in gdf.iterrows():
        props = _sanitize_properties(
            _rename_gadm36_props({k: v for k, v in row.items() if k != "geometry"})
        )
        geom = row.geometry.__geo_interface__
        features.append({"type": "Feature", "properties": props, "geometry": geom})
    fc = {"type": "FeatureCollection", "features": features}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fc), encoding="utf-8")
    return len(features)


def discover_iso3_with_adm2(
    root: Path,
    *,
    version: str,
    iso3_filter: set[str] | None = None,
) -> list[str]:
    """ISO3 codes with ``gadm{ver}_{ISO3}_shp/`` and ``_2.shp`` present."""
    version_dir = GADM_VERSIONS[version]
    gadm_root = root / "data" / "raw" / "gadm" / version_dir
    if not gadm_root.is_dir():
        return []
    found: list[str] = []
    for shp_dir in sorted(gadm_root.glob(f"gadm{version}_*_shp")):
        if not shp_dir.is_dir():
            continue
        name = shp_dir.name
        # gadm36_MWI_shp -> MWI
        iso3 = name.removeprefix(f"gadm{version}_").removesuffix("_shp").upper()
        if iso3_filter is not None and iso3 not in iso3_filter:
            continue
        if (shp_dir / f"gadm{version}_{iso3}_2.shp").is_file():
            found.append(iso3)
    return found


def convert_country(
    iso3: str,
    *,
    version: str,
    root: Path,
    shp_dir: Path | None,
    skip_existing: bool,
) -> tuple[str, int | None, int | None, str]:
    """
    Convert ADM1+ADM2 shapefiles to GeoJSON.

    Returns (iso3, n_adm1, n_adm2, status_message).
    """
    version_dir = GADM_VERSIONS[version]
    iso3 = iso3.upper()
    shp_dir = shp_dir or (root / "data" / "raw" / "gadm" / version_dir / f"gadm{version}_{iso3}_shp")
    out_dir = root / "data" / "raw" / "gadm" / version_dir
    out0 = out_dir / f"gadm{version}_{iso3}_0.json"
    out1 = out_dir / f"gadm{version}_{iso3}_1.json"
    out2 = out_dir / f"gadm{version}_{iso3}_2.json"

    shp2 = shp_dir / f"gadm{version}_{iso3}_2.shp"
    adm1_only = not shp2.is_file()
    if adm1_only:
        if skip_existing and out1.is_file():
            return iso3, None, None, "skipped (json exists)"
        levels = [0, 1]
    else:
        if skip_existing and out1.is_file() and out2.is_file():
            return iso3, None, None, "skipped (json exists)"
        levels = [1, 2]

    counts: list[int] = []
    for level in levels:
        shp = shp_dir / f"gadm{version}_{iso3}_{level}.shp"
        if not shp.is_file():
            if adm1_only and level == 0:
                continue
            return iso3, None, None, f"error: missing {shp}"
        out = out_dir / f"gadm{version}_{iso3}_{level}.json"
        counts.append(shp_to_geojson(shp, out))

    if adm1_only:
        n1 = counts[-1] if counts else None
        return iso3, n1, None, "ok (ADM1 only, no ADM2)"
    return iso3, counts[0], counts[1], "ok"


def main() -> None:
    p = argparse.ArgumentParser(description="GADM shapefile → GeoJSON for EE pipeline")
    p.add_argument("--iso3", help="GADM ID_0, e.g. ZWE (comma-separated for multiple)")
    p.add_argument("--version", default="36", help="GADM version key: 41, 40, 36, 28")
    p.add_argument(
        "--all",
        action="store_true",
        help="Convert all gadm{ver}_*_shp folders that have ADM2 shapefile",
    )
    p.add_argument(
        "--shp-dir",
        type=Path,
        help="Folder with gadm{ver}_{ISO3}_{level}.shp (single-country mode)",
    )
    p.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip if both _1.json and _2.json exist (default: true)",
    )
    args = p.parse_args()
    root = find_repo_root()
    ver = args.version
    if ver not in GADM_VERSIONS:
        raise SystemExit(f"Unknown version {ver!r}; expected {list(GADM_VERSIONS)}")

    if args.all:
        iso3_filter = None
        if args.iso3:
            iso3_filter = {x.strip().upper() for x in args.iso3.split(",") if x.strip()}
        iso3_list = discover_iso3_with_adm2(root, version=ver, iso3_filter=iso3_filter)
        if not iso3_list:
            raise SystemExit(f"No ADM2 shapefile folders under data/raw/gadm/{GADM_VERSIONS[ver]}/")
        print(f"{'ISO3':<6} {'ADM1':>6} {'ADM2':>6}  status")
        print("-" * 40)
        for iso3 in iso3_list:
            iso3, n1, n2, status = convert_country(
                iso3,
                version=ver,
                root=root,
                shp_dir=None,
                skip_existing=args.skip_existing,
            )
            if status == "ok":
                print(f"{iso3:<6} {n1:>6} {n2:>6}  {status}")
            else:
                print(f"{iso3:<6} {'—':>6} {'—':>6}  {status}")
        return

    if not args.iso3:
        raise SystemExit("Provide --iso3 ISO3 or use --all")

    for iso3 in [x.strip().upper() for x in args.iso3.split(",") if x.strip()]:
        iso3, n1, n2, status = convert_country(
            iso3,
            version=ver,
            root=root,
            shp_dir=args.shp_dir,
            skip_existing=args.skip_existing,
        )
        if status == "ok":
            version_dir = GADM_VERSIONS[ver]
            out_dir = root / "data" / "raw" / "gadm" / version_dir
            print(f"Wrote {out_dir / f'gadm{ver}_{iso3}_1.json'} ({n1} features)")
            print(f"Wrote {out_dir / f'gadm{ver}_{iso3}_2.json'} ({n2} features)")
        else:
            print(f"{iso3}: {status}")


if __name__ == "__main__":
    main()
