"""Reusable Earth Engine helpers for fire / burned-area zonal stats (admin-2 GAUL).

Notebooks should import from here instead of duplicating collection IDs and
``reduceRegions`` boilerplate. Requires ``earthengine-api`` (``import ee``).
"""

from __future__ import annotations

import json
import os
from typing import Any

import ee
import pandas as pd

# Inline GADM GeoJSON FeatureCollections can exceed EE's ~10 MiB request limit.
# Chunking uses both a max feature count and a serialized JSON byte budget.
DEFAULT_REGION_CHUNK_SIZE = 40
DEFAULT_REGION_CHUNK_MAX_BYTES = 5_000_000


def gaul2015_level2_regions(adm0_name: str, *, use_simplified: bool = False) -> ee.FeatureCollection:
    """FAO GAUL 2015 admin-2 polygons for one country (``ADM0_NAME`` match)."""
    asset = (
        "FAO/GAUL_SIMPLIFIED_500m/2015/level2"
        if use_simplified
        else "FAO/GAUL/2015/level2"
    )
    return ee.FeatureCollection(asset).filter(ee.Filter.eq("ADM0_NAME", adm0_name))


def mcd64a1_burn_area_m2_image(date_start: str, date_end_exclusive: str) -> ee.Image:
    """
    One month (or any window): max BurnDate > 0 → binary mask × pixel area (m²).

    ``date_*`` are ISO date strings for ``ee.Filter.date`` (upper bound exclusive).
    """
    mcd = (
        ee.ImageCollection("MODIS/061/MCD64A1")
        .filter(ee.Filter.date(date_start, date_end_exclusive))
        .select("BurnDate")
    )
    burned = mcd.max().gt(0).rename("burn_mask")
    return burned.multiply(ee.Image.pixelArea()).rename("burn_area_m2")


def firms_hot_area_m2_image(
    date_start: str,
    date_end_exclusive: str,
    *,
    t21_min_kelvin: float = 325.0,
) -> ee.Image:
    """Monthly mosaic: max T21 over window, threshold (K), × pixel area (m²)."""
    firms = (
        ee.ImageCollection("FIRMS")
        .filter(ee.Filter.date(date_start, date_end_exclusive))
        .select("T21")
    )
    hot = firms.max().gt(t21_min_kelvin).rename("hot_mask")
    return hot.multiply(ee.Image.pixelArea()).rename("hot_area_m2")


def _feature_dict_chunks(
    features: list[dict[str, Any]], chunk_size: int
) -> list[list[dict[str, Any]]]:
    if len(features) <= chunk_size:
        return [features]
    return [features[i : i + chunk_size] for i in range(0, len(features), chunk_size)]


def _feature_dict_chunks_by_bytes(
    features: list[dict[str, Any]],
    *,
    max_bytes: int,
    max_count: int,
) -> list[list[dict[str, Any]]]:
    """Split features so each chunk stays under EE's inline payload limit."""
    if not features:
        return [[]]
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    for feat in features:
        feat_bytes = len(json.dumps(feat, separators=(",", ":")))
        if current and (
            len(current) >= max_count or current_bytes + feat_bytes > max_bytes
        ):
            chunks.append(current)
            current = []
            current_bytes = 0
        current.append(feat)
        current_bytes += feat_bytes
    if current:
        chunks.append(current)
    return chunks


def _region_collections_for_reduce(
    regions: ee.FeatureCollection,
    *,
    region_features: list[dict[str, Any]] | None,
    chunk_size: int,
    chunk_max_bytes: int = DEFAULT_REGION_CHUNK_MAX_BYTES,
) -> list[ee.FeatureCollection]:
    """
    Build one or more FeatureCollections under EE's request size limit.

    Prefer ``region_features`` (normalized GADM dicts) so geometry is not sent as one
    giant inline collection.
    """
    if region_features is not None:
        return [
            ee.FeatureCollection(chunk)
            for chunk in _feature_dict_chunks_by_bytes(
                region_features,
                max_bytes=chunk_max_bytes,
                max_count=chunk_size,
            )
        ]
    n = int(regions.size().getInfo())
    if n <= chunk_size:
        return [regions]
    lst = regions.toList(n)
    return [
        ee.FeatureCollection(lst.slice(start, min(start + chunk_size, n)))
        for start in range(0, n, chunk_size)
    ]


def _reduce_regions_to_rows(
    image: ee.Image,
    regions: ee.FeatureCollection,
    *,
    band_name: str,
    reducer: ee.Reducer,
    scale_m: float,
    tile_scale: int,
    max_pixels_per_region: float,
) -> list[dict[str, Any]]:
    reduced = image.reduceRegions(
        collection=regions,
        reducer=reducer,
        scale=scale_m,
        tileScale=tile_scale,
        maxPixelsPerRegion=max_pixels_per_region,
    )
    rows: list[dict[str, Any]] = []
    for f in reduced.getInfo().get("features", []):
        rows.append(dict(f.get("properties") or {}))
    return rows


def _reduce_regions_sum_to_rows(
    image: ee.Image,
    regions: ee.FeatureCollection,
    *,
    band_name: str,
    scale_m: float,
    tile_scale: int,
    max_pixels_per_region: float,
) -> list[dict[str, Any]]:
    return _reduce_regions_to_rows(
        image,
        regions,
        band_name=band_name,
        reducer=ee.Reducer.sum(),
        scale_m=scale_m,
        tile_scale=tile_scale,
        max_pixels_per_region=max_pixels_per_region,
    )


def reduce_sum_m2_per_feature_to_df(
    area_m2: ee.Image,
    regions: ee.FeatureCollection,
    *,
    band_name: str,
    out_ha_column: str,
    scale_m: float,
    tile_scale: int = 4,
    max_pixels_per_region: float = 1e13,
    region_chunk_size: int = DEFAULT_REGION_CHUNK_SIZE,
    region_features: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """
    ``reduceRegions`` with ``Reducer.sum()``; maps m² → ha in ``out_ha_column``.

    EE often names the summed band ``sum`` in properties; we accept either.
    Large inline boundaries are processed in chunks (see ``DEFAULT_REGION_CHUNK_SIZE``).
    """
    rows: list[dict[str, Any]] = []
    for chunk_fc in _region_collections_for_reduce(
        regions,
        region_features=region_features,
        chunk_size=region_chunk_size,
    ):
        rows.extend(
            _reduce_regions_sum_to_rows(
                area_m2,
                chunk_fc,
                band_name=band_name,
                scale_m=scale_m,
                tile_scale=tile_scale,
                max_pixels_per_region=max_pixels_per_region,
            )
        )
    for p in rows:
        m2 = p.get(band_name) if p.get(band_name) is not None else p.get("sum")
        p[out_ha_column] = float(m2) / 10000.0 if m2 is not None else None
    return pd.DataFrame(rows)


def reduce_sum_per_feature_to_df(
    image: ee.Image,
    regions: ee.FeatureCollection,
    *,
    band_name: str,
    out_column: str,
    scale_m: float,
    tile_scale: int = 4,
    max_pixels_per_region: float = 1e13,
    region_chunk_size: int = DEFAULT_REGION_CHUNK_SIZE,
    region_features: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """``reduceRegions`` sum; copy summed band to ``out_column`` without unit conversion."""
    rows: list[dict[str, Any]] = []
    for chunk_fc in _region_collections_for_reduce(
        regions,
        region_features=region_features,
        chunk_size=region_chunk_size,
    ):
        rows.extend(
            _reduce_regions_sum_to_rows(
                image,
                chunk_fc,
                band_name=band_name,
                scale_m=scale_m,
                tile_scale=tile_scale,
                max_pixels_per_region=max_pixels_per_region,
            )
        )
    for p in rows:
        val = p.get(band_name) if p.get(band_name) is not None else p.get("sum")
        p[out_column] = float(val) if val is not None else None
    return pd.DataFrame(rows)


def reduce_max_per_feature_to_df(
    image: ee.Image,
    regions: ee.FeatureCollection,
    *,
    band_name: str,
    out_column: str,
    scale_m: float,
    tile_scale: int = 4,
    max_pixels_per_region: float = 1e13,
    region_chunk_size: int = DEFAULT_REGION_CHUNK_SIZE,
    region_features: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """``reduceRegions`` max; copy max band value to ``out_column``."""
    rows: list[dict[str, Any]] = []
    for chunk_fc in _region_collections_for_reduce(
        regions,
        region_features=region_features,
        chunk_size=region_chunk_size,
    ):
        rows.extend(
            _reduce_regions_to_rows(
                image,
                chunk_fc,
                band_name=band_name,
                reducer=ee.Reducer.max(),
                scale_m=scale_m,
                tile_scale=tile_scale,
                max_pixels_per_region=max_pixels_per_region,
            )
        )
    for p in rows:
        val = p.get(band_name) if p.get(band_name) is not None else p.get("max")
        p[out_column] = float(val) if val is not None else None
    return pd.DataFrame(rows)


def ee_initialize_from_environ(default_project: str = "ipv-exposure-research") -> str:
    """``ee.Initialize(project=...)`` using ``EARTHENGINE_PROJECT`` or default."""
    pid = (os.environ.get("EARTHENGINE_PROJECT") or default_project).strip()
    ee.Initialize(project=pid)
    return pid
