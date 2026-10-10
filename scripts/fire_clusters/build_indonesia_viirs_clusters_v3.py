#!/usr/bin/env python3
"""Append VNP64A1 burn-patch counts to Indonesia's frozen v2 VIIRS files.

Only cluster counts are rendered. The 16 v2 fields are copied as CSV strings,
including unique VNP14A1 active-fire count, FRP, and VNP64A1 burned area.
Calendar-month VNP64A1 burn-date nodes are cached so adjacent 12-month windows
reuse source downloads. The 8-neighbor, <=5-day graph follows the VACS demo;
Indonesia uses the image's native sinusoidal grid and COD/BPS ADM2 polygons.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import ee
import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fire_clusters import build_vacs_viirs_fire_clusters_v1 as vacs
from scripts.fire_clusters import build_zambia_viirs_fire_clusters_v1 as zambia
from utils.gee_fire_zonal import ee_initialize_from_environ
from utils.indonesia_viirs import EXPECTED_ADM2_UNITS, load_indonesia_reference

V2_DIR = ROOT / "data/processed/viirs_combined_idn_v2"
V3_DIR = ROOT / "data/processed/viirs_combined_idn_v3"
CLUSTER_DIR = ROOT / "data/processed/viirs_fire_clusters/indonesia_codbps_v1"
CACHE_DIR = CLUSTER_DIR / "monthly_native_nodes"
REFERENCE_DIR = ROOT / "indonesia_side_tasks/team_reference"
SHAPEFILE = ROOT / "data/processed/idn_team_data/Indonesia shape files/idn_admbnda_adm2_bps_20200401.shp"
COLLECTION = "NASA/VIIRS/002/VNP64A1"
PROJ4 = "+proj=sinu +R=6371007.181 +lon_0=0 +x_0=0 +y_0=0 +units=m +no_defs"
NATIVE_CRS = "SR-ORG:6974"
NATIVE_TRANSFORM = [463.3127165279165, 0, -20015109.354, 0, -463.3127165279165, 8895604.157333]
PIXEL_M = NATIVE_TRANSFORM[0]
MAX_DATE_GAP = 5
MONTHLY_COLUMN = "monthly_viirs_fire_cluster_count"
AVG12_COLUMN = "avg12_viirs_fire_cluster_count"
KEYS = ["adm2_gid", "month_start", "month_end"]


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def month_starts(start: date, end: date) -> list[date]:
    cursor = date(start.year, start.month, 1)
    last = end - timedelta(days=1)
    values = []
    while cursor <= last:
        values.append(cursor)
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    return values


def next_month(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def read_v2(year: int) -> tuple[Path, pd.DataFrame, pd.DataFrame]:
    path = V2_DIR / f"indonesia_viirs_vnp14a1_{year}_combined.csv"
    if not path.is_file():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, dtype={"adm2_gid": str})
    if len(frame.columns) != 16 or len(frame) != EXPECTED_ADM2_UNITS * 12:
        raise ValueError(f"{path}: expected 16 columns and 6,264 rows")
    for key in ("month_start", "month_end"):
        frame[key] = pd.to_datetime(frame[key], format="mixed").dt.strftime("%Y-%m-%d")
    if frame.duplicated(KEYS).any() or frame.adm2_gid.nunique() != EXPECTED_ADM2_UNITS:
        raise ValueError(f"{path}: duplicate keys or wrong ADM2 count")
    months = frame[["month_start", "month_end"]].drop_duplicates().sort_values("month_start").reset_index(drop=True)
    if len(months) != 12 or not (months.month_end.iloc[:-1].to_numpy() == months.month_start.iloc[1:].to_numpy()).all():
        raise ValueError(f"{path}: expected 12 contiguous exposure months")
    reference = load_indonesia_reference(REFERENCE_DIR / f"{year}_AOD.csv")
    expected_months = reference.months[["month_start", "month_end"]].astype(str)
    if not months.equals(expected_months) or set(frame.adm2_gid) != set(reference.codes):
        raise ValueError(f"{path}: keys differ from Indonesia reference")
    return path, frame, months


def load_boundaries(codes: set[str]) -> tuple[gpd.GeoDataFrame, shapely.Geometry, tuple[int, int, int, int]]:
    raw = gpd.read_file(SHAPEFILE)[["ADM2_PCODE", "geometry"]]
    raw["GID"] = raw.ADM2_PCODE.astype(str)
    if len(raw) != EXPECTED_ADM2_UNITS or raw.GID.duplicated().any() or set(raw.GID) != codes:
        raise ValueError("COD/BPS shape keys differ from v2 codes")
    if raw.crs is None:
        raise ValueError("COD/BPS boundary is missing a CRS")
    repaired = raw.geometry.map(lambda geom: shapely.make_valid(geom, method="structure", keep_collapsed=False))
    if repaired.is_empty.any() or (~repaired.is_valid).any():
        raise ValueError("Invalid COD/BPS boundary after repair")
    raw = gpd.GeoDataFrame(raw[["GID"]], geometry=repaired, crs=raw.crs)
    projected = raw.to_crs(PROJ4)
    country = projected.geometry.union_all()
    if country.is_empty:
        raise ValueError("Empty Indonesia country union")
    shapely.prepare(country)
    minx, miny, maxx, maxy = projected.total_bounds
    x_origin, y_origin = NATIVE_TRANSFORM[2], NATIVE_TRANSFORM[5]
    col0 = math.floor((minx - x_origin) / PIXEL_M) - 1
    col1 = math.ceil((maxx - x_origin) / PIXEL_M) + 1
    row0 = math.floor((y_origin - maxy) / PIXEL_M) - 1
    row1 = math.ceil((y_origin - miny) / PIXEL_M) + 1
    return projected, country, (row0, col0, row1, col1)


def selected_tiles(country: shapely.Geometry, bounds: tuple[int, int, int, int], side: int) -> list[tuple[int, int, int, int]]:
    row0, col0, row1, col1 = bounds
    x_origin, y_origin = NATIVE_TRANSFORM[2], NATIVE_TRANSFORM[5]
    windows = []
    for row in range(row0, row1, side):
        for col in range(col0, col1, side):
            height, width = min(side, row1 - row), min(side, col1 - col)
            footprint = box(
                x_origin + col * PIXEL_M,
                y_origin - (row + height) * PIXEL_M,
                x_origin + (col + width) * PIXEL_M,
                y_origin - row * PIXEL_M,
            )
            if shapely.intersects(country, footprint):
                windows.append((row, col, height, width))
    if not windows:
        raise ValueError("No native-grid tiles intersect Indonesia")
    return windows


def check_projection(image: ee.Image) -> None:
    projection = image.select("Burn_Date").projection().getInfo()
    if projection["crs"] != NATIVE_CRS or not np.allclose(
        projection["transform"], NATIVE_TRANSFORM, rtol=0, atol=1e-7
    ):
        raise ValueError(f"VNP64A1 native projection changed: {projection}")


def download_tile(burn: ee.Image, window: tuple[int, int, int, int], session: requests.Session) -> np.ndarray:
    row, col, height, width = window
    params = {
        "crs": NATIVE_CRS,
        "crs_transform": [PIXEL_M, 0, NATIVE_TRANSFORM[2] + col * PIXEL_M, 0, -PIXEL_M, NATIVE_TRANSFORM[5] - row * PIXEL_M],
        "dimensions": [width, height],
        "format": "NPY",
    }
    last_error = None
    for attempt in range(5):
        try:
            url = burn.getDownloadURL(params)
            response = session.get(url, timeout=240)
            response.raise_for_status()
            array = np.load(io.BytesIO(response.content))["burn_day"]
            if array.shape != (height, width):
                raise ValueError(f"Unexpected tile shape {array.shape}, expected {(height, width)}")
            return array
        except (ee.EEException, requests.RequestException) as exc:
            last_error = exc
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"Failed VNP64A1 tile {window}: {last_error}")


def download_tile_with_session(burn: ee.Image, window: tuple[int, int, int, int]) -> np.ndarray:
    with requests.Session() as session:
        return download_tile(burn, window, session)


def month_nodes(
    month: date,
    country: shapely.Geometry,
    windows: list[tuple[int, int, int, int]],
    session: requests.Session,
    collection: ee.ImageCollection,
    workers: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{month:%Y%m}.npz"
    if cache.exists():
        with np.load(cache) as saved:
            return saved["row"], saved["col"], saved["day"]
    one = collection.filterDate(month.isoformat(), next_month(month).isoformat())
    n_images = int(one.size().getInfo())
    if n_images != 1:
        raise ValueError(f"{month}: expected one VNP64A1 image, got {n_images}")
    image = ee.Image(one.first())
    check_projection(image)
    qa = image.select("QA")
    valid = qa.bitwiseAnd(1).neq(0).And(qa.bitwiseAnd(2).neq(0))
    burn = image.select("Burn_Date").updateMask(valid).unmask(0).toInt16().rename("burn_day")
    rows, cols, days = [], [], []
    x_origin, y_origin = NATIVE_TRANSFORM[2], NATIVE_TRANSFORM[5]
    if workers == 1:
        tile_arrays = (download_tile(burn, window, session) for window in windows)
        tile_pool = None
    else:
        tile_pool = ThreadPoolExecutor(max_workers=workers)
        tile_arrays = tile_pool.map(lambda window: download_tile_with_session(burn, window), windows)
    try:
        for window, array in zip(windows, tile_arrays, strict=True):
            row0, col0, _, _ = window
            local_row, local_col = np.nonzero(array > 0)
            if not len(local_row):
                continue
            burn_doy = array[local_row, local_col].astype(np.int32)
            if np.any((burn_doy < 1) | (burn_doy > (date(month.year + 1, 1, 1) - date(month.year, 1, 1)).days)):
                raise ValueError(f"{month}: invalid burn day-of-year")
            global_row, global_col = local_row + row0, local_col + col0
            inside = shapely.contains_xy(
                country,
                x_origin + (global_col + 0.5) * PIXEL_M,
                y_origin - (global_row + 0.5) * PIXEL_M,
            )
            if not inside.any():
                continue
            rows.append(global_row[inside].astype(np.int32))
            cols.append(global_col[inside].astype(np.int32))
            days.append((date(month.year, 1, 1).toordinal() + burn_doy[inside] - 1).astype(np.int32))
    finally:
        if tile_pool is not None:
            tile_pool.shutdown(wait=True)
    row = np.concatenate(rows) if rows else np.empty(0, dtype=np.int32)
    col = np.concatenate(cols) if cols else np.empty(0, dtype=np.int32)
    day = np.concatenate(days) if days else np.empty(0, dtype=np.int32)
    if len(row):
        keys = np.stack([row, col, day], axis=1)
        if len(np.unique(keys, axis=0)) != len(keys):
            raise ValueError(f"{month}: duplicate native-grid cell/day across tiles")
    tmp = CACHE_DIR / f".{month:%Y%m}.{os.getpid()}.tmp"
    with tmp.open("wb") as handle:
        np.savez_compressed(handle, row=row, col=col, day=day)
    tmp.replace(cache)
    print(f"  {month}: {len(row):,} country burned-cell records across {len(windows)} tiles", flush=True)
    return row, col, day


def cluster_year(
    year: int,
    source_path: Path,
    source: pd.DataFrame,
    months: pd.DataFrame,
    projected: gpd.GeoDataFrame,
    country: shapely.Geometry,
    bounds: tuple[int, int, int, int],
    windows: list[tuple[int, int, int, int]],
    session: requests.Session,
    collection: ee.ImageCollection,
    workers: int,
) -> tuple[pd.DataFrame, dict]:
    start = date.fromisoformat(months.month_start.iloc[0])
    end = date.fromisoformat(months.month_end.iloc[-1])
    observations = [month_nodes(month, country, windows, session, collection, workers) for month in month_starts(start, end)]
    row = np.concatenate([part[0] for part in observations])
    col = np.concatenate([part[1] for part in observations])
    day = np.concatenate([part[2] for part in observations])
    keep = (day >= start.toordinal()) & (day < end.toordinal())
    row, col, day = row[keep], col[keep], day[keep]
    if not len(day):
        raise ValueError(f"{year}: no burned cells in survey window")
    row0, col0, row1, col1 = bounds
    width, height = col1 - col0, row1 - row0
    cells = ((row.astype(np.int64) - row0) * width + col.astype(np.int64) - col0)
    order = np.lexsort((day, cells))
    cells, day = cells[order], day[order]
    unique = np.r_[True, (cells[1:] != cells[:-1]) | (day[1:] != day[:-1])]
    duplicates = len(cells) - int(unique.sum())
    cells, day = cells[unique], day[unique]
    n_patches, labels, n_edges = zambia.label_patches(cells, day, width, height, MAX_DATE_GAP)
    x0 = NATIVE_TRANSFORM[2] + col0 * PIXEL_M
    y0 = NATIVE_TRANSFORM[5] - row0 * PIXEL_M
    grid = (x0, y0, width, height)
    x, y, sizes = zambia.centroids_for_patches(labels, cells, n_patches, grid, scale_m=PIXEL_M)
    assigned, ties, fallback, nearest, farthest_m = vacs.assign_units(
        x, y, projected, labels, cells, grid, PROJ4, scale_m=PIXEL_M
    )
    end_days = np.array([date.fromisoformat(value).toordinal() for value in months.month_end], dtype=np.int32)
    month_index = np.searchsorted(end_days, day, side="right")
    if np.any(month_index >= 12):
        raise ValueError(f"{year}: burned node outside 12 months")
    patch_month = np.unique(labels.astype(np.int64) * 12 + month_index)
    patch_ids = (patch_month // 12).astype(np.int32)
    month_ids = (patch_month % 12).astype(np.int32)
    by_month = pd.DataFrame({"adm2_gid": assigned[patch_ids], "month_index": month_ids})
    by_month = by_month.groupby(["adm2_gid", "month_index"]).size().rename(MONTHLY_COLUMN).reset_index()
    by_month = by_month.merge(months.reset_index(names="month_index"), on="month_index", validate="many_to_one")
    output = source[KEYS].merge(by_month[KEYS + [MONTHLY_COLUMN]], on=KEYS, how="left", validate="one_to_one")
    output[MONTHLY_COLUMN] = output[MONTHLY_COLUMN].fillna(0).astype(int)
    output[AVG12_COLUMN] = output.groupby("adm2_gid")[MONTHLY_COLUMN].transform("mean")
    if output[KEYS].duplicated().any() or len(output) != len(source) or int(output[MONTHLY_COLUMN].sum()) != len(patch_month):
        raise ValueError(f"{year}: cluster output lost or duplicated patch-month counts")
    if not set(output.adm2_gid) == set(source.adm2_gid) or output[[MONTHLY_COLUMN, AVG12_COLUMN]].isna().any().any():
        raise ValueError(f"{year}: incomplete cluster output")
    raster_area = len(cells) * (PIXEL_M / 1000) ** 2
    zonal_area = float(source.monthly_viirs_burned_area_km2.sum())
    area_pct = 100 * (raster_area / zonal_area - 1) if zonal_area else float("nan")
    if not np.isfinite(area_pct) or abs(area_pct) > 5:
        raise ValueError(f"{year}: native raster vs v2 burned-area difference {area_pct:+.2f}% requires review")
    audit = {
        "year": year,
        "window_start": start.isoformat(),
        "window_end_exclusive": end.isoformat(),
        "v2_path": str(source_path.relative_to(ROOT)),
        "v2_sha256": digest(source_path),
        "collection": COLLECTION,
        "projection": NATIVE_CRS,
        "transform": NATIVE_TRANSFORM,
        "qa": "land bit 0 and sufficient-valid-observation bit 1",
        "connectivity": 8,
        "max_adjacent_burn_date_gap_days": MAX_DATE_GAP,
        "raster_burned_cell_day_records": len(cells),
        "duplicate_cell_days_removed": duplicates,
        "graph_edges": n_edges,
        "distinct_patches": n_patches,
        "patch_months": len(patch_month),
        "multi_month_patches": int(np.sum(np.bincount(patch_ids, minlength=n_patches) > 1)),
        "centroid_boundary_ties": ties,
        "centroid_burned_cell_fallbacks": fallback,
        "nearest_polygon_fallbacks": nearest,
        "greatest_nearest_distance_m": farthest_m,
        "minimum_patch_cells": int(sizes.min()),
        "maximum_patch_cells": int(sizes.max()),
        "raster_nominal_burned_km2": raster_area,
        "v2_zonal_burned_km2": zonal_area,
        "raster_vs_zonal_area_pct": area_pct,
    }
    return output, audit


def append_v3(year: int, v2_path: Path, clusters: pd.DataFrame) -> Path:
    destination = V3_DIR / f"indonesia_viirs_vnp14a1_{year}_combined_v3.csv"
    if destination.exists():
        raise FileExistsError(destination)
    lookup = {
        (str(row.adm2_gid), str(row.month_start), str(row.month_end)): (int(row.monthly_viirs_fire_cluster_count), float(row.avg12_viirs_fire_cluster_count))
        for row in clusters.itertuples(index=False)
    }
    if len(lookup) != len(clusters):
        raise ValueError(f"{year}: duplicate cluster keys")
    V3_DIR.mkdir(parents=True, exist_ok=True)
    temporary = V3_DIR / f".{destination.name}.{os.getpid()}.tmp"
    with v2_path.open(newline="", encoding="utf-8") as source, temporary.open("x", newline="", encoding="utf-8") as target:
        reader = csv.DictReader(source)
        original = list(reader.fieldnames or [])
        if len(original) != 16 or any(column in original for column in (MONTHLY_COLUMN, AVG12_COLUMN)):
            raise ValueError(f"{v2_path}: unexpected schema")
        writer = csv.DictWriter(target, fieldnames=original + [MONTHLY_COLUMN, AVG12_COLUMN])
        writer.writeheader()
        written = 0
        for row in reader:
            key = (row["adm2_gid"], pd.Timestamp(row["month_start"]).strftime("%Y-%m-%d"), pd.Timestamp(row["month_end"]).strftime("%Y-%m-%d"))
            if key not in lookup:
                raise ValueError(f"{year}: v2 key missing cluster count: {key}")
            monthly, average = lookup[key]
            row[MONTHLY_COLUMN] = str(monthly)
            row[AVG12_COLUMN] = repr(average)
            writer.writerow(row)
            written += 1
    if written != len(lookup):
        temporary.unlink(missing_ok=True)
        raise ValueError(f"{year}: v3 row count differs from cluster count")
    with v2_path.open(newline="", encoding="utf-8") as left, temporary.open(newline="", encoding="utf-8") as right:
        old = csv.DictReader(left)
        new = csv.DictReader(right)
        original = list(old.fieldnames or [])
        if list(new.fieldnames or []) != original + [MONTHLY_COLUMN, AVG12_COLUMN]:
            raise ValueError(f"{year}: v3 schema mismatch")
        for old_row, new_row in zip(old, new, strict=True):
            if any(old_row[column] != new_row[column] for column in original):
                raise ValueError(f"{year}: original v2 field changed")
    try:
        os.link(temporary, destination)  # atomically publish; never overwrite an existing v3
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def verify_existing_year(year: int, v2_path: Path) -> None:
    """Permit an explicit resume only for a complete, source-matched year."""
    destination = V3_DIR / f"indonesia_viirs_vnp14a1_{year}_combined_v3.csv"
    cluster_path = CLUSTER_DIR / f"indonesia_viirs_clusters_codbps20200401_{year}.csv"
    summary_path = CLUSTER_DIR / f"indonesia_viirs_clusters_codbps20200401_{year}_summary.json"
    if not all(path.is_file() for path in (destination, cluster_path, summary_path)):
        raise ValueError(f"{year}: incomplete existing v3/cluster/summary set")
    audit = json.loads(summary_path.read_text())
    for label, path in (("v2", v2_path), ("v3", destination), ("cluster", cluster_path)):
        if audit.get(f"{label}_sha256") != digest(path):
            raise ValueError(f"{year}: existing {label} hash differs from summary")
    with v2_path.open(newline="", encoding="utf-8") as left, destination.open(newline="", encoding="utf-8") as right:
        old = csv.DictReader(left)
        new = csv.DictReader(right)
        original = list(old.fieldnames or [])
        if list(new.fieldnames or []) != original + [MONTHLY_COLUMN, AVG12_COLUMN]:
            raise ValueError(f"{year}: existing v3 schema differs from v2 + clusters")
        n = 0
        for old_row, new_row in zip(old, new, strict=True):
            if any(old_row[column] != new_row[column] for column in original):
                raise ValueError(f"{year}: existing v3 changed a v2 value")
            n += 1
        if n != EXPECTED_ADM2_UNITS * 12:
            raise ValueError(f"{year}: incomplete existing v3")


def main() -> None:
    parser = argparse.ArgumentParser(description="Indonesia VIIRS v3 cluster-only append")
    parser.add_argument("--years", default="2015,2016,2017,2018,2019,2020,2021,2022,2023,2024")
    parser.add_argument("--tile-side", type=int, default=1536)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true", help="skip only fully verified existing years")
    args = parser.parse_args()
    years = [int(piece.strip()) for piece in args.years.split(",") if piece.strip()]
    if len(years) != len(set(years)) or not years or not set(years).issubset(set(range(2015, 2025))):
        raise ValueError("Select distinct Indonesia years from 2015–2024")
    if args.tile_side < 256 or args.tile_side > 1728:
        raise ValueError("tile-side must be between 256 and 1728")
    if args.workers < 1 or args.workers > 8:
        raise ValueError("workers must be between 1 and 8")
    sources = {year: read_v2(year) for year in years}
    code_sets = [set(item[1].adm2_gid) for item in sources.values()]
    if any(codes != code_sets[0] for codes in code_sets[1:]):
        raise ValueError("ADM2 code sets differ across v2 years")
    projected, country, bounds = load_boundaries(code_sets[0])
    windows = selected_tiles(country, bounds, args.tile_side)
    print(f"COD/BPS units={len(projected)}, grid={bounds}, land tiles={len(windows)} at side={args.tile_side}", flush=True)
    skipped = set()
    for year in years:
        path, frame, months = sources[year]
        output = V3_DIR / f"indonesia_viirs_vnp14a1_{year}_combined_v3.csv"
        if output.exists():
            if not args.resume:
                raise FileExistsError(output)
            verify_existing_year(year, path)
            skipped.add(year)
            print(f"{year}: verified existing v3; skip", flush=True)
            continue
        print(f"{year}: {len(frame)} v2 rows, {months.month_start.iloc[0]}..{months.month_end.iloc[-1]} -> {output}", flush=True)
    if args.dry_run or len(skipped) == len(years):
        return
    print("Earth Engine project:", ee_initialize_from_environ(), flush=True)
    collection = ee.ImageCollection(COLLECTION)
    with requests.Session() as session:
        for year in years:
            if year in skipped:
                continue
            source_path, frame, months = sources[year]
            print(f"=== {year} cluster render ===", flush=True)
            clusters, audit = cluster_year(year, source_path, frame, months, projected, country, bounds, windows, session, collection, args.workers)
            CLUSTER_DIR.mkdir(parents=True, exist_ok=True)
            cluster_path = CLUSTER_DIR / f"indonesia_viirs_clusters_codbps20200401_{year}.csv"
            summary_path = CLUSTER_DIR / f"indonesia_viirs_clusters_codbps20200401_{year}_summary.json"
            if cluster_path.exists() or summary_path.exists():
                raise FileExistsError(f"Existing Indonesia cluster intermediate for {year}")
            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv.tmp", dir=CLUSTER_DIR, delete=False) as handle:
                temp_cluster = Path(handle.name)
                clusters.to_csv(handle, index=False)
            os.link(temp_cluster, cluster_path)
            temp_cluster.unlink()
            destination = append_v3(year, source_path, clusters)
            audit["cluster_path"] = str(cluster_path.relative_to(ROOT))
            audit["cluster_sha256"] = digest(cluster_path)
            audit["v3_path"] = str(destination.relative_to(ROOT))
            audit["v3_sha256"] = digest(destination)
            summary_path.write_text(json.dumps(audit, indent=2) + "\n")
            print(f"Saved {destination}; patches={audit['distinct_patches']:,}; patch-months={audit['patch_months']:,}; area_diff={audit['raster_vs_zonal_area_pct']:+.2f}%", flush=True)


if __name__ == "__main__":
    main()
