# AOD exposure scripts

AOD is aerosol optical depth, a satellite measure of particles in the air.

| Script | High-level goal | Main technical tools |
| --- | --- | --- |
| [`run_aod_exports.py`](../scripts/aod_exposure/run_aod_exports.py) | Export monthly MAIAC AOD by administrative area, with checkpoints for resumable jobs. | Earth Engine (`ee`), pandas, `utils.aod` for dates, boundaries, image reduction, and export checks. |
| [`check_nigeria_aod_daily_coverage.py`](../scripts/aod_exposure/check_nigeria_aod_daily_coverage.py) | Check which daily observations contributed to Nigeria's monthly AOD values. | Earth Engine (`ee`), pandas, `utils.aod` for the production image mask, boundaries, and dates. |
| [`__init__.py`](../scripts/aod_exposure/__init__.py) | Let Python import this folder as a package. | Empty marker; no processing. |
