#!/usr/bin/env python3
"""Zambia VNP64A1 patch-month demo: one centroid district, monthly new burning.

This is a FRY-inspired *burn-patch* trial, not a validated individual-ignition
count.  Pixels are joined across survey-month and district borders using
8-neighbor adjacency and a <=5-day difference in estimated burn dates.  Each
patch has one ID and one centroid district; it contributes one count in every
survey month containing a newly burned pixel.  Thus monthly counts are integer
patch-month counts, whereas the same patch may occur in more than one month.

Run with the repository's arm64 virtual environment::

   .venv/bin/python -m scripts.fire_clusters.build_zambia_viirs_fire_clusters_v1

The 500 m pixel grid is a fixed UTM 35S grid. It is a v1 resampling of the
native VNP64A1 sinusoidal grid; cluster counts are sensitive to this choice.
"""

from __future__ import annotations

import io
import math
import sys
from datetime import date
from pathlib import Path

import ee
import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.gee_fire_zonal import ee_initialize_from_environ


ADM2_PATH = ROOT / "data/cleaned_survey_data/zambia_link_v1/gadm36_ZMB_shp/gadm36_ZMB_2.shp"
ADM0_PATH = ROOT / "data/cleaned_survey_data/zambia_link_v1/gadm36_ZMB_shp/gadm36_ZMB_0.shp"
BURNED_CSV = ROOT / "data/processed/viirs_burned_area/zambia_viirs_vnp64a1_gadm36_2014.csv"
ACTIVE_CSV = ROOT / "data/processed/viirs/zambia_viirs_vnp14a1_gadm36_2014.csv"
OUT_DIR = ROOT / "data/processed/viirs_fire_clusters/zambia_fire_cluster_demo"
OUT_CSV = OUT_DIR / "zambia_viirs_clusters_gadm36_2014_v1.csv"
SUMMARY = OUT_DIR / "zambia_viirs_clusters_gadm36_2014_v1_summary.md"
CRS = "EPSG:32735"
SCALE_M = 500
MAX_DATE_GAP = 5


def grid_for_country(adm2: gpd.GeoDataFrame) -> tuple[int, int, int, int]:
    """Align a padded 500 m UTM grid and reject downloads above Earth Engine limits."""
    minx, miny, maxx, maxy = adm2.to_crs(CRS).total_bounds
    x0 = math.floor(minx / SCALE_M) * SCALE_M - SCALE_M
    y0 = math.ceil(maxy / SCALE_M) * SCALE_M + SCALE_M
    width = math.ceil((maxx - x0) / SCALE_M) + 1
    height = math.ceil((y0 - miny) / SCALE_M) + 1
    if width >= 10000 or height >= 10000 or width * height * 2 >= 32_000_000:
        raise ValueError("Zambia grid exceeds Earth Engine small-download limits")
    return int(x0), int(y0), int(width), int(height)


def calendar_months(start: date, end_exclusive: date) -> list[date]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end_exclusive.year, end_exclusive.month):
        months.append(date(year, month, 1))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def download_burn_nodes(
    country_geojson: dict, grid: tuple[int, int, int, int], start: date, end: date
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return sorted unique (grid-cell, absolute burn-day) observations."""
    x0, y0, width, height = grid
    country = ee.Geometry(country_geojson)
    pieces_cell, pieces_day = [], []
    observed = 0
    params = {
        "crs": CRS,
        "crs_transform": [SCALE_M, 0, x0, 0, -SCALE_M, y0],
        "dimensions": [width, height],
        "format": "NPY",
    }
    session = requests.Session()
    for month in calendar_months(start, end):
        following = date(month.year + 1, 1, 1) if month.month == 12 else date(month.year, month.month + 1, 1)
        image = ee.Image(
            ee.ImageCollection("NASA/VIIRS/002/VNP64A1")
            .filterDate(month.isoformat(), following.isoformat())
            .first()
        )
        qa = image.select("QA")
        valid = qa.bitwiseAnd(1).neq(0).And(qa.bitwiseAnd(2).neq(0))
        burn = (
            image.select("Burn_Date")
            .updateMask(valid)
            .clip(country)
            .unmask(0)
            .toInt16()
            .rename("burn_day")
        )
        url = burn.getDownloadURL(params)
        response = session.get(url, timeout=180)
        response.raise_for_status()
        array = np.load(io.BytesIO(response.content))["burn_day"]
        if array.shape != (height, width):
            raise ValueError(f"{month}: unexpected image grid {array.shape}")
        row, col = np.nonzero(array)
        day = array[row, col].astype(np.int32)
        absolute_day = date(month.year, 1, 1).toordinal() + day - 1
        keep = (absolute_day >= start.toordinal()) & (absolute_day < end.toordinal())
        cells = (row[keep] * width + col[keep]).astype(np.int32)
        days = absolute_day[keep].astype(np.int32)
        pieces_cell.append(cells)
        pieces_day.append(days)
        observed += len(cells)
        print(f"  {month}: {len(cells):,} eligible burned-cell observations", flush=True)
    cells = np.concatenate(pieces_cell)
    days = np.concatenate(pieces_day)
    if len(cells) == 0:
        return cells, days, 0
    order = np.lexsort((days, cells))
    cells, days = cells[order], days[order]
    unique = np.empty(len(cells), dtype=bool)
    unique[0] = True
    unique[1:] = (cells[1:] != cells[:-1]) | (days[1:] != days[:-1])
    return cells[unique], days[unique], observed - int(unique.sum())


def label_patches(cells: np.ndarray, days: np.ndarray, width: int, height: int, gap: int) -> tuple[int, np.ndarray, int]:
    """Connected components of neighboring cell-day nodes, even across months."""
    n = len(cells)
    if n == 0:
        return 0, np.empty(0, dtype=np.int32), 0
    if np.any(cells[1:] < cells[:-1]):
        raise ValueError("Burn nodes must be sorted by grid cell")
    row, col = cells // width, cells % width
    source_parts, target_parts = [], []
    sources = np.arange(n, dtype=np.int32)

    # Same physical cell may have two burn records near a calendar-month edge.
    same = (cells[1:] == cells[:-1]) & (days[1:] - days[:-1] <= gap)
    src = np.flatnonzero(same).astype(np.int32)
    source_parts.append(src)
    target_parts.append(src + 1)

    # Only the forward half of the queen neighborhood is needed for an
    # undirected graph: right, down-left, down, down-right.
    for dr, dc in ((0, 1), (1, -1), (1, 0), (1, 1)):
        valid = (row + dr < height) & (col + dc >= 0) & (col + dc < width)
        possible_source = sources[valid]
        wanted = cells[valid] + dr * width + dc
        left = np.searchsorted(cells, wanted, side="left")
        right = np.searchsorted(cells, wanted, side="right")
        # A cell can appear in more than one monthly source image. Usually it
        # appears once; handle all records without silently dropping repeats.
        max_records = int(np.max(right - left, initial=0))
        for offset in range(max_records):
            possible_target = left + offset
            exists = possible_target < right
            if not exists.any():
                break
            from_idx = possible_source[exists]
            to_idx = possible_target[exists].astype(np.int32)
            close = np.abs(days[from_idx] - days[to_idx]) <= gap
            source_parts.append(from_idx[close])
            target_parts.append(to_idx[close])
    source = np.concatenate(source_parts)
    target = np.concatenate(target_parts)
    # SciPy's sparse graph labels transitive patches without allocating an n-by-n dense matrix.
    graph = coo_matrix((np.ones(len(source), dtype=np.uint8), (source, target)), shape=(n, n)).tocsr()
    count, labels = connected_components(graph, directed=False, return_labels=True)
    return int(count), labels.astype(np.int32), len(source)


def centroids_for_patches(labels: np.ndarray, cells: np.ndarray, count: int, grid: tuple[int, int, int, int], scale_m: float = SCALE_M) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mean coordinates of distinct burned cell centers for each patch."""
    x0, y0, width, height = grid
    key = np.unique(labels.astype(np.int64) * (width * height) + cells.astype(np.int64))
    patch = (key // (width * height)).astype(np.int32)
    cell = (key % (width * height)).astype(np.int32)
    n_cells = np.bincount(patch, minlength=count)
    mean_col = np.bincount(patch, weights=(cell % width).astype(float), minlength=count) / n_cells
    mean_row = np.bincount(patch, weights=(cell // width).astype(float), minlength=count) / n_cells
    x = x0 + (mean_col + 0.5) * scale_m
    y = y0 - (mean_row + 0.5) * scale_m
    return x, y, n_cells


def assign_districts(
    x: np.ndarray, y: np.ndarray, adm2: gpd.GeoDataFrame, labels: np.ndarray,
    cells: np.ndarray, grid: tuple[int, int, int, int]
) -> tuple[np.ndarray, int, int, int, float]:
    """Point-in-polygon assignment; documented fallback for boundary/outside points."""
    projected = adm2[["GID_2", "geometry"]].to_crs(CRS)
    points = gpd.GeoDataFrame(
        {"patch_id": np.arange(len(x), dtype=np.int32)},
        geometry=gpd.points_from_xy(x, y), crs=CRS,
    )
    joined = gpd.sjoin(points, projected, how="left", predicate="intersects")
    multiple = int(joined.index.duplicated().sum())
    joined = joined.sort_values(["patch_id", "GID_2"], na_position="last").drop_duplicates("patch_id")
    gid = joined.set_index("patch_id")["GID_2"].reindex(np.arange(len(x)))
    missing = np.flatnonzero(gid.isna().to_numpy())
    if len(missing):
        # A centroid of a curved/concave patch can be outside the country. Use
        # the burned cell closest to that centroid, then assign that point.
        x0, y0, width, _ = grid
        ordered = np.argsort(labels, kind="stable")
        sorted_labels = labels[ordered]
        fallback_cell = []
        for patch_id in missing:
            lo = np.searchsorted(sorted_labels, patch_id, side="left")
            hi = np.searchsorted(sorted_labels, patch_id, side="right")
            candidate = cells[ordered[lo:hi]]
            candidate_x = x0 + ((candidate % width) + 0.5) * SCALE_M
            candidate_y = y0 - ((candidate // width) + 0.5) * SCALE_M
            nearest = np.argmin((candidate_x - x[patch_id]) ** 2 + (candidate_y - y[patch_id]) ** 2)
            fallback_cell.append((int(patch_id), float(candidate_x[nearest]), float(candidate_y[nearest])))
        fallback = gpd.GeoDataFrame(
            {"patch_id": [v[0] for v in fallback_cell]},
            geometry=gpd.points_from_xy([v[1] for v in fallback_cell], [v[2] for v in fallback_cell]),
            crs=CRS,
        )
        fallback_join = gpd.sjoin(fallback, projected, how="left", predicate="intersects")
        fallback_join = fallback_join.sort_values(["patch_id", "GID_2"], na_position="last").drop_duplicates("patch_id")
        for row in fallback_join.itertuples():
            if isinstance(row.GID_2, str):
                gid.iloc[row.patch_id] = row.GID_2
    unresolved_ids = np.flatnonzero(gid.isna().to_numpy())
    farthest_m = 0.0
    if len(unresolved_ids):
        # Edge pixels admitted by EE's polygon clip need not have centers inside
        # a GADM polygon after reprojection. Choose the closest ADM2 polygon.
        outside = points.iloc[unresolved_ids]
        nearest = gpd.sjoin_nearest(outside, projected, how="left", distance_col="distance_m")
        nearest = nearest.sort_values(["patch_id", "distance_m", "GID_2"]).drop_duplicates("patch_id")
        farthest_m = float(nearest.distance_m.max())
        for row in nearest.itertuples():
            if isinstance(row.GID_2, str):
                gid.iloc[row.patch_id] = row.GID_2
    unresolved = int(gid.isna().sum())
    if unresolved:
        raise ValueError(f"{unresolved} burn patches have no GADM ADM2 assignment")
    return gid.to_numpy(dtype=str), multiple, len(missing), len(unresolved_ids), farthest_m


def main() -> None:
    active = pd.read_csv(ACTIVE_CSV)
    burned = pd.read_csv(BURNED_CSV)
    months = active[["month_start", "month_end"]].drop_duplicates().copy()
    months["month_start"] = pd.to_datetime(months["month_start"])
    months["month_end"] = pd.to_datetime(months["month_end"])
    months = months.sort_values("month_start").reset_index(drop=True)
    if len(months) != 12 or not (months.month_end.iloc[:-1].to_numpy() == months.month_start.iloc[1:].to_numpy()).all():
        raise ValueError("Expected 12 contiguous Zambia survey intervals")
    start, end = months.month_start.iloc[0].date(), months.month_end.iloc[-1].date()
    adm2 = gpd.read_file(ADM2_PATH)
    expected_gids = set(active.adm2_gid.astype(str))
    if len(adm2) != 72 or set(adm2.GID_2.astype(str)) != expected_gids:
        raise ValueError("GADM ADM2 districts do not match the Zambia reference")
    grid = grid_for_country(adm2)
    print(f"Grid {grid[2]} x {grid[3]}, {CRS}, {SCALE_M} m", flush=True)
    print("Earth Engine project:", ee_initialize_from_environ(), flush=True)
    country = gpd.read_file(ADM0_PATH)
    cells, days, duplicates = download_burn_nodes(country.geometry.iloc[0].__geo_interface__, grid, start, end)
    print(f"Unique burn observations: {len(cells):,}; repeated cell-date records removed: {duplicates:,}", flush=True)
    count, labels, edges = label_patches(cells, days, grid[2], grid[3], MAX_DATE_GAP)
    print(f"Patches: {count:,}; graph links: {edges:,}", flush=True)
    x, y, n_cells = centroids_for_patches(labels, cells, count, grid)
    gid, boundary_ties, fallback_count, nearest_count, farthest_m = assign_districts(x, y, adm2, labels, cells, grid)
    end_ordinal = np.array([d.date().toordinal() for d in months.month_end], dtype=np.int32)
    month_index = np.searchsorted(end_ordinal, days, side="right")
    if np.any(month_index >= 12):
        raise ValueError("Burn observation fell outside 12-month survey window")
    patch_month = np.unique(labels.astype(np.int64) * 12 + month_index)
    patch_ids = (patch_month // 12).astype(np.int32)
    month_ids = (patch_month % 12).astype(np.int32)
    multi_month = int(np.sum(np.bincount(patch_ids, minlength=count) > 1))
    monthly = pd.DataFrame({"adm2_gid": gid[patch_ids], "month_index": month_ids})
    monthly = monthly.groupby(["adm2_gid", "month_index"]).size().rename("monthly_viirs_fire_cluster_count").reset_index()
    monthly = monthly.merge(
        months.reset_index(names="month_index"), on="month_index", how="left", validate="many_to_one"
    ).drop(columns="month_index")
    for key in ("month_start", "month_end"):
        monthly[key] = monthly[key].dt.strftime("%Y-%m-%d")
        burned[key] = pd.to_datetime(burned[key]).dt.strftime("%Y-%m-%d")
    keys = ["adm2_gid", "month_start", "month_end"]
    if burned.duplicated(keys).any():
        raise ValueError("Duplicate keys in burned-area source")
    output = burned.merge(monthly, on=keys, how="left", validate="one_to_one")
    output["monthly_viirs_fire_cluster_count"] = output["monthly_viirs_fire_cluster_count"].fillna(0).astype(int)
    output["avg12_viirs_fire_cluster_count"] = output.groupby("adm2_gid")["monthly_viirs_fire_cluster_count"].transform("mean")
    if len(output) != 864 or output[keys].drop_duplicates().shape[0] != 864:
        raise ValueError("Output is not exactly 72 ADM2 districts x 12 months")
    if int(output.monthly_viirs_fire_cluster_count.sum()) != len(patch_month):
        raise ValueError("Patch-month count was duplicated or lost during district assignment")
    if set(output.adm2_gid) != expected_gids:
        raise ValueError("Output ADM2 units differ from the Zambia reference")
    nominal_pixel_area = (SCALE_M / 1000) ** 2
    raster_nominal_km2 = len(cells) * nominal_pixel_area
    source_burned_km2 = float(burned.monthly_viirs_burned_area_km2.sum())
    area_difference_pct = 100 * (raster_nominal_km2 / source_burned_km2 - 1)
    if abs(area_difference_pct) > 5:
        raise ValueError(f"Cluster raster and burned-area source differ by {area_difference_pct:.1f}% in area")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUT_CSV, index=False)
    summary = f"""# Zambia VIIRS burn-patch v1 result

**Trial, generated from VNP64A1 on {date.today().isoformat()}.** Method: 500 m UTM 35S grid; QA land and valid observations; 8-neighbor connectivity; adjacent estimated burn dates <= {MAX_DATE_GAP} days; all patch sizes included; patch centroid assigned to one GADM 3.6 ADM2 district; one count in every survey month with new burned pixels. A patch is not necessarily one independently ignited fire.

| Audit item | Result |
| --- | ---: |
| ADM2 x survey-month rows | {len(output):,} |
| Distinct patches across full 12-month window | {count:,} |
| Patches with new burned pixels in more than one survey month | {multi_month:,} |
| Total patch-months (sum of monthly district counts) | {len(patch_month):,} |
| Unique burned cell-day observations | {len(cells):,} |
| Repeated identical cell-day records removed | {duplicates:,} |
| Centroid points intersecting multiple districts (lexical GID tie-break) | {boundary_ties:,} |
| Centroids outside all districts (closest burned pixel fallback) | {fallback_count:,} |
| Still outside after pixel fallback (nearest GADM district) | {nearest_count:,} |
| Greatest nearest-district fallback distance (m) | {farthest_m:,.1f} |
| Smallest / largest patch, distinct pixels | {int(n_cells.min()):,} / {int(n_cells.max()):,} |
| Largest patch, nominal raster area | {int(n_cells.max()) * nominal_pixel_area:,.2f} km² |
| Patches with exactly 1 burned pixel | {int(np.sum(n_cells == 1)):,} |
| Patches with fewer than 5 burned pixels | {int(np.sum(n_cells < 5)):,} |
| Raster nominal pixel area vs source burned area | {raster_nominal_km2:,.2f} vs {source_burned_km2:,.2f} km² ({area_difference_pct:+.2f}%) |

The cluster columns are **monthly counts of burn patches assigned by centroid**, not active-fire detections, fractional shares, or verified individual ignitions. The 12-month cluster column is the arithmetic mean of monthly patch counts. The VIIRS burned-area columns are copied exactly from the already generated Zambia source, and may use a different raster reduction grid near district boundaries. Survey month starts are included; ends are excluded. A component continuing across a month boundary keeps one patch ID but appears in each month with newly burned pixels. The first and last survey windows censor events outside the observed year; they can still contribute to the observed month.

**Methods still to review:** sensitivity to the 5-day date gap, small-patch inclusion, and UTM resampling. The centroid can lie outside its own burned pixels, especially for curved patches. Fallbacks and boundary ties are reported above. A very large patch can indicate that several physical fires were connected by this rule; the patch count must not be presented as a verified ignition count. No respondent-level append is made by this script.
"""
    SUMMARY.write_text(summary)
    print(f"Saved {OUT_CSV}", flush=True)
    print(f"Saved {SUMMARY}", flush=True)
    print(f"Multi-month patches: {multi_month:,}; centroid fallbacks: {fallback_count:,}; nearest-district fallbacks: {nearest_count:,}; boundary ties: {boundary_ties:,}", flush=True)


if __name__ == "__main__":
    main()
