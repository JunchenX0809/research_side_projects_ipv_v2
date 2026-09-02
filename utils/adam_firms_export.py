"""
Build FIRMS admin-2 tables in Adam's export shape (see ``skills/Adam_Firm.docx``).

Export columns:
  adm0_name, adm0_pcode, adm1_name, adm1_pcode, adm2_name, adm2_pcode,
  month_start, month_end, monthly_fire_count, avg12_fire_count

GEE logic matches Adam's script: daily ``FIRMS`` ``T21`` → binary fire (masked),
sum over the month per pixel → ``monthly_fire_count``. ``avg12_fire_count`` is the mean of
the unit's ``monthly_fire_count`` over the 12-month exposure window (fixed window, constant
within an admin area; not a trailing rolling average).

Default ``scale_m=1000`` per Adam_Firm.docx (MODIS uses 500 m).
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
from utils.gee_fire_zonal import reduce_sum_per_feature_to_df

# Re-export for notebooks that build months_table once for MODIS + FIRMS
__all__ = [
    "build_adam_firms_export",
    "firms_monthly_fire_count_image",
    "months_table_for_rolling",
    "write_adam_firms_csv",
]


def firms_monthly_fire_count_image(date_start: str, date_end_exclusive: str) -> ee.Image:
    """
    Adam FIRMS: sum of daily binary fire flags in the month (``Adam_Firm.docx``).

    Each daily image contributes ``T21.mask().unmask(0)``; monthly sum → fire-detection
    count per pixel before zonal sum.
    """
    firms = (
        ee.ImageCollection("FIRMS")
        .filter(ee.Filter.date(date_start, date_end_exclusive))
        .select("T21")
    )

    def _daily_fire(img: ee.Image) -> ee.Image:
        return img.select("T21").mask().unmask(0).rename("fire")

    summed = firms.map(_daily_fire).sum()
    empty = ee.Image.constant(0).rename("monthly_fire_count")
    return ee.Image(ee.Algorithms.If(firms.size().gt(0), summed, empty)).rename(
        "monthly_fire_count"
    )


def district_monthly_firms_from_gee(
    months_table: pd.DataFrame,
    regions: ee.FeatureCollection,
    *,
    scale_m: float = 1000.0,
    region_features: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Long table: district × month with ``monthly_fire_count``."""
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
        img = firms_monthly_fire_count_image(ms.isoformat(), mex_s)
        bdf = reduce_sum_per_feature_to_df(
            img,
            regions,
            band_name="monthly_fire_count",
            out_column="monthly_fire_count",
            scale_m=scale_m,
            region_features=region_features,
        )
        bdf["month_start"] = ms
        parts.append(bdf)
    return pd.concat(parts, ignore_index=True)


def to_adam_firms_wide_columns(
    long_df: pd.DataFrame,
    *,
    adm0_name: str,
    adm0_pcode: str,
    unit_level: int = 2,
) -> pd.DataFrame:
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
        "avg12_fire_count",
    ]
    cols = [c for c in adam_cols if c in df.columns]
    out = df.loc[:, cols]
    if out.columns.duplicated().any():
        out = out.loc[:, ~pd.Index(out.columns).duplicated(keep="first")]
    sort_cols = [c for c in ("adm1_name", "adm2_name") if c in out.columns] + ["month_start"]
    return out.sort_values(sort_cols)


def build_adam_firms_export(
    months_table: pd.DataFrame,
    regions: ee.FeatureCollection,
    *,
    adm0_name: str,
    adm0_pcode: str,
    exposure_start: date,
    exposure_end: date,
    scale_m: float = 1000.0,
    region_features: list[dict[str, Any]] | None = None,
    unit_level: int = 2,
) -> pd.DataFrame:
    """GEE pull → exposure-month filter → fixed 12-month avg → Adam FIRMS column names."""
    unit_col = f"ADM{unit_level}_CODE"
    long_df = district_monthly_firms_from_gee(
        months_table, regions, scale_m=scale_m, region_features=region_features
    )
    long_df = filter_export_months(long_df, exposure_start, exposure_end)
    long_df = add_window_avg(
        long_df,
        unit_col=unit_col,
        value_col="monthly_fire_count",
        out_col="avg12_fire_count",
    )
    return to_adam_firms_wide_columns(
        long_df, adm0_name=adm0_name, adm0_pcode=adm0_pcode, unit_level=unit_level
    )


def write_adam_firms_csv(df: pd.DataFrame, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path
