#!/usr/bin/env python3
"""Generate and append VIIRS VNP64A1 burned area for Indonesia Admin-2.

This is an additive PI side-task runner.  It does not modify the existing GADM
runner or overwrite existing country outputs.  VNP14A1 active-fire/FRP and
VNP64A1 burned area are written separately before a validated one-to-one append.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.adam_viirs_burn_export import AVG12_BURN_COLUMN, MONTHLY_BURN_COLUMN
from utils.gee_fire_zonal import ee_initialize_from_environ
from utils.indonesia_viirs import (
    ACTIVE_VALUE_COLUMNS,
    append_viirs_burned_area,
    fetch_active_viirs_chunk,
    fetch_burned_area_chunk,
    finalize_active_viirs,
    finalize_burned_area,
    indonesia_feature_chunks,
    indonesia_output_paths,
    load_cod_bps_adm2_features,
    load_indonesia_reference,
    replace_feature_areas,
    validate_indonesia_export,
    write_csv_atomic,
)


REFERENCE_DIR = _REPO / "indonesia_side_tasks" / "team_reference"
ADM2_SHAPEFILE = (
    _REPO
    / "data"
    / "processed"
    / "idn_team_data"
    / "Indonesia shape files"
    / "idn_admbnda_adm2_bps_20200401.shp"
)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(_REPO / ".env", override=False)
    except ImportError:
        pass


def _selected_references(years: set[int] | None) -> list[Path]:
    paths = sorted(REFERENCE_DIR.glob("*_AOD.csv"))
    if years is not None:
        paths = [path for path in paths if int(path.stem.split("_", 1)[0]) in years]
    if not paths:
        raise ValueError("No Indonesia AOD reference files selected")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Indonesia VNP14A1 + VNP64A1 Admin-2 test outputs"
    )
    parser.add_argument(
        "--years",
        help="Comma-separated reference years (default: every *_AOD.csv in team_reference)",
    )
    parser.add_argument("--project", help="Earth Engine GCP project id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate and replace this runner's Indonesia outputs",
    )
    parser.add_argument("--simplify-tolerance-m", type=float, default=10.0)
    parser.add_argument("--chunk-count", type=int, default=80)
    parser.add_argument("--chunk-bytes", type=int, default=4_000_000)
    args = parser.parse_args()

    years = None
    if args.years:
        years = {int(value.strip()) for value in args.years.split(",") if value.strip()}
    references = [load_indonesia_reference(path) for path in _selected_references(years)]

    base_features, diagnostics = load_cod_bps_adm2_features(
        ADM2_SHAPEFILE,
        area_by_code=references[0].area_by_code,
        simplify_tolerance_m=args.simplify_tolerance_m,
    )
    print(
        "Boundary: "
        f"{diagnostics.feature_count} Admin-2; repaired={diagnostics.repaired_count}; "
        f"simplified={diagnostics.simplify_tolerance_m:g}m; "
        f"max area change={diagnostics.maximum_relative_area_change_pct:.4f}% "
        f"({diagnostics.maximum_absolute_area_change_km2:.4f} km2); "
        f"payload={diagnostics.serialized_size_mb:.1f}MB; "
        f"largest feature={diagnostics.maximum_feature_size_mb:.2f}MB",
        flush=True,
    )

    for reference in references:
        active_path, burned_path, combined_path = indonesia_output_paths(_REPO, reference.year)
        print(
            f"{reference.year}: {len(reference.codes)} Admin-2 × {len(reference.months)} intervals; "
            f"{reference.months.iloc[0]['month_start']}.."
            f"{reference.months.iloc[-1]['month_end']} exclusive",
            flush=True,
        )
        print(f"  active:   {active_path}", flush=True)
        print(f"  burned:   {burned_path}", flush=True)
        print(f"  combined: {combined_path}", flush=True)

    if args.dry_run:
        return

    _load_dotenv()
    if args.project:
        os.environ["EARTHENGINE_PROJECT"] = args.project
    project = ee_initialize_from_environ()
    print(f"Earth Engine project: {project}", flush=True)

    for reference in references:
        active_path, burned_path, combined_path = indonesia_output_paths(_REPO, reference.year)
        need_active = args.force or not active_path.is_file()
        need_burned = args.force or not burned_path.is_file()
        features = replace_feature_areas(base_features, reference.area_by_code)

        if need_active or need_burned:
            chunks = indonesia_feature_chunks(
                features, max_count=args.chunk_count, max_bytes=args.chunk_bytes
            )
            print(
                f"\n=== Indonesia {reference.year}: {len(chunks)} boundary chunks ===",
                flush=True,
            )
            active_parts: list[pd.DataFrame] = []
            burned_parts: list[pd.DataFrame] = []
            for index, chunk in enumerate(chunks, start=1):
                print(
                    f"  chunk {index}/{len(chunks)} ({len(chunk)} units):",
                    end="",
                    flush=True,
                )
                if need_active:
                    active_parts.append(fetch_active_viirs_chunk(reference.months, chunk))
                    print(" active", end="", flush=True)
                if need_burned:
                    burned_parts.append(fetch_burned_area_chunk(reference.months, chunk))
                    print(" burned", end="", flush=True)
                print(" OK", flush=True)

            if need_active:
                active = finalize_active_viirs(pd.concat(active_parts, ignore_index=True))
                validate_indonesia_export(
                    active,
                    reference,
                    value_columns=[*ACTIVE_VALUE_COLUMNS, "avg12_fire_count", "avg12_sum_frp_mw"],
                    label=f"Indonesia {reference.year} VNP14A1",
                )
                write_csv_atomic(active, active_path)
                print(f"  wrote {active_path}", flush=True)
            if need_burned:
                burned = finalize_burned_area(pd.concat(burned_parts, ignore_index=True))
                validate_indonesia_export(
                    burned,
                    reference,
                    value_columns=[MONTHLY_BURN_COLUMN, AVG12_BURN_COLUMN],
                    label=f"Indonesia {reference.year} VNP64A1",
                )
                write_csv_atomic(burned, burned_path)
                print(f"  wrote {burned_path}", flush=True)

        active = pd.read_csv(active_path)
        burned = pd.read_csv(burned_path)
        validate_indonesia_export(
            active,
            reference,
            value_columns=[*ACTIVE_VALUE_COLUMNS, "avg12_fire_count", "avg12_sum_frp_mw"],
            label=f"Indonesia {reference.year} VNP14A1",
        )
        validate_indonesia_export(
            burned,
            reference,
            value_columns=[MONTHLY_BURN_COLUMN, AVG12_BURN_COLUMN],
            label=f"Indonesia {reference.year} VNP64A1",
        )
        combined = append_viirs_burned_area(active, burned)
        validate_indonesia_export(
            combined,
            reference,
            value_columns=[
                *ACTIVE_VALUE_COLUMNS,
                "avg12_fire_count",
                "avg12_sum_frp_mw",
                MONTHLY_BURN_COLUMN,
                AVG12_BURN_COLUMN,
            ],
            label=f"Indonesia {reference.year} combined VIIRS",
        )
        if args.force or not combined_path.is_file():
            write_csv_atomic(combined, combined_path)
            print(f"  wrote {combined_path}", flush=True)
        else:
            existing = pd.read_csv(combined_path)
            validate_indonesia_export(
                existing,
                reference,
                value_columns=[MONTHLY_BURN_COLUMN, AVG12_BURN_COLUMN],
                label=f"existing Indonesia {reference.year} combined VIIRS",
            )
            print(f"  kept validated existing {combined_path}", flush=True)


if __name__ == "__main__":
    main()

