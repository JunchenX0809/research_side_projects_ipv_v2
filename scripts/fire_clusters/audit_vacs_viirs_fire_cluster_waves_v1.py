#!/usr/bin/env python3
"""Independent file-level audit of the remaining-wave VNP64A1 v1 panels."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.fire_clusters.run_vacs_viirs_fire_cluster_waves_v1 import QUEUE, ROOT, RUN_STATUS, wave_row

REPORT = ROOT / "skills/0927_fireClusters/vacs_viirs_generation_audit_v1.md"
MEASURES = [
    "monthly_viirs_burned_area_km2",
    "avg12_viirs_burned_area_km2",
    "monthly_viirs_fire_cluster_count",
    "avg12_viirs_fire_cluster_count",
]


def iso_dates(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for column in ("month_start", "month_end"):
        frame[column] = pd.to_datetime(frame[column], format="mixed", errors="raise").dt.strftime("%Y-%m-%d")
    return frame


def main() -> None:
    with RUN_STATUS.open(newline="") as handle:
        records = {(row["wave"], row["level"]): row for row in csv.DictReader(handle)}
    details = []
    errors = []
    uganda = {}
    for slug, year, _, active_name, level in QUEUE:
        wave = f"{slug}_{year}"
        key = (wave, f"ADM{level}")
        record = records.get(key)
        if not record or record["status"] != "complete":
            errors.append(f"{wave} ADM{level}: run status is not complete")
            continue
        try:
            panel = iso_dates(pd.read_csv(ROOT / record["panel"]))
            burned = iso_dates(pd.read_csv(ROOT / record["burned_area"]))
            active = iso_dates(pd.read_csv(ROOT / "data/processed/viirs" / active_name))
            status = wave_row(slug, year)
            start, end = status["window"].split("..")
            gid = f"adm{level}_gid"
            keys = [gid, "month_start", "month_end"]
            if any(column not in panel for column in keys + MEASURES):
                raise ValueError("required keys or measures missing")
            if any(column in panel for column in ("monthly_fire_count", "monthly_sum_frp_mw", "monthly_mean_aod")):
                raise ValueError("unrequested active-fire/AOD measure present")
            units = active[gid].nunique()
            if len(panel) != 12 * units or panel.duplicated(keys).any():
                raise ValueError("panel rows or unique keys do not equal 12 x reference GADM units")
            if panel.month_start.min() != start or panel.month_end.max() != end:
                raise ValueError("panel window differs from wave status")
            if set(map(tuple, panel[keys].to_numpy())) != set(map(tuple, active[keys].to_numpy())):
                raise ValueError("panel GADM/date keys differ from active reference")
            if set(map(tuple, panel[keys].to_numpy())) != set(map(tuple, burned[keys].to_numpy())):
                raise ValueError("panel GADM/date keys differ from burned-area source")
            if panel[MEASURES].isna().any().any() or (panel[MEASURES] < 0).any().any():
                raise ValueError("missing or negative measure")
            source = panel[keys + MEASURES[:2]].merge(burned[keys + MEASURES[:2]], on=keys, validate="one_to_one", suffixes=("_panel", "_source"))
            for measure in MEASURES[:2]:
                if not np.allclose(source[f"{measure}_panel"], source[f"{measure}_source"], rtol=0, atol=1e-10):
                    raise ValueError(f"{measure} differs from source")
            for monthly, avg in ((MEASURES[0], MEASURES[1]), (MEASURES[2], MEASURES[3])):
                true_mean = panel.groupby(gid)[monthly].transform("mean")
                if not np.allclose(true_mean, panel[avg], rtol=0, atol=1e-10):
                    raise ValueError(f"{avg} is not the mean of 12 monthly values")
            if not np.allclose(panel[MEASURES[2]], np.round(panel[MEASURES[2]]), rtol=0, atol=0):
                raise ValueError("monthly patch count is not integer")
            summary_path = (ROOT / record["panel"]).with_name(Path(record["panel"]).stem + "_summary.md")
            summary = summary_path.read_text()
            match = re.search(r"Nominal raster area / zonal burned area \|[^\n]*\(([+-]?\d+(?:\.\d+)?)%\)", summary)
            if not match:
                raise ValueError("raster/zonal area audit missing")
            area_pct = float(match.group(1))
            if abs(area_pct) > 5:
                raise ValueError(f"raster/zonal area difference {area_pct:+.2f}% exceeds 5%")
            cluster_total = int(panel[MEASURES[2]].sum())
            if slug == "uganda":
                uganda[level] = panel.groupby(["month_start", "month_end"])[MEASURES[2]].sum().sort_index()
            details.append((wave, level, units, len(panel), cluster_total, area_pct))
        except Exception as exc:
            errors.append(f"{wave} ADM{level}: {type(exc).__name__}: {exc}")
    if set(uganda) == {1, 2} and not uganda[1].equals(uganda[2]):
        errors.append("Uganda: national monthly cluster totals differ between ADM1 and ADM2 panels")
    lines = [
        "# VACS VIIRS burned-area and burn-patch v1: final file audit", "",
        f"**Result:** {len(details)}/{len(QUEUE)} requested panels passed; {len(errors)} audit issue(s). Cambodia 2013 remains deferred for incomplete VNP64A1 coverage. Zambia was the earlier method demo; Indonesia is outside scope.", "",
        "Checks: selected GADM unit-month keys equal the local reference and burned-area source; exact survey window; one row per unit-month; nonmissing/nonnegative values; burned-area values match source; both 12-month means equal monthly arithmetic means; integer monthly cluster count; raster-versus-zonal burned-area difference within 5%. Uganda ADM1 and ADM2 national monthly cluster totals are compared.", "",
        "| Wave | Level | GADM units | Rows | Patch-months | Raster vs zonal area |", "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    lines += [f"| {wave} | ADM{level} | {units:,} | {rows:,} | {clusters:,} | {pct:+.2f}% |" for wave, level, units, rows, clusters, pct in details]
    lines += ["", "## Issues", ""]
    lines += [f"- {item}" for item in errors] if errors else ["None in the final file audit."]
    lines += ["", "This file audit does not validate the 5-day clustering rule against an independent fire-event reference. The measure is a count of burn patches under the documented v1 parameters, not verified ignitions. No respondent linkage was run.", ""]
    REPORT.write_text("\n".join(lines))
    print(f"{len(details)}/{len(QUEUE)} panels passed; {len(errors)} issues. Report: {REPORT}")
    for item in errors:
        print("ISSUE:", item)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
