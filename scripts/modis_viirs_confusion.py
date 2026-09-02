"""MODIS vs VIIRS agreement — confusion matrices + difference summary.

Translates the MODIS/VIIRS correlations into interpretable agreement: at the
district-month level, how often do the two sensors agree that fire was present, and
how often do they agree on intensity tier? Compares comparable metrics:

  active-fire pixel-days : MODIS EE ``FIRMS`` monthly_fire_count vs VIIRS VNP14A1 monthly_fire_count
  max FRP (MW)           : MODIS MOD14A1/MYD14A1 monthly_max_frp_mw vs VIIRS monthly_max_frp_mw
  summed FRP (MW)        : MODIS monthly_sum_frp_mw vs VIIRS monthly_sum_frp_mw  (once VIIRS is refreshed)

For each metric: a presence confusion matrix (value>0) with agreement rate + Cohen's
kappa, an intensity-tier confusion matrix (none/low/med/high on pooled terciles), and
the VIIRS-minus-MODIS difference distribution. Joined on [adm{level}_gid, month_start].

Usage: ./.venv/bin/python -m scripts.modis_viirs_confusion [slug ver year level]
       (defaults: zimbabwe 36 2016 2)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EPS = 1e-9


def cohen_kappa(m: np.ndarray, v: np.ndarray) -> float:
    po = float((m == v).mean())
    p1a, p1b = float(m.mean()), float(v.mean())
    pe = p1a * p1b + (1 - p1a) * (1 - p1b)
    return (po - pe) / (1 - pe) if (1 - pe) > 0 else float("nan")


def presence_matrix(modis: pd.Series, viirs: pd.Series) -> dict:
    m = (modis > EPS).astype(int).to_numpy()
    v = (viirs > EPS).astype(int).to_numpy()
    both = int(((m == 1) & (v == 1)).sum())
    modis_only = int(((m == 1) & (v == 0)).sum())
    viirs_only = int(((m == 0) & (v == 1)).sum())
    neither = int(((m == 0) & (v == 0)).sum())
    n = len(m)
    return dict(
        both=both, modis_only=modis_only, viirs_only=viirs_only, neither=neither, n=n,
        agree=(both + neither) / n, kappa=cohen_kappa(m, v),
    )


def tier_labels(modis: pd.Series, viirs: pd.Series) -> tuple[np.ndarray, np.ndarray, list[float]]:
    pooled = pd.concat([modis, viirs])
    nz = pooled[pooled > EPS]
    e1, e2 = (np.quantile(nz, [1 / 3, 2 / 3]) if len(nz) else (0.0, 0.0))
    edges = [EPS, float(e1), float(e2)]

    def lab(x: pd.Series) -> np.ndarray:
        t = np.zeros(len(x), dtype=int)
        for i, e in enumerate(edges):
            t = np.where(x.to_numpy() > e, i + 1, t)
        return t  # 0 none, 1 low, 2 med, 3 high

    return lab(modis), lab(viirs), edges


def run(slug: str, ver: str, year: str, level: int) -> None:
    lvl = "" if level == 2 else f"_adm{level}"
    gid = f"adm{level}_gid"
    key = [gid, "_ms"]

    firms = pd.read_csv(ROOT / f"data/processed/firms/{slug}_firms_gadm{ver}{lvl}_{year}.csv")
    frp = pd.read_csv(ROOT / f"data/processed/frp/{slug}_modis_frp_sum_gadm{ver}{lvl}_{year}.csv")
    viirs = pd.read_csv(ROOT / f"data/processed/viirs/{slug}_viirs_vnp14a1_gadm{ver}{lvl}_{year}.csv")
    # month_start format can differ across sources (ISO vs M/D/YY) — normalize for the join.
    for d in (firms, frp, viirs):
        d["_ms"] = pd.to_datetime(d["month_start"])

    v_cols = ["monthly_fire_count", "monthly_max_frp_mw"]
    if "monthly_sum_frp_mw" in viirs.columns:
        v_cols.append("monthly_sum_frp_mw")
    df = (
        firms[key + ["monthly_fire_count"]].rename(columns={"monthly_fire_count": "modis_fire_count"})
        .merge(
            viirs[key + v_cols].rename(columns={
                "monthly_fire_count": "viirs_fire_count",
                "monthly_max_frp_mw": "viirs_max_frp",
                "monthly_sum_frp_mw": "viirs_sum_frp",
            }), on=key)
        .merge(
            frp[key + ["monthly_max_frp_mw", "monthly_sum_frp_mw"]].rename(columns={
                "monthly_max_frp_mw": "modis_max_frp",
                "monthly_sum_frp_mw": "modis_sum_frp",
            }), on=key)
    )
    print(f"\n################  {slug} ADM{level}  —  {len(df)} district-months  ################")

    pairs = [
        ("active-fire pixel-days", "modis_fire_count", "viirs_fire_count"),
        ("max FRP (MW)", "modis_max_frp", "viirs_max_frp"),
    ]
    if "viirs_sum_frp" in df.columns:
        pairs.append(("summed FRP (MW)", "modis_sum_frp", "viirs_sum_frp"))

    for label, mcol, vcol in pairs:
        c = presence_matrix(df[mcol], df[vcol])
        print(f"\n=== {label} — PRESENCE (value > 0) ===")
        print("                VIIRS+    VIIRS-")
        print(f"   MODIS+      {c['both']:6d}    {c['modis_only']:6d}")
        print(f"   MODIS-      {c['viirs_only']:6d}    {c['neither']:6d}")
        print(f"   agreement = {c['agree']*100:5.1f}%   Cohen's kappa = {c['kappa']:.3f}")
        print(f"   -> both={c['both']}, MODIS-only={c['modis_only']}, VIIRS-only={c['viirs_only']}, neither={c['neither']}")

        mt, vt, edges = tier_labels(df[mcol], df[vcol])
        mat = pd.crosstab(pd.Series(mt, name="MODIS"), pd.Series(vt, name="VIIRS"))
        mat = mat.reindex(index=[0, 1, 2, 3], columns=[0, 1, 2, 3], fill_value=0)
        diag = int(np.trace(mat.to_numpy()))
        print(f"   intensity tiers (none / low / med / high; edges>0, {edges[1]:.1f}, {edges[2]:.1f}):")
        print("      rows=MODIS  cols=VIIRS  [none low med high]")
        for r in [0, 1, 2, 3]:
            print(f"        {['none','low ','med ','high'][r]}  {list(mat.loc[r])}")
        print(f"   tier agreement (diagonal) = {diag/len(df)*100:.1f}%")

        d = (df[vcol] - df[mcol])
        both_mask = (df[mcol] > EPS) & (df[vcol] > EPS)
        print(f"   diff VIIRS-MODIS: mean={d.mean():.2f}  median={d.median():.2f}  "
              f"(where both>0, n={int(both_mask.sum())}: mean={d[both_mask].mean():.2f})")


if __name__ == "__main__":
    a = sys.argv[1:]
    slug = a[0] if len(a) > 0 else "zimbabwe"
    ver = a[1] if len(a) > 1 else "36"
    year = a[2] if len(a) > 2 else "2016"
    level = int(a[3]) if len(a) > 3 else 2
    run(slug, ver, year, level)
