#!/usr/bin/env python3
"""Count Nigeria ADM1 dates contributing to the shipped monthly MAIAC AOD means.

Uses the production collection, QA=0 mask, boundaries, and exposure windows.
Counts daily data availability on the product's native sinusoidal grid, a
half-size sampling grid, and the 1 km export grid. Combines the checks in a
daily audit and monthly summary.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ee
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.aod.boundaries import load_boundary_features
from utils.aod.dates import complete_calendar_months, resolve_exposure_window
from utils.aod.export import write_csv_atomic
from utils.aod.maiac import (
    AOD_BAND,
    MAIAC_COLLECTION,
    OUTPUT_BAND,
    aod_collection,
    modis_tiles_for_features,
)
from utils.aod.manifest import load_manifest

JOB_ID = "NGA_2014_ADM1"
OUT_DIR = ROOT / "data" / "processed" / "modis_aod_qa_check"
PRODUCTION_PATH = ROOT / "data" / "processed" / "aod" / "nigeria_maiac_aod_gadm36_adm1_2014.csv"
FINAL_DAILY_PATH = OUT_DIR / "nigeria_adm1_qa0_daily_coverage_2013_2014.csv"
FINAL_MONTHLY_PATH = OUT_DIR / "nigeria_adm1_qa0_monthly_coverage_2013_2014.csv"
NATIVE_DAILY_PATH = OUT_DIR / "nigeria_adm1_qa0_native_daily_coverage_2013_2014.csv"
HALF_DAILY_PATH = OUT_DIR / "nigeria_adm1_qa0_half_native_daily_coverage_2013_2014.csv"
EXPORT_DAILY_PATH = OUT_DIR / "nigeria_adm1_qa0_export_1km_daily_coverage_2013_2014.csv"


def _batches(months: pd.DataFrame, batch_days: int) -> list[list[pd.Timestamp]]:
    result = []
    for month in months.itertuples(index=False):
        dates = list(pd.date_range(month.month_start, month.month_end, inclusive="left"))
        result.extend(dates[i : i + batch_days] for i in range(0, len(dates), batch_days))
    return result


def _count_batch(
    dates: list[pd.Timestamp],
    features: list[dict],
    tiles: list[str],
    native_projection: ee.Projection | None,
    scale_m: float | None,
    count_column: str,
    attempts: int = 3,
) -> pd.DataFrame:
    # A masked zero-band guarantees a band even if a date has no granules.
    empty = ee.Image.constant(0).rename(OUTPUT_BAND).updateMask(ee.Image.constant(0))
    images = []
    for day in dates:
        start = day.date().isoformat()
        end = (day + pd.Timedelta(days=1)).date().isoformat()
        image = (
            aod_collection(start, end, tiles=tiles)
            .merge(ee.ImageCollection([empty]))
            .mean()
            .rename("d" + day.strftime("%Y%m%d"))
        )
        images.append(image)
    grid = {"crs": native_projection} if native_projection is not None else {}
    if scale_m is not None:
        grid["scale"] = scale_m
    reduced = ee.Image.cat(images).reduceRegions(
        collection=ee.FeatureCollection(features),
        reducer=ee.Reducer.count(),
        tileScale=4,
        maxPixelsPerRegion=1e13,
        **grid,
    )
    for attempt in range(attempts):
        try:
            result = reduced.getInfo()
            break
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))

    rows = []
    for feature in result.get("features", []):
        props = feature["properties"]
        for day in dates:
            band = "d" + day.strftime("%Y%m%d")
            count = props.get(band)
            if count is None:
                raise ValueError(f"Missing daily count for {props.get('ADM1_CODE')} {day}")
            rows.append(
                {
                    "adm1_name": props["ADM1_NAME"],
                    "adm1_gid": props["ADM1_CODE"],
                    "date": day.date().isoformat(),
                    count_column: int(count),
                }
            )
    expected = len(features) * len(dates)
    if len(rows) != expected:
        raise ValueError(f"Expected {expected} rows for batch, received {len(rows)}")
    return pd.DataFrame(rows)


def _max_zero_run(values: pd.Series) -> int:
    current = maximum = 0
    for count in values:
        current = current + 1 if count == 0 else 0
        maximum = max(maximum, current)
    return maximum


def _summarize(daily: pd.DataFrame, months: pd.DataFrame, count_column: str) -> pd.DataFrame:
    production = pd.read_csv(PRODUCTION_PATH)
    if production.duplicated(["adm1_gid", "month_start"]).any():
        raise ValueError("Production file has duplicate ADM1-month keys")
    monthly_rows = []
    for month in months.itertuples(index=False):
        start = month.month_start.isoformat()
        end = month.month_end.isoformat()
        window = daily[(daily.date >= start) & (daily.date < end)]
        for gid, group in window.groupby("adm1_gid", sort=True):
            group = group.sort_values("date")
            days = len(group)
            available = int((group[count_column] > 0).sum())
            monthly_rows.append(
                {
                    "adm1_name": group.adm1_name.iloc[0],
                    "adm1_gid": gid,
                    "month_start": start,
                    "month_end_exclusive": end,
                    "calendar_days": days,
                    "days_with_qa0_aod": available,
                    "days_without_qa0_aod": days - available,
                    "pct_days_without_qa0_aod": round(100 * (days - available) / days, 2),
                    "longest_run_without_qa0_aod_days": _max_zero_run(
                        group[count_column]
                    ),
                }
            )
    monthly = pd.DataFrame(monthly_rows)
    monthly = monthly.merge(
        production[["adm1_gid", "month_start", "monthly_mean_aod"]],
        on=["adm1_gid", "month_start"],
        how="left",
        validate="one_to_one",
    )
    return monthly.sort_values(["adm1_name", "month_start"]).reset_index(drop=True)


def _build_combined(months: pd.DataFrame, expected_rows: int) -> None:
    if not all(p.exists() for p in (NATIVE_DAILY_PATH, HALF_DAILY_PATH, EXPORT_DAILY_PATH)):
        print("All three grid audits are needed before writing combined coverage files")
        return
    native = pd.read_csv(NATIVE_DAILY_PATH)
    half = pd.read_csv(HALF_DAILY_PATH)
    export = pd.read_csv(EXPORT_DAILY_PATH)
    keys = ["adm1_name", "adm1_gid", "date"]
    combined = native.merge(half, on=keys, how="outer", validate="one_to_one", indicator=True)
    if len(combined) != expected_rows or not combined._merge.eq("both").all():
        raise ValueError("Native and half-native daily files do not align")
    combined = combined.drop(columns="_merge").merge(
        export, on=keys, how="outer", validate="one_to_one", indicator=True
    )
    if len(combined) != expected_rows or not combined._merge.eq("both").all():
        raise ValueError("Export-grid daily file does not align")
    combined = combined.drop(columns="_merge")
    combined["has_qa0_aod"] = (
        (combined.valid_qa0_native_pixel_count > 0)
        | (combined.valid_qa0_half_native_cell_count > 0)
        | (combined.valid_qa0_export_grid_pixel_count > 0)
    ).astype(int)
    combined = combined.sort_values(["adm1_name", "date"]).reset_index(drop=True)
    monthly = _summarize(combined, months, "has_qa0_aod")
    export_monthly = _summarize(combined, months, "valid_qa0_export_grid_pixel_count")
    monthly = monthly.merge(
        export_monthly[["adm1_gid", "month_start", "days_with_qa0_aod"]].rename(
            columns={"days_with_qa0_aod": "days_with_qa0_aod_at_export_grid"}
        ),
        on=["adm1_gid", "month_start"],
        how="left",
        validate="one_to_one",
    )
    if (monthly.days_with_qa0_aod.eq(0) != monthly.monthly_mean_aod.isna()).any():
        raise ValueError("Combined coverage disagrees with production monthly means")
    write_csv_atomic(combined, FINAL_DAILY_PATH)
    write_csv_atomic(monthly, FINAL_MONTHLY_PATH)
    print(f"Wrote {FINAL_DAILY_PATH} ({len(combined)} rows)")
    print(f"Wrote {FINAL_MONTHLY_PATH} ({len(monthly)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--batch-days", type=int, default=7)
    parser.add_argument(
        "--grid",
        choices=("half-native", "native", "export-1km"),
        default="half-native",
        help="Half-native samples a finer grid to detect partial boundary cells.",
    )
    args = parser.parse_args()
    if args.workers < 1 or args.batch_days < 1:
        parser.error("--workers and --batch-days must be positive")

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass
    ee.Initialize(project=os.environ.get("EARTHENGINE_PROJECT", "ipv-exposure-research"))
    job = next(
        job
        for job in load_manifest(ROOT / "config" / "aod_runs.csv", repo_root=ROOT)
        if job.job_id == JOB_ID
    )
    features = load_boundary_features(job)
    start, end = resolve_exposure_window(ROOT, job.country_wave)
    months = complete_calendar_months(start, end)
    tiles = modis_tiles_for_features(features)
    native_projection = (
        ee.ImageCollection(MAIAC_COLLECTION)
        .filterDate(months.iloc[0].month_start.isoformat(), months.iloc[0].month_end.isoformat())
        .first()
        .select(AOD_BAND)
        .projection()
    )
    if args.grid == "native":
        stem = "nigeria_adm1_qa0_native"
        count_column = "valid_qa0_native_pixel_count"
        scale_m = None
        reduction_projection = native_projection
    elif args.grid == "half-native":
        stem = "nigeria_adm1_qa0_half_native"
        count_column = "valid_qa0_half_native_cell_count"
        scale_m = float(native_projection.nominalScale().getInfo()) / 2
        reduction_projection = native_projection
    else:
        stem = "nigeria_adm1_qa0_export_1km"
        count_column = "valid_qa0_export_grid_pixel_count"
        scale_m = 1000
        reduction_projection = None
    daily_path = OUT_DIR / f"{stem}_daily_coverage_2013_2014.csv"
    monthly_path = OUT_DIR / f"{stem}_monthly_coverage_2013_2014.csv"
    batches = _batches(months, args.batch_days)
    expected_gids = {f["properties"]["ADM1_CODE"] for f in features}
    expected_dates = {d.date().isoformat() for batch in batches for d in batch}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    daily = pd.read_csv(daily_path) if daily_path.exists() else pd.DataFrame()
    if not daily.empty and count_column not in daily:
        raise ValueError(f"Existing daily file {daily_path} does not match {args.grid} grid")
    if not daily.empty and daily.duplicated(["adm1_gid", "date"]).any():
        raise ValueError("Daily checkpoint contains duplicate ADM1-date keys")
    complete_dates = set()
    if not daily.empty:
        for date, group in daily.groupby("date"):
            if set(group.adm1_gid) == expected_gids:
                complete_dates.add(date)
    pending = [batch for batch in batches if any(d.date().isoformat() not in complete_dates for d in batch)]
    print(
        f"{JOB_ID}: {len(features)} ADM1 units, {len(expected_dates)} dates, "
        f"{len(pending)} of {len(batches)} batches pending; tiles={','.join(tiles)}",
        flush=True,
    )
    if pending:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    _count_batch,
                    batch,
                    features,
                    tiles,
                    reduction_projection,
                    scale_m,
                    count_column,
                ): batch
                for batch in pending
            }
            for index, future in enumerate(as_completed(futures), start=1):
                batch = futures[future]
                part = future.result()
                daily = pd.concat([daily, part], ignore_index=True)
                daily = daily.drop_duplicates(["adm1_gid", "date"], keep="last")
                daily = daily.sort_values(["adm1_name", "date"]).reset_index(drop=True)
                write_csv_atomic(daily, daily_path)
                print(
                    f"{index}/{len(pending)} batches complete: "
                    f"{batch[0].date()}..{batch[-1].date()}",
                    flush=True,
                )
    expected_rows = len(expected_gids) * len(expected_dates)
    if len(daily) != expected_rows or set(daily.date) != expected_dates:
        raise ValueError(f"Daily coverage incomplete: {len(daily)} rows vs {expected_rows}")
    if daily[count_column].isna().any() or (daily[count_column] < 0).any():
        raise ValueError("Invalid daily pixel counts")
    monthly = _summarize(daily, months, count_column)
    if len(monthly) != len(expected_gids) * len(months):
        raise ValueError("Monthly coverage row count mismatch")
    if not (monthly.days_with_qa0_aod + monthly.days_without_qa0_aod == monthly.calendar_days).all():
        raise ValueError("Monthly day counts do not reconcile")
    if (monthly.days_with_qa0_aod.eq(0) != monthly.monthly_mean_aod.isna()).any():
        raise ValueError("Coverage disagrees with presence of production monthly mean")
    write_csv_atomic(monthly, monthly_path)
    print(f"Wrote {daily_path} ({len(daily)} rows)")
    print(f"Wrote {monthly_path} ({len(monthly)} rows)")
    _build_combined(months, expected_rows)


if __name__ == "__main__":
    main()
