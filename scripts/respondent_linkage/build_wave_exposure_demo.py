#!/usr/bin/env python3
"""Attach GADM exposure to VACS respondents for one country-wave.

The outcome file is the anchor. Every respondent row in `combined_df_clean.csv` for the wave
is carried through byte-for-byte; exposure is joined onto it through the settled crosswalk in
`vacs_gadm_linkage_v1_master.csv`. Nothing is dropped, and a respondent whose unit has no
exposure keeps its row with null exposure and `link_status = "no_exposure"`.

Four files are written per run, into the wave's demo folder:

  {slug}_{year}_demo_{ver}.csv               one row per respondent
  {slug}_{year}_exposure_panel_{ver}.csv     the unit x month exposure actually used
  {slug}_{year}_demo_{ver}_linkage_log.json  counts, coverage, provenance, warnings
  {slug}_{year}_demo_{ver}_run_log.md        timestamped record of the run

Which exposure files a wave uses is declared in `config/wave_exposure_products.csv`, one line
per product. Metric columns are not declared there; they are inferred from the file, because
the fleet's exposure files already follow two stable schemas:

  adm0_name, adm0_pcode, adm1_name, adm1_gid, adm1_area_km2, month_start, month_end, ...
  COUNTRY, GID_0, NAME_1, GID_1, TYPE_1, admin1_area_km2, month_start, month_end, ...

Inference rules, reported in the JSON log so a reader never has to guess:

  avg<N>_<base>   checked against the recomputed mean. If it agrees it is carried as
                  {product}_avg<N>_<base>. If it does NOT, it is carried as
                  {product}_avg<N>_<base>_as_supplied, so a column that does not hold a
                  12-month mean can never be mistaken for one; the exposure value is then
                  {product}_mean<n>_<base>, recomputed here from the monthly column
  ...max...       summarised over the window as {product}_max<n>_<base>
  anything else   summarised as {product}_mean<n>_<base> and {product}_sum<n>_<base>

Exception: MAIAC AOD's supplied avg12_mean_aod is the approved full-window composite.
Carry it as aod_avg12_mean_aod; retain monthly AOD in the panel without making a competing
respondent-level mean or sum.

Window-level exposure is what a respondent gets: the survey records no date per respondent,
so the 12 monthly buckets can only enter as a summary. The monthly detail is preserved in the
panel file rather than pivoted into 48 respondent columns.

Usage::

    .venv/bin/python -m scripts.respondent_linkage.build_wave_exposure_demo --country Eswatini --year 2007
    .venv/bin/python -m scripts.respondent_linkage.build_wave_exposure_demo --country Eswatini --year 2007 --dry-run

Outputs land under `data/`, which is git-ignored — respondent-level data must not be
committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

REGISTRY = "config/wave_exposure_products.csv"
OUTCOME = "data/cleaned_survey_data/combined_df_clean.csv"
MASTER = "data/cleaned_survey_data/vacs_gadm_linkage_v1_master.csv"
SURVEY_TIME = "data/raw/VACS_survey_time.csv"

# Exposure-file identity columns, by GADM level. First match in each list wins.
IDENTITY = {
    1: {
        "gid": ["adm1_gid", "GID_1"],
        "name": ["adm1_name", "NAME_1"],
        "area": ["adm1_area_km2", "admin1_area_km2"],
    },
    2: {
        "gid": ["adm2_gid", "GID_2"],
        "name": ["adm2_name", "NAME_2"],
        "area": ["adm2_area_km2", "admin2_area_km2"],
    },
}

# Never treated as metrics, whatever their dtype.
NON_METRIC = {
    "adm0_name", "adm0_pcode", "COUNTRY", "GID_0", "NAME_0",
    "adm1_name", "adm1_gid", "adm2_name", "adm2_gid",
    "NAME_1", "GID_1", "NAME_2", "GID_2",
    "TYPE_1", "TYPE_2", "ENGTYPE_1", "ENGTYPE_2",
    "VARNAME_1", "VARNAME_2", "CC_1", "CC_2", "HASC_1", "HASC_2",
    "adm1_area_km2", "adm2_area_km2", "admin1_area_km2", "admin2_area_km2",
    "month_start", "month_end",
}

# Month-over-month percent change is a between-month quantity; averaging or summing it over
# the window is meaningless, so it is dropped rather than silently aggregated.
SKIP_METRIC = {"mom_pct_change"}

AVG_RE = re.compile(r"^avg(\d+)_(.+)$")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_product_path(spec: str) -> tuple[str, str]:
    """Parse a per-run product source without changing the shared v1 registry."""
    product, sep, source = spec.partition("=")
    if not sep or not re.fullmatch(r"[a-z][a-z0-9_]*", product) or not source:
        raise ValueError(f"expected product=repository/relative/path.csv, got {spec!r}")
    source_path = (_REPO / source).resolve()
    if Path(source).is_absolute() or not source_path.is_relative_to(_REPO):
        raise ValueError(f"source must be within the repository: {source!r}")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    return product, str(source_path.relative_to(_REPO))


def check_v2_panels(panels: list[pd.DataFrame], provs: list[dict]) -> None:
    """Require identical, complete unit-month keys before building a v2 outer panel."""
    baseline: set[tuple[str, str, str]] | None = None
    for panel, prov in zip(panels, provs):
        if prov["months"] != 12:
            raise ValueError(f"{prov['product']}: expected 12 exposure months")
        windows = panel[["month_start", "month_end"]].drop_duplicates().sort_values("month_start")
        if len(windows) != 12:
            raise ValueError(f"{prov['product']}: expected 12 distinct date pairs")
        starts = pd.to_datetime(windows["month_start"])
        ends = pd.to_datetime(windows["month_end"])
        if not (ends > starts).all() or not (ends.iloc[:-1].to_numpy() == starts.iloc[1:].to_numpy()).all():
            raise ValueError(f"{prov['product']}: exposure windows are not contiguous")
        keys = set(zip(panel.gadm_gid.astype(str), panel.month_start, panel.month_end))
        if len(keys) != len(panel):
            raise ValueError(f"{prov['product']}: duplicate unit-month keys")
        if baseline is None:
            baseline = keys
        elif keys != baseline:
            raise ValueError(
                f"{prov['product']}: unit-month keys differ from the first product "
                f"({len(keys - baseline)} extra, {len(baseline - keys)} missing)"
            )


def check_viirs_burn_patch(panel: pd.DataFrame, prov: dict) -> None:
    """Do not turn missing VNP64A1 data into a complete VIIRS exposure."""
    for col in (
        "viirs_burn_patch_monthly_viirs_burned_area_km2",
        "viirs_burn_patch_monthly_viirs_fire_cluster_count",
    ):
        values = pd.to_numeric(panel[col], errors="raise")
        if values.isna().any() or not np.isfinite(values).all() or (values < 0).any():
            raise ValueError(f"{prov['path']}: {col} has missing, nonfinite, or negative values")
        if col.endswith("cluster_count") and not np.allclose(values, np.round(values)):
            raise ValueError(f"{prov['path']}: cluster counts are not integers")
    for check in prov["supplied_vs_recomputed_checks"]:
        if check["equals_recomputed_mean"] is not True:
            raise ValueError(f"{prov['path']}: {check['supplied']} is not its 12-month mean")


class RunLog:
    """Timestamped, append-only record of the run. Printed live and written to disk."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []
        self.warnings: list[str] = []

    def step(self, msg: str) -> None:
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        self.lines.append((ts, msg))
        print(f"[{ts}] {msg}", flush=True)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.step(f"WARNING  {msg}")

    def to_markdown(self, title: str) -> str:
        out = [f"# {title}", "", "| time | step |", "| --- | --- |"]
        out += [f"| `{ts}` | {m.replace('|', chr(92) + '|')} |" for ts, m in self.lines]
        if self.warnings:
            out += ["", "## Warnings", ""]
            out += [f"- {w}" for w in self.warnings]
        return "\n".join(out) + "\n"


def pick(df: pd.DataFrame, candidates: list[str], what: str, path: Path) -> str:
    for c in candidates:
        if c in df.columns:
            return c
    raise KeyError(f"{path.name}: no {what} column among {candidates}; has {list(df.columns)}")


def classify(df: pd.DataFrame) -> dict[str, str]:
    """Map each metric column to a role: 'supplied', 'max' or 'mean_sum'."""
    roles: dict[str, str] = {}
    for c in df.columns:
        if c in NON_METRIC or c in SKIP_METRIC:
            continue
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        if AVG_RE.match(c):
            roles[c] = "supplied"
        elif "max" in c.lower():
            roles[c] = "max"
        else:
            roles[c] = "mean_sum"
    return roles


def summarise_product(
    path: Path, product: str, level: int, log: RunLog
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return (per-unit window summary, monthly panel slice, provenance dict)."""
    df = pd.read_csv(path)
    # Source CSVs use both ISO dates and M/D/YY. Normalize labels before comparing
    # windows or merging the monthly panels; do not change the source files.
    for col in ("month_start", "month_end"):
        df[col] = pd.to_datetime(df[col], format="mixed", errors="raise").dt.strftime("%Y-%m-%d")
    gid = pick(df, IDENTITY[level]["gid"], "gid", path)
    name = pick(df, IDENTITY[level]["name"], "name", path)
    area = pick(df, IDENTITY[level]["area"], "area", path)

    if df.duplicated([gid, "month_start"]).any():
        raise ValueError(f"{path.name}: duplicate ({gid}, month_start) rows")

    months = sorted(df["month_start"].unique())
    n = len(months)
    per_unit_months = df.groupby(gid)["month_start"].nunique()
    if per_unit_months.nunique() != 1 or int(per_unit_months.iloc[0]) != n:
        raise ValueError(f"{path.name}: units do not all carry the same {n} months")

    roles = classify(df)
    if (product == "aod" and roles.get("avg12_mean_aod") == "supplied"
            and roles.get("monthly_mean_aod") == "mean_sum"):
        # The approved MAIAC annual value is a separate full-window composite, not the
        # arithmetic mean of the twelve monthly polygon means. Keep monthly AOD in the
        # panel and carry the supplied annual value onto respondents unchanged in meaning.
        roles["monthly_mean_aod"] = "monthly_only"
        log.step(f"{path.name}: carrying supplied full-window `avg12_mean_aod` as AOD exposure")
    out = pd.DataFrame({gid: sorted(df[gid].unique())}).set_index(gid)
    out[f"{product}_unit_name"] = df.groupby(gid)[name].first()
    out[f"{product}_unit_area_km2"] = df.groupby(gid)[area].first()

    checks: list[dict] = []
    carried: list[str] = []
    recomputed_means: dict[str, str] = {}   # base -> output column name

    for col, role in roles.items():
        if role in ("mean_sum", "max"):
            base = col[len("monthly_"):] if col.startswith("monthly_") else col
            if role == "max":
                nm = f"{product}_max{n}_{base}"
                out[nm] = df.groupby(gid)[col].max()
                carried.append(nm)
            else:
                nm_mean = f"{product}_mean{n}_{base}"
                nm_sum = f"{product}_sum{n}_{base}"
                out[nm_mean] = df.groupby(gid)[col].mean()
                out[nm_sum] = df.groupby(gid)[col].sum()
                carried += [nm_mean, nm_sum]
                recomputed_means[base] = nm_mean

    for col, role in roles.items():
        if role != "supplied":
            continue
        grouped = df.groupby(gid)[col]
        bounds = grouped.agg(["min", "max"])
        mixed_missing = grouped.apply(lambda values: values.isna().any() and values.notna().any())
        not_constant = (~np.isclose(bounds["min"], bounds["max"], rtol=1e-7,
                                    atol=1e-9, equal_nan=True) | mixed_missing)
        if not_constant.any():
            log.warn(
                f"{path.name}: `{col}` is not constant within a unit; taking the first value"
            )
        supplied = df.groupby(gid)[col].first().reindex(out.index)

        m = AVG_RE.match(col)
        base = m.group(2)
        check = {"supplied": col, "declared_window_months": int(m.group(1)),
                 "file_window_months": n, "recomputed": None,
                 "equals_recomputed_mean": None, "max_abs_rel_diff": None,
                 "written_as": None}
        equal = True
        if base in recomputed_means:
            mean_col = recomputed_means[base]
            check["recomputed"] = mean_col
            a, b = supplied.to_numpy(float), out[mean_col].to_numpy(float)
            with np.errstate(divide="ignore", invalid="ignore"):
                rel = np.abs(a - b) / np.where(np.abs(b) > 0, np.abs(b), np.nan)
            # Supplied summaries are rounded in some exports; ignore differences
            # limited to their final printed digits while still catching totals.
            equal = bool(np.allclose(a, b, rtol=1e-7, atol=1e-9))
            check["equals_recomputed_mean"] = equal
            check["max_abs_rel_diff"] = None if np.all(np.isnan(rel)) else float(np.nanmax(rel))

        # A supplied avg column that fails the check does not hold what its name promises, so
        # it must not keep a bare `avg<N>` name in the deliverable. It is retained under an
        # `_as_supplied` suffix for traceability, and the recomputed mean — which this build
        # derives from the file's own monthly column — is left as the only column carrying
        # the project's avg12 meaning.
        nm = f"{product}_{col}" if equal else f"{product}_{col}_as_supplied"
        out[nm] = supplied
        carried.append(nm)
        check["written_as"] = nm
        if not equal:
            log.warn(
                f"{path.name}: `{col}` does not equal the mean of the file's {n} monthly "
                f"`{base}` values (max relative difference {check['max_abs_rel_diff']:.4g}). "
                f"Kept for traceability as `{nm}`; the exposure value to use is "
                f"`{recomputed_means[base]}`, recomputed here from the file's monthly column."
            )
        checks.append(check)

    panel = df.rename(columns={gid: "gadm_gid", name: "unit_name", area: "unit_area_km2"})
    keep = ["gadm_gid", "unit_name", "unit_area_km2", "month_start", "month_end"]
    metric_cols = [c for c in roles]
    panel = panel[keep + metric_cols].rename(
        columns={c: f"{product}_{c}" for c in metric_cols}
    )

    prov = {
        "product": product,
        "path": str(path.relative_to(_REPO)) if path.is_relative_to(_REPO) else str(path),
        "sha256": sha256(path),
        "rows": int(len(df)),
        "units": int(df[gid].nunique()),
        "months": n,
        "window_start": str(min(months)),
        "window_end": str(df["month_end"].max()),
        "identity_columns": {"gid": gid, "name": name, "area": area},
        "metric_roles": roles,
        "columns_written": carried,
        "supplied_vs_recomputed_checks": checks,
    }
    log.step(
        f"{product}: {len(df)} rows, {prov['units']} units x {n} months, "
        f"{prov['window_start']} -> {prov['window_end']}, {len(carried)} columns"
    )
    return out.reset_index().rename(columns={gid: "gadm_gid"}), panel, prov


def resolve_window(country_wave: str, log: RunLog) -> dict:
    """The repo's own exposure-window rule, for comparison against what the files contain."""
    try:
        from utils.vacs_survey_time import (
            add_parsed_field_dates,
            exposure_window_inclusive_before_field_start,
            field_dates_as_python_dates,
            load_survey_time_table,
            resolve_vacs_survey_time_csv,
        )

        tbl = add_parsed_field_dates(load_survey_time_table(resolve_vacs_survey_time_csv(_REPO)))
        row = tbl[tbl["country_wave"] == country_wave]
        if row.empty:
            log.warn(f"no row for `{country_wave}` in {SURVEY_TIME}; window rule not checked")
            return {}
        fs, fe = field_dates_as_python_dates(row.iloc[0])
        es, ee = exposure_window_inclusive_before_field_start(fs)
        return {
            "field_start": str(fs), "field_end": str(fe),
            "rule_exposure_start": str(es), "rule_exposure_end": str(ee),
            "rule": "12 months ending the day before field start",
        }
    except Exception as exc:  # the check is diagnostic; never fail the build on it
        log.warn(f"could not resolve the exposure window rule: {exc}")
        return {}


def build(country: str, year: int, version: str, out_dir: Path, dry_run: bool,
          survey_key: str | None = None, crosswalk_path: str | None = None,
          source_overrides: tuple[str, ...] = (),
          extra_products: tuple[str, ...] = ()) -> None:
    log = RunLog()
    slug = country.lower().replace(" ", "").replace("'", "")
    log.step(f"start  country={country} year={year} version={version}")

    # ---- registry ------------------------------------------------------------------
    reg = pd.read_csv(_REPO / REGISTRY)
    reg = reg[(reg.country == country) & (reg.year == year)].copy()
    if reg.empty:
        raise SystemExit(
            f"no products registered for {country} {year} in {REGISTRY}. "
            "Add one line per exposure file before running."
        )
    levels = sorted(set(reg.level.astype(int)))
    versions = sorted(set(reg.gadm_version.astype(str)))
    if len(levels) != 1 or len(versions) != 1:
        raise SystemExit(f"registry mixes levels {levels} or GADM versions {versions}")
    level, gadm_version = levels[0], versions[0]
    country_wave = str(reg.country_wave.iloc[0])
    log.step(f"registry: {len(reg)} product(s), GADM {gadm_version} ADM{level}, wave `{country_wave}`")
    if (source_overrides or extra_products) and version != "v2":
        raise ValueError("source overrides and added products require --version v2")
    selected_sources: dict[str, dict[str, str]] = {}
    for spec in source_overrides:
        product, path = parse_product_path(spec)
        if product in selected_sources:
            raise ValueError(f"product selected more than once: {product}")
        mask = reg["product"] == product
        if int(mask.sum()) != 1:
            raise ValueError(f"override requires one registered {product} source")
        old_path = str(reg.loc[mask, "path"].iloc[0])
        reg.loc[mask, "path"] = path
        selected_sources[product] = {"kind": "override", "path": path, "replaces": old_path}
        log.step(f"override {product}: {old_path} -> {path}")
    for spec in extra_products:
        product, path = parse_product_path(spec)
        if product in selected_sources or product in set(reg["product"]):
            raise ValueError(f"product already selected or registered: {product}")
        reg = pd.concat([reg, pd.DataFrame([{
            "country": country, "year": year, "country_wave": country_wave,
            "product": product, "gadm_version": gadm_version, "level": level,
            "path": path, "source": "v2 added local exposure panel",
            "notes": "per-run source; v1 registry unchanged",
        }])], ignore_index=True)
        selected_sources[product] = {"kind": "added", "path": path}
        log.step(f"add {product}: {path}")

    # ---- crosswalk -----------------------------------------------------------------
    master_p = _REPO / (crosswalk_path or MASTER)
    master = pd.read_csv(master_p)
    xw = master[(master.country == country) & (master.year == year)].copy()
    if xw.empty:
        raise SystemExit(f"no rows for {country} {year} in {master_p}")
    if crosswalk_path:
        # The prepared 4.1 wave crosswalks use a compact schema. Adapt it in
        # memory; the shared master workbook remains unchanged.
        if "admin_level" in xw and "gadm_level_used" not in xw:
            xw["gadm_level_used"] = xw["admin_level"]
        if "gadm_gid" in xw:
            xw[f"gadm_adm{level}_gid"] = xw["gadm_gid"]
        if "survey_name" not in xw and "survey_municipio" in xw:
            xw["survey_name"] = xw["survey_municipio"]
        log.step(f"using wave-specific crosswalk {master_p.relative_to(_REPO)}")
    lv = sorted(set(xw.gadm_level_used.dropna().astype(str)))
    if lv != [f"ADM{level}"]:
        raise SystemExit(
            f"crosswalk is at {lv} but the registry declares ADM{level}; resolve before joining"
        )
    if str(xw.gadm_version.iloc[0]) not in (gadm_version, gadm_version.rstrip("0").rstrip(".")):
        log.warn(
            f"crosswalk says GADM {xw.gadm_version.iloc[0]}, registry says {gadm_version}"
        )
    gid_col = "gadm_adm1_gid" if level == 1 else "gadm_adm2_gid"
    key_cols = ([f"survey_{survey_key}"] if survey_key else
                (["survey_admin1"] if level == 1 else ["survey_admin1", "survey_admin2"]))
    key_cols = [c for c in key_cols if xw[c].notna().any()]
    if not key_cols:
        raise SystemExit(f"crosswalk has no values for requested survey key {survey_key}")
    xw["_key"] = xw[key_cols].astype("Int64").astype(str).agg("|".join, axis=1)
    if xw["_key"].duplicated().any():
        raise SystemExit(f"crosswalk has duplicate survey keys on {key_cols}")
    log.step(
        f"crosswalk: {len(xw)} unit(s) keyed on {key_cols}, "
        f"{xw[gid_col].notna().sum()} with a GADM GID"
    )

    # ---- outcome -------------------------------------------------------------------
    # Read as text so every respondent value round-trips exactly as the PI's file has it.
    outcome_p = _REPO / OUTCOME
    raw = pd.read_csv(outcome_p, dtype=str, na_filter=False, low_memory=False)
    id_col = raw.columns[0]
    raw = raw.rename(columns={id_col: "source_row_id"})
    wave = raw[(raw.country == country) & (raw.year == str(year))].copy()
    if wave.empty:
        raise SystemExit(f"no rows for {country} {year} in {OUTCOME}")
    n_resp = len(wave)
    log.step(f"outcome: {n_resp} respondents of {len(raw)} rows in combined_df_clean.csv")

    survey_keys = [c.removeprefix("survey_") for c in key_cols]
    if not all(k in wave.columns for k in survey_keys):
        raise SystemExit(f"outcome lacks requested survey key(s) {survey_keys}")
    for k in survey_keys:
        blank = int((wave[k].str.strip().isin(["", "NA", "NaN"])).sum())
        if blank:
            log.warn(f"{blank} respondents have a blank `{k}` and cannot be linked")
    parsed = wave[survey_keys].apply(lambda s: pd.to_numeric(s, errors="coerce").astype("Int64"))
    wave["_key"] = parsed.astype(str).agg("|".join, axis=1)

    # ---- exposure ------------------------------------------------------------------
    summaries, panels, provs = [], [], []
    for _, r in reg.iterrows():
        p = _REPO / str(r.path)
        if not p.is_file():
            raise SystemExit(f"registered exposure file is missing: {p}")
        s, pan, prov = summarise_product(p, str(r["product"]), level, log)
        prov["source"] = str(r.get("source", ""))
        prov["registry_notes"] = str(r.get("notes", ""))
        summaries.append(s)
        panels.append(pan)
        provs.append(prov)

    if version == "v2":
        check_v2_panels(panels, provs)
        for pan, prov in zip(panels, provs):
            if prov["product"] == "viirs_burn_patch":
                check_viirs_burn_patch(pan, prov)
        log.step("v2 source keys: all products match the same 12 contiguous unit-months")

    windows = {(p["window_start"], p["window_end"]) for p in provs}
    if len(windows) > 1:
        log.warn(f"products disagree on the exposure window: {sorted(windows)}")
    w_start, w_end = sorted(windows)[0]
    n_months = provs[0]["months"]

    rule = resolve_window(country_wave, log)
    if rule:
        log.step(
            f"window rule: field start {rule['field_start']} -> "
            f"{rule['rule_exposure_start']}..{rule['rule_exposure_end']}; "
            f"files carry {w_start}..{w_end}"
        )
        # CSV month_end is the exclusive boundary. The rule's end is inclusive,
        # so its corresponding exclusive date is the survey field start.
        if rule.get("rule_exposure_start") != w_start or rule.get("field_start") != w_end:
            log.warn(
                "the exposure files' labeled window does not match the expected exclusive "
                f"boundaries ({w_start}..{w_end} against "
                f"{rule['rule_exposure_start']}..{rule['field_start']})"
            )

    exposure = summaries[0]
    for s in summaries[1:]:
        exposure = exposure.merge(s, on="gadm_gid", how="outer", validate="one_to_one")

    panel = panels[0]
    for pan in panels[1:]:
        panel = panel.merge(
            pan.drop(columns=["unit_name", "unit_area_km2"]),
            on=["gadm_gid", "month_start", "month_end"], how="outer", validate="one_to_one",
        )
    panel = panel.sort_values(["gadm_gid", "month_start"]).reset_index(drop=True)

    # ---- join ----------------------------------------------------------------------
    link = xw[["_key", "survey_name", gid_col, "gadm_name"]].rename(
        columns={gid_col: "gadm_gid", "survey_name": "survey_unit_name",
                 "gadm_name": "gadm_unit_name"}
    )
    out = wave.merge(link, on="_key", how="left", validate="many_to_one")
    out = out.merge(exposure, on="gadm_gid", how="left", validate="many_to_one")

    has_gid = out["gadm_gid"].notna()
    exp_cols = [c for c in exposure.columns if c != "gadm_gid"]
    has_exp = has_gid & out[exp_cols].notna().any(axis=1)
    out["link_status"] = np.where(~out["_key"].isin(link["_key"]), "no_crosswalk_entry",
                          np.where(~has_gid, "no_gadm_gid",
                          np.where(~has_exp, "no_exposure", "linked")))

    out["gadm_version"] = gadm_version
    out["gadm_level"] = f"ADM{level}"
    out["exposure_window_start"] = w_start
    out["exposure_window_end"] = w_end
    out["exposure_n_months"] = n_months
    out = out.drop(columns="_key")

    front = ["source_row_id"]
    meta = ["survey_unit_name", "gadm_version", "gadm_level", "gadm_gid", "gadm_unit_name",
            "link_status", "exposure_window_start", "exposure_window_end", "exposure_n_months"]
    resp_cols = [c for c in wave.columns if c not in ("_key", "source_row_id")]
    out = out[front + resp_cols + [c for c in meta if c in out.columns]
              + [c for c in exposure.columns if c != "gadm_gid"]]
    if out.columns.duplicated().any() or panel.columns.duplicated().any():
        raise ValueError("product names produced duplicate output columns")

    status = out.link_status.value_counts().to_dict()
    n_linked = int(status.get("linked", 0))
    log.step(
        f"join: {n_linked}/{n_resp} respondents linked "
        f"({n_linked / n_resp * 100:.1f}%), status {status}"
    )

    per_unit = []
    for _, r in xw.sort_values(key_cols).iterrows():
        k = r["_key"]
        n_out = int((wave["_key"] == k).sum())
        per_unit.append({
            "survey_key": k,
            "survey_name": r["survey_name"],
            "gadm_gid": None if pd.isna(r[gid_col]) else str(r[gid_col]),
            "gadm_name": None if pd.isna(r["gadm_name"]) else str(r["gadm_name"]),
            "n_respondents_outcome": n_out,
            "n_respondents_crosswalk": None if pd.isna(r["n_respondents"]) else int(r["n_respondents"]),
            "counts_agree": (not pd.isna(r["n_respondents"])) and n_out == int(r["n_respondents"]),
            "exposure_found": bool(
                pd.notna(r[gid_col]) and (exposure["gadm_gid"] == r[gid_col]).any()
            ),
        })
    for u in per_unit:
        if not u["counts_agree"]:
            log.warn(
                f"unit {u['survey_name']}: outcome has {u['n_respondents_outcome']} respondents, "
                f"crosswalk records {u['n_respondents_crosswalk']}"
            )

    orphan = sorted(set(exposure["gadm_gid"]) - set(xw[gid_col].dropna()))
    if orphan:
        log.step(f"exposure units with no respondents (kept in the panel only): {orphan}")

    # ---- write ---------------------------------------------------------------------
    stem = f"{slug}_{year}"
    paths = {
        "demo": out_dir / f"{stem}_demo_{version}.csv",
        "panel": out_dir / f"{stem}_exposure_panel_{version}.csv",
        "json": out_dir / f"{stem}_demo_{version}_linkage_log.json",
        "runlog": out_dir / f"{stem}_demo_{version}_run_log.md",
    }
    if dry_run:
        log.step(f"dry run: would write {len(out)} respondent rows, {len(panel)} panel rows")
        print(log.to_markdown(f"{country} {year} exposure demo ({version}) — DRY RUN"))
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    existing = [str(p) for p in paths.values() if p.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite existing demo files: {existing}")
    log.step(f"prepared {paths['demo'].name}  {len(out)} rows x {len(out.columns)} cols")
    log.step(f"prepared {paths['panel'].name}  {len(panel)} rows x {len(panel.columns)} cols")

    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "scripts/respondent_linkage/build_wave_exposure_demo.py",
        "version": version,
        "wave": {"country": country, "year": year, "country_wave": country_wave,
                 "gadm_version": gadm_version, "gadm_level": f"ADM{level}"},
        "sources": {
            "outcome": {"path": OUTCOME, "sha256": sha256(outcome_p),
                        "rows_total": int(len(raw)), "rows_this_wave": n_resp},
            "crosswalk": {"path": str(master_p.relative_to(_REPO)), "sha256": sha256(master_p),
                          "rows_this_wave": int(len(xw))},
            "registry": {"path": REGISTRY, "products": int(len(reg))},
            "per_run_selections": selected_sources,
        },
        "linkage": {
            "join_key": survey_keys,
            "survey_units_in_outcome": int(wave["_key"].nunique()),
            "survey_units_in_crosswalk": int(len(xw)),
            "units_with_gadm_gid": int(xw[gid_col].notna().sum()),
            "units_matched_to_exposure": int(sum(u["exposure_found"] for u in per_unit)),
            "unit_match_pct": round(
                sum(u["exposure_found"] for u in per_unit) / len(per_unit) * 100, 4),
            "respondents_total": n_resp,
            "respondents_linked": n_linked,
            "respondents_unlinked": n_resp - n_linked,
            "respondent_link_pct": round(n_linked / n_resp * 100, 4),
            "link_status_counts": {k: int(v) for k, v in status.items()},
            "per_unit": per_unit,
            "exposure_units_without_respondents": orphan,
        },
        "exposure": {
            "window_start": w_start, "window_end": w_end, "n_months": n_months,
            "window_rule_check": rule,
            "products": provs,
        },
        "outputs": {k: str(v.relative_to(_REPO)) for k, v in paths.items()},
        "warnings": log.warnings,
    }
    # Stage every output, then create each destination only if absent. Roll back
    # newly created links on failure; no existing v1 or v2 file can be replaced.
    with tempfile.TemporaryDirectory(prefix=f".{stem}_{version}_", dir=out_dir) as staging:
        staged = {kind: Path(staging) / path.name for kind, path in paths.items()}
        out.to_csv(staged["demo"], index=False, lineterminator="\n")
        panel.to_csv(staged["panel"], index=False, lineterminator="\n")
        staged["json"].write_text(json.dumps(payload, indent=2) + "\n")
        staged["runlog"].write_text(
            log.to_markdown(f"{country} {year} exposure demo ({version}) — run log")
        )
        created: list[Path] = []
        try:
            for kind, path in paths.items():
                os.link(staged[kind], path)
                created.append(path)
        except Exception:
            for path in created:
                path.unlink()
            raise
    log.step(f"wrote four {version} files in {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--country", required=True)
    ap.add_argument("--year", required=True, type=int)
    ap.add_argument("--version", default="v1")
    ap.add_argument("--out-dir", default=None,
                    help="default: data/cleaned_survey_data/{slug}_{year}_demo")
    ap.add_argument("--survey-key", choices=["admin1", "admin2"], default=None,
                    help="override the default survey key, e.g. Malawi's admin2 districts map to GADM ADM1")
    ap.add_argument("--crosswalk", default=None,
                    help="wave-specific crosswalk CSV, relative to the repository root")
    ap.add_argument("--source-override", action="append", default=[], metavar="PRODUCT=PATH",
                    help="v2 only: replace one registered product source for this run")
    ap.add_argument("--extra-product", action="append", default=[], metavar="PRODUCT=PATH",
                    help="v2 only: add one product source for this run")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    slug = a.country.lower().replace(" ", "").replace("'", "")
    out_dir = Path(a.out_dir) if a.out_dir else (
        _REPO / "data" / "cleaned_survey_data" / f"{slug}_{a.year}_demo")
    build(a.country, a.year, a.version, out_dir, a.dry_run, a.survey_key, a.crosswalk,
          tuple(a.source_override), tuple(a.extra_product))


if __name__ == "__main__":
    main()
