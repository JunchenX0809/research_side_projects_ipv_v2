"""VIIRS VNP64A1 burned-area helpers.

This module is deliberately separate from :mod:`utils.adam_viirs_export`, which
implements the VNP14A1 active-fire and FRP sensitivity layer.  VNP64A1 is a
monthly 500 m burned-area product whose ``Burn_Date`` values are ordinal days
of year.  Using those values lets the exporter honor exposure intervals that
do not begin on the first day of a calendar month.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import ee
import pandas as pd


VNP64A1_COLLECTION = "NASA/VIIRS/002/VNP64A1"
# The current Earth Engine collection's first monthly image is 2012_03_01.
VNP64A1_EE_FIRST_IMAGE = date(2012, 3, 1)
MONTHLY_BURN_COLUMN = "monthly_viirs_burned_area_km2"
AVG12_BURN_COLUMN = "avg12_viirs_burned_area_km2"


@dataclass(frozen=True)
class BurnYearSegment:
    """One within-year portion of an inclusive/exclusive date interval."""

    year: int
    start_doy: int
    end_doy_exclusive: int


def burn_year_segments(date_start: date, date_end_exclusive: date) -> list[BurnYearSegment]:
    """Split ``[date_start, date_end_exclusive)`` into ordinal-day year segments."""
    if date_end_exclusive <= date_start:
        raise ValueError(
            f"date_end_exclusive {date_end_exclusive} must follow date_start {date_start}"
        )

    segments: list[BurnYearSegment] = []
    year = date_start.year
    while year <= (date_end_exclusive - pd.Timedelta(days=1)).year:
        year_start = date(year, 1, 1)
        next_year = date(year + 1, 1, 1)
        segment_start = max(date_start, year_start)
        segment_end = min(date_end_exclusive, next_year)
        segments.append(
            BurnYearSegment(
                year=year,
                start_doy=(segment_start - year_start).days + 1,
                end_doy_exclusive=(segment_end - year_start).days + 1,
            )
        )
        year += 1
    return segments


def validate_vnp64a1_coverage(date_start: date) -> None:
    """Reject intervals earlier than the first monthly image actually present in EE."""
    if date_start < VNP64A1_EE_FIRST_IMAGE:
        raise ValueError(
            f"{VNP64A1_COLLECTION} first Earth Engine image is "
            f"{VNP64A1_EE_FIRST_IMAGE}; date_start={date_start} is not fully covered"
        )


def _segment_burn_km2_image(segment: BurnYearSegment) -> ee.Image:
    year_start = f"{segment.year:04d}-01-01"
    next_year = f"{segment.year + 1:04d}-01-01"
    collection = ee.ImageCollection(VNP64A1_COLLECTION).filterDate(year_start, next_year)
    projection = (
        ee.Image(ee.ImageCollection(VNP64A1_COLLECTION).first())
        .select("Burn_Date")
        .projection()
    )

    def _per_image(image: ee.Image) -> ee.Image:
        burn_date = image.select("Burn_Date")
        qa = image.select("QA")
        # QA bit 0 = land and bit 1 = sufficient valid reflectance observations.
        valid_land = qa.bitwiseAnd(1).neq(0).And(qa.bitwiseAnd(2).neq(0))
        in_interval = burn_date.gte(segment.start_doy).And(
            burn_date.lt(segment.end_doy_exclusive)
        )
        return (
            ee.Image.pixelArea()
            .divide(1e6)
            .updateMask(in_interval.And(valid_land))
            .rename(MONTHLY_BURN_COLUMN)
        )

    summed = (
        collection.map(_per_image)
        .sum()
        .unmask(0)
        .rename(MONTHLY_BURN_COLUMN)
        .setDefaultProjection(projection)
    )
    empty = (
        ee.Image.constant(0)
        .rename(MONTHLY_BURN_COLUMN)
        .setDefaultProjection(projection)
    )
    return ee.Image(ee.Algorithms.If(collection.size().gt(0), summed, empty))


def vnp64a1_burn_km2_image(date_start: str, date_end_exclusive: str) -> ee.Image:
    """Burned km² for an exact interval using VNP64A1 ordinal ``Burn_Date`` values."""
    start = date.fromisoformat(date_start)
    end = date.fromisoformat(date_end_exclusive)
    validate_vnp64a1_coverage(start)
    images = [_segment_burn_km2_image(segment) for segment in burn_year_segments(start, end)]
    return (
        ee.ImageCollection.fromImages(images)
        .sum()
        .unmask(0)
        .rename(MONTHLY_BURN_COLUMN)
    )


def to_adam_viirs_burned_area_columns(
    long_df: pd.DataFrame,
    *,
    adm0_name: str,
    adm0_pcode: str,
    unit_level: int = 2,
) -> pd.DataFrame:
    """Finalize exact-date VNP64A1 zonal rows without recalculating ``month_end``."""
    df = long_df.copy()
    unit_code = f"ADM{unit_level}_CODE"
    if df.duplicated([unit_code, "month_start", "month_end"]).any():
        raise ValueError("Duplicate boundary-month rows in VNP64A1 burned-area results")

    df[AVG12_BURN_COLUMN] = df.groupby(unit_code)[MONTHLY_BURN_COLUMN].transform("mean")
    df["adm0_name"] = adm0_name
    df["adm0_pcode"] = adm0_pcode
    if unit_level >= 1:
        df["adm1_name"] = df["ADM1_NAME"]
        df["adm1_gid"] = df["ADM1_CODE"].astype(str)
    if unit_level >= 2:
        df["adm2_name"] = df["ADM2_NAME"]
        df["adm2_gid"] = df["ADM2_CODE"].astype(str)
    area_source = f"ADM{unit_level}_AREA_KM2"
    if area_source in df.columns:
        df[f"adm{unit_level}_area_km2"] = df[area_source]

    for column in ("month_start", "month_end"):
        df[column] = pd.to_datetime(df[column]).dt.strftime("%Y-%m-%d")

    preferred = [
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
        MONTHLY_BURN_COLUMN,
        AVG12_BURN_COLUMN,
    ]
    columns = [column for column in preferred if column in df.columns]
    sort_columns = [column for column in ("adm1_name", "adm2_name") if column in df] + [
        "month_start"
    ]
    return df.loc[:, columns].sort_values(sort_columns).reset_index(drop=True)


def write_adam_viirs_burned_area_csv(df: pd.DataFrame, path: Path) -> Path:
    """Atomically write a VNP64A1 table."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(temporary, index=False)
    temporary.replace(path)
    return path

