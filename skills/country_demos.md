# Country demo scripts

These are focused exports for a named country and survey window. FRP means fire radiative power.

| Script | High-level goal | Main technical tools |
| --- | --- | --- |
| [`uganda_frp_sum_run.py`](../scripts/country_demos/uganda_frp_sum_run.py) | Export summed MODIS FRP for Uganda 2015 at ADM1 and ADM2. | Earth Engine (`ee`), `utils.adam_frp_export`, GADM boundaries, survey-window helper. |
| [`uganda_viirs_run.py`](../scripts/country_demos/uganda_viirs_run.py) | Export VIIRS active-fire and FRP exposure for the same Uganda window. | Earth Engine (`ee`), `utils.adam_viirs_export`, GADM boundaries, survey-window helper. |
| [`zimbabwe_frp_sum_demo.py`](../scripts/country_demos/zimbabwe_frp_sum_demo.py) | Export a Zimbabwe 2016 summed-FRP example using the fleet's exposure window. | Earth Engine (`ee`), `utils.adam_frp_export`, `run_gadm_fire_exports.resolve_exposure_window`. |
| [`__init__.py`](../scripts/country_demos/__init__.py) | Let Python import this folder as a package. | Empty marker; no processing. |
