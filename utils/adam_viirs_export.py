"""
Build VIIRS VNP14A1 active-fire admin tables in the same shape as FIRMS exports.

The historical VIIRS layer available in Earth Engine is ``NASA/VIIRS/002/VNP14A1``:
daily, global, 1 km, with ``FireMask`` classes matching the MODIS active-fire family.
This exporter uses active fire pixels (``FireMask >= 7``) as monthly fire pixel-days,
then computes a fixed 12-month exposure-window average.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import ee
import pandas as pd

from utils.adam_modis_export import (
    adam_date_fields,
    add_window_avg,
    filter_export_months,
    months_table_for_rolling,
)
from utils.gee_fire_zonal import reduce_max_per_feature_to_df, reduce_sum_per_feature_to_df

__all__ = [
    "VIIRS_COLLECTION",
    "VIIRS_FULL_COVERAGE_START",
    "build_adam_viirs_export",
    "months_table_for_rolling",
    "to_adam_viirs_wide_columns",
    "validate_viirs_coverage",
    "viirs_monthly_fire_count_image",
    "viirs_monthly_max_frp_mw_image",
    "viirs_monthly_sum_frp_mw_image",
    "write_adam_viirs_csv",
]

VIIRS_COLLECTION = "NASA/VIIRS/002/VNP14A1"
VIIRS_FULL_COVERAGE_START = date(2012, 1, 19)
FIREMASK_FIRE_MIN = 7


def validate_viirs_coverage(exposure_start: date, *, require_full_coverage: bool = True) -> None:
    """Guard against silently exporting a partial pre-VIIRS exposure window."""
    if require_full_coverage and exposure_start < VIIRS_FULL_COVERAGE_START:
        raise ValueError(
            f"{VIIRS_COLLECTION} starts on {VIIRS_FULL_COVERAGE_START}; "
            f"exposure_start={exposure_start} would produce a partial VIIRS window."
        )


def _viirs_fire_flag_image(img: ee.Image) -> ee.Image:
    """Binary active-fire presence (1 where FireMask >= fire threshold, else 0)."""
    return img.select("FireMask").gte(FIREMASK_FIRE_MIN).unmask(0).rename("viirs_fire")


def _viirs_projection() -> ee.Projection:
    return (
        ee.Image(ee.ImageCollection(VIIRS_COLLECTION).first())
        .select("FireMask")
        .projection()
    )


def viirs_monthly_fire_count_image(date_start: str, date_end_exclusive: str) -> ee.Image:
    """Monthly VIIRS active-fire pixel-days from ``VNP14A1`` ``FireMask``."""
    projection = _viirs_projection()
    viirs = (
        ee.ImageCollection(VIIRS_COLLECTION)
        .filter(ee.Filter.date(date_start, date_end_exclusive))
        .select("FireMask")
    )
    summed = (
        viirs.map(_viirs_fire_flag_image)
        .sum()
        .unmask(0)
        .rename("monthly_fire_count")
        .setDefaultProjection(projection)
    )
    empty = (
        ee.Image.constant(0)
        .rename("monthly_fire_count")
        .setDefaultProjection(projection)
    )
    return ee.Image(ee.Algorithms.If(viirs.size().gt(0), summed, empty)).rename(
        "monthly_fire_count"
    )


def _viirs_frp_image(img: ee.Image) -> ee.Image:
    """VIIRS MaxFRP in MW on active-fire pixels."""
    fire = img.select("FireMask").gte(FIREMASK_FIRE_MIN)
    return img.select("MaxFRP").updateMask(fire).rename("monthly_max_frp_mw")


def viirs_monthly_max_frp_mw_image(date_start: str, date_end_exclusive: str) -> ee.Image:
    """Monthly maximum VIIRS FRP (MW) from active-fire pixels."""
    projection = _viirs_projection()
    viirs = (
        ee.ImageCollection(VIIRS_COLLECTION)
        .filter(ee.Filter.date(date_start, date_end_exclusive))
        .select(["FireMask", "MaxFRP"])
    )
    max_frp = (
        viirs.map(_viirs_frp_image)
        .max()
        .unmask(0)
        .rename("monthly_max_frp_mw")
        .setDefaultProjection(projection)
    )
    empty = (
        ee.Image.constant(0)
        .rename("monthly_max_frp_mw")
        .setDefaultProjection(projection)
    )
    return ee.Image(ee.Algorithms.If(viirs.size().gt(0), max_frp, empty)).rename(
        "monthly_max_frp_mw"
    )


def viirs_monthly_sum_frp_mw_image(date_start: str, date_end_exclusive: str) -> ee.Image:
    """Monthly SUM of daily per-cell VIIRS FRP (MW) over active-fire days (``VNP14A1``).

    Mirrors the MODIS summed-FRP construction (``.sum()`` of per-cell ``MaxFRP`` on fire
    pixels). VNP14A1 ``MaxFRP`` is already in MW (no 0.1 scale, unlike MODIS ``MOD14A1``).
    Single sensor (Suomi-NPP), so it accumulates fewer daily samples than the MODIS
    Terra+Aqua merge — internally valid, but not magnitude-comparable to MODIS summed FRP.
    """
    projection = _viirs_projection()
    viirs = (
        ee.ImageCollection(VIIRS_COLLECTION)
        .filter(ee.Filter.date(date_start, date_end_exclusive))
        .select(["FireMask", "MaxFRP"])
    )
    summed = (
        viirs.map(_viirs_frp_image)
        .sum()
        .unmask(0)
        .rename("monthly_sum_frp_mw")
        .setDefaultProjection(projection)
    )
    empty = (
        ee.Image.constant(0)
        .rename("monthly_sum_frp_mw")
        .setDefaultProjection(projection)
    )
    return ee.Image(ee.Algorithms.If(viirs.size().gt(0), summed, empty)).rename(
        "monthly_sum_frp_mw"
    )


def admin_monthly_viirs_from_gee(
    months_table: pd.DataFrame,
    regions: ee.FeatureCollection,
    *,
    scale_m: float = 1000.0,
    region_features: list[dict] | None = None,
) -> pd.DataFrame:
    """Long table: admin unit x month with active-fire count, max FRP, and summed FRP."""
    parts: list[pd.DataFrame] = []
    for _, mr in months_table.iterrows():
        ms = mr["month_start"]
        if not isinstance(ms, date):
            ms = pd.Timestamp(ms).date()
        mex_s = (
            mr["filter_end_exclusive"].isoformat()
            if hasattr(mr["filter_end_exclusive"], "isoformat")
            else str(mr["filter_end_exclusive"])[:10]
        )
        fire_df = reduce_sum_per_feature_to_df(
            viirs_monthly_fire_count_image(ms.isoformat(), mex_s),
            regions,
            band_name="monthly_fire_count",
            out_column="monthly_fire_count",
            scale_m=scale_m,
            region_features=region_features,
        )
        max_df = reduce_max_per_feature_to_df(
            viirs_monthly_max_frp_mw_image(ms.isoformat(), mex_s),
            regions,
            band_name="monthly_max_frp_mw",
            out_column="monthly_max_frp_mw",
            scale_m=scale_m,
            region_features=region_features,
        )
        sum_df = reduce_sum_per_feature_to_df(
            viirs_monthly_sum_frp_mw_image(ms.isoformat(), mex_s),
            regions,
            band_name="monthly_sum_frp_mw",
            out_column="monthly_sum_frp_mw",
            scale_m=scale_m,
            region_features=region_features,
        )
        key = "ADM2_CODE" if "ADM2_CODE" in fire_df.columns else "ADM1_CODE"
        merged = fire_df.merge(max_df[[key, "monthly_max_frp_mw"]], on=key).merge(
            sum_df[[key, "monthly_sum_frp_mw"]], on=key
        )
        merged["month_start"] = ms
        parts.append(merged)
    return pd.concat(parts, ignore_index=True)


def to_adam_viirs_wide_columns(
    long_df: pd.DataFrame,
    *,
    adm0_name: str,
    adm0_pcode: str,
    unit_level: int = 2,
) -> pd.DataFrame:
    """VIIRS CSV columns, intentionally matching the FIRMS active-fire table shape."""
    df = long_df.copy()
    df["adm0_name"] = adm0_name
    df["adm0_pcode"] = adm0_pcode
    if unit_level >= 1:
        df["adm1_name"] = df["ADM1_NAME"]
        df["adm1_gid"] = df["ADM1_CODE"].astype(str) if "ADM1_CODE" in df.columns else ""
    if unit_level >= 2:
        df["adm2_name"] = df["ADM2_NAME"]
        df["adm2_gid"] = df["ADM2_CODE"].astype(str) if "ADM2_CODE" in df.columns else ""
    area_src = f"ADM{unit_level}_AREA_KM2"
    if area_src in df.columns:
        df[f"adm{unit_level}_area_km2"] = df[area_src]

    df = df.loc[:, ~df.columns.duplicated(keep="first")]
    ms = pd.to_datetime(df["month_start"])
    date_rows = [adam_date_fields(pd.Timestamp(ts).date()) for ts in ms]
    for key in ("month_start", "month_end"):
        df[key] = [row[key] for row in date_rows]

    adam_cols = [
        "adm0_name",
        "adm0_pcode",
        "adm1_name",
        "adm1_gid",
        "adm1_area_km2",
        "adm2_name",
        "adm2_gid",
        "adm2_area_km2",
        "month_start",
        "month_end",
        "monthly_fire_count",
        "monthly_max_frp_mw",
        "monthly_sum_frp_mw",
        "avg12_fire_count",
        "avg12_sum_frp_mw",
    ]
    cols = [c for c in adam_cols if c in df.columns]
    out = df.loc[:, cols]
    if out.columns.duplicated().any():
        out = out.loc[:, ~pd.Index(out.columns).duplicated(keep="first")]
    sort_cols = [c for c in ("adm1_name", "adm2_name") if c in out.columns] + ["month_start"]
    return out.sort_values(sort_cols)


def build_adam_viirs_export(
    months_table: pd.DataFrame,
    regions: ee.FeatureCollection,
    *,
    adm0_name: str,
    adm0_pcode: str,
    exposure_start: date,
    exposure_end: date,
    scale_m: float = 1000.0,
    region_features: list[dict] | None = None,
    unit_level: int = 2,
    require_full_coverage: bool = True,
) -> pd.DataFrame:
    """GEE pull -> exposure-month filter -> fixed 12-month avg -> Adam columns."""
    validate_viirs_coverage(exposure_start, require_full_coverage=require_full_coverage)
    unit_col = f"ADM{unit_level}_CODE"
    long_df = admin_monthly_viirs_from_gee(
        months_table, regions, scale_m=scale_m, region_features=region_features
    )
    long_df = filter_export_months(long_df, exposure_start, exposure_end)
    long_df = add_window_avg(
        long_df,
        unit_col=unit_col,
        value_col="monthly_fire_count",
        out_col="avg12_fire_count",
    )
    long_df = add_window_avg(
        long_df,
        unit_col=unit_col,
        value_col="monthly_sum_frp_mw",
        out_col="avg12_sum_frp_mw",
    )
    return to_adam_viirs_wide_columns(
        long_df, adm0_name=adm0_name, adm0_pcode=adm0_pcode, unit_level=unit_level
    )


def write_adam_viirs_csv(df: pd.DataFrame, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path
