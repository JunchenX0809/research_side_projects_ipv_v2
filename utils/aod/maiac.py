"""MAIAC AOD image construction and polygon means."""

from __future__ import annotations

import math
from typing import Any

import ee
import pandas as pd
from shapely.geometry import shape

MAIAC_COLLECTION = "MODIS/061/MCD19A2_GRANULES"
AOD_BAND = "Optical_Depth_055"
AOD_QA_BAND = "AOD_QA"
AOD_SCALE_FACTOR = 0.001
OUTPUT_BAND = "monthly_mean_aod"

_SINUSOIDAL_RADIUS_M = 6_371_007.181
_TILE_SIZE_M = 1_111_950.5196666666
_X_MIN_M = -20_015_109.354
_Y_MAX_M = 10_007_554.677


def modis_tile_for_lonlat(lon: float, lat: float) -> tuple[int, int]:
    lat_rad = math.radians(lat)
    x = _SINUSOIDAL_RADIUS_M * math.radians(lon) * math.cos(lat_rad)
    y = _SINUSOIDAL_RADIUS_M * lat_rad
    h = math.floor((x - _X_MIN_M) / _TILE_SIZE_M)
    v = math.floor((_Y_MAX_M - y) / _TILE_SIZE_M)
    return min(35, max(0, h)), min(17, max(0, v))


def modis_tiles_for_features(features: list[dict[str, Any]]) -> list[str]:
    """Return a conservative MODIS tile rectangle covering the boundaries."""
    if not features:
        raise ValueError("At least one boundary feature is required")
    bounds = [shape(feature["geometry"]).bounds for feature in features]
    min_lon = min(bound[0] for bound in bounds)
    min_lat = min(bound[1] for bound in bounds)
    max_lon = max(bound[2] for bound in bounds)
    max_lat = max(bound[3] for bound in bounds)
    nearest_equator = min(max(0.0, min_lat), max_lat)
    samples = [
        modis_tile_for_lonlat(lon, lat)
        for lon in (min_lon, max_lon)
        for lat in (min_lat, nearest_equator, max_lat)
    ]
    hs = [h for h, _ in samples]
    vs = [v for _, v in samples]
    return [
        f"h{h:02d}v{v:02d}"
        for h in range(min(hs), max(hs) + 1)
        for v in range(min(vs), max(vs) + 1)
    ]


def _tile_filter(tiles: list[str]) -> ee.Filter:
    filters = [
        ee.Filter.stringContains("system:index", f"_{tile}_") for tile in tiles
    ]
    if not filters:
        raise ValueError("At least one MODIS tile is required")
    return filters[0] if len(filters) == 1 else ee.Filter.Or(*filters)


def _scaled_best_quality_aod(image: ee.Image) -> ee.Image:
    raw = image.select(AOD_BAND)
    aod_quality = image.select(AOD_QA_BAND).rightShift(8).bitwiseAnd(15)
    return (
        raw.multiply(AOD_SCALE_FACTOR)
        .rename(OUTPUT_BAND)
        .updateMask(aod_quality.eq(0))
        .updateMask(raw.gte(0))
        .copyProperties(image, ["system:time_start"])
    )


def aod_collection(
    date_start: str, date_end_exclusive: str, *, tiles: list[str]
) -> ee.ImageCollection:
    return (
        ee.ImageCollection(MAIAC_COLLECTION)
        .filter(ee.Filter.date(date_start, date_end_exclusive))
        .filter(_tile_filter(tiles))
        .map(_scaled_best_quality_aod)
    )


def mean_aod_image(
    date_start: str,
    date_end_exclusive: str,
    *,
    tiles: list[str],
    output_band: str,
) -> ee.Image:
    collection = aod_collection(date_start, date_end_exclusive, tiles=tiles)
    empty = ee.Image.constant(0).rename(output_band).updateMask(ee.Image.constant(0))
    return ee.Image(
        ee.Algorithms.If(
            collection.size().gt(0),
            collection.mean().rename(output_band),
            empty,
        )
    )


def reduce_mean_chunk(
    image: ee.Image,
    features: list[dict[str, Any]],
    *,
    band_name: str,
    output_column: str,
    scale_m: float = 1000.0,
    tile_scale: int = 4,
    max_pixels_per_region: float = 1e13,
) -> pd.DataFrame:
    """Evaluate one small boundary chunk with ``Reducer.mean``."""
    reduced = image.reduceRegions(
        collection=ee.FeatureCollection(features),
        reducer=ee.Reducer.mean(),
        scale=scale_m,
        tileScale=tile_scale,
        maxPixelsPerRegion=max_pixels_per_region,
    )
    rows: list[dict[str, Any]] = []
    for feature in reduced.getInfo().get("features", []):
        properties = dict(feature.get("properties") or {})
        value = properties.get(band_name)
        if value is None:
            value = properties.get("mean")
        properties[output_column] = float(value) if value is not None else None
        rows.append(properties)
    return pd.DataFrame(rows)
