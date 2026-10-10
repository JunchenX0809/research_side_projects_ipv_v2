#!/usr/bin/env python3
"""Build one VACS VNP64A1 burn-patch exposure panel using Zambia v1 rules.

The active-fire CSV supplies geography and survey-month keys only. The two new
measures come from VNP64A1. This does not link exposure to respondents.
"""

from __future__ import annotations

import argparse
import io
import math
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import ee
import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.fire_clusters.build_zambia_viirs_fire_clusters_v1 as zambia
from utils.gadm_boundaries import gadm_geojson_path
from utils.gee_fire_zonal import ee_initialize_from_environ

SCALE_M = 500
MAX_DATE_GAP = 5
MAX_TILE_CELLS = 3_000_000
MEASURES = [
    "monthly_viirs_burned_area_km2",
    "avg12_viirs_burned_area_km2",
    "monthly_viirs_fire_cluster_count",
    "avg12_viirs_fire_cluster_count",
]


def month_starts(start: date, end: date) -> list[date]:
    current = date(start.year, start.month, 1)
    last = end - timedelta(days=1)
    out = []
    while current <= last:
        out.append(current)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return out


def read_reference(path: Path, level: int, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Use the active-fire CSV only to lock GADM units and the exact 12-month keys."""
    active = pd.read_csv(path)
    gid_col = f"adm{level}_gid"
    if gid_col not in active:
        raise ValueError(f"{path}: expected {gid_col}")
    active["month_start"] = pd.to_datetime(active.month_start, format="mixed", errors="raise").dt.strftime("%Y-%m-%d")
    active["month_end"] = pd.to_datetime(active.month_end, format="mixed", errors="raise").dt.strftime("%Y-%m-%d")
    months = active[["month_start", "month_end"]].drop_duplicates().sort_values("month_start").reset_index(drop=True)
    if len(months) != 12 or months.month_start.iloc[0] != start or months.month_end.iloc[-1] != end:
        raise ValueError("Reference does not match the wave-status 12-month window")
    if not (months.month_end.iloc[:-1].to_numpy() == months.month_start.iloc[1:].to_numpy()).all():
        raise ValueError("Reference survey months are not contiguous")
    gids = sorted(active[gid_col].astype(str).unique())
    keys = [gid_col, "month_start", "month_end"]
    if active.duplicated(keys).any() or len(active) != len(gids) * 12:
        raise ValueError("Reference does not contain exactly one row per GADM unit and month")
    return active, months, gids


def load_boundaries(iso3: str, level: int, version: str, gids: list[str]) -> gpd.GeoDataFrame:
    """Require GADM polygons to match every unit in the active-fire reference."""
    frame = gpd.read_file(gadm_geojson_path(iso3, level, version=version, root=ROOT))
    raw_gid = f"ID_{level}" if f"ID_{level}" in frame else f"GID_{level}"
    if raw_gid not in frame:
        raise ValueError(f"GADM boundary lacks ID_{level}/GID_{level}")
    frame = frame[[raw_gid, "geometry"]].rename(columns={raw_gid: "GID"})
    frame["GID"] = frame.GID.astype(str)
    if frame.GID.duplicated().any() or set(frame.GID) != set(gids):
        raise ValueError(f"GADM {version} ADM{level} polygons do not match active reference IDs")
    if frame.crs is None:
        raise ValueError("GADM boundary file has no CRS")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError("GADM boundary has empty geometry")
    return frame


def projected_grid(boundaries: gpd.GeoDataFrame) -> tuple[str, gpd.GeoDataFrame, tuple[int, int, int, int]]:
    """Choose the country UTM zone and align its raster grid to 500 m cells."""
    center = boundaries.to_crs("EPSG:4326").geometry.union_all().representative_point()
    zone = min(60, max(1, int(math.floor((center.x + 180) / 6) + 1)))
    crs = f"EPSG:{32600 + zone if center.y >= 0 else 32700 + zone}"
    projected = boundaries.to_crs(crs)
    minx, miny, maxx, maxy = projected.total_bounds
    x0 = math.floor(minx / SCALE_M) * SCALE_M - SCALE_M
    y0 = math.ceil(maxy / SCALE_M) * SCALE_M + SCALE_M
    width = math.ceil((maxx - x0) / SCALE_M) + 1
    height = math.ceil((y0 - miny) / SCALE_M) + 1
    return crs, projected, (int(x0), int(y0), int(width), int(height))


def tile_windows(width: int, height: int):
    """Yield raster windows small enough for Earth Engine tile downloads."""
    side = int(math.floor(math.sqrt(MAX_TILE_CELLS)))
    for row0 in range(0, height, side):
        for col0 in range(0, width, side):
            yield row0, col0, min(side, height - row0), min(side, width - col0)


def download_nodes(
    grid: tuple[int, int, int, int], crs: str, country: shapely.Geometry,
    start: date, end: date,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Download aligned grid tiles; admit cells whose center is within GADM country."""
    x0, y0, width, height = grid
    collection = ee.ImageCollection("NASA/VIIRS/002/VNP64A1")
    months = month_starts(start, end)
    available = collection.filterDate(months[0].isoformat(), end.isoformat()).aggregate_array("system:time_start").getInfo()
    present_months = {datetime.fromtimestamp(value / 1000, UTC).strftime("%Y-%m") for value in available}
    missing = [m.strftime("%Y-%m") for m in months if m.strftime("%Y-%m") not in present_months]
    if missing:
        raise ValueError(f"VNP64A1 monthly image(s) absent: {missing}")
    shapely.prepare(country)
    session = requests.Session()
    all_cells, all_days = [], []
    observed = 0
    for month in months:
        following = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        image = ee.Image(collection.filterDate(month.isoformat(), following.isoformat()).first())
        qa = image.select("QA")
        valid = qa.bitwiseAnd(1).neq(0).And(qa.bitwiseAnd(2).neq(0))
        burn = image.select("Burn_Date").updateMask(valid).unmask(0).toInt16().rename("burn_day")
        month_count = 0
        for row0, col0, tile_height, tile_width in tile_windows(width, height):
            params = {
                "crs": crs,
                "crs_transform": [SCALE_M, 0, x0 + col0 * SCALE_M, 0, -SCALE_M, y0 - row0 * SCALE_M],
                "dimensions": [tile_width, tile_height],
                "format": "NPY",
            }
            url = burn.getDownloadURL(params)
            response = session.get(url, timeout=240)
            response.raise_for_status()
            array = np.load(io.BytesIO(response.content))["burn_day"]
            if array.shape != (tile_height, tile_width):
                raise ValueError(f"{month}: unexpected tile size {array.shape}")
            row, col = np.nonzero(array)
            if not len(row):
                continue
            absolute_day = date(month.year, 1, 1).toordinal() + array[row, col].astype(np.int32) - 1
            keep_date = (absolute_day >= start.toordinal()) & (absolute_day < end.toordinal())
            row, col, absolute_day = row[keep_date] + row0, col[keep_date] + col0, absolute_day[keep_date]
            if not len(row):
                continue
            inside = shapely.contains_xy(country, x0 + (col + 0.5) * SCALE_M, y0 - (row + 0.5) * SCALE_M)
            row, col, absolute_day = row[inside], col[inside], absolute_day[inside]
            cells = (row.astype(np.int64) * width + col).astype(np.int32)
            all_cells.append(cells)
            all_days.append(absolute_day.astype(np.int32))
            month_count += len(cells)
        observed += month_count
        print(f"  {month}: {month_count:,} eligible burned-cell observations", flush=True)
    if not all_cells:
        return np.empty(0, np.int32), np.empty(0, np.int32), 0, 0
    cells = np.concatenate(all_cells)
    days = np.concatenate(all_days)
    order = np.lexsort((days, cells))
    cells, days = cells[order], days[order]
    unique = np.r_[True, (cells[1:] != cells[:-1]) | (days[1:] != days[:-1])]
    return cells[unique], days[unique], observed - int(unique.sum()), len(months)


def assign_units(
    x: np.ndarray, y: np.ndarray, projected: gpd.GeoDataFrame,
    labels: np.ndarray, cells: np.ndarray, grid: tuple[int, int, int, int], crs: str,
    scale_m: float = SCALE_M,
) -> tuple[np.ndarray, int, int, int, float]:
    """Assign each patch by centroid, then burned-cell and nearest-polygon fallbacks."""
    points = gpd.GeoDataFrame({"patch_id": np.arange(len(x), dtype=np.int32)}, geometry=gpd.points_from_xy(x, y), crs=crs)
    joined = gpd.sjoin(points, projected, how="left", predicate="intersects")
    ties = int(joined.index.duplicated().sum())
    joined = joined.sort_values(["patch_id", "GID"], na_position="last").drop_duplicates("patch_id")
    gid = joined.set_index("patch_id").GID.reindex(np.arange(len(x)))
    missing = np.flatnonzero(gid.isna().to_numpy())
    if len(missing):
        x0, y0, width, _ = grid
        ordered = np.argsort(labels, kind="stable")
        sorted_labels = labels[ordered]
        fallback = []
        for patch in missing:
            lo = np.searchsorted(sorted_labels, patch, side="left")
            hi = np.searchsorted(sorted_labels, patch, side="right")
            candidate = cells[ordered[lo:hi]]
            candidate_x = x0 + ((candidate % width) + 0.5) * scale_m
            candidate_y = y0 - ((candidate // width) + 0.5) * scale_m
            near = np.argmin((candidate_x - x[patch]) ** 2 + (candidate_y - y[patch]) ** 2)
            fallback.append((int(patch), float(candidate_x[near]), float(candidate_y[near])))
        fallback_points = gpd.GeoDataFrame(
            {"patch_id": [item[0] for item in fallback]},
            geometry=gpd.points_from_xy([item[1] for item in fallback], [item[2] for item in fallback]), crs=crs,
        )
        fallback_join = gpd.sjoin(fallback_points, projected, how="left", predicate="intersects")
        fallback_join = fallback_join.sort_values(["patch_id", "GID"], na_position="last").drop_duplicates("patch_id")
        for row in fallback_join.itertuples():
            if isinstance(row.GID, str):
                gid.iloc[row.patch_id] = row.GID
    unresolved_ids = np.flatnonzero(gid.isna().to_numpy())
    farthest_m = 0.0
    if len(unresolved_ids):
        nearest = gpd.sjoin_nearest(points.iloc[unresolved_ids], projected, how="left", distance_col="distance_m")
        nearest = nearest.sort_values(["patch_id", "distance_m", "GID"]).drop_duplicates("patch_id")
        farthest_m = float(nearest.distance_m.max())
        for row in nearest.itertuples():
            if isinstance(row.GID, str):
                gid.iloc[row.patch_id] = row.GID
    if gid.isna().any():
        raise ValueError(f"{int(gid.isna().sum())} patches have no GADM assignment")
    return gid.to_numpy(dtype=str), ties, len(missing), len(unresolved_ids), farthest_m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wave", required=True)
    ap.add_argument("--active", type=Path, required=True)
    ap.add_argument("--burned", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--iso3", required=True)
    ap.add_argument("--level", type=int, choices=(1, 2), required=True)
    ap.add_argument("--gadm-version", choices=("36", "40", "41"), required=True)
    ap.add_argument("--window-start", required=True)
    ap.add_argument("--window-end", required=True)
    args = ap.parse_args()
    gid_col = f"adm{args.level}_gid"
    active, months, gids = read_reference(args.active, args.level, args.window_start, args.window_end)
    boundaries = load_boundaries(args.iso3, args.level, args.gadm_version, gids)
    crs, projected, grid = projected_grid(boundaries)
    print(f"{args.wave} ADM{args.level}: {len(gids)} units, grid {grid[2]} x {grid[3]} {crs}", flush=True)
    country = projected.geometry.union_all()
    if country.is_empty:
        raise ValueError("Empty country polygon")
    burned = pd.read_csv(args.burned)
    for key in ("month_start", "month_end"):
        burned[key] = pd.to_datetime(burned[key], format="mixed", errors="raise").dt.strftime("%Y-%m-%d")
    keys = [gid_col, "month_start", "month_end"]
    if burned.duplicated(keys).any() or set(map(tuple, burned[keys].to_numpy())) != set(map(tuple, active[keys].to_numpy())):
        raise ValueError("Burned-area keys do not match the wave's active reference exactly")
    if burned[MEASURES[:2]].isna().any().any() or (burned[MEASURES[:2]] < 0).any().any():
        raise ValueError("Burned-area source contains missing or negative measures")
    mean = burned.groupby(gid_col)[MEASURES[0]].transform("mean")
    if not np.allclose(mean, burned[MEASURES[1]], rtol=0, atol=1e-8):
        raise ValueError("Burned-area 12-month mean does not equal its monthly values")
    print("Earth Engine project:", ee_initialize_from_environ(), flush=True)
    start, end = date.fromisoformat(args.window_start), date.fromisoformat(args.window_end)
    cells, days, duplicates, images = download_nodes(grid, crs, country, start, end)
    if not len(cells):
        raise ValueError("No burned cells in the 12-month window; inspect source coverage")
    # Patch graph and centroids come from scripts/fire_clusters/build_zambia_viirs_fire_clusters_v1.py.
    count, labels, edges = zambia.label_patches(cells, days, grid[2], grid[3], MAX_DATE_GAP)
    zambia.CRS = crs
    x, y, patch_sizes = zambia.centroids_for_patches(labels, cells, count, grid)
    unit, ties, fallback, nearest, farthest_m = assign_units(x, y, projected, labels, cells, grid, crs)
    end_ordinals = np.array([date.fromisoformat(d).toordinal() for d in months.month_end], dtype=np.int32)
    month_index = np.searchsorted(end_ordinals, days, side="right")
    if np.any(month_index >= 12):
        raise ValueError("Burned cell lies outside survey windows")
    patch_month = np.unique(labels.astype(np.int64) * 12 + month_index)
    patch_ids = (patch_month // 12).astype(np.int32)
    month_ids = (patch_month % 12).astype(np.int32)
    multi_month = int(np.sum(np.bincount(patch_ids, minlength=count) > 1))
    monthly = pd.DataFrame({gid_col: unit[patch_ids], "month_index": month_ids})
    monthly = monthly.groupby([gid_col, "month_index"]).size().rename(MEASURES[2]).reset_index()
    monthly = monthly.merge(months.reset_index(names="month_index"), on="month_index", validate="many_to_one").drop(columns="month_index")
    output = burned.merge(monthly, on=keys, how="left", validate="one_to_one")
    output[MEASURES[2]] = output[MEASURES[2]].fillna(0).astype(int)
    output[MEASURES[3]] = output.groupby(gid_col)[MEASURES[2]].transform("mean")
    if len(output) != len(gids) * 12 or output.duplicated(keys).any():
        raise ValueError("Output does not have one row per GADM unit and month")
    if int(output[MEASURES[2]].sum()) != len(patch_month):
        raise ValueError("Patch-month count was lost or duplicated")
    if output[MEASURES].isna().any().any() or (output[MEASURES] < 0).any().any():
        raise ValueError("Output has missing or negative measures")
    raster_area = len(cells) * (SCALE_M / 1000) ** 2
    source_area = float(burned[MEASURES[0]].sum())
    area_pct = 100 * (raster_area / source_area - 1) if source_area else float("nan")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_{gid_col.replace('_gid', '')}" if args.wave.lower().startswith("uganda") else ""
    stem = f"{args.wave.lower().replace(' ', '_')}_viirs_clusters_gadm{args.gadm_version}{suffix}_v1"
    csv_path = args.out_dir / f"{stem}.csv"
    summary_path = args.out_dir / f"{stem}_summary.md"
    output.to_csv(csv_path.with_suffix(".csv.tmp"), index=False)
    csv_path.with_suffix(".csv.tmp").replace(csv_path)
    summary_path.write_text(
        f"# {args.wave} ADM{args.level} VIIRS burn-patch v1\n\n"
        f"Generated {date.today().isoformat()} from VNP64A1; geographic exposure only. "
        f"QA land+valid; 8-neighbor; adjacent burn dates <=5 days; all patch sizes; "
        f"one centroid-assigned GADM unit; count in each survey month with new burn pixels. "
        f"This is a burn-patch count, not verified ignitions.\n\n"
        f"| Audit | Result |\n| --- | ---: |\n"
        f"| Window | {start}..{end} (end exclusive) |\n"
        f"| Level / GADM | ADM{args.level} / {args.gadm_version} |\n"
        f"| GADM units / rows | {len(gids):,} / {len(output):,} |\n"
        f"| Projection / grid | {crs} / {SCALE_M} m |\n"
        f"| Calendar images queried | {images} |\n"
        f"| Distinct patches | {count:,} |\n"
        f"| Multi-month patches | {multi_month:,} |\n"
        f"| Patch-months | {len(patch_month):,} |\n"
        f"| Burned cell-day observations | {len(cells):,} |\n"
        f"| Duplicate cell-day records removed | {duplicates:,} |\n"
        f"| Graph links | {edges:,} |\n"
        f"| Centroid boundary ties | {ties:,} |\n"
        f"| Outside-centroid burned-cell fallbacks | {fallback:,} |\n"
        f"| Nearest-polygon fallbacks | {nearest:,} |\n"
        f"| Greatest nearest-polygon distance | {farthest_m:,.1f} m |\n"
        f"| Smallest / largest patch | {int(patch_sizes.min()):,} / {int(patch_sizes.max()):,} cells |\n"
        f"| Nominal raster area / zonal burned area | {raster_area:,.2f} / {source_area:,.2f} km² ({area_pct:+.2f}%) |\n\n"
        f"The burned-cell raster is downloaded in aligned tiles, resampled to the fixed UTM grid, "
        f"and clipped by GADM country polygon at cell centers before patch labeling. "
        f"Zonal burned area uses Earth Engine pixel-area reductions, so small area differences are expected. "
        f"The first and last survey windows censor activity beyond the observed year. "
        f"A large connected patch may contain several physical fires.\n"
    )
    print(f"Saved {csv_path} and {summary_path}; area difference {area_pct:+.2f}%", flush=True)
    if not np.isfinite(area_pct) or abs(area_pct) > 5:
        raise ValueError(f"Raster and zonal burned area differ by {area_pct:+.2f}%; inspect before using")


if __name__ == "__main__":
    main()
