#!/usr/bin/env python3
"""Check every exposure file's ``avg12_*`` column against the project definition.

The definition (`report_outputs/0723_process_update.md`): ``avg12_x`` is the **arithmetic mean
of the unit's 12 monthly ``monthly_x`` values**, constant within a unit. A file that breaks this
is not necessarily wrong — it may be using a different convention on purpose — but it must never
break it silently, because the column name promises a monthly rate and the alternatives are
year totals.

Three departures have been seen, and the script names them rather than just failing:

``name_grouping``
    ``avg12`` was grouped by unit NAME instead of GID, pooling ADM2 units that share a name
    (Malawi has eight polygons called "Lake Malawi"). Fixed in the exporters 2026-07-06/07;
    only files rendered before that carry it. Detected by reproducing ``avg12`` exactly as a
    name-grouped mean.

``window_total``
    ``avg12`` holds the whole window's total rather than the monthly mean — roughly 12x too
    large, and exactly equal to the sum of the monthly values wherever nothing burned twice.
    Seen in externally supplied MODIS files.

``aod_full_window``
    MAIAC AOD only, and **deliberate**: the teammate's ``avg12_mean_aod`` is the polygon mean of
    one full-window composite image, not the mean of the 12 monthly polygon means. Documented in
    `report_outputs/0718_process_update.md` and `skills/aod_data_methods.md`. Reported as
    ``by design`` so nobody "fixes" it.

Usage::

    .venv/bin/python -m scripts.quality_checks.audit_avg12_convention
    .venv/bin/python -m scripts.quality_checks.audit_avg12_convention --root data/processed --out audit.csv
    .venv/bin/python -m scripts.quality_checks.audit_avg12_convention --fail-on-new   # non-zero exit on an unexplained break
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[2]

GID_CANDIDATES = ["adm2_gid", "GID_2", "adm1_gid", "GID_1", "ADM2_PCODE"]
NAME_CANDIDATES = ["adm2_name", "NAME_2", "adm1_name", "NAME_1"]

# avg12 column -> the monthly column it should summarise, where the names do not simply
# swap the prefix.
MONTHLY_FOR = {
    "avg12_fire_count": "monthly_fire_count",
    "avg12_sum_frp_mw": "monthly_sum_frp_mw",
    "avg12_max_frp_mw": "monthly_max_frp_mw",
    "avg12_burned_area_km2": "monthly_burned_area_km2",
    "avg12_viirs_burned_area_km2": "monthly_viirs_burned_area_km2",
    "avg12_mean_aod": "monthly_mean_aod",
    "avg12_fire_count_pixeldays": "monthly_fire_count_pixeldays",
}

RTOL = 1e-9


def first_present(df: pd.DataFrame, names: list[str]) -> str | None:
    return next((c for c in names if c in df.columns), None)


def classify(df: pd.DataFrame, avg_col: str, mon_col: str, gid: str, name: str | None,
             is_aod: bool) -> dict:
    g = df.groupby(gid)
    supplied, mean12, sum12 = g[avg_col].first(), g[mon_col].mean(), g[mon_col].sum()
    n_units = int(g.ngroups)

    constant = bool((g[avg_col].nunique(dropna=False) <= 1).all())
    ok = np.isclose(supplied, mean12, rtol=RTOL, equal_nan=True)
    n_wrong = int((~ok).sum())

    nz = sum12.abs() > 0
    ratio = (supplied[nz] / mean12[nz].replace(0, np.nan)).dropna()
    # A window total equals the monthly SUM, or sits just below it when a cell that burned in
    # two monthly composites is counted once. It never exceeds it by more than rounding.
    to_sum = (supplied[nz] / sum12[nz].replace(0, np.nan)).dropna()
    exact_sum = int(np.isclose(supplied[nz], sum12[nz], rtol=RTOL).sum())

    repeated_names = 0
    name_explains = np.nan
    if name is not None:
        rn = df.groupby(name)[gid].nunique()
        repeated_names = int((rn > 1).sum())
        by_name = df[name].map(df.groupby(name)[mon_col].mean())
        name_explains = float(np.isclose(by_name, df[avg_col], rtol=RTOL,
                                         equal_nan=True).mean())

    if n_wrong == 0:
        verdict, note = "ok", "avg12 == mean(monthly) for every unit"
    elif is_aod:
        verdict, note = "by design", "MAIAC full-window composite; documented, do not change"
    elif name_explains == 1.0:
        verdict, note = ("name_grouping",
                         f"avg12 reproduced exactly as a NAME-grouped mean; "
                         f"{repeated_names} repeated unit names")
    elif len(to_sum) and to_sum.between(0.75, 1.02).all():
        verdict, note = ("window_total",
                         f"avg12 is the window TOTAL, not the monthly mean "
                         f"({ratio.min():.1f}x-{ratio.max():.1f}x the mean); equals the monthly "
                         f"SUM exactly in {exact_sum}/{int(nz.sum())} burning units")
    else:
        verdict, note = "UNEXPLAINED", "does not match any known convention — investigate"

    return {
        "verdict": verdict, "avg12_col": avg_col, "units": n_units, "units_wrong": n_wrong,
        "avg12_constant_within_unit": constant,
        "ratio_min": round(float(ratio.min()), 4) if len(ratio) else None,
        "ratio_max": round(float(ratio.max()), 4) if len(ratio) else None,
        "units_avg12_equals_sum": exact_sum,
        "ratio_to_sum_min": round(float(to_sum.min()), 4) if len(to_sum) else None,
        "ratio_to_sum_max": round(float(to_sum.max()), 4) if len(to_sum) else None,
        "repeated_unit_names": repeated_names,
        "pct_rows_explained_by_name_grouping": (
            None if np.isnan(name_explains) else round(name_explains * 100, 1)),
        "note": note,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default="data/processed")
    ap.add_argument("--out", default=None, help="write the full table to this CSV")
    ap.add_argument("--all", action="store_true", help="list passing files too")
    ap.add_argument("--fail-on-new", action="store_true",
                    help="exit 1 if any file is UNEXPLAINED")
    a = ap.parse_args()

    root = Path(a.root) if Path(a.root).is_absolute() else _REPO / a.root
    rows: list[dict] = []
    skipped = 0

    for p in sorted(root.rglob("*.csv")):
        if p.name.startswith("."):
            continue
        try:
            df = pd.read_csv(p, low_memory=False)
        except Exception:
            skipped += 1
            continue
        avg_cols = [c for c in df.columns if c.startswith("avg12_")]
        if not avg_cols or "month_start" not in df.columns:
            continue
        gid = first_present(df, GID_CANDIDATES)
        if gid is None:
            skipped += 1
            continue
        name = first_present(df, NAME_CANDIDATES)
        is_aod = "aod" in p.parts[-2].lower() or "aod" in p.name.lower()
        for ac in avg_cols:
            mc = MONTHLY_FOR.get(ac, ac.replace("avg12_", "monthly_", 1))
            if mc not in df.columns:
                continue
            r = classify(df, ac, mc, gid, name, is_aod)
            r["file"] = str(p.relative_to(_REPO))
            r["months"] = int(df["month_start"].nunique())
            rows.append(r)

    out = pd.DataFrame(rows)
    if out.empty:
        raise SystemExit(f"no exposure files with an avg12 column under {root}")
    cols = ["file", "avg12_col", "verdict", "units", "units_wrong", "months",
            "avg12_constant_within_unit", "ratio_min", "ratio_max",
            "units_avg12_equals_sum", "ratio_to_sum_min", "ratio_to_sum_max", "repeated_unit_names",
            "pct_rows_explained_by_name_grouping", "note"]
    out = out[cols].sort_values(["verdict", "file"]).reset_index(drop=True)

    print(f"checked {out.file.nunique()} files / {len(out)} avg12 columns under {root}"
          f"{f'  ({skipped} unreadable, skipped)' if skipped else ''}\n")
    print(out.verdict.value_counts().to_string(), "\n")
    show = out if a.all else out[out.verdict != "ok"]
    if len(show):
        print(show[["file", "avg12_col", "verdict", "units_wrong", "units",
                    "ratio_min", "ratio_max", "units_avg12_equals_sum"]].to_string(index=False))
    else:
        print("every file matches the project definition")

    if a.out:
        dest = Path(a.out) if Path(a.out).is_absolute() else _REPO / a.out
        dest.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(dest, index=False, lineterminator="\n")
        print(f"\nwrote {dest.relative_to(_REPO)}  ({len(out)} rows)")

    if a.fail_on_new and (out.verdict == "UNEXPLAINED").any():
        sys.exit(1)


if __name__ == "__main__":
    main()
