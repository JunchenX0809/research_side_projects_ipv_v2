#!/usr/bin/env python3
"""Run the approved VACS VNP64A1 geographic exposure queue sequentially.

This intentionally excludes Zambia (already done), Cambodia (incomplete source
window), Indonesia (separate study), and sensor-ineligible waves. Uganda ADM1
and ADM2 run last, as separately labeled outputs. A failed wave is recorded
and the next wave is still attempted.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WAVE_STATUS = ROOT / "skills/0920_linkage_demo/wave_status_2026-09-22.csv"
RUN_STATUS = ROOT / "skills/0927_fireClusters/vacs_viirs_generation_status_v1.csv"

# slug, VACS year, GADM ISO3, active-reference filename, ADM level
QUEUE = [
    ("eswatini", 2022, "SWZ", "eswatini_viirs_vnp14a1_gadm41_adm1_2022.csv", 1),
    ("rwanda", 2016, "RWA", "rwanda_viirs_vnp14a1_gadm36_2015.csv", 2),
    ("el_salvador", 2018, "SLV", "elsalvador_viirs_vnp14a1_gadm36_2017.csv", 2),
    ("lesotho", 2018, "LSO", "lesotho_viirs_vnp14a1_gadm36_adm1_2018.csv", 1),
    ("moldova", 2013, "MDA", "moldova_viirs_vnp14a1_gadm36_adm1_2018.csv", 1),
    ("malawi", 2013, "MWI", "malawi_viirs_vnp14a1_gadm36_adm1_2013.csv", 1),
    ("cote_divoire", 2019, "CIV", "cotedivoire_viirs_vnp14a1_gadm36_2018.csv", 2),
    ("honduras", 2017, "HND", "honduras_viirs_vnp14a1_gadm36_2017.csv", 2),
    ("zimbabwe", 2017, "ZWE", "zimbabwe_viirs_vnp14a1_gadm36_2016.csv", 2),
    ("kenya", 2019, "KEN", "kenya_viirs_vnp14a1_gadm36_adm1_2018.csv", 1),
    ("tanzania", 2024, "TZA", "tanzania_viirs_vnp14a1_gadm41_adm1_2024.csv", 1),
    ("nigeria", 2014, "NGA", "nigeria_viirs_vnp14a1_gadm36_adm1_2014.csv", 1),
    ("namibia", 2019, "NAM", "namibia_viirs_vnp14a1_gadm36_adm1_2019.csv", 1),
    ("mozambique", 2019, "MOZ", "mozambique_viirs_vnp14a1_gadm40_adm1_2019.csv", 1),
    ("colombia", 2018, "COL", "colombia_viirs_vnp14a1_gadm41_2018.csv", 2),
    ("uganda", 2015, "UGA", "uganda_viirs_vnp14a1_gadm36_adm1_2015.csv", 1),
    ("uganda", 2015, "UGA", "uganda_viirs_vnp14a1_gadm36_2015.csv", 2),
]


def wave_row(slug: str, year: int) -> dict[str, str]:
    with WAVE_STATUS.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_key = {(row["country"].lower().replace(" ", "_").replace("'", "").replace("_d_", "_"), int(row["year"])): row for row in rows}
    # The status CSV uses a different punctuation convention for these names.
    aliases = {"el_salvador": "el_salvador", "cote_divoire": "cote_divoire"}
    key = (aliases.get(slug, slug), year)
    if key not in by_key:
        raise ValueError(f"Wave absent from status table: {slug} {year}")
    return by_key[key]


def log_command(command: list[str], log_path: Path) -> int:
    print("$", " ".join(command), flush=True)
    with log_path.open("a") as log:
        log.write("\n$ " + " ".join(command) + "\n")
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        return process.wait()


def save_status(records: list[dict[str, str]]) -> None:
    RUN_STATUS.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUN_STATUS.with_suffix(".csv.tmp")
    columns = ["wave", "level", "status", "burned_area", "panel", "run_log", "updated_at", "detail"]
    with tmp.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)
    tmp.replace(RUN_STATUS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="wave slugs to run (e.g. rwanda uganda)")
    parser.add_argument("--force", action="store_true", help="rerender already completed panels")
    args = parser.parse_args()
    previous = {}
    if RUN_STATUS.is_file():
        with RUN_STATUS.open(newline="") as handle:
            previous = {(row["wave"], row["level"]): row for row in csv.DictReader(handle)}
    records = previous.copy()
    for slug, year, iso3, active_name, level in QUEUE:
        if args.only and slug not in args.only:
            continue
        name = f"{slug}_{year}"
        key = (name, f"ADM{level}")
        status = wave_row(slug, year)
        if status["VIIRS"] != "yes" or status["gadm"] not in ("3.6", "4", "4.0", "4.1"):
            raise ValueError(f"Status table excludes {name}")
        if f"ADM{level}" not in status["level"].split("+"):
            raise ValueError(f"Status table does not request ADM{level} for {name}")
        version = status["gadm"].replace(".", "")
        if version == "4":
            version = "40"
        start, end = status["window"].split("..")
        active = ROOT / "data/processed/viirs" / active_name
        out_dir = ROOT / "data/processed/viirs_fire_clusters" / f"{name}_demo"
        out_dir.mkdir(parents=True, exist_ok=True)
        burned = out_dir / "viirs_burned_area" / active_name.replace("vnp14a1", "vnp64a1")
        if slug == "colombia":
            burned = ROOT / "data/processed/gadm4_1_new/viirs_burned_area/colombia_viirs_vnp64a1_gadm41_2018.csv"
        suffix = f"_adm{level}" if slug == "uganda" else ""
        panel = out_dir / f"{name}_viirs_clusters_gadm{version}{suffix}_v1.csv"
        summary = panel.with_name(panel.stem + "_summary.md")
        log_path = out_dir / f"run_adm{level}_v1.log"
        record = {
            "wave": name, "level": f"ADM{level}", "status": "running",
            "burned_area": str(burned.relative_to(ROOT)), "panel": str(panel.relative_to(ROOT)),
            "run_log": str(log_path.relative_to(ROOT)), "updated_at": datetime.now().isoformat(timespec="seconds"), "detail": "",
        }
        records[key] = record
        save_status(list(records.values()))
        print(f"\n=== {name} ADM{level} ===", flush=True)
        try:
            if not active.is_file():
                raise FileNotFoundError(active)
            if panel.is_file() and summary.is_file() and not args.force:
                record["status"] = "complete"
                record["detail"] = "existing panel and summary; skipped"
                if not log_path.is_file():
                    record["run_log"] = ""
                continue
            if not burned.is_file() or (args.force and slug != "colombia"):
                command = [
                    sys.executable, "-m", "scripts.fire_exposure.run_gadm_viirs_burned_area",
                    "--active", str(active), "--iso3", iso3, "--gadm-version", version,
                    "--out-dir", str(out_dir), "--burned-only",
                ]
                if log_command(command, log_path):
                    raise RuntimeError("burned-area renderer exited nonzero")
            command = [
                sys.executable, "-m", "scripts.fire_clusters.build_vacs_viirs_fire_clusters_v1",
                "--wave", name, "--active", str(active), "--burned", str(burned),
                "--out-dir", str(out_dir), "--iso3", iso3, "--level", str(level),
                "--gadm-version", version, "--window-start", start, "--window-end", end,
            ]
            if log_command(command, log_path):
                raise RuntimeError("burn-patch renderer exited nonzero; inspect run log and summary")
            if not panel.is_file() or not summary.is_file():
                raise RuntimeError("expected final panel/summary absent")
            record["status"] = "complete"
            record["detail"] = "rendered and in-script checks passed"
        except Exception as exc:
            record["status"] = "issue"
            record["detail"] = f"{type(exc).__name__}: {exc}"
            print(f"ISSUE {name} ADM{level}: {record['detail']}", flush=True)
        finally:
            record["updated_at"] = datetime.now().isoformat(timespec="seconds")
            records[key] = record
            save_status(list(records.values()))
    print(f"Status table: {RUN_STATUS}", flush=True)


if __name__ == "__main__":
    main()
