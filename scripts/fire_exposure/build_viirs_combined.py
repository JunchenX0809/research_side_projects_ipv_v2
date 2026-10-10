#!/usr/bin/env python3
"""Join every VIIRS metric into one file per country-level.

Replaces the manual join that was needed after the Indonesia delivery. Sources:

  viirs/             VNP14A1 pixel-days + FRP  (legacy count, sensitivity only)
  viirs_unique/      VNP14A1 unique pixels     (THE active-fire count going forward)
  viirs_burned_area/ VNP64A1 burned area       (optional; absent for some waves)

**`monthly_fire_count` / `avg12_fire_count` carry the UNIQUE-pixel values**, because that is
the metric the PI uses. The legacy pixel-day counts are kept under explicit ``_pixeldays``
suffixes so the two can never be confused: for Cambodia ADM2 they differ by 17.7%
(46,372 pixel-days against 38,184 unique).

FRP columns stay pixel-day based, since FRP is only computed in the legacy pass. Making FRP
unique-based would need an Earth Engine change, not a join. Deliberately out of scope.

When burned area is unavailable for a wave (Cambodia: VNP64A1 starts 2012-03-01, after its
window opens) the burned-area columns are still emitted, as **NULL**, so every country-level
file shares an identical schema and the set can be stacked without reconciliation.

Usage::

    .venv/bin/python -m scripts.fire_exposure.build_viirs_combined --dir data/processed/gadm4_1_new
    .venv/bin/python -m scripts.fire_exposure.build_viirs_combined --dir data/processed/gadm4_1_new --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

MONTHLY_BURN = "monthly_viirs_burned_area_km2"
AVG12_BURN = "avg12_viirs_burned_area_km2"

# legacy pixel-day count columns, renamed so they cannot be mistaken for the primary metric
PIXELDAY_RENAME = {
    "monthly_fire_count": "monthly_fire_count_pixeldays",
    "avg12_fire_count": "avg12_fire_count_pixeldays",
}
FRP_COLS = ["monthly_max_frp_mw", "monthly_sum_frp_mw", "avg12_sum_frp_mw"]

COLUMN_ORDER = [
    "adm0_name", "adm0_pcode", "adm1_name", "adm1_gid",
    "adm2_name", "adm2_gid", "adm1_area_km2", "adm2_area_km2",
    "month_start", "month_end",
    "monthly_fire_count", "avg12_fire_count",                      # unique, primary
    "monthly_fire_count_pixeldays", "avg12_fire_count_pixeldays",  # legacy, sensitivity
    "monthly_max_frp_mw", "monthly_sum_frp_mw", "avg12_sum_frp_mw",
    MONTHLY_BURN, AVG12_BURN,
]


def keys_for(df: pd.DataFrame) -> list[str]:
    gid = "adm2_gid" if "adm2_gid" in df.columns else "adm1_gid"
    return [gid, "month_start", "month_end"]


def load(path: Path, label: str) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    df = pd.read_csv(path)
    k = keys_for(df)
    if df.duplicated(k).any():
        raise ValueError(f"{label}: duplicate {k} rows")
    return df


def build_one(base: Path, unique_path: Path, dry_run: bool) -> tuple[Path, int, bool]:
    """Combine one country-level triple. Returns (output path, rows, had burned area)."""
    stem = unique_path.name
    legacy_path = base / "viirs" / stem
    burn_path = base / "viirs_burned_area" / stem.replace("vnp14a1", "vnp64a1")
    out_path = base / "viirs_combined" / stem.replace("vnp14a1", "vnp14a1_vnp64a1")

    uniq = load(unique_path, "viirs_unique")
    legacy = load(legacy_path, "viirs")
    k = keys_for(uniq)

    if set(map(tuple, uniq[k].astype(str).to_numpy())) != set(
        map(tuple, legacy[k].astype(str).to_numpy())
    ):
        raise ValueError(f"{stem}: unique and legacy key sets differ")

    # unique is the base table; its fire-count columns stay as the primary metric
    out = uniq.copy()
    legacy_cols = [c for c in FRP_COLS if c in legacy.columns]
    add = legacy[k + list(PIXELDAY_RENAME) + legacy_cols].rename(columns=PIXELDAY_RENAME)
    out = out.merge(add, on=k, how="left", validate="one_to_one", indicator=True)
    if (out["_merge"] != "both").any():
        raise ValueError(f"{stem}: legacy join is not one-to-one")
    out = out.drop(columns="_merge")

    had_burn = burn_path.is_file()
    if had_burn:
        burn = load(burn_path, "viirs_burned_area")
        out = out.merge(
            burn[k + [MONTHLY_BURN, AVG12_BURN]],
            on=k, how="left", validate="one_to_one", indicator=True,
        )
        if (out["_merge"] != "both").any():
            raise ValueError(f"{stem}: burned-area join is not one-to-one")
        out = out.drop(columns="_merge")
    else:
        # schema parity: emit the columns as NULL so every file stacks without reconciliation
        out[MONTHLY_BURN] = pd.NA
        out[AVG12_BURN] = pd.NA

    out = out[[c for c in COLUMN_ORDER if c in out.columns]]
    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".csv.tmp")
        out.to_csv(tmp, index=False)
        tmp.replace(out_path)
    return out_path, len(out), had_burn


def main() -> None:
    ap = argparse.ArgumentParser(description="Join VIIRS metrics into one file per country-level")
    ap.add_argument("--dir", default="data/processed/gadm4_1_new",
                    help="folder holding viirs/, viirs_unique/ and optionally viirs_burned_area/")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    base = Path(args.dir)
    sources = sorted((base / "viirs_unique").glob("*.csv"))
    if not sources:
        raise SystemExit(f"no viirs_unique/*.csv under {base}")

    for src in sources:
        out_path, rows, had_burn = build_one(base, src, args.dry_run)
        note = "with burned area" if had_burn else "burned area NULL (not available for this wave)"
        verb = "would write" if args.dry_run else "wrote"
        print(f"  {verb} {out_path.name}  {rows} rows, {note}", flush=True)


if __name__ == "__main__":
    main()
