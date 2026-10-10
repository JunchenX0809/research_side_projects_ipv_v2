# Fire exposure scripts

These scripts export or combine fire measures before respondent linkage.

| Script | High-level goal | Main technical tools |
| --- | --- | --- |
| [`run_gadm_fire_exports.py`](../scripts/fire_exposure/run_gadm_fire_exports.py) | Run the country manifest's MODIS burned area, FIRMS fire count, FRP, and VIIRS exports on GADM boundaries. | Earth Engine (`ee`), `utils.adam_*` exporters, GADM and survey-window helpers. |
| [`run_unique_active_fire_exports.py`](../scripts/fire_exposure/run_unique_active_fire_exports.py) | Export distinct monthly FIRMS or VIIRS fire pixels for the approved active-fire count. | Earth Engine, `utils.adam_firms_export`, `utils.adam_viirs_export`, fleet manifest helpers. |
| [`run_gadm_viirs_burned_area.py`](../scripts/fire_exposure/run_gadm_viirs_burned_area.py) | Calculate VNP64A1 burned area for GADM units and append it to a matching VIIRS table. | Earth Engine, pandas, `utils.adam_viirs_burn_export`, GADM boundaries. |
| [`run_indonesia_viirs_burned_area.py`](../scripts/fire_exposure/run_indonesia_viirs_burned_area.py) | Export and append Indonesia ADM2 VNP64A1 burned area. | `utils.indonesia_viirs`, `utils.adam_viirs_burn_export`, Earth Engine, pandas. |
| [`run_indonesia_viirs_unique.py`](../scripts/fire_exposure/run_indonesia_viirs_unique.py) | Export Indonesia's distinct monthly VNP14A1 fire-pixel count. | `utils.indonesia_viirs` handles boundary chunks and export checks; Earth Engine and pandas. |
| [`build_viirs_combined.py`](../scripts/fire_exposure/build_viirs_combined.py) | Join VIIRS unique fire count, FRP, and available burned area into country-level tables. | pandas CSV joins and validation. |
| [`build_indonesia_viirs_combined_v2.py`](../scripts/fire_exposure/build_indonesia_viirs_combined_v2.py) | Replace Indonesia v1 pixel-day counts with unique-pixel counts in the v2 combined files. | pandas matches rows and carries FRP and burned area forward. |
| [`__init__.py`](../scripts/fire_exposure/__init__.py) | Let Python import this folder as a package. | Empty marker; no processing. |
