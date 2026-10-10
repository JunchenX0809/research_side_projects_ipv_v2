#!/usr/bin/env python3
"""Generate active-fire-only tables from distinct monthly FIRMS or VIIRS pixels.

This is deliberately separate from ``run_gadm_fire_exports.py`` so the corrected
active-fire counts cannot overwrite the existing multi-product outputs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Country selection and exposure windows come from scripts/fire_exposure/run_gadm_fire_exports.py.
from scripts.fire_exposure.run_gadm_fire_exports import (
    MANIFEST_PATH,
    CountryJob,
    _load_dotenv,
    load_manifest,
    output_paths,
    qa_export_df,
    resolve_exposure_window,
    viirs_output_path,
)
from utils.adam_firms_export import (
    build_adam_firms_unique_export,
    months_table_for_rolling,
    write_adam_firms_csv,
)
from utils.adam_viirs_export import (
    VIIRS_FULL_COVERAGE_START,
    build_adam_viirs_unique_export,
    write_adam_viirs_csv,
)
from utils.gadm_boundaries import GADM_VERSIONS, gadm_level_normalized_features
from utils.gee_fire_zonal import ee_initialize_from_environ
from utils.repo_paths import find_repo_root
from utils.vacs_survey_time import (
    add_parsed_field_dates,
    load_survey_time_table,
    resolve_vacs_survey_time_csv,
)


DEFAULT_FAILURE_LOG = _REPO / "output" / "unique_active_fire_failures.jsonl"
# Existing reference CSVs store some area values to five decimal places. Half of
# that last decimal is 0.000005 km² (5 m²), so differences within this bound are
# serialization rounding rather than evidence of a different boundary geometry.
REFERENCE_AREA_ATOL_KM2 = 5e-6


def record_failure(
    path: Path,
    *,
    sensor: str,
    job: CountryJob,
    level: int | None,
    output_path: Path | None,
    error: Exception,
) -> None:
    """Append one durable, machine-readable record without stopping the batch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "sensor": sensor,
        "country_wave": job.country_wave,
        "iso3": job.iso3,
        "gadm_version": job.gadm_version,
        "admin_level": level,
        "expected_output": str(output_path) if output_path is not None else None,
        "error_type": type(error).__name__,
        "error": str(error),
    }
    # Each record is one compact line, so a failure remains visible even if the
    # process is interrupted before the overall run reaches its summary.
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def unique_output_path(
    root: Path,
    job: CountryJob,
    exposure_end,
    *,
    sensor: str,
    gadm_version: str,
    admin_level: int,
) -> Path:
    """Version 1 basename under the dedicated unique-count directory."""
    if sensor == "firms":
        _, reference = output_paths(
            root,
            job,
            exposure_end,
            gadm_version=gadm_version,
            admin_level=admin_level,
        )
        return root / "data" / "processed" / "firms_unique" / reference.name
    if sensor == "viirs":
        reference = viirs_output_path(
            root,
            job,
            exposure_end,
            gadm_version=gadm_version,
            admin_level=admin_level,
        )
        return root / "data" / "processed" / "viirs_unique" / reference.name
    raise ValueError(f"Unknown sensor: {sensor!r}")


def reference_output_path(
    root: Path,
    job: CountryJob,
    exposure_end,
    *,
    sensor: str,
    gadm_version: str,
    admin_level: int,
) -> Path:
    if sensor == "firms":
        return output_paths(
            root,
            job,
            exposure_end,
            gadm_version=gadm_version,
            admin_level=admin_level,
        )[1]
    return viirs_output_path(
        root,
        job,
        exposure_end,
        gadm_version=gadm_version,
        admin_level=admin_level,
    )


def select_unique_jobs(
    jobs: list[CountryJob],
    *,
    all_waves: bool,
    iso3_list: list[str] | None,
    gadm_version: str | None,
) -> list[CountryJob]:
    """Select reviewed waves without using Version 1's operational ``enabled`` flag."""
    if all_waves:
        selected = jobs
    elif iso3_list:
        requested = set(iso3_list)
        selected = [job for job in jobs if job.iso3 in requested]
        missing = sorted(requested - {job.iso3 for job in selected})
        if missing:
            raise ValueError(f"No manifest row for ISO3: {', '.join(missing)}")
    else:
        raise ValueError("Provide --all-waves or --iso3 ISO3[,ISO3,...]")
    if gadm_version is not None:
        selected = [job for job in selected if job.gadm_version == gadm_version]
    if not selected:
        raise ValueError("No jobs match the requested selection")
    return selected


def admin_levels_for_job(job: CountryJob, override: int | None) -> tuple[int, ...]:
    """Export both available levels by default; reject ADM2 for ADM1-only waves."""
    if override is not None:
        if override == 2 and job.admin_level < 2:
            raise ValueError(f"{job.country_wave} is ADM1-only; ADM2 is unavailable")
        return (override,)
    return (2, 1) if job.admin_level == 2 else (1,)


def validate_unique_output(df: pd.DataFrame, *, n_units: int, level: int, label: str) -> pd.DataFrame:
    """Validate the active-fire-only contract and store monthly counts as integers."""
    required = {
        "adm0_name",
        "adm0_pcode",
        "adm1_name",
        "adm1_gid",
        f"adm{level}_area_km2",
        "month_start",
        "month_end",
        "monthly_fire_count",
        "avg12_fire_count",
    }
    if level == 2:
        required.update({"adm2_name", "adm2_gid"})
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{label}: missing required columns: {missing}")

    expected_columns = [
        "adm0_name",
        "adm0_pcode",
        "adm1_name",
        "adm1_gid",
    ]
    if level == 1:
        expected_columns.append("adm1_area_km2")
    else:
        expected_columns.extend(["adm2_name", "adm2_gid", "adm2_area_km2"])
    expected_columns.extend(
        ["month_start", "month_end", "monthly_fire_count", "avg12_fire_count"]
    )
    if list(df.columns) != expected_columns:
        raise ValueError(
            f"{label}: unexpected schema\nexpected={expected_columns}\nactual={list(df.columns)}"
        )

    out = df.copy()
    monthly = pd.to_numeric(out["monthly_fire_count"], errors="raise")
    if monthly.isna().any() or (monthly < 0).any():
        raise ValueError(f"{label}: monthly_fire_count contains missing or negative values")
    rounded = monthly.round()
    if not np.allclose(monthly.to_numpy(), rounded.to_numpy(), atol=1e-9, rtol=0):
        raise ValueError(f"{label}: monthly_fire_count is not integer-valued")
    out["monthly_fire_count"] = rounded.astype("int64")

    qa_export_df(out, n_units, level=level, label=label)
    gid = f"adm{level}_gid"
    if out.duplicated([gid, "month_start"]).any():
        raise ValueError(f"{label}: duplicate admin-month keys")
    per_unit_rows = out.groupby(gid, dropna=False).size()
    if not (per_unit_rows == 12).all():
        raise ValueError(f"{label}: every admin unit must have exactly 12 rows")
    if out["month_start"].nunique() != 12:
        raise ValueError(f"{label}: expected 12 unique monthly intervals")

    actual_avg = pd.to_numeric(out["avg12_fire_count"], errors="raise")
    expected_avg = out.groupby(gid)["monthly_fire_count"].transform("mean")
    if not np.allclose(actual_avg.to_numpy(), expected_avg.to_numpy(), atol=1e-9, rtol=0):
        raise ValueError(f"{label}: avg12_fire_count does not equal the unit's 12-month mean")
    if not (out.groupby(gid)["avg12_fire_count"].nunique(dropna=False) == 1).all():
        raise ValueError(f"{label}: avg12_fire_count is not constant within admin unit")
    return out


def validate_reference_keys(
    unique_df: pd.DataFrame,
    reference_path: Path,
    *,
    level: int,
    label: str,
) -> None:
    """When Version 1 exists, require identical admin/date keys and areas."""
    if not reference_path.is_file():
        print(f"  reference QA skipped (not found): {reference_path.name}")
        return
    reference = pd.read_csv(reference_path)
    gid = f"adm{level}_gid"
    area = f"adm{level}_area_km2"
    keys = [gid, "month_start", "month_end"]

    def normalized_keys(frame: pd.DataFrame) -> pd.DataFrame:
        normalized = frame[keys].copy()
        normalized[gid] = normalized[gid].astype(str)
        for column in ("month_start", "month_end"):
            normalized[column] = pd.to_datetime(
                normalized[column].astype(str), format="mixed", errors="raise"
            ).dt.strftime("%Y-%m-%d")
        return normalized.sort_values(keys).reset_index(drop=True)

    left = normalized_keys(unique_df)
    right = normalized_keys(reference)
    if not left.equals(right):
        raise ValueError(f"{label}: admin/date keys differ from {reference_path.name}")

    unique_areas = unique_df[[gid, area]].drop_duplicates().sort_values(gid)
    reference_areas = reference[[gid, area]].drop_duplicates().sort_values(gid)
    if unique_areas[gid].astype(str).tolist() != reference_areas[gid].astype(str).tolist():
        raise ValueError(f"{label}: area keys differ from {reference_path.name}")
    if not np.allclose(
        pd.to_numeric(unique_areas[area]).to_numpy(),
        pd.to_numeric(reference_areas[area]).to_numpy(),
        atol=REFERENCE_AREA_ATOL_KM2,
        rtol=0,
    ):
        raise ValueError(f"{label}: admin areas differ from {reference_path.name}")
    print(f"  reference QA OK: identifiers, dates, and areas match {reference_path.name}")


def run_one(
    *,
    root: Path,
    job: CountryJob,
    survey_parsed: pd.DataFrame,
    sensor: str,
    level: int,
    skip_existing: bool,
    dry_run: bool,
) -> str:
    """Export one unique-pixel panel using the fleet window and manifest rules."""
    exposure_start, exposure_end = resolve_exposure_window(survey_parsed, job.country_wave)
    if sensor == "viirs" and exposure_start < VIIRS_FULL_COVERAGE_START:
        print(
            f"SKIP coverage: {job.country_wave} ADM{level} starts {exposure_start}, "
            f"before {VIIRS_FULL_COVERAGE_START}"
        )
        return "coverage"

    out_path = unique_output_path(
        root,
        job,
        exposure_end,
        sensor=sensor,
        gadm_version=job.gadm_version,
        admin_level=level,
    )
    if skip_existing and out_path.is_file():
        print(f"SKIP exists: {out_path}")
        return "exists"
    print(
        f"RUN {sensor.upper()}: {job.country_wave} GADM{job.gadm_version} ADM{level} "
        f"{exposure_start}..{exposure_end} -> {out_path.name}"
    )
    if dry_run:
        return "dry-run"

    import ee

    region_features = gadm_level_normalized_features(
        job.iso3, level=level, version=job.gadm_version, root=root
    )
    regions = ee.FeatureCollection(region_features[:1])
    months = months_table_for_rolling(exposure_start, exposure_end, history_months=0)
    if len(months) != 12:
        raise ValueError(f"{job.country_wave}: expected 12 exposure slices, got {len(months)}")

    kwargs = dict(
        months_table=months,
        regions=regions,
        adm0_name=job.adm0_name,
        adm0_pcode=job.adm0_pcode,
        exposure_start=exposure_start,
        exposure_end=exposure_end,
        scale_m=1000.0,
        region_features=region_features,
        unit_level=level,
    )
    if sensor == "firms":
        result = build_adam_firms_unique_export(**kwargs)
    else:
        result = build_adam_viirs_unique_export(**kwargs)
    label = f"{sensor.upper()} unique {job.country_wave} ADM{level}"
    result = validate_unique_output(result, n_units=len(region_features), level=level, label=label)
    validate_reference_keys(
        result,
        reference_output_path(
            root,
            job,
            exposure_end,
            sensor=sensor,
            gadm_version=job.gadm_version,
            admin_level=level,
        ),
        level=level,
        label=label,
    )
    if sensor == "firms":
        write_adam_firms_csv(result, out_path)
    else:
        write_adam_viirs_csv(result, out_path)
    print(f"  wrote {out_path}")
    return "written"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-waves", action="store_true", help="All reviewed manifest waves")
    parser.add_argument("--iso3", help="Comma-separated GADM ISO3 codes")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--sensor", choices=("firms", "viirs", "both"), default="viirs")
    parser.add_argument("--gadm-version", choices=tuple(GADM_VERSIONS), default=None)
    parser.add_argument("--admin-level", type=int, choices=(1, 2), default=None)
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume by preserving outputs that already exist",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project", help="Earth Engine GCP project id")
    parser.add_argument(
        "--failure-log",
        type=Path,
        default=DEFAULT_FAILURE_LOG,
        help="Append-only JSONL ledger for failed outputs",
    )
    args = parser.parse_args()
    if args.all_waves and args.iso3:
        parser.error("Use either --all-waves or --iso3, not both")

    root = find_repo_root()
    _load_dotenv(root)
    if args.project:
        os.environ["EARTHENGINE_PROJECT"] = args.project
    iso3_list = (
        [value.strip().upper() for value in args.iso3.split(",") if value.strip()]
        if args.iso3
        else None
    )
    try:
        jobs = select_unique_jobs(
            load_manifest(args.manifest),
            all_waves=args.all_waves,
            iso3_list=iso3_list,
            gadm_version=args.gadm_version,
        )
    except ValueError as exc:
        parser.error(str(exc))

    survey_parsed = add_parsed_field_dates(
        load_survey_time_table(resolve_vacs_survey_time_csv(root))
    )
    # When both are requested, finish the VIIRS pass first, then always proceed to
    # FIRMS. Per-file errors are caught below and therefore never abort either pass.
    sensors = ("viirs", "firms") if args.sensor == "both" else (args.sensor,)
    if not args.dry_run:
        project = ee_initialize_from_environ()
        print(f"Earth Engine project: {project}")

    counts = {"written": 0, "exists": 0, "coverage": 0, "dry-run": 0, "failed": 0}
    failures: list[str] = []
    for sensor in sensors:
        for job in jobs:
            try:
                levels = admin_levels_for_job(job, args.admin_level)
            except ValueError as exc:
                counts["failed"] += 1
                failures.append(str(exc))
                record_failure(
                    args.failure_log,
                    sensor=sensor,
                    job=job,
                    level=args.admin_level,
                    output_path=None,
                    error=exc,
                )
                continue
            for level in levels:
                expected_output = None
                try:
                    _, exposure_end = resolve_exposure_window(survey_parsed, job.country_wave)
                    expected_output = unique_output_path(
                        root,
                        job,
                        exposure_end,
                        sensor=sensor,
                        gadm_version=job.gadm_version,
                        admin_level=level,
                    )
                    status = run_one(
                        root=root,
                        job=job,
                        survey_parsed=survey_parsed,
                        sensor=sensor,
                        level=level,
                        skip_existing=args.skip_existing,
                        dry_run=args.dry_run,
                    )
                    counts[status] += 1
                except Exception as exc:
                    counts["failed"] += 1
                    failure = f"{sensor} {job.country_wave} ADM{level}: {exc}"
                    failures.append(failure)
                    print(f"FAILED: {failure}", file=sys.stderr)
                    record_failure(
                        args.failure_log,
                        sensor=sensor,
                        job=job,
                        level=level,
                        output_path=expected_output,
                        error=exc,
                    )
                    print(f"  recorded failure: {args.failure_log}", file=sys.stderr)
                    traceback.print_exc()

    print("Summary: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    if failures:
        print("Failures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
