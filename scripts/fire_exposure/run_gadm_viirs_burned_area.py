#!/usr/bin/env python3
"""Generate VIIRS VNP64A1 burned area on GADM boundaries, and the combined VIIRS table.

The GADM counterpart to ``run_indonesia_viirs_burned_area.py``. The Earth Engine
half is already country-agnostic in ``utils.adam_viirs_burn_export``; only the
Indonesia wrapper was COD/BPS-specific, so this reuses the former and replaces the
latter rather than generalising ``utils.indonesia_viirs`` (which would put the
working Indonesia path at risk for no gain).

**A rendered VNP14A1 active-fire CSV is required and is the reference.** It fixes
the unit set and the exact month windows, which is what makes the burned-area
append a validated one-to-one join instead of a re-derivation that might drift.
This mirrors how the Indonesia runner uses its reference file.

Usage::

    .venv/bin/python -m scripts.fire_exposure.run_gadm_viirs_burned_area \\
        --active data/processed/viirs/colombia_viirs_vnp14a1_gadm41_2018.csv \\
        --out-dir data/processed/gadm4_1_new

Writes ``<out-dir>/viirs_burned_area/<stem with vnp64a1>.csv`` and
``<out-dir>/viirs_combined/<stem with vnp14a1_vnp64a1>.csv``.

VNP64A1 begins 2012-03-01 in Earth Engine. A window starting earlier is refused
outright rather than silently returning zeros; see ``validate_vnp64a1_coverage``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.adam_viirs_burn_export import (
    AVG12_BURN_COLUMN,
    MONTHLY_BURN_COLUMN,
    to_adam_viirs_burned_area_columns,
    validate_vnp64a1_coverage,
    vnp64a1_burn_km2_image,
)
from utils.gadm_boundaries import gadm_level_normalized_features

APPEND_KEYS = ["month_start", "month_end"]


def parse_active_reference(path: Path) -> dict[str, Any]:
    """Read the rendered VNP14A1 table: its units and exact month windows are the contract."""
    df = pd.read_csv(path)
    level = 2 if "adm2_gid" in df.columns else 1
    gid_col = f"adm{level}_gid"
    for col in (gid_col, "month_start", "month_end", "adm0_name", "adm0_pcode"):
        if col not in df.columns:
            raise ValueError(f"{path.name}: missing required column {col!r}")
    # Teammate exports use both ISO and M/D/YY text. Normalize before sorting,
    # comparing, and sending intervals to the exact-date burned-area helper.
    for col in APPEND_KEYS:
        df[col] = pd.to_datetime(df[col], format="mixed", errors="raise").dt.strftime("%Y-%m-%d")
    months = (
        df[["month_start", "month_end"]]
        .drop_duplicates()
        .sort_values("month_start")
        .reset_index(drop=True)
    )
    if len(months) != 12 or not (months.month_end.iloc[:-1].to_numpy() == months.month_start.iloc[1:].to_numpy()).all():
        raise ValueError(f"{path.name}: expected 12 contiguous, unique survey months")
    if df.duplicated([gid_col, *APPEND_KEYS]).any() or len(df) != df[gid_col].nunique() * 12:
        raise ValueError(f"{path.name}: expected one row per GADM unit and survey month")
    return {
        "frame": df,
        "level": level,
        "gid_col": gid_col,
        "gids": sorted(df[gid_col].astype(str).unique()),
        "months": months,
        "adm0_name": str(df["adm0_name"].iloc[0]),
        "adm0_pcode": str(df["adm0_pcode"].iloc[0]),
    }


def select_features(iso3: str, level: int, version: str, gids: list[str]) -> list[dict[str, Any]]:
    """GADM features restricted to the reference's unit set, so the join cannot drift."""
    code_key = f"ADM{level}_CODE"
    features = gadm_level_normalized_features(iso3, level=level, version=version, root=_REPO)
    wanted = set(gids)
    kept = [f for f in features if str(f["properties"].get(code_key)) in wanted]
    missing = wanted - {str(f["properties"].get(code_key)) for f in kept}
    if missing:
        raise ValueError(
            f"{len(missing)} reference unit(s) absent from GADM {version} ADM{level}: "
            f"{sorted(missing)[:5]}"
        )
    return kept


def fetch_burned_area(
    features: list[dict[str, Any]],
    months: pd.DataFrame,
    level: int,
    *,
    scale_m: float = 500.0,
) -> pd.DataFrame:
    """One Earth Engine request per boundary chunk, all months batched inside it."""
    import ee

    code_key = f"ADM{level}_CODE"
    keep = [code_key, f"ADM{level}_NAME", f"ADM{level}_AREA_KM2", "ADM1_CODE", "ADM1_NAME"]
    keep = [k for k in keep if k in features[0]["properties"]]

    # Chunk by serialized JSON size, not feature count: GADM 4.1 geometry is heavy
    # (Colombia ADM1 alone is 23 MB) and EE rejects requests over ~10 MiB. Reuses the
    # same budget the fire runner uses so behaviour is consistent across pipelines.
    from utils.gee_fire_zonal import (
        DEFAULT_REGION_CHUNK_MAX_BYTES,
        DEFAULT_REGION_CHUNK_SIZE,
        _feature_dict_chunks_by_bytes,
    )

    rows: list[dict[str, Any]] = []
    chunks = _feature_dict_chunks_by_bytes(
        features,
        max_bytes=DEFAULT_REGION_CHUNK_MAX_BYTES,
        max_count=DEFAULT_REGION_CHUNK_SIZE,
    )
    for n, chunk in enumerate(chunks, start=1):
        regions = ee.FeatureCollection(chunk)
        collections = []
        for row in months.itertuples(index=False):
            start, end = str(row.month_start), str(row.month_end)
            reduced = vnp64a1_burn_km2_image(start, end).reduceRegions(
                collection=regions,
                reducer=ee.Reducer.sum(),
                scale=scale_m,
                tileScale=4,
                maxPixelsPerRegion=1e13,
            )

            def _format(feature, start=start, end=end):
                value = ee.Algorithms.If(
                    feature.propertyNames().contains(MONTHLY_BURN_COLUMN),
                    feature.get(MONTHLY_BURN_COLUMN),
                    feature.get("sum"),
                )
                props = (
                    ee.Dictionary(feature.toDictionary(keep))
                    .set("month_start", start)
                    .set("month_end", end)
                    .set(MONTHLY_BURN_COLUMN, value)
                )
                return ee.Feature(None, props)

            collections.append(reduced.map(_format))

        merged = ee.FeatureCollection(collections).flatten().getInfo()
        rows.extend(item.get("properties") or {} for item in merged["features"])
        print(f"  chunk {n}/{len(chunks)}: {len(rows)} rows", flush=True)
    return pd.DataFrame(rows)


def append_burned_area(active: pd.DataFrame, burned: pd.DataFrame, gid_col: str) -> pd.DataFrame:
    """Validated one-to-one append, the same contract the Indonesia runner enforces."""
    keys = [gid_col] + APPEND_KEYS
    for label, frame in (("active", active), ("burned", burned)):
        missing = sorted(set(keys) - set(frame.columns))
        if missing:
            raise ValueError(f"{label} table is missing append keys: {missing}")
        if frame.duplicated(keys).any():
            raise ValueError(f"{label} table has duplicate unit/date keys")
    if set(map(tuple, active[keys].astype(str).to_numpy())) != set(
        map(tuple, burned[keys].astype(str).to_numpy())
    ):
        raise ValueError("VNP14A1 and VNP64A1 key sets differ")
    merged = active.merge(
        burned[keys + [MONTHLY_BURN_COLUMN, AVG12_BURN_COLUMN]],
        how="left",
        on=keys,
        validate="one_to_one",
        indicator=True,
    )
    if len(merged) != len(active) or (merged["_merge"] != "both").any():
        raise ValueError("VNP14A1 and VNP64A1 keys do not match one-to-one")
    return merged.drop(columns="_merge")


def main() -> None:
    ap = argparse.ArgumentParser(description="VIIRS VNP64A1 burned area on GADM boundaries")
    ap.add_argument("--active", required=True, help="rendered VNP14A1 CSV, used as the reference")
    ap.add_argument("--iso3", help="GADM ISO3; inferred from the filename when omitted")
    ap.add_argument("--gadm-version", default="41")
    ap.add_argument("--out-dir", default="data/processed")
    ap.add_argument("--project", help="Earth Engine GCP project id")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--burned-only", action="store_true", help="write only the VNP64A1 burned-area table")
    args = ap.parse_args()

    active_path = Path(args.active)
    if not active_path.is_file():
        raise SystemExit(f"active reference not found: {active_path}")
    ref = parse_active_reference(active_path)
    level, gid_col = ref["level"], ref["gid_col"]

    iso3 = args.iso3 or str(ref["frame"][gid_col].iloc[0]).split(".")[0]
    start = pd.Timestamp(ref["months"]["month_start"].min()).date()
    end = pd.Timestamp(ref["months"]["month_end"].max()).date()

    print(f"=== {ref['adm0_name']} ADM{level} × GADM {args.gadm_version} ===")
    print(f"  reference : {active_path.name}")
    print(f"  units     : {len(ref['gids'])}")
    print(f"  months    : {len(ref['months'])}  ({start} .. {end})")

    # Refuse a window the product does not cover, rather than returning zeros.
    validate_vnp64a1_coverage(start)

    out_dir = Path(args.out_dir)
    stem = active_path.stem
    burned_path = out_dir / "viirs_burned_area" / f"{stem.replace('vnp14a1', 'vnp64a1')}.csv"
    combined_path = (
        out_dir / "viirs_combined" / f"{stem.replace('vnp14a1', 'vnp14a1_vnp64a1')}.csv"
    )
    print(f"  burned    : {burned_path}")
    if not args.burned_only:
        print(f"  combined  : {combined_path}")
    if args.dry_run:
        print("  dry-run: no Earth Engine calls made")
        return

    import ee
    import os

    from utils.gee_fire_zonal import ee_initialize_from_environ

    # Match every other runner: EARTHENGINE_PROJECT, else the repo default. A bare
    # ee.Initialize() has no project and fails.
    if args.project:
        os.environ["EARTHENGINE_PROJECT"] = args.project
    print("Earth Engine project:", ee_initialize_from_environ(), flush=True)

    features = select_features(iso3, level, args.gadm_version, ref["gids"])
    raw = fetch_burned_area(features, ref["months"], level)
    burned = to_adam_viirs_burned_area_columns(
        raw, adm0_name=ref["adm0_name"], adm0_pcode=ref["adm0_pcode"], unit_level=level
    )
    combined = append_burned_area(ref["frame"], burned, gid_col)

    outputs = ((burned_path, burned),) if args.burned_only else ((burned_path, burned), (combined_path, combined))
    for path, frame in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".csv.tmp")
        frame.to_csv(tmp, index=False)
        tmp.replace(path)
        print(f"  wrote {path}  ({len(frame)} rows)")


if __name__ == "__main__":
    main()
