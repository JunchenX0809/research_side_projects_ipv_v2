"""One-off Uganda (2015) VIIRS VNP14A1 export — GADM 3.6, ADM2 + ADM1.

The field start below is approved study-timing metadata; this script does not read or
require respondent-level records. Exposure window = 12 calendar months before field start =
``2014-09-01 .. 2015-08-31`` (Sep 2014 - Aug 2015, filename year 2015). This matches the
Uganda summed-FRP run (``scripts/uganda_frp_sum_run.py``). VIIRS coverage starts 2012-01-19,
so this window is fully covered.

Run: ``set -a; . ./.env; set +a; ./.venv/bin/python -m scripts.uganda_viirs_run``
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import ee

from utils.adam_viirs_export import (
    build_adam_viirs_export,
    months_table_for_rolling,
    write_adam_viirs_csv,
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
        df = build_adam_viirs_export(
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
        out = ROOT / "data" / "processed" / "viirs" / f"{SLUG}_viirs_vnp14a1_gadm{VERSION}{lvl}_{year}.csv"
        write_adam_viirs_csv(df, out)

        gid = f"adm{level}_gid"
        n_units = df[gid].nunique()
        rows_ok = len(df) == n_units * 12
        print(
            f"  wrote {out.name}  rows={len(df)} (units*12 ok={rows_ok})  "
            f"units={n_units}  months={df['month_start'].nunique()}"
        )


if __name__ == "__main__":
    main()
