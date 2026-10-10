#!/usr/bin/env python3
"""Per-wave readiness: can we attach exposure to this wave's respondents, and what is missing?

One row per VACS country-wave. Everything is measured, not quoted:

* **linkage level and %** from `vacs_gadm_linkage_v1_master.csv` — respondents whose survey unit
  carries a GADM GID at the level that wave links on, over that wave's respondents in
  `combined_df_clean.csv`.
* **exposure availability** by looking for each product's file on disk at that level and GADM
  version, then reading its window so a "missing" is never confused with a product that cannot
  cover the period.

Product status values:

``yes``           a file exists at the wave's linkage level and GADM version
``n/a (sensor)``  the sensor's record starts after the wave's exposure window opens
``not requested`` AOD only — AOD is a requested subset (`config/aod_runs.csv`), not a fleet product
``MISSING``       should exist and does not

Usage::

    .venv/bin/python -m scripts.respondent_linkage.build_linkage_exposure_status
    .venv/bin/python -m scripts.respondent_linkage.build_linkage_exposure_status --out skills/0920_linkage_demo/wave_status.csv
    .venv/bin/python -m scripts.respondent_linkage.build_linkage_exposure_status --md   # markdown table for a doc
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[2]

OUTCOME = _REPO / "data/cleaned_survey_data/combined_df_clean.csv"
MASTER = _REPO / "data/cleaned_survey_data/vacs_gadm_linkage_v1_master.csv"
AOD_RUNS = _REPO / "config/aod_runs.csv"
PROC = _REPO / "data/processed"

SLUG = {
    "Cambodia": "cambodia", "Colombia": "colombia", "Cote d'Ivoire": "cotedivoire",
    "El Salvador": "elsalvador", "Eswatini": "eswatini", "Haiti": "haiti",
    "Honduras": "honduras", "Kenya": "kenya", "Lesotho": "lesotho", "Malawi": "malawi",
    "Moldova": "moldova", "Mozambique": "mozambique", "Namibia": "namibia",
    "Nigeria": "nigeria", "Rwanda": "rwanda", "Tanzania": "tanzania",
    "Uganda": "uganda", "Zambia": "zambia", "Zimbabwe": "zimbabwe",
}

# product -> (folder, filename infix). Level is encoded by the presence of "_adm1_".
PRODUCTS = {
    "FIRMS": ("firms_unique", "_firms_gadm{v}"),
    "FRP": ("frp", "_modis_frp_sum_gadm{v}"),
    "MODIS_BA": ("modis", "_modis_mcd64_gadm{v}"),
    "VIIRS": ("viirs_unique", "_viirs_vnp14a1_gadm{v}"),
    "AOD": ("aod", "_maiac_aod_gadm{v}"),
}

# Sensor record starts. A window opening before these cannot be covered.
SENSOR_START = {"VIIRS": date(2012, 1, 19)}

# Externally supplied MODIS burned-area files, which do not follow the repo's naming.
EXTERNAL_MODIS = {
    ("eswatini", 2007): "Eswatini_modis_2007_admin1.csv",
    ("cotedivoire", 2019): "Cotedevoire_modis_2018_admin1.csv",
    ("honduras", 2017): "Honduras_modis_2017_admin1.csv",
    ("elsalvador", 2018): "../ElSalvador_2017_v2.csv",
}

# Waves whose crosswalk has a better GADM version available than the master workbook records.
BETTER_VERSION = {
    ("Cambodia", 2013): ("4.1", "cambodia_link_v1/cambodia_2013_admin2_crosswalk_gadm41.csv"),
    ("Colombia", 2018): ("4.1", "colombia_link_v1/colombia_2018_admin2_crosswalk_gadm41.csv"),
}


def candidates(slug: str, version: str, level: int, folder: str, infix: str) -> list[Path]:
    """Every file matching this product, version and level, in the wave's folders."""
    v = version.replace(".", "")
    pat = infix.format(v=v)
    out = []
    for root in (PROC / folder, PROC / "gadm4_1_new" / folder):
        if not root.is_dir():
            continue
        for p in sorted(root.glob("*.csv")):
            n = p.name
            if not n.startswith(slug + "_") or pat not in n:
                continue
            if (level == 1) == ("_adm1_" in n):
                out.append(p)
    return out


def find_product(slug: str, version: str, level: int, folder: str, infix: str,
                 field_start: date | None) -> Path | None:
    """The file whose exposure window belongs to THIS wave.

    Two waves of one country can sit on the same GADM version (Kenya 2010 and 2019 are both
    3.6), so the name alone is ambiguous. The window decides: an exposure window ends at the
    wave's field start, so a file is accepted only if its last month_end lands within ~2
    months of it.
    """
    cands = candidates(slug, version, level, folder, infix)
    if not cands:
        return None
    if field_start is None:
        return cands[0]
    best, best_gap = None, None
    for p in cands:
        w = window_of(p)
        if w is None:
            continue
        gap = abs((w[1] - field_start).days)
        if best_gap is None or gap < best_gap:
            best, best_gap = p, gap
    if best is None:
        return None
    return best if best_gap <= 62 else None


def window_of(path: Path) -> tuple[date, date] | None:
    try:
        df = pd.read_csv(path, usecols=["month_start", "month_end"])
    except Exception:
        return None
    s = pd.to_datetime(df.month_start, errors="coerce", format="mixed")
    e = pd.to_datetime(df.month_end, errors="coerce", format="mixed")
    if s.isna().all() or e.isna().all():
        return None
    return s.min().date(), e.max().date()


def field_starts() -> dict[tuple[str, int], date]:
    """(country, wave year) -> field start, from the repo's own survey-time table."""
    import sys
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    from utils.vacs_survey_time import (
        add_parsed_field_dates, load_survey_time_table, resolve_vacs_survey_time_csv,
    )
    tbl = add_parsed_field_dates(load_survey_time_table(resolve_vacs_survey_time_csv(_REPO)))
    # the table keys waves by its own labels; map them onto (country, outcome-file year)
    LABEL = {
        "Cambodia (2013)": ("Cambodia", 2013), "Colombia (2018)": ("Colombia", 2018),
        "Cotedivoire (2019)": ("Cote d'Ivoire", 2019), "El Salvador (2018)": ("El Salvador", 2018),
        "Eswatini (2007)": ("Eswatini", 2007), "Eswatini (2022)": ("Eswatini", 2022),
        "Haiti (2012)": ("Haiti", 2012), "Honduras (2017)": ("Honduras", 2017),
        "Kenya (2010)": ("Kenya", 2010), "Kenya(2019)": ("Kenya", 2019),
        "Letsotho (2018)": ("Lesotho", 2018), "Malawi (2013)": ("Malawi", 2013),
        "Moldova (2013)": ("Moldova", 2013), "Mozambique (2019)": ("Mozambique", 2019),
        "Namibia (2019)": ("Namibia", 2019), "Nigeria (2014)": ("Nigeria", 2014),
        "Rwanda": ("Rwanda", 2016), "Tanzania (2024)": ("Tanzania", 2024),
        "Zambia (2014)": ("Zambia", 2014), "Zimbabwe (2017)": ("Zimbabwe", 2017),
    }
    out: dict[tuple[str, int], date] = {}
    for _, r in tbl.iterrows():
        key = LABEL.get(str(r.country_wave))
        if key and pd.notna(r.field_start):
            out[key] = pd.Timestamp(r.field_start).date()
    # Uganda is absent from the table; config/gadm_fire_countries.csv records the approved start
    out.setdefault(("Uganda", 2015), date(2015, 9, 1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None)
    ap.add_argument("--md", action="store_true", help="print a markdown table")
    a = ap.parse_args()

    outc = pd.read_csv(OUTCOME, usecols=["country", "year"], low_memory=False)
    wave_n = outc.groupby(["country", "year"]).size()

    m = pd.read_csv(MASTER)
    m["_op"] = np.where(m.gadm_level_used.astype(str) == "ADM2", m.gadm_adm2_gid, m.gadm_adm1_gid)

    aod_req = set()
    if AOD_RUNS.is_file():
        for _, r in pd.read_csv(AOD_RUNS).iterrows():
            cw = str(r.country_wave)
            ctry = cw.split("(")[0].strip()
            yr = int(cw.split("(")[1].rstrip(")")) if "(" in cw else None
            aod_req.add((ctry, yr, int(r.admin_level)))

    fstarts = field_starts()
    rows = []
    for (wno, ctry, yr), d in m.groupby(["wave_no", "country", "year"]):
        slug = SLUG[ctry]
        n_survey = int(wave_n.get((ctry, yr), 0))
        linked = int(d.loc[d._op.notna(), "n_respondents"].sum())
        lvls = sorted({x for x in d.gadm_level_used.dropna().astype(str)})
        level_str = "+".join(lvls) if lvls else "none"
        level = 2 if lvls == ["ADM2"] else 1
        version = str(d.gadm_version.iloc[0])
        note = ""

        pct = np.nan if n_survey == 0 else round(linked / n_survey * 100, 1)
        if (ctry, yr) in BETTER_VERSION:
            bv, xw = BETTER_VERSION[(ctry, yr)]
            better = pd.read_csv(_REPO / "data/cleaned_survey_data" / xw)
            gc = next(c for c in better.columns if c.endswith("gadm_gid") or c == "gadm_gid")
            nc = next(c for c in better.columns if "respond" in c)
            bpct = round(better.loc[better[gc].notna(), nc].sum() / better[nc].sum() * 100, 1)
            note = (f"master workbook is still on {version} ({pct}%); a {bv} crosswalk exists "
                    f"and reaches {bpct}% — switch the workbook before building the demo")
            version, pct, linked = bv, bpct, int(round(bpct / 100 * n_survey))
        if ctry == "Kenya" and yr == 2010:
            pct, note = np.nan, "blocked: survey is 8 provinces, GADM ADM1 is 47 counties"
        if ctry == "Uganda":
            note = "mixed level (ADM1+ADM2) and 28 districts have no GADM polygon"
        if ctry == "Kenya" and yr == 2019:
            note = ("AOD exists but on GADM 4.1 (kenya_maiac_aod_gadm41_adm1_2018.csv, correct "
                    "window) while the crosswalk and every other Kenya 2019 product are 3.6 — "
                    "a version mismatch, not an absent export")

        fs = fstarts.get((ctry, yr))
        ref_window = None
        prod = {}
        for name, (folder, infix) in PRODUCTS.items():
            p = find_product(slug, version, level, folder, infix, fs)
            if p is None and name == "MODIS_BA" and (slug, yr) in EXTERNAL_MODIS:
                cand = PROC / "modis" / EXTERNAL_MODIS[(slug, yr)]
                p = cand.resolve() if cand.resolve().is_file() else None
            if p is not None and ref_window is None:
                ref_window = window_of(p)
            prod[name] = p

        status = {}
        for name, p in prod.items():
            if p is not None:
                status[name] = "yes"
                continue
            if name in SENSOR_START and ref_window and ref_window[0] < SENSOR_START[name]:
                status[name] = "n/a (sensor)"
            elif name == "AOD" and (ctry, yr, level) not in aod_req:
                status[name] = "not requested"
            else:
                status[name] = "MISSING"

        rows.append({
            "wave": int(wno), "country": ctry, "year": int(yr),
            "level": level_str, "gadm": version,
            "units": int(len(d)), "respondents": n_survey,
            "linked": linked, "link_pct": pct,
            **status,
            "field_start": str(fs) if fs else "",
            "window": f"{ref_window[0]}..{ref_window[1]}" if ref_window else "",
            "note": note,
        })

    out = pd.DataFrame(rows).sort_values(["country", "year"]).reset_index(drop=True)
    cols = ["wave", "country", "year", "level", "gadm", "units", "respondents", "linked",
            "link_pct", *PRODUCTS, "field_start", "window", "note"]
    out = out[cols]

    if a.md:
        hdr = ["country", "year", "level", "link_pct", *PRODUCTS, "note"]
        print("| " + " | ".join(hdr) + " |")
        print("|" + "---|" * len(hdr))
        for _, r in out.iterrows():
            v = ["" if pd.isna(r[c]) else str(r[c]) for c in hdr]
            print("| " + " | ".join(v) + " |")
    else:
        print(out.drop(columns=["note", "field_start"]).to_string(index=False))
        print()
        for _, r in out[out.note != ""].iterrows():
            print(f"  {r.country} {r.year}: {r.note}")

    miss = [(r.country, r.year, k) for _, r in out.iterrows()
            for k in PRODUCTS if r[k] == "MISSING"]
    print(f"\n{len(out)} waves | products marked MISSING: {len(miss)}")
    for c, y, k in miss:
        print(f"  MISSING  {c} {y}  {k}")

    if a.out:
        dest = Path(a.out) if Path(a.out).is_absolute() else _REPO / a.out
        dest.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(dest, index=False, lineterminator="\n")
        print(f"\nwrote {dest.relative_to(_REPO)}")


if __name__ == "__main__":
    main()
