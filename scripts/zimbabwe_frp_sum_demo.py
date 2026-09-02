"""One-off demo: Zimbabwe summed-FRP (avg12_sum_frp_mw) export, GADM 3.6 ADM2, 2016 window.

Reuses the pipeline's exposure-window resolver so the "12 months before survey date"
criterion is honored exactly (Zimbabwe fieldwork 2017 -> burn window 2016-01-01..2016-12-31).
"""

from __future__ import annotations

import os
from pathlib import Path

import ee

from scripts.run_gadm_fire_exports import resolve_exposure_window
from utils.adam_frp_export import (
    build_adam_frp_sum_export,
    months_table_for_rolling,
    write_adam_frp_csv,
)
from utils.gadm_boundaries import gadm_level_normalized_features
from utils.gee_fire_zonal import ee_initialize_from_environ
from utils.vacs_survey_time import (
    add_parsed_field_dates,
    load_survey_time_table,
    resolve_vacs_survey_time_csv,
)

ROOT = Path(__file__).resolve().parents[1]
ISO3, WAVE, VERSION, LEVEL = "ZWE", "Zimbabwe (2017)", "36", 2
OUT = ROOT / "data" / "processed" / "frp" / "zimbabwe_modis_frp_sum_gadm36_2016.csv"


def main() -> None:
    ee_initialize_from_environ(os.environ.get("EARTHENGINE_PROJECT", "ipv-exposure-research"))

    survey = add_parsed_field_dates(load_survey_time_table(resolve_vacs_survey_time_csv(ROOT)))
    exposure_start, exposure_end = resolve_exposure_window(survey, WAVE)
    print(f"exposure window: {exposure_start} .. {exposure_end}")

    region_features = gadm_level_normalized_features(ISO3, level=LEVEL, version=VERSION, root=ROOT)
    print(f"ADM{LEVEL} units: {len(region_features)}")
    regions = ee.FeatureCollection(region_features[:1])

    months = months_table_for_rolling(exposure_start, exposure_end, history_months=0)
    print(f"months to pull: {len(months)}")

    df = build_adam_frp_sum_export(
        months,
        regions,
        adm0_name="Zimbabwe",
        adm0_pcode="ZW",
        exposure_start=exposure_start,
        exposure_end=exposure_end,
        scale_m=1000.0,
        region_features=region_features,
        unit_level=LEVEL,
    )
    write_adam_frp_csv(df, OUT)
    print(f"wrote {OUT}  rows={len(df)}  units={df['adm2_gid'].nunique()}  months={df['month_start'].nunique()}")


if __name__ == "__main__":
    main()
