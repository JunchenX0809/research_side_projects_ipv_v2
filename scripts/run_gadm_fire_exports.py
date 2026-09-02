#!/usr/bin/env python3
"""
Batch GADM admin-level MODIS MCD64A1, FIRMS, FRP, and VIIRS exports.

Uses ``config/gadm_fire_countries.csv`` (per-row ``gadm_version``), local GADM GeoJSON,
and VACS survey dates. See ``howto_docs/modis_gadm_country_pipeline.md``.

Examples::

    python scripts/gadm_shp_to_geojson.py --version 40 --iso3 MOZ
    python scripts/run_gadm_fire_exports.py --iso3 MOZ --export-only
    python scripts/run_gadm_fire_exports.py --iso3 TZA --gadm-version 41 --export-only
    python scripts/run_gadm_fire_exports.py --all
    python scripts/run_gadm_fire_exports.py --iso3 ZWE --viirs-only --export-only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.adam_firms_export import build_adam_firms_export, write_adam_firms_csv
from utils.adam_frp_export import (
    build_adam_frp_export,
    build_adam_frp_sum_export,
    write_adam_frp_csv,
)
from utils.adam_modis_export import (
    build_adam_modis_export,
    months_table_for_rolling,
    write_adam_modis_csv,
)
from utils.adam_viirs_export import (
    VIIRS_FULL_COVERAGE_START,
    build_adam_viirs_export,
    validate_viirs_coverage,
    write_adam_viirs_csv,
)
from utils.gadm_boundaries import (
    GADM_VERSIONS,
    gadm_geojson_path,
    gadm_level_normalized_features,
    load_gadm_geojson,
)
from utils.gee_fire_zonal import (
    DEFAULT_REGION_CHUNK_MAX_BYTES,
    DEFAULT_REGION_CHUNK_SIZE,
    _feature_dict_chunks_by_bytes,
    ee_initialize_from_environ,
)
from utils.repo_paths import find_repo_root
from utils.vacs_survey_time import (
    add_parsed_field_dates,
    exposure_window_inclusive_before_field_start,
    field_dates_as_python_dates,
    get_country_wave_row,
    load_survey_time_table,
    resolve_vacs_survey_time_csv,
)

MANIFEST_PATH = _REPO / "config" / "gadm_fire_countries.csv"

ALLOWED_DATE_FLAGS = frozenset(
    {
        "range_ok",
        "single_day",
        "month_year_range_ok",
        "month_pair_year_ok",
        "month_abbr_year_ok",
        "month_only_year_ok",
        "month_name_pair_manual",
    }
)


@dataclass(frozen=True)
class CountryJob:
    iso3: str
    country_wave: str
    adm0_name: str
    adm0_pcode: str
    country_slug: str
    gadm_version: str
    enabled: bool
    defer_reason: str
    notes: str
    admin_level: int = 2


def _load_dotenv(root: Path) -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env", override=False)
    except ImportError:
        pass


def _csv_cell(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def load_manifest(path: Path | None = None) -> list[CountryJob]:
    path = path or MANIFEST_PATH
    df = pd.read_csv(path)
    jobs: list[CountryJob] = []
    for _, row in df.iterrows():
        gadm_version = _csv_cell(row.get("gadm_version")) or "36"
        if gadm_version not in GADM_VERSIONS:
            raise ValueError(
                f"Invalid gadm_version {gadm_version!r} for {row.get('iso3')}; "
                f"expected one of {list(GADM_VERSIONS)}"
            )
        admin_level = int(_csv_cell(row.get("admin_level")) or "2")
        if admin_level not in (0, 1, 2):
            raise ValueError(
                f"Invalid admin_level {admin_level!r} for {row.get('iso3')}; expected 0, 1, or 2"
            )
        jobs.append(
            CountryJob(
                iso3=_csv_cell(row["iso3"]).upper(),
                country_wave=_csv_cell(row["country_wave"]),
                adm0_name=_csv_cell(row["adm0_name"]),
                adm0_pcode=_csv_cell(row["adm0_pcode"]),
                country_slug=_csv_cell(row["country_slug"]).lower(),
                gadm_version=gadm_version,
                enabled=bool(int(row["enabled"])),
                defer_reason=_csv_cell(row.get("defer_reason")),
                notes=_csv_cell(row.get("notes")),
                admin_level=admin_level,
            )
        )
    return jobs


def effective_gadm_version(job: CountryJob, cli_version: str | None) -> str:
    """Manifest row version unless ``--gadm-version`` was passed on the CLI."""
    if cli_version is not None:
        return cli_version
    return job.gadm_version


def effective_admin_level(job: CountryJob, cli_level: int | None) -> int:
    """Manifest row admin level unless ``--admin-level`` was passed on the CLI."""
    if cli_level is not None:
        return cli_level
    return job.admin_level


def feature_count(iso3: str, *, level: int, version: str, root: Path) -> int:
    data = load_gadm_geojson(iso3, level, version=version, root=root)
    return len(data["features"])


def output_paths(
    root: Path,
    job: CountryJob,
    exposure_end: date,
    *,
    gadm_version: str,
    admin_level: int = 2,
) -> tuple[Path, Path]:
    year = exposure_end.year
    processed = root / "data" / "processed"
    # ADM2 keeps the original bare name; ADM1/ADM0 get a level marker so both can coexist.
    lvl = "" if admin_level == 2 else f"_adm{admin_level}"
    modis = processed / "modis" / f"{job.country_slug}_modis_mcd64_gadm{gadm_version}{lvl}_{year}.csv"
    firms = processed / "firms" / f"{job.country_slug}_firms_gadm{gadm_version}{lvl}_{year}.csv"
    return modis, firms


def frp_output_path(
    root: Path,
    job: CountryJob,
    exposure_end: date,
    *,
    gadm_version: str,
    admin_level: int = 2,
    metric: str = "max",
) -> Path:
    year = exposure_end.year
    lvl = "" if admin_level == 2 else f"_adm{admin_level}"
    # 'max' keeps the original bare `_frp_` stub; 'sum' gets `_frp_sum_` so both coexist.
    stub = "frp_sum" if metric == "sum" else "frp"
    return (
        root
        / "data"
        / "processed"
        / "frp"
        / f"{job.country_slug}_modis_{stub}_gadm{gadm_version}{lvl}_{year}.csv"
    )


def viirs_output_path(
    root: Path,
    job: CountryJob,
    exposure_end: date,
    *,
    gadm_version: str,
    admin_level: int = 2,
) -> Path:
    year = exposure_end.year
    lvl = "" if admin_level == 2 else f"_adm{admin_level}"
    return (
        root
        / "data"
        / "processed"
        / "viirs"
        / f"{job.country_slug}_viirs_vnp14a1_gadm{gadm_version}{lvl}_{year}.csv"
    )


def resolve_exposure_window(survey_parsed: pd.DataFrame, country_wave: str) -> tuple[date, date]:
    row = get_country_wave_row(survey_parsed, country_wave)
    flag = row.get("date_parse_flag")
    if flag not in ALLOWED_DATE_FLAGS:
        raise ValueError(
            f"{country_wave!r}: date_parse_flag={flag!r} not in allowed set; fix VACS CSV first."
        )
    field_start, _ = field_dates_as_python_dates(row)
    return exposure_window_inclusive_before_field_start(field_start)


def qa_export_df(df: pd.DataFrame, n_units: int, *, level: int, label: str) -> None:
    n_months = df["month_start"].nunique() if "month_start" in df.columns else 0
    expected = n_units * 12
    if len(df) != expected:
        raise ValueError(f"{label}: expected {expected} rows ({n_units} units × 12 months), got {len(df)}")
    gid_col = f"adm{level}_gid"
    if df[gid_col].nunique() != n_units:
        raise ValueError(
            f"{label}: expected {n_units} unique {gid_col}, got {df[gid_col].nunique()}"
        )
    print(f"  QA OK: {len(df)} rows, {n_units} ADM{level} units, {n_months} exposure months")


def warn_excel_crosswalk(iso3: str, df: pd.DataFrame, root: Path) -> None:
    """Log ISO_2 match rate vs teammate Excel when both exist (non-fatal)."""
    xlsx = root / "skills" / "GADM_admin_areas_v1.xlsx"
    if not xlsx.is_file():
        return
    try:
        adm2 = pd.read_excel(xlsx, sheet_name="ADM2")
        country = df["adm0_name"].iloc[0] if len(df) else ""
        sub = adm2[adm2["COUNTRY"] == country]
        if sub.empty:
            return
        excel_ids = set(sub["ISO_2"].astype(str))
        export_ids = set(df["adm2_gid"].astype(str).unique())
        matched = len(excel_ids & export_ids)
        if matched != len(export_ids) or matched != len(excel_ids):
            print(
                f"  warn: Excel ISO_2 crosswalk — export {len(export_ids)} ids, "
                f"excel {len(excel_ids)}, intersection {matched} ({iso3})"
            )
    except Exception as exc:
        print(f"  warn: Excel crosswalk check skipped: {exc}")


def run_convert_country(root: Path, job: CountryJob, *, skip_existing: bool) -> None:
    cmd = [
        sys.executable,
        str(_REPO / "scripts" / "gadm_shp_to_geojson.py"),
        "--version",
        job.gadm_version,
        "--iso3",
        job.iso3,
    ]
    if skip_existing:
        cmd.append("--skip-existing")
    else:
        cmd.append("--no-skip-existing")
    subprocess.run(cmd, check=True, cwd=root)


def export_country(
    job: CountryJob,
    *,
    root: Path,
    survey_parsed: pd.DataFrame,
    gadm_version: str,
    admin_level: int,
    do_modis: bool,
    do_firms: bool,
    do_frp: bool,
    do_viirs: bool,
    frp_metric: str = "max",
    skip_existing: bool,
    dry_run: bool,
) -> None:
    print(f"\n=== {job.iso3} ({job.country_wave}) gadm{gadm_version} ADM{admin_level} ===")
    if job.defer_reason:
        print(f"  defer: {job.defer_reason}")
    if job.notes:
        print(f"  note: {job.notes}")

    p_geo = gadm_geojson_path(job.iso3, admin_level, version=gadm_version, root=root)
    if not p_geo.is_file():
        raise FileNotFoundError(
            f"Missing GeoJSON: {p_geo}\n"
            f"Run: python scripts/gadm_shp_to_geojson.py --iso3 {job.iso3} --version {gadm_version}"
        )

    exposure_start, exposure_end = resolve_exposure_window(survey_parsed, job.country_wave)
    print(f"  exposure: {exposure_start} .. {exposure_end}")

    modis_path, firms_path = output_paths(
        root, job, exposure_end, gadm_version=gadm_version, admin_level=admin_level
    )
    frp_path = frp_output_path(
        root,
        job,
        exposure_end,
        gadm_version=gadm_version,
        admin_level=admin_level,
        metric=frp_metric,
    )
    viirs_path = viirs_output_path(
        root, job, exposure_end, gadm_version=gadm_version, admin_level=admin_level
    )
    n_units = feature_count(job.iso3, level=admin_level, version=gadm_version, root=root)
    print(f"  ADM{admin_level} polygons: {n_units}")

    requested_paths = []
    if do_modis:
        requested_paths.append(modis_path)
    if do_firms:
        requested_paths.append(firms_path)
    if do_frp:
        requested_paths.append(frp_path)
    if do_viirs:
        validate_viirs_coverage(exposure_start)
        requested_paths.append(viirs_path)

    if dry_run:
        names = ", ".join(p.name for p in requested_paths) or "no outputs"
        print(f"  dry-run: would write {names}")
        return

    if skip_existing and requested_paths and all(p.is_file() for p in requested_paths):
        print("  skipped (requested CSVs exist)")
        return

    months_gee = months_table_for_rolling(exposure_start, exposure_end)
    print(f"  GEE months to pull: {len(months_gee)} (includes rolling history)")

    import ee

    region_features = gadm_level_normalized_features(
        job.iso3, level=admin_level, version=gadm_version, root=root
    )
    n_chunks = len(
        _feature_dict_chunks_by_bytes(
            region_features,
            max_bytes=DEFAULT_REGION_CHUNK_MAX_BYTES,
            max_count=DEFAULT_REGION_CHUNK_SIZE,
        )
    )
    if n_chunks > 1:
        print(
            f"  boundary chunks: {n_chunks} "
            f"(max {DEFAULT_REGION_CHUNK_SIZE} districts, "
            f"{DEFAULT_REGION_CHUNK_MAX_BYTES // 1_000_000}MB JSON budget each)"
        )
    regions = ee.FeatureCollection(region_features[:1])

    if do_modis and not (skip_existing and modis_path.is_file()):
        print("  MODIS export...")
        adam_modis = build_adam_modis_export(
            months_gee,
            regions,
            adm0_name=job.adm0_name,
            adm0_pcode=job.adm0_pcode,
            exposure_start=exposure_start,
            exposure_end=exposure_end,
            scale_m=500.0,
            region_features=region_features,
            unit_level=admin_level,
        )
        write_adam_modis_csv(adam_modis, modis_path)
        qa_export_df(adam_modis, n_units, level=admin_level, label="MODIS")
        if admin_level == 2:
            warn_excel_crosswalk(job.iso3, adam_modis, root)
        print(f"  Wrote {modis_path}")
    elif do_modis:
        print(f"  MODIS skipped (exists): {modis_path}")

    if do_firms and not (skip_existing and firms_path.is_file()):
        print("  FIRMS export...")
        adam_firms = build_adam_firms_export(
            months_gee,
            regions,
            adm0_name=job.adm0_name,
            adm0_pcode=job.adm0_pcode,
            exposure_start=exposure_start,
            exposure_end=exposure_end,
            scale_m=1000.0,
            region_features=region_features,
            unit_level=admin_level,
        )
        write_adam_firms_csv(adam_firms, firms_path)
        qa_export_df(adam_firms, n_units, level=admin_level, label="FIRMS")
        print(f"  Wrote {firms_path}")
    elif do_firms:
        print(f"  FIRMS skipped (exists): {firms_path}")

    if do_frp and not (skip_existing and frp_path.is_file()):
        print(f"  FRP export ({frp_metric})...")
        frp_builder = (
            build_adam_frp_sum_export if frp_metric == "sum" else build_adam_frp_export
        )
        adam_frp = frp_builder(
            months_gee,
            regions,
            adm0_name=job.adm0_name,
            adm0_pcode=job.adm0_pcode,
            exposure_start=exposure_start,
            exposure_end=exposure_end,
            scale_m=1000.0,
            region_features=region_features,
            unit_level=admin_level,
        )
        write_adam_frp_csv(adam_frp, frp_path)
        qa_export_df(adam_frp, n_units, level=admin_level, label=f"FRP ({frp_metric})")
        print(f"  Wrote {frp_path}")
    elif do_frp:
        print(f"  FRP skipped (exists): {frp_path}")

    if do_viirs and not (skip_existing and viirs_path.is_file()):
        print("  VIIRS export...")
        adam_viirs = build_adam_viirs_export(
            months_gee,
            regions,
            adm0_name=job.adm0_name,
            adm0_pcode=job.adm0_pcode,
            exposure_start=exposure_start,
            exposure_end=exposure_end,
            scale_m=1000.0,
            region_features=region_features,
            unit_level=admin_level,
        )
        write_adam_viirs_csv(adam_viirs, viirs_path)
        qa_export_df(adam_viirs, n_units, level=admin_level, label="VIIRS")
        print(f"  Wrote {viirs_path}")
    elif do_viirs:
        print(f"  VIIRS skipped (exists): {viirs_path}")


def select_jobs(
    manifest: list[CountryJob],
    *,
    run_all: bool,
    iso3_list: list[str] | None,
    gadm_version_filter: str | None = None,
) -> list[CountryJob]:
    if iso3_list:
        jobs: list[CountryJob] = []
        for iso in iso3_list:
            candidates = [j for j in manifest if j.iso3 == iso]
            if gadm_version_filter is not None:
                candidates = [j for j in candidates if j.gadm_version == gadm_version_filter]
            if not candidates:
                hint = (
                    f" (no row with gadm_version={gadm_version_filter!r})"
                    if gadm_version_filter
                    else ""
                )
                raise ValueError(f"No manifest row for ISO3 {iso}{hint}")
            if len(candidates) > 1:
                opts = ", ".join(f"{j.country_wave} (gadm {j.gadm_version})" for j in candidates)
                raise ValueError(
                    f"Ambiguous ISO3 {iso}: {len(candidates)} rows ({opts}). "
                    "Pass --gadm-version to disambiguate."
                )
            jobs.append(candidates[0])
        return jobs

    if run_all:
        return [j for j in manifest if j.enabled]

    raise ValueError("Provide --all or --iso3 ISO3[,ISO3,...]")


def filter_viirs_available_jobs(
    jobs: list[CountryJob],
    survey_parsed: pd.DataFrame,
) -> list[CountryJob]:
    """Keep jobs whose full 12-month exposure window is covered by VNP14A1."""
    keep: list[CountryJob] = []
    skipped: list[str] = []
    for job in jobs:
        exposure_start, _ = resolve_exposure_window(survey_parsed, job.country_wave)
        if exposure_start >= VIIRS_FULL_COVERAGE_START:
            keep.append(job)
        else:
            skipped.append(f"{job.iso3} ({job.country_wave})")
    if skipped:
        print(
            "VIIRS coverage: skipped "
            f"{len(skipped)} pre-{VIIRS_FULL_COVERAGE_START} window(s): "
            + ", ".join(skipped)
        )
    return keep


def main() -> None:
    p = argparse.ArgumentParser(description="Batch GADM MODIS + FIRMS exports (ADM1/ADM2)")
    p.add_argument("--all", action="store_true", help="All enabled countries in manifest")
    p.add_argument("--iso3", help="Comma-separated GADM ISO3 codes")
    p.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    p.add_argument(
        "--gadm-version",
        default=None,
        help="GADM version key (36/40/41); disambiguates duplicate ISO3 and overrides manifest row",
    )
    p.add_argument(
        "--admin-level",
        type=int,
        default=None,
        choices=(0, 1, 2),
        help="Admin level (0/1/2); overrides manifest admin_level (1 for ADM1-only LSO/MDA)",
    )
    p.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip country when output CSVs already exist",
    )
    p.add_argument("--convert-only", action="store_true", help="Only run shapefile → GeoJSON")
    p.add_argument("--export-only", action="store_true", help="Skip convert step")
    p.add_argument("--modis-only", action="store_true")
    p.add_argument("--firms-only", action="store_true")
    p.add_argument("--frp-only", action="store_true", help="Only export MODIS FRP intensity")
    p.add_argument("--include-frp", action="store_true", help="Also export MODIS FRP intensity")
    p.add_argument("--viirs-only", action="store_true", help="Only export VIIRS active fire")
    p.add_argument("--include-viirs", action="store_true", help="Also export VIIRS active fire")
    p.add_argument(
        "--frp-metric",
        choices=("max", "sum"),
        default="max",
        help="FRP aggregation: 'max' (peak-intensity, legacy) or 'sum' (summed observed FRP)",
    )
    p.add_argument("--dry-run", action="store_true", help="Print plan; no GEE")
    p.add_argument("--project", help="Earth Engine GCP project id")
    args = p.parse_args()

    if args.frp_only and (
        args.modis_only
        or args.firms_only
        or args.include_frp
        or args.viirs_only
        or args.include_viirs
    ):
        p.error(
            "--frp-only cannot be combined with --modis-only, --firms-only, "
            "--include-frp, --viirs-only, or --include-viirs"
        )
    if args.viirs_only and (
        args.modis_only
        or args.firms_only
        or args.frp_only
        or args.include_frp
        or args.include_viirs
    ):
        p.error(
            "--viirs-only cannot be combined with --modis-only, --firms-only, "
            "--frp-only, --include-frp, or --include-viirs"
        )

    cli_gadm_version = str(args.gadm_version) if args.gadm_version is not None else None
    if cli_gadm_version is not None and cli_gadm_version not in GADM_VERSIONS:
        p.error(f"Unknown --gadm-version {cli_gadm_version!r}; expected {list(GADM_VERSIONS)}")

    root = find_repo_root()
    _load_dotenv(root)

    iso3_list = None
    if args.iso3:
        iso3_list = [x.strip().upper() for x in args.iso3.split(",") if x.strip()]

    if not args.all and not iso3_list:
        p.error("Provide --all or --iso3")

    manifest = load_manifest(args.manifest)
    jobs = select_jobs(
        manifest,
        run_all=args.all,
        iso3_list=iso3_list,
        gadm_version_filter=cli_gadm_version,
    )
    if not jobs:
        raise SystemExit("No countries selected.")

    if args.convert_only or not args.export_only:
        if not args.export_only:
            for job in jobs:
                run_convert_country(root, job, skip_existing=args.skip_existing)
        if args.convert_only:
            return

    if args.frp_only:
        do_modis = False
        do_firms = False
        do_frp = True
        do_viirs = False
    elif args.viirs_only:
        do_modis = False
        do_firms = False
        do_frp = False
        do_viirs = True
    else:
        do_modis = not args.firms_only
        do_firms = not args.modis_only
        do_frp = args.include_frp
        do_viirs = args.include_viirs

    survey_path = resolve_vacs_survey_time_csv(root)
    survey_parsed = add_parsed_field_dates(load_survey_time_table(survey_path))
    if args.viirs_only and args.all:
        jobs = filter_viirs_available_jobs(jobs, survey_parsed)
        if not jobs:
            raise SystemExit("No selected countries have full VIIRS VNP14A1 coverage.")

    if not args.dry_run:
        if args.project:
            import os

            os.environ["EARTHENGINE_PROJECT"] = args.project
        project = ee_initialize_from_environ()
        print(f"Earth Engine project: {project}")

    for job in jobs:
        ver = effective_gadm_version(job, cli_gadm_version)
        lvl = effective_admin_level(job, args.admin_level)
        try:
            export_country(
                job,
                root=root,
                survey_parsed=survey_parsed,
                gadm_version=ver,
                admin_level=lvl,
                do_modis=do_modis,
                do_firms=do_firms,
                do_frp=do_frp,
                do_viirs=do_viirs,
                frp_metric=args.frp_metric,
                skip_existing=args.skip_existing,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            print(f"  FAILED {job.iso3}: {exc}", file=sys.stderr)
            raise


if __name__ == "__main__":
    main()
