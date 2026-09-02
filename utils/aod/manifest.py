"""Configuration contract for standalone AOD jobs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class AodJob:
    job_id: str
    iso3: str
    country_wave: str
    adm0_name: str
    adm0_pcode: str
    country_slug: str
    gadm_version: str
    admin_level: int
    boundary_format: str
    boundary_dir: Path
    expected_units: int
    enabled: bool
    notes: str = ""


def _cell(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def load_manifest(path: Path, *, repo_root: Path) -> list[AodJob]:
    """Load and validate the explicit wave × GADM × administrative-level jobs."""
    # ``keep_default_na=False`` is required because Namibia's project code is the
    # literal string ``NA``, not a missing value.
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = {
        "job_id",
        "iso3",
        "country_wave",
        "adm0_name",
        "adm0_pcode",
        "country_slug",
        "gadm_version",
        "admin_level",
        "boundary_format",
        "boundary_dir",
        "expected_units",
        "enabled",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"AOD manifest is missing columns: {sorted(missing)}")

    jobs: list[AodJob] = []
    for _, row in frame.iterrows():
        job_id = _cell(row["job_id"]).upper()
        level = int(row["admin_level"])
        version = _cell(row["gadm_version"])
        boundary_format = _cell(row["boundary_format"]).lower()
        if level not in (1, 2):
            raise ValueError(f"{job_id}: admin_level must be 1 or 2")
        if version not in {"36", "40", "41"}:
            raise ValueError(f"{job_id}: unsupported GADM version {version!r}")
        if boundary_format not in {"geojson", "shapefile"}:
            raise ValueError(f"{job_id}: boundary_format must be geojson or shapefile")
        boundary_dir = Path(_cell(row["boundary_dir"]))
        if not boundary_dir.is_absolute():
            boundary_dir = repo_root / boundary_dir
        jobs.append(
            AodJob(
                job_id=job_id,
                iso3=_cell(row["iso3"]).upper(),
                country_wave=_cell(row["country_wave"]),
                adm0_name=_cell(row["adm0_name"]),
                adm0_pcode=_cell(row["adm0_pcode"]),
                country_slug=_cell(row["country_slug"]).lower(),
                gadm_version=version,
                admin_level=level,
                boundary_format=boundary_format,
                boundary_dir=boundary_dir,
                expected_units=int(row["expected_units"]),
                enabled=bool(int(row["enabled"])),
                notes=_cell(row.get("notes")),
            )
        )

    ids = [job.job_id for job in jobs]
    if len(ids) != len(set(ids)):
        raise ValueError("AOD manifest job_id values must be unique")
    combinations = [
        (job.country_wave, job.gadm_version, job.admin_level) for job in jobs
    ]
    if len(combinations) != len(set(combinations)):
        raise ValueError("AOD manifest contains a duplicate wave/GADM/admin-level job")
    return jobs
