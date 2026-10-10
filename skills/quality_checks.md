# Quality-check scripts

These scripts check exposure summaries and compare sensor outputs.

| Script | High-level goal | Main technical tools |
| --- | --- | --- |
| [`audit_avg12_convention.py`](../scripts/quality_checks/audit_avg12_convention.py) | Check whether each `avg12_*` value matches the mean of its 12 monthly values; identify known exceptions. | pandas and NumPy group and compare CSV values. |
| [`modis_viirs_confusion.py`](../scripts/quality_checks/modis_viirs_confusion.py) | Compare MODIS and VIIRS district-month fire presence and intensity. | pandas and NumPy join matching months and calculate agreement tables. |
| [`__init__.py`](../scripts/quality_checks/__init__.py) | Let Python import this folder as a package. | Empty marker; no processing. |
