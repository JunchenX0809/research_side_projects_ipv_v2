"""One-off Uganda (2015) summed-FRP export — GADM 3.6, ADM2 + ADM1.

The field start below is approved study-timing metadata; this script does not read or
require respondent-level records. The exposure window is the 12 calendar months before
field start (resolved by the same helper the fleet uses):
``2014-09-01 .. 2015-08-31`` -> Sep 2014 through Aug 2015 (filename year 2015).

This deliberately does NOT match the teammate's ``Uganda_2015.csv``, which anchored on
the field END (~2015-12-19) and sliced on the 19th; the correct anchor is the field start.

Run: ``set -a; . ./.env; set +a; ./.venv/bin/python -m scripts.uganda_frp_sum_run``
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import ee

from utils.adam_frp_export import (
    build_adam_frp_sum_export,
    months_table_for_rolling,
    write_adam_frp_csv,
)
from utils.gadm_boundaries import gadm_level_normalized_features
from utils.gee_fire_zonal import ee_initialize_from_environ
from utils.vacs_survey_time import exposure_window_inclusive_before_field_start

ROOT = Path(__file__).resolve().parents[1]
ISO3, VERSION = "UGA", "36"
ADM0_NAME, ADM0_PCODE, SLUG = "Uganda", "UG", "uganda"
FIELD_START = date(2015, 9, 1)  # Approved project-level field-start metadata.


def main() -> None:
    ee_initialize_from_environ(os.environ.get("EARTHENGINE_PROJECT", "ipv-exposure-research"))

    exposure_start, exposure_end = exposure_window_inclusive_before_field_start(FIELD_START)
    year = exposure_end.year
    print(f"field start {FIELD_START} -> exposure window {exposure_start} .. {exposure_end} (year {year})")

    months = months_table_for_rolling(exposure_start, exposure_end, history_months=0)
    print(f"months to pull: {len(months)}")

    for level in (2, 1):
        region_features = gadm_level_normalized_features(ISO3, level=level, version=VERSION, root=ROOT)
        print(f"\nADM{level}: {len(region_features)} units")
        regions = ee.FeatureCollection(region_features[:1])
        df = build_adam_frp_sum_export(
            months,
            regions,
            adm0_name=ADM0_NAME,
            adm0_pcode=ADM0_PCODE,
            exposure_start=exposure_start,
            exposure_end=exposure_end,
            scale_m=1000.0,
            region_features=region_features,
            unit_level=level,
        )
        lvl = "" if level == 2 else f"_adm{level}"
        out = ROOT / "data" / "processed" / "frp" / f"{SLUG}_modis_frp_sum_gadm{VERSION}{lvl}_{year}.csv"
        write_adam_frp_csv(df, out)

        gid = f"adm{level}_gid"
        n_units = df[gid].nunique()
        rows_ok = len(df) == n_units * 12
        avg_ok = (
            df.groupby(gid)
            .apply(
                lambda g: (g["avg12_sum_frp_mw"].nunique() == 1)
                and abs(g["monthly_sum_frp_mw"].mean() - g["avg12_sum_frp_mw"].iloc[0]) < 1e-6,
                include_groups=False,
            )
            .all()
        )
        print(
            f"  wrote {out.name}  rows={len(df)} (units*12 ok={rows_ok})  "
            f"units={n_units}  months={df['month_start'].nunique()}  avg12_ok={bool(avg_ok)}"
        )


if __name__ == "__main__":
    main()
