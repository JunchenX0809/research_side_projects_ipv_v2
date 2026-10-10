#!/usr/bin/env python3
"""Generate Indonesia VNP14A1 **unique active-fire pixel** counts on COD/BPS Admin-2.

The unique-pixel count is the active-fire metric going forward; the existing pixel-day
product (``data/processed/viirs/indonesia_*``) is retained only as a legacy record and is
**not** modified by this script.

Additive: it reuses ``fetch_unique_viirs_chunk`` and every existing Indonesia helper, and
leaves ``fetch_active_viirs_chunk`` and the burned-area runner untouched.

Output, one file per year::

    data/processed/viirs_unique_idn/indonesia_viirs_vnp14a1_unique_<year>.csv

Usage::

    .venv/bin/python -m scripts.fire_exposure.run_indonesia_viirs_unique --years 2015 --dry-run
    caffeinate -dimsu .venv/bin/python -u -m scripts.fire_exposure.run_indonesia_viirs_unique --years 2015

Resume is per-year by file existence, the same pattern the burned-area runner uses: a
ten-year run that dies at year 7 skips 1-6 when restarted. Pass ``--force`` to rebuild.
There is no shared checkpoint keyed by an id, so this cannot collide with another job's
state the way the AOD job ids did.

Run long jobs on AC power under ``caffeinate -dimsu``; macOS maintenance sleep on battery
has killed exports on this project twice.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.gee_fire_zonal import ee_initialize_from_environ
from utils.indonesia_viirs import (
    fetch_unique_viirs_chunk,
    finalize_unique_viirs,
    indonesia_feature_chunks,
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
OUTPUT_DIR = _REPO / "data" / "processed" / "viirs_unique_idn"


def _load_dotenv() -> None:
    env = _REPO / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _selected_references(years: set[int] | None) -> list[Path]:
    paths = sorted(REFERENCE_DIR.glob("*_AOD.csv"))
    if years is not None:
        paths = [p for p in paths if int(p.stem.split("_", 1)[0]) in years]
    if not paths:
        raise ValueError("No Indonesia AOD reference files selected")
    return paths


def output_path(year: int) -> Path:
    return OUTPUT_DIR / f"indonesia_viirs_vnp14a1_unique_{year}.csv"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Indonesia VNP14A1 unique active-fire pixels, COD/BPS Admin-2"
    )
    ap.add_argument("--years", help="Comma-separated years; default all references")
    ap.add_argument("--project", help="Earth Engine GCP project id")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="Rebuild years that already exist")
    ap.add_argument("--simplify-tolerance-m", type=float, default=10.0)
    ap.add_argument("--chunk-count", type=int, default=80)
    ap.add_argument("--chunk-bytes", type=int, default=4_000_000)
    args = ap.parse_args()

    years = None
    if args.years:
        years = {int(v.strip()) for v in args.years.split(",") if v.strip()}
    references = [load_indonesia_reference(p) for p in _selected_references(years)]

    base_features, diag = load_cod_bps_adm2_features(
        ADM2_SHAPEFILE,
        area_by_code=references[0].area_by_code,
        simplify_tolerance_m=args.simplify_tolerance_m,
    )
    print(
        f"Boundary: {diag.feature_count} Admin-2; repaired={diag.repaired_count}; "
        f"simplified={diag.simplify_tolerance_m:g}m; "
        f"payload={diag.serialized_size_mb:.1f}MB; "
        f"largest feature={diag.maximum_feature_size_mb:.2f}MB",
        flush=True,
    )
    for ref in references:
        print(
            f"{ref.year}: {len(ref.codes)} Admin-2 × {len(ref.months)} intervals -> "
            f"{output_path(ref.year)}",
            flush=True,
        )
    if args.dry_run:
        print("dry-run: no Earth Engine calls made", flush=True)
        return

    _load_dotenv()
    if args.project:
        os.environ["EARTHENGINE_PROJECT"] = args.project
    print(f"Earth Engine project: {ee_initialize_from_environ()}", flush=True)

    for ref in references:
        out = output_path(ref.year)
        if out.is_file() and not args.force:
            print(f"\n{ref.year}: exists, skipping ({out.name})", flush=True)
            continue

        features = replace_feature_areas(base_features, ref.area_by_code)
        chunks = indonesia_feature_chunks(
            features, max_count=args.chunk_count, max_bytes=args.chunk_bytes
        )
        print(f"\n=== Indonesia {ref.year}: {len(chunks)} boundary chunks ===", flush=True)

        started = time.time()
        parts: list[pd.DataFrame] = []
        for i, chunk in enumerate(chunks, start=1):
            parts.append(fetch_unique_viirs_chunk(ref.months, chunk))
            print(
                f"  chunk {i}/{len(chunks)} ({len(chunk)} units) "
                f"[{time.time() - started:.0f}s elapsed]",
                flush=True,
            )
        frame = finalize_unique_viirs(pd.concat(parts, ignore_index=True))
        # Only the two count columns exist in this product; the legacy validator takes
        # the value columns explicitly rather than assuming the active-fire set.
        validate_indonesia_export(
            frame,
            ref,
            value_columns=["monthly_fire_count", "avg12_fire_count"],
            label=f"Indonesia {ref.year} unique VNP14A1",
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        write_csv_atomic(frame, out)
        print(
            f"  wrote {out} ({len(frame)} rows) in {time.time() - started:.1f}s",
            flush=True,
        )


if __name__ == "__main__":
    main()
