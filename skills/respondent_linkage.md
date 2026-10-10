# Respondent linkage scripts

These scripts map VACS survey locations to GADM units, attach exposure, and check the result.

| Script | High-level goal | Main technical tools |
| --- | --- | --- |
| [`build_vacs_gadm_linkage_workbook.py`](../scripts/respondent_linkage/build_vacs_gadm_linkage_workbook.py) | Combine wave crosswalks into the VACS-to-GADM master workbook and CSV. | pandas and openpyxl assemble and validate wave tables. |
| [`build_linkage_exposure_status.py`](../scripts/respondent_linkage/build_linkage_exposure_status.py) | Show each wave's linkage coverage and which exposure files are ready or missing. | pandas/NumPy inspect crosswalks, files, and survey windows. |
| [`build_wave_exposure_demo.py`](../scripts/respondent_linkage/build_wave_exposure_demo.py) | Join registered exposure products to respondents for one VACS wave. | pandas joins outcomes, the master crosswalk, and `config/wave_exposure_products.csv`. |
| [`verify_wave_exposure_demo.py`](../scripts/respondent_linkage/verify_wave_exposure_demo.py) | Read back one linked wave and compare it with source files. | pandas/NumPy checks rows and measures; SHA-256 checks provenance. |
| [`build_kenya2010_province_demo.py`](../scripts/respondent_linkage/build_kenya2010_province_demo.py) | Trial a Kenya 2010 join by aggregating county exposures to survey provinces. | pandas grouping and joins; reuses the wave builder's logging and hashing helpers. |
| [`__init__.py`](../scripts/respondent_linkage/__init__.py) | Let Python import this folder as a package. | Empty marker; no processing. |

**Review note:** `build_vacs_gadm_linkage_workbook.py` writes outputs when imported; even `--help` executes it.
