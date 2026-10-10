#!/usr/bin/env python3
"""Build the Indonesia v2 combined VIIRS files, with unique-pixel active-fire counts.

Takes each existing combined file and replaces its active-fire counts with the
unique-pixel values, leaving FRP and burned area untouched.

**The v2 schema is identical to the v1 schema: same 16 columns, same order, same names.
Only the MEANING of `monthly_fire_count` and `avg12_fire_count` changes**, from pixel-days
(a cell detected on 10 days counted 10) to unique pixels (each cell at most once per
month). Junchen's decision: no legacy columns and no `_pixeldays` suffixes, because the v1
folder is kept as the pixel-day record.

That makes the two folders visually indistinguishable, so **never compare counts across
them and read the difference as a change in fires**. For 2015 the unique total is 18.7%
below pixel-days.

    in   data/processed/viirs_combined/indonesia_viirs_vnp14a1_vnp64a1_codbps20200401_<year>.csv
    in   data/processed/viirs_unique_idn/indonesia_viirs_vnp14a1_unique_<year>.csv
    out  data/processed/viirs_combined_idn_v2/indonesia_viirs_vnp14a1_<year>_combined.csv

`avg12_fire_count` is taken from the unique file, where it was recomputed from the new
monthly values. It is never carried over from v1.

Usage::

    .venv/bin/python -m scripts.fire_exposure.build_indonesia_viirs_combined_v2 --dry-run
    .venv/bin/python -m scripts.fire_exposure.build_indonesia_viirs_combined_v2
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

V1_DIR = _REPO / "data" / "processed" / "viirs_combined"
UNIQUE_DIR = _REPO / "data" / "processed" / "viirs_unique_idn"
V2_DIR = _REPO / "data" / "processed" / "viirs_combined_idn_v2"

KEYS = ["adm2_gid", "month_start", "month_end"]
REPLACED = ["monthly_fire_count", "avg12_fire_count"]


def build_year(year: int, dry_run: bool) -> tuple[Path, int, float]:
    """Returns (output path, rows, unique/pixel-days ratio) for one year."""
    v1_path = V1_DIR / f"indonesia_viirs_vnp14a1_vnp64a1_codbps20200401_{year}.csv"
    uniq_path = UNIQUE_DIR / f"indonesia_viirs_vnp14a1_unique_{year}.csv"
    out_path = V2_DIR / f"indonesia_viirs_vnp14a1_{year}_combined.csv"
    for label, p in (("v1 combined", v1_path), ("unique", uniq_path)):
        if not p.is_file():
            raise FileNotFoundError(f"{label} input missing: {p}")

    v1 = pd.read_csv(v1_path)
    uq = pd.read_csv(uniq_path)

    # The v1 files are not consistent about date format: 2017 stores US dates
    # ("2/29/16") while every other year stores ISO ("2016-02-29"). The intervals are
    # the same, so normalise both sides to ISO before joining rather than treating a
    # formatting difference as a data mismatch. v1 keeps whatever it had on disk for
    # every other column; only the join keys are normalised, and they are rewritten
    # to ISO in the output so v2 is internally consistent.
    for df in (v1, uq):
        for col in ("month_start", "month_end"):
            df[col] = pd.to_datetime(df[col], format="mixed").dt.strftime("%Y-%m-%d")

    for label, df in (("v1", v1), ("unique", uq)):
        if df.duplicated(KEYS).any():
            raise ValueError(f"{year} {label}: duplicate {KEYS} rows")
    if set(map(tuple, v1[KEYS].astype(str).to_numpy())) != set(
        map(tuple, uq[KEYS].astype(str).to_numpy())
    ):
        raise ValueError(f"{year}: v1 and unique key sets differ")

    ratio = uq["monthly_fire_count"].sum() / max(v1["monthly_fire_count"].sum(), 1e-9)

    out = v1.drop(columns=REPLACED).merge(
        uq[KEYS + REPLACED], on=KEYS, how="left", validate="one_to_one", indicator=True
    )
    if len(out) != len(v1) or (out["_merge"] != "both").any():
        raise ValueError(f"{year}: join is not one-to-one")
    out = out.drop(columns="_merge")[list(v1.columns)]  # restore the v1 column order

    if list(out.columns) != list(v1.columns):
        raise ValueError(f"{year}: schema drifted from v1")
    if out[REPLACED].isna().any().any():
        raise ValueError(f"{year}: null counts after the join")

    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".csv.tmp")
        out.to_csv(tmp, index=False)
        tmp.replace(out_path)
    return out_path, len(out), ratio


def main() -> None:
    ap = argparse.ArgumentParser(description="Indonesia v2 combined VIIRS files")
    ap.add_argument("--years", help="Comma-separated years; default every unique file found")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.years:
        years = sorted(int(v.strip()) for v in args.years.split(",") if v.strip())
    else:
        years = sorted(
            int(m.group(1))
            for p in UNIQUE_DIR.glob("indonesia_viirs_vnp14a1_unique_*.csv")
            if (m := re.search(r"_(\d{4})\.csv$", p.name))
        )
    if not years:
        raise SystemExit(f"no unique files found under {UNIQUE_DIR}")

    verb = "would write" if args.dry_run else "wrote"
    for year in years:
        path, rows, ratio = build_year(year, args.dry_run)
        print(
            f"  {verb} {path.name}  {rows} rows, "
            f"unique/pixel-days {ratio:.3f} ({100 * (1 - ratio):.1f}% lower)",
            flush=True,
        )


if __name__ == "__main__":
    main()
