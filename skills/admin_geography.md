# Admin geography scripts

These scripts prepare survey timing and GADM geography for later exposure and respondent joins.

| Script | High-level goal | Main technical tools |
| --- | --- | --- |
| [`build_vacs_survey_time_gadm_version.py`](../scripts/admin_geography/build_vacs_survey_time_gadm_version.py) | Add the intended GADM version to each VACS survey wave's timing record. | `utils.vacs_survey_time` reads and writes the survey-time table. |
| [`gadm_shp_to_geojson.py`](../scripts/admin_geography/gadm_shp_to_geojson.py) | Convert downloaded GADM shapefiles into GeoJSON used by the export scripts. | GeoPandas reads shapes; `utils.gadm_boundaries` prepares their properties. |
| [`lesotho_district_gadm_match.py`](../scripts/admin_geography/lesotho_district_gadm_match.py) | Match approved Lesotho district names to GADM ADM1 codes. | pandas, Unicode name normalization, `utils.gadm_boundaries`. |
| [`moldova_reg_gadm_match.py`](../scripts/admin_geography/moldova_reg_gadm_match.py) | Match approved Moldova region names to GADM ADM1 codes. | pandas, Unicode name normalization, `utils.gadm_boundaries`. |
| [`__init__.py`](../scripts/admin_geography/__init__.py) | Let Python import this folder as a package. | Empty marker; no processing. |
