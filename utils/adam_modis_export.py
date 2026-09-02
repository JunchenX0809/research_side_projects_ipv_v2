"""
Build MODIS MCD64A1 admin-2 tables in Adam's export shape (see ``skills/Adam_Modis.docx``).

Export columns:
  adm0_name, adm0_pcode, adm1_name, adm1_pcode, adm2_name, adm2_pcode,
  month_start, month_end, monthly_burned_area_km2, avg12_burned_area_km2, mom_pct_change

``avg12_burned_area_km2`` is the mean of the unit's ``monthly_burned_area_km2`` over the
12-month exposure window (the 12 months before the survey) — a fixed window, constant for
every row within an admin area (it is NOT a trailing rolling average). ``mom_pct_change`` is
month-over-month % change of the monthly value within each unit; we pull one history month
before the exposure window so the first exposure month has a defined MoM.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import ee
import pandas as pd

from utils.gee_fire_zonal import reduce_sum_per_feature_to_df
from utils.vacs_survey_time import months_df_inclusive_range


def mcd64a1_monthly_burn_km2_image(date_start: str, date_end_exclusive: str) -> ee.Image:
    """Adam MODIS: sum of per-scene burned km² where ``BurnDate > 0`` (``Adam_Modis.docx``)."""
    mcd = (
        ee.ImageCollection("MODIS/061/MCD64A1")
        .filter(ee.Filter.date(date_start, date_end_exclusive))
        .select("BurnDate")
    )

    def _per_scene(img: ee.Image) -> ee.Image:
        burned = img.select("BurnDate").gt(0)
        return (
            ee.Image.pixelArea()
            .divide(1e6)
            .updateMask(burned)
            .rename("burned_area_km2")
        )

    summed = mcd.map(_per_scene).sum()
    empty = ee.Image.constant(0).rename("burned_area_km2")
    return ee.Image(ee.Algorithms.If(mcd.size().gt(0), summed, empty))


def adam_month_end_exclusive(month_start: date) -> date:
    """``monthEnd`` in Adam's script: ``month_start`` + 1 calendar month."""
    ts = pd.Timestamp(month_start) + pd.DateOffset(months=1)
    return ts.date()


def adam_date_fields(month_start: date) -> dict[str, str]:
    return {
        "month_start": month_start.isoformat(),
        "month_end": adam_month_end_exclusive(month_start).isoformat(),
    }


def months_table_for_rolling(
    exposure_start: date,
    exposure_end: date,
    *,
    history_months: int = 1,
) -> pd.DataFrame:
    """
    Month rows for GEE: ``history_months`` of context before ``exposure_start``, through ``exposure_end``.

    Only one history month is needed now (so the first exposure month has a defined
    ``mom_pct_change``); the 12-month average is computed over the exposure window itself.
    Every slice stays anchored on the exposure start's day of month.  With one
    history month this yields one context slice followed by the 12 exposure slices.
    """
    ext_start = (pd.Timestamp(exposure_start) - pd.DateOffset(months=history_months)).date()
    raw = months_df_inclusive_range(ext_start, exposure_end)
    rows: list[dict[str, Any]] = []
    for _, mr in raw.iterrows():
        ms = mr["month_start"]
        if not isinstance(ms, date):
            ms = pd.Timestamp(ms).date()
        m_end = adam_month_end_exclusive(ms)
        rows.append(
            {
                "month_start": ms,
                "month_end": m_end,
                "filter_end_exclusive": m_end,
            }
        )
    return pd.DataFrame(rows)


def district_monthly_burn_from_gee(
    months_table: pd.DataFrame,
    regions: ee.FeatureCollection,
    *,
    scale_m: float = 500.0,
    region_features: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Long table: district × month with ``monthly_burned_area_km2``."""
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
        img = mcd64a1_monthly_burn_km2_image(ms.isoformat(), mex_s)
        bdf = reduce_sum_per_feature_to_df(
            img,
            regions,
            band_name="burned_area_km2",
            out_column="monthly_burned_area_km2",
            scale_m=scale_m,
            region_features=region_features,
        )
        bdf["month_start"] = ms
        parts.append(bdf)
    return pd.concat(parts, ignore_index=True)


def add_mom(
    long_df: pd.DataFrame,
    *,
    unit_col: str = "ADM2_NAME",
    value_col: str = "monthly_burned_area_km2",
) -> pd.DataFrame:
    """Month-over-month % change of ``value_col`` within each admin unit."""
    out = long_df.copy()
    out["month_start"] = pd.to_datetime(out["month_start"])
    out = out.sort_values([unit_col, "month_start"])
    out["mom_pct_change"] = out.groupby(unit_col, group_keys=False)[value_col].transform(
        lambda s: s.pct_change() * 100.0
    )
    return out


def add_window_avg(
    df: pd.DataFrame,
    *,
    unit_col: str,
    value_col: str,
    out_col: str,
) -> pd.DataFrame:
    """Fixed-window mean of ``value_col`` per admin unit (constant across the unit's rows).

    Apply AFTER filtering to the exposure months so the mean covers exactly the 12-month
    exposure window.
    """
    out = df.copy()
    out[out_col] = out.groupby(unit_col)[value_col].transform("mean")
    return out


def to_adam_modis_wide_columns(
    long_df: pd.DataFrame,
    *,
    adm0_name: str,
    adm0_pcode: str,
    unit_level: int = 2,
) -> pd.DataFrame:
    df = long_df.copy()
    df["adm0_name"] = adm0_name
    df["adm0_pcode"] = adm0_pcode
    # Boundary-source codes on the regions FC (GAUL ADM*_CODE or GADM ID_1 / ID_2 as strings).
    # ADM1-only countries (no GADM ADM2) carry no adm2_* columns.
    if unit_level >= 1:
        df["adm1_name"] = df["ADM1_NAME"]
        df["adm1_gid"] = df["ADM1_CODE"].astype(str) if "ADM1_CODE" in df.columns else ""
    if unit_level >= 2:
        df["adm2_name"] = df["ADM2_NAME"]
        df["adm2_gid"] = df["ADM2_CODE"].astype(str) if "ADM2_CODE" in df.columns else ""
    # Unit area (km², constant per unit) from the boundary polygon — for % burned / density
    area_src = f"ADM{unit_level}_AREA_KM2"
    if area_src in df.columns:
        df[f"adm{unit_level}_area_km2"] = df[area_src]

    df = df.loc[:, ~df.columns.duplicated(keep="first")]
    ms = pd.to_datetime(df["month_start"])
    date_rows = [adam_date_fields(pd.Timestamp(ts).date()) for ts in ms]
    for key in ("month_start", "month_end"):
        df[key] = [row[key] for row in date_rows]

    adam_first = [
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
        "monthly_burned_area_km2",
        "avg12_burned_area_km2",
        "mom_pct_change",
    ]
    cols = [c for c in adam_first if c in df.columns]
    out = df.loc[:, cols]
    if out.columns.duplicated().any():
        out = out.loc[:, ~pd.Index(out.columns).duplicated(keep="first")]
    sort_cols = [c for c in ("adm1_name", "adm2_name") if c in out.columns] + ["month_start"]
    return out.sort_values(sort_cols)


def filter_export_months(df: pd.DataFrame, exposure_start: date, exposure_end: date) -> pd.DataFrame:
    """Keep anchored slices whose starts fall in the inclusive exposure interval."""
    ms = pd.to_datetime(df["month_start"])
    lo = pd.Timestamp(exposure_start)
    hi = pd.Timestamp(exposure_end)
    return df[(ms >= lo) & (ms <= hi)].copy()


def build_adam_modis_export(
    months_table: pd.DataFrame,
    regions: ee.FeatureCollection,
    *,
    adm0_name: str,
    adm0_pcode: str,
    exposure_start: date,
    exposure_end: date,
    scale_m: float = 500.0,
    region_features: list[dict[str, Any]] | None = None,
    unit_level: int = 2,
) -> pd.DataFrame:
    """GEE pull → MoM → exposure-month filter → fixed 12-month avg → Adam column names.

    ``unit_level`` selects the admin level of the regions (2 = districts, 1 = provinces/raions
    for countries with no GADM ADM2, 0 = national).
    """
    unit_col = f"ADM{unit_level}_CODE"
    long_df = district_monthly_burn_from_gee(
        months_table, regions, scale_m=scale_m, region_features=region_features
    )
    long_df = add_mom(long_df, unit_col=unit_col)
    long_df = filter_export_months(long_df, exposure_start, exposure_end)
    long_df = add_window_avg(
        long_df,
        unit_col=unit_col,
        value_col="monthly_burned_area_km2",
        out_col="avg12_burned_area_km2",
    )
    return to_adam_modis_wide_columns(
        long_df, adm0_name=adm0_name, adm0_pcode=adm0_pcode, unit_level=unit_level
    )


def write_adam_modis_csv(df: pd.DataFrame, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path
