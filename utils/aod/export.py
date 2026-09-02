"""Output paths, schema construction, and validation for AOD jobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from utils.aod.manifest import AodJob


def output_path(repo_root: Path, job: AodJob, exposure_end_year: int) -> Path:
    level_marker = "" if job.admin_level == 2 else f"_adm{job.admin_level}"
    return (
        repo_root
        / "data"
        / "processed"
        / "aod"
        / (
            f"{job.country_slug}_maiac_aod_gadm{job.gadm_version}"
            f"{level_marker}_{exposure_end_year}.csv"
        )
    )


def checkpoint_paths(repo_root: Path, job: AodJob) -> tuple[Path, Path]:
    directory = repo_root / "data" / "processed" / "aod" / ".checkpoints"
    return (
        directory / f"{job.job_id}.monthly.partial.csv",
        directory / f"{job.job_id}.avg12.partial.csv",
    )


def write_csv_atomic(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)
    return path


def finalize_export(
    monthly: pd.DataFrame,
    annual: pd.DataFrame,
    *,
    job: AodJob,
) -> pd.DataFrame:
    """Merge teammate-compatible full-window means and format the public schema."""
    gid_source = f"ADM{job.admin_level}_CODE"
    if annual[gid_source].duplicated().any():
        raise ValueError(f"{job.job_id}: duplicate annual {gid_source} rows")
    annual_values = annual[[gid_source, "avg12_mean_aod"]]
    frame = monthly.merge(
        annual_values,
        on=gid_source,
        how="left",
        validate="many_to_one",
    )
    frame["adm0_name"] = job.adm0_name
    frame["adm0_pcode"] = job.adm0_pcode
    frame["adm1_name"] = frame["ADM1_NAME"]
    frame["adm1_gid"] = frame["ADM1_CODE"].astype(str)
    if job.admin_level == 1:
        frame["adm1_area_km2"] = frame["ADM1_AREA_KM2"]
    else:
        frame["adm2_name"] = frame["ADM2_NAME"]
        frame["adm2_gid"] = frame["ADM2_CODE"].astype(str)
        frame["adm2_area_km2"] = frame["ADM2_AREA_KM2"]
    frame["month_start"] = pd.to_datetime(frame["month_start"]).dt.strftime("%Y-%m-%d")
    frame["month_end"] = pd.to_datetime(frame["month_end"]).dt.strftime("%Y-%m-%d")

    desired = [
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
        "monthly_mean_aod",
        "avg12_mean_aod",
    ]
    columns = [column for column in desired if column in frame.columns]
    names = ["adm1_name"]
    if job.admin_level == 2:
        names.append("adm2_name")
    return frame[columns].sort_values(names + ["month_start"]).reset_index(drop=True)


def validate_export(frame: pd.DataFrame, *, job: AodJob) -> dict[str, Any]:
    gid = f"adm{job.admin_level}_gid"
    expected_rows = job.expected_units * 12
    errors: list[str] = []
    if len(frame) != expected_rows:
        errors.append(f"expected {expected_rows} rows; found {len(frame)}")
    if frame[gid].nunique() != job.expected_units:
        errors.append(
            f"expected {job.expected_units} unique {gid}; found {frame[gid].nunique()}"
        )
    if frame["month_start"].nunique() != 12:
        errors.append(f"expected 12 month_start values; found {frame['month_start'].nunique()}")
    duplicate_count = int(frame.duplicated([gid, "month_start"]).sum())
    if duplicate_count:
        errors.append(f"found {duplicate_count} duplicate GID-month rows")
    monthly = pd.to_numeric(frame["monthly_mean_aod"], errors="coerce")
    annual = pd.to_numeric(frame["avg12_mean_aod"], errors="coerce")
    if not monthly.dropna().between(0, 8).all():
        errors.append("monthly AOD values outside the documented 0..8 valid range")
    if not annual.dropna().between(0, 8).all():
        errors.append("full-window AOD values outside the documented 0..8 valid range")
    annual_unique = frame.groupby(gid, dropna=False)["avg12_mean_aod"].nunique(dropna=False)
    if (annual_unique > 1).any():
        errors.append("avg12_mean_aod is not constant within every GID")
    if errors:
        raise ValueError(f"{job.job_id} QA failed: " + "; ".join(errors))
    return {
        "job_id": job.job_id,
        "iso3": job.iso3,
        "country_wave": job.country_wave,
        "gadm_version": job.gadm_version,
        "admin_level": job.admin_level,
        "rows": len(frame),
        "units": int(frame[gid].nunique()),
        "months": int(frame["month_start"].nunique()),
        "monthly_missing": int(monthly.isna().sum()),
        "avg12_missing_units": int(
            frame.loc[annual.isna(), gid].drop_duplicates().shape[0]
        ),
        "monthly_min": monthly.min(),
        "monthly_max": monthly.max(),
        "avg12_min": annual.min(),
        "avg12_max": annual.max(),
    }
