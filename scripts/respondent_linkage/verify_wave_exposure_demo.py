#!/usr/bin/env python3
"""Read-only, source-based checks for one respondent-level exposure demo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.respondent_linkage.build_wave_exposure_demo import sha256

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/cleaned_survey_data"
METRICS = {
    "firms_unique": ("monthly_fire_count", "firms_unique_mean12_fire_count"),
    "frp": ("monthly_sum_frp_mw", "frp_mean12_sum_frp_mw"),
    "modis_mcd64": ("monthly_burned_area_km2", "modis_mcd64_mean12_burned_area_km2"),
    "viirs_unique": ("monthly_fire_count", "viirs_unique_mean12_fire_count"),
}


def verify_v2(folder: Path, stem: str) -> None:
    """Check a v2 demo against v1 and every source recorded in its own log."""
    old = pd.read_csv(folder / f"{stem}_demo_v1.csv", dtype=str, na_filter=False)
    new = pd.read_csv(folder / f"{stem}_demo_v2.csv", dtype=str, na_filter=False)
    old_panel = pd.read_csv(folder / f"{stem}_exposure_panel_v1.csv", dtype=str, na_filter=False)
    panel = pd.read_csv(folder / f"{stem}_exposure_panel_v2.csv", dtype=str, na_filter=False)
    old_log = json.loads((folder / f"{stem}_demo_v1_linkage_log.json").read_text())
    log = json.loads((folder / f"{stem}_demo_v2_linkage_log.json").read_text())
    assert log["version"] == "v2" and old_log["version"] == "v1"
    assert len(new) == len(old) and new.source_row_id.is_unique
    assert new.source_row_id.equals(old.source_row_id)
    assert log["linkage"]["link_status_counts"] == old_log["linkage"]["link_status_counts"]
    selections = log["sources"]["per_run_selections"]
    changed_modis = "modis_mcd64" in selections
    added_viirs = "viirs_burn_patch" in selections
    for path in (ROOT / log["sources"]["outcome"]["path"],
                 ROOT / log["sources"]["crosswalk"]["path"]):
        kind = "outcome" if path.name == "combined_df_clean.csv" else "crosswalk"
        assert sha256(path) == log["sources"][kind]["sha256"]

    for prior, current in ((old, new), (old_panel, panel)):
        assert len(prior) == len(current)
        for column in prior:
            if changed_modis and column.startswith("modis_mcd64_"):
                continue
            assert column in current and prior[column].equals(current[column]), (
                f"{stem}: unexpected change in {column}"
            )
    expected_new = set()
    if added_viirs:
        expected_new = {
            "viirs_burn_patch_unit_name", "viirs_burn_patch_unit_area_km2",
            "viirs_burn_patch_mean12_viirs_burned_area_km2",
            "viirs_burn_patch_sum12_viirs_burned_area_km2",
            "viirs_burn_patch_avg12_viirs_burned_area_km2",
            "viirs_burn_patch_mean12_viirs_fire_cluster_count",
            "viirs_burn_patch_sum12_viirs_fire_cluster_count",
            "viirs_burn_patch_avg12_viirs_fire_cluster_count",
        }
    assert set(new.columns) - set(old.columns) == expected_new
    assert set(new.columns).issuperset(old.columns)

    panel_numeric = pd.read_csv(folder / f"{stem}_exposure_panel_v2.csv")
    panel_keys = ["gadm_gid", "month_start", "month_end"]
    assert not panel_numeric.duplicated(panel_keys).any()
    products = log["exposure"]["products"]
    assert len(products) == len({item["product"] for item in products})
    for item in products:
        product = item["product"]
        path = ROOT / item["path"]
        assert sha256(path) == item["sha256"], f"{stem}: source changed: {path}"
        source = pd.read_csv(path)
        gid = item["identity_columns"]["gid"]
        source = source.rename(columns={gid: "gadm_gid"})
        for date_col in ("month_start", "month_end"):
            source[date_col] = pd.to_datetime(source[date_col], format="mixed").dt.strftime("%Y-%m-%d")
        assert not source.duplicated(panel_keys).any()
        matched = panel_numeric[panel_keys].merge(source[panel_keys], on=panel_keys,
                                                  how="outer", indicator=True)
        assert len(matched) == len(panel_numeric) and matched._merge.eq("both").all(), (
            f"{stem}: {product} unit-month keys differ"
        )
        check = panel_numeric.merge(source, on=panel_keys, validate="one_to_one")
        for metric in item["metric_roles"]:
            output = f"{product}_{metric}"
            assert output in check, f"{stem}: missing {output}"
            left = pd.to_numeric(check[output], errors="coerce").to_numpy(float)
            right = pd.to_numeric(check[metric], errors="coerce").to_numpy(float)
            assert np.allclose(left, right, rtol=1e-9, atol=1e-9, equal_nan=True), (
                f"{stem}: {output} differs from its source"
            )
        if product in ("modis_mcd64", "viirs_burn_patch"):
            metrics = (["monthly_burned_area_km2"] if product == "modis_mcd64" else
                       ["monthly_viirs_burned_area_km2", "monthly_viirs_fire_cluster_count"])
            respondents = new[new.gadm_gid != ""].drop_duplicates("gadm_gid").set_index("gadm_gid")
            for metric in metrics:
                base = metric.removeprefix("monthly_")
                grouped = source.groupby("gadm_gid")[metric]
                for op, expected in (("mean12", grouped.mean()), ("sum12", grouped.sum())):
                    column = f"{product}_{op}_{base}"
                    actual = pd.to_numeric(respondents[column]).to_numpy(float)
                    wanted = expected.reindex(respondents.index).to_numpy(float)
                    assert np.allclose(actual, wanted, rtol=1e-8, atol=1e-8), (
                        f"{stem}: respondent {column} differs from source"
                    )
    print(f"PASS v2 {stem}: {len(new)} respondents, {len(panel)} unit-months, "
          f"{len(products)} sources, MODIS corrected={changed_modis}, VIIRS added={added_viirs}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--country", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--version", choices=["v1", "v2"], default="v1")
    ap.add_argument("--crosswalk", help="prepared wave-specific crosswalk, if used")
    ap.add_argument("--survey-key", choices=["admin1", "admin2"])
    args = ap.parse_args()

    slug = args.country.lower().replace(" ", "").replace("'", "")
    stem = f"{slug}_{args.year}"
    folder = BASE / f"{stem}_demo"
    if args.version == "v2":
        verify_v2(folder, stem)
        return
    demo = pd.read_csv(folder / f"{stem}_demo_v1.csv", dtype=str, na_filter=False)
    panel = pd.read_csv(folder / f"{stem}_exposure_panel_v1.csv")

    raw = pd.read_csv(BASE / "combined_df_clean.csv", dtype=str, na_filter=False, low_memory=False)
    raw = raw.rename(columns={raw.columns[0]: "source_row_id"})
    wave = raw[(raw.country == args.country) & (raw.year == str(args.year))]
    assert len(demo) == len(wave) and demo[wave.columns].reset_index(drop=True).equals(
        wave.reset_index(drop=True)
    ), "respondent fields or row count differ from the source"
    assert demo.source_row_id.is_unique and not any(c.startswith("aod_") for c in demo)

    reg = pd.read_csv(ROOT / "config/wave_exposure_products.csv")
    reg = reg[(reg.country == args.country) & (reg.year == args.year)]
    assert len(reg) >= 3 and set(reg["product"]).issubset(METRICS)
    level = int(reg.level.iloc[0])
    if args.crosswalk:
        xw = pd.read_csv(ROOT / args.crosswalk)
        gid_col = "gadm_gid"
    else:
        master = pd.read_csv(BASE / "vacs_gadm_linkage_v1_master.csv")
        xw = master[(master.country == args.country) & (master.year == args.year)]
        gid_col = f"gadm_adm{level}_gid"
    key_cols = ([f"survey_{args.survey_key}"] if args.survey_key else
                (["survey_admin1"] if level == 1 else ["survey_admin1", "survey_admin2"]))
    key_cols = [c for c in key_cols if xw[c].notna().any()]
    assert key_cols, "no survey key in crosswalk"
    for _, row in xw.iterrows():
        selection = pd.Series(True, index=demo.index)
        for col in key_cols:
            selection &= demo[col.removeprefix("survey_")] == str(int(row[col]))
        matched = demo[selection]
        assert len(matched) == int(row.n_respondents), "crosswalk respondent count differs"
        expected_gid = row[gid_col]
        if pd.isna(expected_gid):
            assert matched.gadm_gid.eq("").all()
        else:
            assert matched.gadm_gid.eq(str(expected_gid)).all(), "respondent GID differs"

    panel_keys = set(zip(panel.gadm_gid, panel.month_start, panel.month_end))
    assert len(panel_keys) == len(panel), "duplicate panel unit-month key"
    for _, item in reg.iterrows():
        src = pd.read_csv(ROOT / item.path)
        gid = (f"adm{level}_gid" if f"adm{level}_gid" in src else f"GID_{level}")
        start = pd.to_datetime(src.month_start, format="mixed", errors="raise").dt.strftime("%Y-%m-%d")
        end = pd.to_datetime(src.month_end, format="mixed", errors="raise").dt.strftime("%Y-%m-%d")
        keys = set(zip(src[gid], start, end))
        assert keys == panel_keys, f"{item['product']} panel keys differ from source"
        source_metric, demo_metric = METRICS[item["product"]]
        expected = src.groupby(gid)[source_metric].mean()
        actual = demo[demo.gadm_gid != ""].groupby("gadm_gid")[demo_metric].first().astype(float)
        assert np.allclose(actual, expected.reindex(actual.index), rtol=1e-8, atol=1e-8,
                           equal_nan=True), f"{item['product']} annual mean differs"

    print(f"PASS {args.country} {args.year}: {len(demo)} respondent rows, "
          f"{demo.link_status.value_counts().to_dict()}, {len(panel)} panel rows, "
          f"{len(reg)} products, AOD absent")


if __name__ == "__main__":
    main()
