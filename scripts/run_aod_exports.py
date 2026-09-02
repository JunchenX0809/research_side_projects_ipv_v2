#!/usr/bin/env python3
"""Run standalone, checkpointed MAIAC AOD administrative exposure jobs."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Callable, TypeVar

import ee
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.aod.boundaries import feature_chunks, load_boundary_features
from utils.aod.dates import complete_calendar_months, resolve_exposure_window
from utils.aod.export import (
    checkpoint_paths,
    finalize_export,
    output_path,
    validate_export,
    write_csv_atomic,
)
from utils.aod.maiac import (
    aod_collection,
    mean_aod_image,
    modis_tiles_for_features,
    reduce_mean_chunk,
)
from utils.aod.manifest import AodJob, load_manifest

MANIFEST_PATH = ROOT / "config" / "aod_runs.csv"
T = TypeVar("T")


def _initialize_ee(project_override: str | None) -> str:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass
    project = (project_override or os.environ.get("EARTHENGINE_PROJECT") or "ipv-exposure-research").strip()
    ee.Initialize(project=project)
    return project


def _retry(
    operation: Callable[[], T],
    *,
    label: str,
    max_attempts: int,
    retry_seconds: float,
) -> T:
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if attempt == max_attempts:
                raise
            wait = retry_seconds * attempt
            print(
                f"    {label}: attempt {attempt}/{max_attempts} failed "
                f"({type(exc).__name__}: {exc}); retrying in {wait:.0f}s",
                flush=True,
            )
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _read_checkpoint(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.is_file() else pd.DataFrame()


def _completed_gids(frame: pd.DataFrame, gid_source: str, month_start: str | None = None) -> set[str]:
    if frame.empty or gid_source not in frame.columns:
        return set()
    subset = frame
    if month_start is not None:
        subset = subset[
            pd.to_datetime(subset["month_start"]).dt.strftime("%Y-%m-%d") == month_start
        ]
    return set(subset[gid_source].astype(str))


def _append_checkpoint(
    existing: pd.DataFrame,
    new: pd.DataFrame,
    *,
    path: Path,
    keys: list[str],
) -> pd.DataFrame:
    combined = pd.concat([existing, new], ignore_index=True)
    combined = combined.drop_duplicates(keys, keep="last")
    write_csv_atomic(combined, path)
    return combined


def _extract_job(
    job: AodJob,
    *,
    resume: bool,
    overwrite: bool,
    smoke_test: bool,
    max_attempts: int,
    retry_seconds: float,
) -> tuple[Path | None, dict | None]:
    started = time.monotonic()
    exposure_start, exposure_end = resolve_exposure_window(ROOT, job.country_wave)
    months = complete_calendar_months(exposure_start, exposure_end)
    features = load_boundary_features(job)
    chunks = feature_chunks(features)
    tiles = modis_tiles_for_features(features)
    output = output_path(ROOT, job, exposure_end.year)
    gid_source = f"ADM{job.admin_level}_CODE"
    window_start = months.iloc[0]["month_start"]
    window_end = months.iloc[-1]["month_end"]

    print(
        f"\n=== {job.job_id}: {job.country_wave} × GADM {job.gadm_version} × ADM{job.admin_level} ===",
        flush=True,
    )
    print(
        f"  exact exposure: {exposure_start}..{exposure_end}; "
        f"anchored output: {window_start}..{window_end} exclusive",
        flush=True,
    )
    print(
        f"  boundaries={len(features)} chunks={len(chunks)} tiles={','.join(tiles)}",
        flush=True,
    )
    if job.notes:
        print(f"  note: {job.notes}", flush=True)

    if output.is_file() and not overwrite and not smoke_test:
        existing = pd.read_csv(output)
        qa = validate_export(existing, job=job)
        print(f"  validated existing output: {output}", flush=True)
        return output, qa

    if smoke_test:
        first_month = months.iloc[0]
        month_start = first_month["month_start"].isoformat()
        month_end = first_month["month_end"].isoformat()
        count = int(aod_collection(month_start, month_end, tiles=tiles).size().getInfo())
        monthly_image = mean_aod_image(
            month_start, month_end, tiles=tiles, output_band="monthly_mean_aod"
        )
        monthly = _retry(
            lambda: reduce_mean_chunk(
                monthly_image,
                chunks[0],
                band_name="monthly_mean_aod",
                output_column="monthly_mean_aod",
            ),
            label="monthly smoke chunk",
            max_attempts=max_attempts,
            retry_seconds=retry_seconds,
        )
        annual_image = mean_aod_image(
            window_start.isoformat(),
            window_end.isoformat(),
            tiles=tiles,
            output_band="avg12_mean_aod",
        )
        annual = _retry(
            lambda: reduce_mean_chunk(
                annual_image,
                chunks[0],
                band_name="avg12_mean_aod",
                output_column="avg12_mean_aod",
            ),
            label="full-window smoke chunk",
            max_attempts=max_attempts,
            retry_seconds=retry_seconds,
        )
        if len(monthly) != len(chunks[0]) or len(annual) != len(chunks[0]):
            raise ValueError(f"{job.job_id}: smoke test returned an incomplete chunk")
        print(
            f"  smoke OK: {count} MAIAC granules; {len(chunks[0])} monthly and annual rows",
            flush=True,
        )
        return None, None

    monthly_path, annual_path = checkpoint_paths(ROOT, job)
    monthly_partial = _read_checkpoint(monthly_path) if resume else pd.DataFrame()
    annual_partial = _read_checkpoint(annual_path) if resume else pd.DataFrame()
    if not resume:
        monthly_path.unlink(missing_ok=True)
        annual_path.unlink(missing_ok=True)

    for month_number, month in months.iterrows():
        month_start = month["month_start"].isoformat()
        month_end = month["month_end"].isoformat()
        image = mean_aod_image(
            month_start, month_end, tiles=tiles, output_band="monthly_mean_aod"
        )
        completed = _completed_gids(monthly_partial, gid_source, month_start)
        for chunk_number, chunk in enumerate(chunks, start=1):
            chunk_gids = {
                str(feature["properties"][gid_source]) for feature in chunk
            }
            if chunk_gids <= completed:
                continue
            label = f"month {month_number + 1}/12 {month_start} chunk {chunk_number}/{len(chunks)}"
            print(f"  {label}", flush=True)
            part = _retry(
                lambda chunk=chunk: reduce_mean_chunk(
                    image,
                    chunk,
                    band_name="monthly_mean_aod",
                    output_column="monthly_mean_aod",
                ),
                label=label,
                max_attempts=max_attempts,
                retry_seconds=retry_seconds,
            )
            part["month_start"] = month_start
            part["month_end"] = month_end
            monthly_partial = _append_checkpoint(
                monthly_partial,
                part,
                path=monthly_path,
                keys=[gid_source, "month_start"],
            )
            completed.update(chunk_gids)

    annual_image = mean_aod_image(
        window_start.isoformat(),
        window_end.isoformat(),
        tiles=tiles,
        output_band="avg12_mean_aod",
    )
    annual_completed = _completed_gids(annual_partial, gid_source)
    for chunk_number, chunk in enumerate(chunks, start=1):
        chunk_gids = {str(feature["properties"][gid_source]) for feature in chunk}
        if chunk_gids <= annual_completed:
            continue
        label = f"full-window chunk {chunk_number}/{len(chunks)}"
        print(f"  {label}", flush=True)
        part = _retry(
            lambda chunk=chunk: reduce_mean_chunk(
                annual_image,
                chunk,
                band_name="avg12_mean_aod",
                output_column="avg12_mean_aod",
            ),
            label=label,
            max_attempts=max_attempts,
            retry_seconds=retry_seconds,
        )
        annual_partial = _append_checkpoint(
            annual_partial,
            part,
            path=annual_path,
            keys=[gid_source],
        )
        annual_completed.update(chunk_gids)

    final = finalize_export(monthly_partial, annual_partial, job=job)
    qa = validate_export(final, job=job)
    write_csv_atomic(final, output)
    print(
        f"  wrote {output} ({len(final)} rows) in {time.monotonic() - started:.1f}s",
        flush=True,
    )
    return output, qa


def _select_jobs(jobs: list[AodJob], args: argparse.Namespace) -> list[AodJob]:
    selected = [job for job in jobs if job.enabled]
    if args.job_id:
        wanted = {value.strip().upper() for value in args.job_id.split(",") if value.strip()}
        selected = [job for job in jobs if job.job_id in wanted]
        missing = wanted - {job.job_id for job in selected}
        if missing:
            raise ValueError(f"Unknown AOD job IDs: {sorted(missing)}")
    elif args.iso3:
        wanted = {value.strip().upper() for value in args.iso3.split(",") if value.strip()}
        selected = [job for job in jobs if job.enabled and job.iso3 in wanted]
        missing = wanted - {job.iso3 for job in selected}
        if missing:
            raise ValueError(f"No enabled AOD jobs for ISO3: {sorted(missing)}")
    elif not args.all:
        raise ValueError("Choose --all, --job-id, or --iso3")
    # Run all smaller ADM1 jobs before ADM2, then progress from smaller to larger
    # boundary sets. This provides early validated outputs and leaves the two long
    # NGA/COL ADM2 jobs until checkpoints have already proved reliable.
    return sorted(selected, key=lambda job: (job.admin_level, job.expected_units))


def _upsert_qa_summary(qa_row: dict) -> Path:
    """Persist QA immediately so later job failures cannot erase completed evidence."""
    import fcntl

    qa_path = ROOT / "data" / "processed" / "aod" / "aod_qa_summary.csv"
    lock_path = qa_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        qa_frame = pd.DataFrame([qa_row])
        if qa_path.is_file():
            previous = pd.read_csv(qa_path)
            qa_frame = pd.concat([previous, qa_frame], ignore_index=True)
            qa_frame = qa_frame.drop_duplicates("job_id", keep="last")
        qa_frame = qa_frame.sort_values("job_id").reset_index(drop=True)
        write_csv_atomic(qa_frame, qa_path)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return qa_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--all", action="store_true", help="Run all enabled AOD jobs")
    selector.add_argument("--job-id", help="Comma-separated manifest job IDs")
    selector.add_argument("--iso3", help="Comma-separated ISO3 codes (all configured waves/levels)")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--smoke-test", action="store_true", help="Evaluate first month and first chunk only; write no files")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--project", help="Earth Engine project override")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-seconds", type=float, default=10.0)
    args = parser.parse_args()
    if args.max_attempts < 1:
        parser.error("--max-attempts must be at least 1")

    jobs = load_manifest(args.manifest, repo_root=ROOT)
    try:
        selected = _select_jobs(jobs, args)
    except ValueError as exc:
        parser.error(str(exc))

    print(f"Selected {len(selected)} AOD job(s)")
    if args.dry_run:
        total_rows = 0
        for job in selected:
            exposure_start, exposure_end = resolve_exposure_window(ROOT, job.country_wave)
            months = complete_calendar_months(exposure_start, exposure_end)
            features = load_boundary_features(job)
            chunks = feature_chunks(features)
            tiles = modis_tiles_for_features(features)
            out = output_path(ROOT, job, exposure_end.year)
            rows = job.expected_units * 12
            total_rows += rows
            print(
                f"{job.job_id}: {len(features)} units × 12 = {rows} rows; "
                f"{months.iloc[0]['month_start']}..{months.iloc[-1]['month_end']} exclusive; "
                f"{len(chunks)} chunks; {len(tiles)} tiles; {out.name}"
            )
        print(f"Dry-run total: {total_rows} rows")
        return

    project = _initialize_ee(args.project)
    print(f"Earth Engine project: {project}")
    for job in selected:
        _, qa = _extract_job(
            job,
            resume=args.resume,
            overwrite=args.overwrite,
            smoke_test=args.smoke_test,
            max_attempts=args.max_attempts,
            retry_seconds=args.retry_seconds,
        )
        if qa is not None:
            print(f"Updated QA summary: {_upsert_qa_summary(qa)}")


if __name__ == "__main__":
    main()
