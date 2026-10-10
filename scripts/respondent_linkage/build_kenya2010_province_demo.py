#!/usr/bin/env python3
"""Kenya 2010 v1 trial: aggregate 47 GADM counties to 8 survey provinces."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts.respondent_linkage.build_wave_exposure_demo import RunLog, sha256

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/cleaned_survey_data"
OUTCOME = BASE / "combined_df_clean.csv"
LOOKUP = BASE / "kenya2010_link_v1/kenya_county_to_province_lookup.csv"
REGISTRY = ROOT / "config/wave_exposure_products.csv"
OUT_DIR = BASE / "kenya_2010_demo"

FIELDS = {
    "firms_unique": {"monthly_fire_count": "sum"},
    "frp": {"monthly_sum_frp_mw": "sum", "monthly_max_frp_mw": "max",
            "frp_pixel_days": "sum"},
    "modis_mcd64": {"monthly_burned_area_km2": "sum"},
}


def load_monthly(path: Path, product: str, lookup: pd.DataFrame, log: RunLog):
    df = pd.read_csv(path)
    gid = "adm1_gid" if "adm1_gid" in df else "GID_1"
    for col in ("month_start", "month_end"):
        df[col] = pd.to_datetime(df[col], format="mixed", errors="raise").dt.strftime("%Y-%m-%d")
    if df.duplicated([gid, "month_start"]).any():
        raise ValueError(f"{path.name}: duplicate county-month rows")
    if set(df[gid]) != set(lookup.gadm_gid):
        raise ValueError(f"{path.name}: county GIDs differ from the 47-county lookup")
    if len(df) != 47 * 12 or df.groupby(gid).month_start.nunique().ne(12).any():
        raise ValueError(f"{path.name}: expected 12 months for each of 47 counties")
    metrics = list(FIELDS[product])
    if df[metrics].isna().any().any():
        raise ValueError(f"{path.name}: monthly source metric contains nulls")
    df = df.merge(lookup[["gadm_gid", "survey_admin1"]], left_on=gid, right_on="gadm_gid",
                  how="left", validate="many_to_one")
    agg = df.groupby(["survey_admin1", "month_start", "month_end"], as_index=False).agg(
        FIELDS[product]
    )
    agg = agg.rename(columns={"survey_admin1": "province_code", **{
        col: f"{product}_{col}" for col in metrics
    }})
    log.step(f"{product}: {len(df)} county-month rows -> {len(agg)} province-month rows")
    return agg, {"product": product, "path": str(path.relative_to(ROOT)), "sha256": sha256(path),
                 "county_month_rows": len(df), "province_month_rows": len(agg),
                 "aggregation": FIELDS[product]}


def build(dry_run: bool) -> None:
    log = RunLog()
    log.step("start Kenya 2010 provisional province-level v1 trial")
    lookup = pd.read_csv(LOOKUP)
    if len(lookup) != 47 or lookup.gadm_gid.nunique() != 47 or lookup.survey_admin1.nunique() != 8:
        raise ValueError("county-to-province lookup is not a 47-county / 8-province partition")
    names = lookup.groupby("survey_admin1").province.nunique()
    if names.ne(1).any():
        raise ValueError("province names are not unique by survey code")
    province = lookup.groupby("survey_admin1").agg(
        province_name=("province", "first"), counties_in_province=("gadm_gid", "size")
    ).reset_index().rename(columns={"survey_admin1": "province_code"})

    reg = pd.read_csv(REGISTRY)
    reg = reg[(reg.country == "Kenya") & (reg.year == 2010)]
    if set(reg["product"]) != set(FIELDS):
        raise ValueError("Kenya 2010 trial expects FIRMS, FRP and MODIS only")
    panels, sources = [], []
    for product in FIELDS:
        row = reg[reg["product"] == product].iloc[0]
        pan, source = load_monthly(ROOT / row.path, product, lookup, log)
        panels.append(pan)
        sources.append(source)
    keys = [set(zip(p.province_code, p.month_start, p.month_end)) for p in panels]
    if any(k != keys[0] for k in keys[1:]):
        raise ValueError("products disagree on province-month keys")
    panel = panels[0]
    for extra in panels[1:]:
        panel = panel.merge(extra, on=["province_code", "month_start", "month_end"],
                            validate="one_to_one")
    panel = panel.merge(province, on="province_code", validate="many_to_one")
    panel = panel.sort_values(["province_code", "month_start"]).reset_index(drop=True)
    if len(panel) != 8 * 12:
        raise ValueError("expected 96 province-month panel rows")

    annual = province.copy()
    grouped = panel.groupby("province_code")
    for col in panel.columns:
        if not col.startswith(("firms_unique_", "frp_", "modis_mcd64_")):
            continue
        base = col.removeprefix("firms_unique_").removeprefix("frp_").removeprefix("modis_mcd64_")
        product = col.split("_")[0] if not col.startswith("firms_unique_") else "firms_unique"
        if col.startswith("modis_mcd64_"):
            product = "modis_mcd64"
        base = base.removeprefix("monthly_")
        if base == "max_frp_mw":
            annual[f"{product}_max12_{base}"] = annual.province_code.map(grouped[col].max())
        else:
            annual[f"{product}_mean12_{base}"] = annual.province_code.map(grouped[col].mean())
            annual[f"{product}_sum12_{base}"] = annual.province_code.map(grouped[col].sum())

    raw = pd.read_csv(OUTCOME, dtype=str, na_filter=False, low_memory=False)
    raw = raw.rename(columns={raw.columns[0]: "source_row_id"})
    wave = raw[(raw.country == "Kenya") & (raw.year == "2010")].copy()
    wave["province_code"] = pd.to_numeric(wave.admin1, errors="coerce").astype("Int64")
    out = wave.merge(annual, on="province_code", how="left", validate="many_to_one")
    out["link_status"] = out.province_name.map(lambda x: "linked" if pd.notna(x) else "no_province_lookup")
    out["exposure_geography"] = "survey province (aggregated from GADM 3.6 ADM1 counties)"
    out["aggregation_status"] = "provisional v1"
    out["exposure_window_start"] = panel.month_start.min()
    out["exposure_window_end"] = panel.month_end.max()
    out["exposure_n_months"] = 12
    if len(out) != 2695:
        raise ValueError(f"expected 2695 respondents; got {len(out)}")
    linked = int(out.link_status.eq("linked").sum())
    unlinked = out[out.link_status.ne("linked")]
    log.step(f"join: {linked}/{len(out)} respondents linked to 8 provinces")
    if len(unlinked):
        missing_codes = unlinked.admin1.value_counts(dropna=False).to_dict()
        log.warn(f"{len(unlinked)} respondents have no province exposure; outcome admin1 values: {missing_codes}")
    log.warn("provisional geography: county-month exposure summed or maximized to survey provinces; no direct GADM province polygon exists")

    stem = "kenya_2010"
    paths = {"demo": OUT_DIR / f"{stem}_demo_v1.csv",
             "panel": OUT_DIR / f"{stem}_exposure_panel_v1.csv",
             "json": OUT_DIR / f"{stem}_demo_v1_linkage_log.json",
             "runlog": OUT_DIR / f"{stem}_demo_v1_run_log.md"}
    if dry_run:
        log.step(f"dry run: would write {len(out)} respondent rows and {len(panel)} province-month rows")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(paths["demo"], index=False, lineterminator="\n")
    panel.to_csv(paths["panel"], index=False, lineterminator="\n")
    log.step(f"wrote {paths['demo'].name}: {len(out)} rows")
    log.step(f"wrote {paths['panel'].name}: {len(panel)} rows")
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(),
               "script": "scripts/respondent_linkage/build_kenya2010_province_demo.py",
               "wave": {"country": "Kenya", "year": 2010, "version": "v1",
                        "exposure_geography": "survey province", "source_gadm_version": "3.6",
                        "source_gadm_level": "ADM1 county", "status": "provisional"},
               "sources": {"outcome": {"path": str(OUTCOME.relative_to(ROOT)), "sha256": sha256(OUTCOME)},
                           "county_to_province_lookup": {"path": str(LOOKUP.relative_to(ROOT)),
                                                         "sha256": sha256(LOOKUP)},
                           "products": sources},
               "linkage": {"respondents_total": len(out),
                           "respondents_linked": linked,
                           "respondents_unlinked": len(unlinked),
                           "link_status_counts": {str(k): int(v) for k, v in out.link_status.value_counts().items()},
                           "province_counts": out.groupby(["province_code", "province_name"]).size().to_dict()},
               "exposure": {"months": 12, "panel_rows": len(panel),
                            "window_start": panel.month_start.min(), "window_end_exclusive": panel.month_end.max(),
                            "county_to_province_aggregation": {p: FIELDS[p] for p in FIELDS}},
               "warnings": log.warnings,
               "outputs": {k: str(v.relative_to(ROOT)) for k, v in paths.items()}}
    # JSON keys must be strings, including the province-count table.
    payload["linkage"]["province_counts"] = {
        f"{code} {name}": int(n) for (code, name), n in payload["linkage"]["province_counts"].items()
    }
    paths["json"].write_text(json.dumps(payload, indent=2) + "\n")
    log.step(f"wrote {paths['json'].name}")
    paths["runlog"].write_text(log.to_markdown("Kenya 2010 province exposure demo (v1) — run log"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    build(parser.parse_args().dry_run)
