# AOD utility modules

The AOD runner calls these helpers in sequence: **job settings → dates and boundaries → MAIAC images → checked CSV output**. AOD means aerosol optical depth.

| Module | What it does | Main technical tools |
| --- | --- | --- |
| [`manifest.py`](../utils/aod/manifest.py) | Reads each AOD job's country wave, GADM level, boundary source, and output settings. | pandas reads the job CSV; `AodJob` holds one job's settings. |
| [`dates.py`](../utils/aod/dates.py) | Resolves the survey exposure window and its monthly intervals. | pandas dates and `utils.vacs_survey_time`. |
| [`boundaries.py`](../utils/aod/boundaries.py) | Loads administrative polygons and splits them into export-sized groups. | GeoJSON or GeoPandas shapefiles, `utils.gadm_boundaries`, Python chunking. |
| [`maiac.py`](../utils/aod/maiac.py) | Selects and quality-filters MAIAC AOD images, then calculates polygon means. | Earth Engine (`ee`) for image masks and reductions; Shapely for tile selection. |
| [`export.py`](../utils/aod/export.py) | Builds output paths, validates the table, and writes finished CSVs safely. | pandas, schema checks, atomic file writes. |
| [`__init__.py`](../utils/aod/__init__.py) | Lets Python import `utils.aod` as a package. | Empty marker; no processing. |
