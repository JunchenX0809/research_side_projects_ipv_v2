"""Indonesia-specific schedule, boundary, batching, and append helpers.

The scientific image transformations remain in the existing VIIRS active-fire
module and the separate VNP64A1 burned-area module.  This adapter only handles
the PI side task's COD/BPS boundary and teammate AOD reference schedules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import ee
import pandas as pd

from utils.adam_modis_export import add_window_avg
from utils.adam_viirs_burn_export import (
    AVG12_BURN_COLUMN,
    MONTHLY_BURN_COLUMN,
    to_adam_viirs_burned_area_columns,
    vnp64a1_burn_km2_image,
)
from utils.adam_viirs_export import (
    to_adam_viirs_wide_columns,
    viirs_monthly_fire_count_image,
    viirs_monthly_max_frp_mw_image,
    viirs_monthly_sum_frp_mw_image,
)
from utils.gee_fire_zonal import _feature_dict_chunks_by_bytes


EXPECTED_ADM2_UNITS = 522
BOUNDARY_TAG = "codbps20200401"
BOUNDARY_PROPERTIES = [
    "ADM0_NAME",
    "ADM0_CODE",
    "ADM1_NAME",
    "ADM1_CODE",
    "ADM2_NAME",
    "ADM2_CODE",
    "ADM2_AREA_KM2",
]
ACTIVE_VALUE_COLUMNS = [
    "monthly_fire_count",
    "monthly_max_frp_mw",
    "monthly_sum_frp_mw",
]
APPEND_KEYS = ["adm2_gid", "month_start", "month_end"]


@dataclass(frozen=True)
class IndonesiaReference:
    year: int
    path: Path
    months: pd.DataFrame
    area_by_code: dict[str, float]
    codes: frozenset[str]


@dataclass(frozen=True)
class BoundaryDiagnostics:
    feature_count: int
    repaired_count: int
    simplify_tolerance_m: float
    maximum_relative_area_change_pct: float
    maximum_absolute_area_change_km2: float
    serialized_size_mb: float
    maximum_feature_size_mb: float


def load_indonesia_reference(path: Path) -> IndonesiaReference:
    """Load and validate one teammate AOD file as a date/code/area authority."""
    path = Path(path)
    try:
        year = int(path.stem.split("_", 1)[0])
    except ValueError as exc:
        raise ValueError(f"Reference filename must begin with a year: {path.name}") from exc

    df = pd.read_csv(path)
    required = {
        "ADM2_PCODE",
        "admin2_area_km2",
        "month_start",
        "month_end",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{path.name} is missing required columns: {missing}")

    for column in ("month_start", "month_end"):
        df[column] = pd.to_datetime(df[column], format="mixed", errors="raise").dt.date
    if df["ADM2_PCODE"].isna().any() or df["admin2_area_km2"].isna().any():
        raise ValueError(f"{path.name} contains missing Admin-2 codes or areas")

    codes = frozenset(df["ADM2_PCODE"].astype(str))
    if len(codes) != EXPECTED_ADM2_UNITS:
        raise ValueError(
            f"{path.name}: expected {EXPECTED_ADM2_UNITS} Admin-2 codes, got {len(codes)}"
        )

    schedule_sets = df.groupby(df["ADM2_PCODE"].astype(str), sort=False).apply(
        lambda group: tuple(
            sorted(zip(group["month_start"], group["month_end"], strict=True))
        ),
        include_groups=False,
    )
    canonical = schedule_sets.iloc[0]
    if any(schedule != canonical for schedule in schedule_sets.iloc[1:]):
        raise ValueError(f"{path.name}: Admin-2 units do not share one schedule")
    if len(canonical) != 12:
        raise ValueError(f"{path.name}: expected 12 exposure intervals, got {len(canonical)}")
    for index, (start, end) in enumerate(canonical):
        if end <= start:
            raise ValueError(f"{path.name}: non-positive interval {start}..{end}")
        if index and canonical[index - 1][1] != start:
            raise ValueError(f"{path.name}: exposure intervals are not contiguous")

    months = pd.DataFrame(canonical, columns=["month_start", "month_end"])
    months["filter_end_exclusive"] = months["month_end"]

    areas = (
        df.assign(ADM2_PCODE=df["ADM2_PCODE"].astype(str))
        .groupby("ADM2_PCODE")["admin2_area_km2"]
        .agg(["min", "max"])
    )
    if (areas["max"] - areas["min"] > 1e-9).any():
        raise ValueError(f"{path.name}: Admin-2 area is not constant within the file")
    area_by_code = {code: float(value) for code, value in areas["min"].items()}
    return IndonesiaReference(
        year=year,
        path=path,
        months=months,
        area_by_code=area_by_code,
        codes=codes,
    )


def load_cod_bps_adm2_features(
    shapefile_path: Path,
    *,
    area_by_code: dict[str, float],
    simplify_tolerance_m: float = 10.0,
) -> tuple[list[dict[str, Any]], BoundaryDiagnostics]:
    """Normalize the team COD/BPS shapefile for the existing Earth Engine reducers.

    Invalid rings are repaired without changing their area, then a metric,
    topology-preserving simplification is applied solely to the GEE geometry.
    Output area properties come from the teammate AOD file, not the simplified
    geometry or the shapefile's degree-based ``Shape_Area`` field.
    """
    import geopandas as gpd
    import numpy as np
    from shapely import make_valid
    from shapely.geometry import mapping

    shapefile_path = Path(shapefile_path)
    if not shapefile_path.is_file():
        raise FileNotFoundError(f"Indonesia Admin-2 shapefile not found: {shapefile_path}")
    gdf = gpd.read_file(shapefile_path)
    required = {
        "ADM0_EN",
        "ADM0_PCODE",
        "ADM1_EN",
        "ADM1_PCODE",
        "ADM2_EN",
        "ADM2_PCODE",
    }
    missing = sorted(required - set(gdf.columns))
    if missing:
        raise ValueError(f"Indonesia shapefile is missing required fields: {missing}")
    if gdf.crs is None:
        raise ValueError("Indonesia shapefile has no CRS")
    gdf = gdf.to_crs(4326)
    if len(gdf) != EXPECTED_ADM2_UNITS:
        raise ValueError(
            f"Expected {EXPECTED_ADM2_UNITS} Indonesia Admin-2 features, got {len(gdf)}"
        )
    codes = gdf["ADM2_PCODE"].astype(str)
    if codes.duplicated().any():
        raise ValueError("Indonesia shapefile has duplicate ADM2_PCODE values")
    if set(codes) != set(area_by_code):
        missing_areas = sorted(set(codes) - set(area_by_code))
        extra_areas = sorted(set(area_by_code) - set(codes))
        raise ValueError(
            f"Boundary/reference code mismatch; missing areas={missing_areas[:5]}, "
            f"extra areas={extra_areas[:5]}"
        )

    repaired_count = int((~gdf.geometry.is_valid).sum())
    repaired = gdf.geometry.map(
        lambda geometry: make_valid(
            geometry, method="structure", keep_collapsed=False
        )
    )
    if repaired.is_empty.any() or (~repaired.is_valid).any():
        raise ValueError("Topology repair did not produce valid polygon geometries")

    metric = gpd.GeoSeries(repaired, crs=4326).to_crs(6933)
    original_area_km2 = metric.area.to_numpy() / 1e6
    simplified_metric = metric.simplify(simplify_tolerance_m, preserve_topology=True)
    simplified_area_km2 = simplified_metric.area.to_numpy() / 1e6
    relative_change = np.abs(simplified_area_km2 - original_area_km2) / original_area_km2 * 100
    absolute_change = np.abs(simplified_area_km2 - original_area_km2)
    simplified = gpd.GeoSeries(simplified_metric, crs=6933).to_crs(4326)
    if simplified.is_empty.any() or (~simplified.is_valid).any():
        raise ValueError("Boundary simplification produced an empty or invalid geometry")

    features: list[dict[str, Any]] = []
    serialized_sizes: list[int] = []
    for row, geometry in zip(gdf.itertuples(index=False), simplified, strict=True):
        code = str(row.ADM2_PCODE)
        feature = {
            "type": "Feature",
            "geometry": mapping(geometry),
            "properties": {
                "ADM0_NAME": str(row.ADM0_EN),
                "ADM0_CODE": str(row.ADM0_PCODE),
                "ADM1_NAME": str(row.ADM1_EN),
                "ADM1_CODE": str(row.ADM1_PCODE),
                "ADM2_NAME": str(row.ADM2_EN),
                "ADM2_CODE": code,
                "ADM2_AREA_KM2": float(area_by_code[code]),
                "BOUNDARY_SOURCE": "COD-BPS",
                "BOUNDARY_DATE": "2020-04-01",
            },
        }
        features.append(feature)
        serialized_sizes.append(len(json.dumps(feature, separators=(",", ":"))))

    diagnostics = BoundaryDiagnostics(
        feature_count=len(features),
        repaired_count=repaired_count,
        simplify_tolerance_m=float(simplify_tolerance_m),
        maximum_relative_area_change_pct=float(relative_change.max()),
        maximum_absolute_area_change_km2=float(absolute_change.max()),
        serialized_size_mb=float(sum(serialized_sizes) / 1e6),
        maximum_feature_size_mb=float(max(serialized_sizes) / 1e6),
    )
    return features, diagnostics


def replace_feature_areas(
    features: list[dict[str, Any]], area_by_code: dict[str, float]
) -> list[dict[str, Any]]:
    """Copy normalized features with the selected reference year's area values."""
    output: list[dict[str, Any]] = []
    for feature in features:
        copied = {**feature, "properties": dict(feature["properties"])}
        code = str(copied["properties"]["ADM2_CODE"])
        copied["properties"]["ADM2_AREA_KM2"] = float(area_by_code[code])
        output.append(copied)
    return output


def indonesia_feature_chunks(
    features: list[dict[str, Any]], *, max_count: int = 80, max_bytes: int = 4_000_000
) -> list[list[dict[str, Any]]]:
    """Chunk simplified boundaries below Earth Engine's inline request limit."""
    chunks = _feature_dict_chunks_by_bytes(
        features, max_bytes=max_bytes, max_count=max_count
    )
    if any(
        len(json.dumps(feature, separators=(",", ":"))) > max_bytes
        for feature in features
    ):
        raise ValueError("At least one simplified boundary exceeds the chunk byte budget")
    return chunks


def _flatten_feature_collections(collections: Iterable[ee.FeatureCollection]) -> ee.FeatureCollection:
    return ee.FeatureCollection(list(collections)).flatten()


def fetch_active_viirs_chunk(
    months: pd.DataFrame,
    feature_chunk: list[dict[str, Any]],
    *,
    scale_m: float = 1000.0,
) -> pd.DataFrame:
    """Fetch all 12 VNP14A1 metrics for one boundary chunk in one EE request."""
    regions = ee.FeatureCollection(feature_chunk)
    reducer = ee.Reducer.sum().repeat(2).combine(
        reducer2=ee.Reducer.max(), sharedInputs=False
    )
    monthly_collections: list[ee.FeatureCollection] = []
    for row in months.itertuples(index=False):
        start = row.month_start.isoformat()
        end = row.month_end.isoformat()
        image = ee.Image.cat(
            [
                viirs_monthly_fire_count_image(start, end),
                viirs_monthly_sum_frp_mw_image(start, end),
                viirs_monthly_max_frp_mw_image(start, end),
            ]
        )
        reduced = image.reduceRegions(
            collection=regions,
            reducer=reducer,
            scale=scale_m,
            tileScale=4,
            maxPixelsPerRegion=1e13,
        )

        def _format(feature: ee.Feature, start: str = start, end: str = end) -> ee.Feature:
            sums = ee.List(feature.get("sum"))
            properties = (
                ee.Dictionary(feature.toDictionary(BOUNDARY_PROPERTIES))
                .set("month_start", start)
                .set("month_end", end)
                .set("monthly_fire_count", sums.get(0))
                .set("monthly_sum_frp_mw", sums.get(1))
                .set("monthly_max_frp_mw", feature.get("max"))
            )
            return ee.Feature(None, properties)

        monthly_collections.append(reduced.map(_format))

    response = _flatten_feature_collections(monthly_collections).getInfo()
    return pd.DataFrame([item.get("properties") or {} for item in response["features"]])


def fetch_burned_area_chunk(
    months: pd.DataFrame,
    feature_chunk: list[dict[str, Any]],
    *,
    scale_m: float = 500.0,
) -> pd.DataFrame:
    """Fetch all 12 VNP64A1 burned-area intervals for one chunk in one EE request."""
    regions = ee.FeatureCollection(feature_chunk)
    monthly_collections: list[ee.FeatureCollection] = []
    for row in months.itertuples(index=False):
        start = row.month_start.isoformat()
        end = row.month_end.isoformat()
        image = vnp64a1_burn_km2_image(start, end)
        reduced = image.reduceRegions(
            collection=regions,
            reducer=ee.Reducer.sum(),
            scale=scale_m,
            tileScale=4,
            maxPixelsPerRegion=1e13,
        )

        def _format(feature: ee.Feature, start: str = start, end: str = end) -> ee.Feature:
            burn_value = ee.Algorithms.If(
                feature.propertyNames().contains(MONTHLY_BURN_COLUMN),
                feature.get(MONTHLY_BURN_COLUMN),
                feature.get("sum"),
            )
            properties = (
                ee.Dictionary(feature.toDictionary(BOUNDARY_PROPERTIES))
                .set("month_start", start)
                .set("month_end", end)
                .set(MONTHLY_BURN_COLUMN, burn_value)
            )
            return ee.Feature(None, properties)

        monthly_collections.append(reduced.map(_format))

    response = _flatten_feature_collections(monthly_collections).getInfo()
    return pd.DataFrame([item.get("properties") or {} for item in response["features"]])


def finalize_active_viirs(rows: pd.DataFrame) -> pd.DataFrame:
    """Apply the existing VNP14A1 schema while restoring the exact supplied end dates."""
    long_df = rows.copy()
    long_df = add_window_avg(
        long_df,
        unit_col="ADM2_CODE",
        value_col="monthly_fire_count",
        out_col="avg12_fire_count",
    )
    long_df = add_window_avg(
        long_df,
        unit_col="ADM2_CODE",
        value_col="monthly_sum_frp_mw",
        out_col="avg12_sum_frp_mw",
    )
    exact_ends = {
        pd.Timestamp(start).strftime("%Y-%m-%d"): pd.Timestamp(end).strftime("%Y-%m-%d")
        for start, end in zip(long_df["month_start"], long_df["month_end"], strict=True)
    }
    output = to_adam_viirs_wide_columns(
        long_df, adm0_name="Indonesia", adm0_pcode="ID", unit_level=2
    )
    output["month_end"] = output["month_start"].map(exact_ends)
    if output["month_end"].isna().any():
        raise ValueError("Could not restore exact Indonesia VIIRS month_end values")
    return output.reset_index(drop=True)


def finalize_burned_area(rows: pd.DataFrame) -> pd.DataFrame:
    return to_adam_viirs_burned_area_columns(
        rows, adm0_name="Indonesia", adm0_pcode="ID", unit_level=2
    )


def append_viirs_burned_area(active: pd.DataFrame, burned: pd.DataFrame) -> pd.DataFrame:
    """One-to-one append of VNP64A1 columns onto the VNP14A1 table."""
    for label, frame in (("active", active), ("burned", burned)):
        missing = sorted(set(APPEND_KEYS) - set(frame.columns))
        if missing:
            raise ValueError(f"{label} table is missing append keys: {missing}")
        if frame.duplicated(APPEND_KEYS).any():
            raise ValueError(f"{label} table has duplicate Admin-2/date keys")
    active_keys = set(map(tuple, active[APPEND_KEYS].astype(str).to_numpy()))
    burned_keys = set(map(tuple, burned[APPEND_KEYS].astype(str).to_numpy()))
    if active_keys != burned_keys:
        raise ValueError("VNP14A1 and VNP64A1 key sets differ")
    burn_columns = APPEND_KEYS + [MONTHLY_BURN_COLUMN, AVG12_BURN_COLUMN]
    merged = active.merge(
        burned[burn_columns],
        how="left",
        on=APPEND_KEYS,
        validate="one_to_one",
        indicator=True,
    )
    if len(merged) != len(active) or (merged["_merge"] != "both").any():
        raise ValueError("VNP14A1 and VNP64A1 keys do not match one-to-one")
    return merged.drop(columns="_merge")


def validate_indonesia_export(
    frame: pd.DataFrame,
    reference: IndonesiaReference,
    *,
    value_columns: Iterable[str],
    label: str,
) -> None:
    """Validate exact Admin-2 × interval coverage and nonmissing requested metrics."""
    expected_rows = EXPECTED_ADM2_UNITS * 12
    if len(frame) != expected_rows:
        raise ValueError(f"{label}: expected {expected_rows} rows, got {len(frame)}")
    if frame["adm2_gid"].nunique() != EXPECTED_ADM2_UNITS:
        raise ValueError(f"{label}: expected {EXPECTED_ADM2_UNITS} unique adm2_gid values")
    if set(frame["adm2_gid"].astype(str)) != set(reference.codes):
        raise ValueError(f"{label}: Admin-2 code set differs from {reference.path.name}")
    normalized = frame.copy()
    for column in ("month_start", "month_end"):
        normalized[column] = pd.to_datetime(normalized[column]).dt.date
    expected_dates = set(
        zip(reference.months["month_start"], reference.months["month_end"], strict=True)
    )
    actual_dates = set(zip(normalized["month_start"], normalized["month_end"], strict=True))
    if actual_dates != expected_dates:
        raise ValueError(f"{label}: date intervals differ from {reference.path.name}")
    if normalized.duplicated(APPEND_KEYS).any():
        raise ValueError(f"{label}: duplicate Admin-2/date keys")
    expected_keys = {
        (code, start, end)
        for code in reference.codes
        for start, end in expected_dates
    }
    actual_keys = set(
        zip(
            normalized["adm2_gid"].astype(str),
            normalized["month_start"],
            normalized["month_end"],
            strict=True,
        )
    )
    if actual_keys != expected_keys:
        raise ValueError(f"{label}: incomplete Admin-2 × interval key matrix")
    for column in value_columns:
        if column not in normalized:
            raise ValueError(f"{label}: missing value column {column}")
        if normalized[column].isna().any():
            raise ValueError(f"{label}: {column} contains missing values")

    average_pairs = (
        ("monthly_fire_count", "avg12_fire_count"),
        ("monthly_sum_frp_mw", "avg12_sum_frp_mw"),
        (MONTHLY_BURN_COLUMN, AVG12_BURN_COLUMN),
    )
    for monthly_column, average_column in average_pairs:
        if monthly_column not in normalized or average_column not in normalized:
            continue
        expected_average = normalized.groupby("adm2_gid")[monthly_column].transform("mean")
        if not pd.Series(normalized[average_column]).sub(expected_average).abs().le(1e-8).all():
            raise ValueError(
                f"{label}: {average_column} does not equal the 12-month mean of "
                f"{monthly_column}"
            )


def indonesia_output_paths(root: Path, year: int) -> tuple[Path, Path, Path]:
    processed = Path(root) / "data" / "processed"
    active = processed / "viirs" / f"indonesia_viirs_vnp14a1_{BOUNDARY_TAG}_{year}.csv"
    burned = (
        processed
        / "viirs_burned_area"
        / f"indonesia_viirs_vnp64a1_{BOUNDARY_TAG}_{year}.csv"
    )
    combined = (
        processed
        / "viirs_combined"
        / f"indonesia_viirs_vnp14a1_vnp64a1_{BOUNDARY_TAG}_{year}.csv"
    )
    return active, burned, combined


def write_csv_atomic(frame: pd.DataFrame, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)
    return path
