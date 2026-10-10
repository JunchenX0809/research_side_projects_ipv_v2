# Shared utility modules

Scripts are the entry points; these modules hold reusable calculations and file helpers. For fire exposure, the product modules build satellite measures, `gee_fire_zonal.py` aggregates them to polygons, and `gadm_boundaries.py` supplies those polygons.

| Module | What it does | Main technical tools |
| --- | --- | --- |
| [`adam_firms_export.py`](../utils/adam_firms_export.py) | Builds monthly FIRMS active-fire counts, including distinct-pixel counts. | Earth Engine (`ee`), pandas, `gee_fire_zonal.py`. |
| [`adam_frp_export.py`](../utils/adam_frp_export.py) | Builds monthly MODIS fire radiative power (FRP), including maximum and summed measures. | Earth Engine (`ee`), pandas, `gee_fire_zonal.py`. |
| [`adam_modis_export.py`](../utils/adam_modis_export.py) | Builds monthly MCD64A1 burned area and 12-month summaries. | Earth Engine (`ee`), pandas, survey-window and zonal helpers. |
| [`adam_viirs_export.py`](../utils/adam_viirs_export.py) | Builds VNP14A1 active-fire counts and FRP, including distinct-pixel counts. | Earth Engine (`ee`), pandas, `gee_fire_zonal.py`. |
| [`adam_viirs_burn_export.py`](../utils/adam_viirs_burn_export.py) | Builds VNP64A1 burned area for exact date windows from estimated burn dates. | Earth Engine (`ee`), pandas, year-segment helpers. |
| [`gee_fire_zonal.py`](../utils/gee_fire_zonal.py) | Sums or maximizes satellite image values within administrative polygons. | Earth Engine region reductions, chunking, pandas output. |
| [`gadm_boundaries.py`](../utils/gadm_boundaries.py) | Loads local GADM polygons and standardizes IDs, names, and areas. | GeoJSON geometry, geodesic area calculation, Python dictionaries. |
| [`vacs_survey_time.py`](../utils/vacs_survey_time.py) | Parses VACS field dates and derives exposure windows and GADM-version guidance. | pandas dates and Python date parsing. |
| [`indonesia_viirs.py`](../utils/indonesia_viirs.py) | Adapts VIIRS exports to Indonesia's COD/BPS ADM2 boundaries and validates combined files. | Earth Engine, pandas, boundary chunking, CSV checks. |
| [`repo_paths.py`](../utils/repo_paths.py) | Finds the repository root for scripts and notebooks. | `pathlib` and Python import paths. |
| [`plot_style.py`](../utils/plot_style.py) | Applies shared chart colors and formatting. | Matplotlib, Seaborn, Cycler. |
| [`__init__.py`](../utils/__init__.py) | Lets Python import `utils` as a package. | Empty marker; no processing. |
