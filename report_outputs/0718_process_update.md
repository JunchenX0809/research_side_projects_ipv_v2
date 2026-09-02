# 0718 Process Update — MAIAC AOD pipeline and country outputs

## Outcome

Built and completed a standalone MAIAC aerosol optical depth (AOD) pipeline for the
countries and administrative levels the team could not render in Earth Engine. All 15
requested CSVs were generated under `data/processed/aod/` and passed a final fleet-wide
validation: **38,244 rows, the expected boundary count for every file, 12 months per
boundary, and no duplicate boundary-month rows**.

This pipeline is separate from MODIS burned area, FIRMS, FRP, and VIIRS.

## Method

- Product: MCD19A2 Version 6.1 MAIAC daily AOD at 0.55 μm, 1 km.
- Kept best-quality AOD retrievals, calculated monthly polygon means, and retained the
  teammate's full-window definition for `avg12_mean_aod`.
- Matched each survey wave to its intended GADM version, including Kenya 2010 × GADM
  3.6 and Kenya 2019 × GADM 4.1.
- Improved runtime by filtering to intersecting MODIS tiles, processing month-by-month
  and boundary-chunk-by-boundary-chunk, and checkpointing every completed chunk.

## Completed files

| Wave | GADM | ADM1 rows | ADM2 rows |
|---|---:|---:|---:|
| Colombia 2018 | 3.6 | 384 | 12,780 |
| Kenya 2010 | 3.6 | 564 | 3,612 |
| Kenya 2019 | 4.1 | 564 | 3,600 |
| Mozambique 2019 | 4.0 | 132 | 1,548 |
| Namibia 2019 | 3.6 | 156 | Not requested |
| Nigeria 2014 | 3.6 | 444 | 9,300 |
| Tanzania 2009 | 3.6 | 360 | 2,196 |
| Tanzania 2024 | 4.1 | 372 | 2,232 |

## QA notes

- **1,075 of 38,244 unit-month rows are missing AOD retrievals (2.8%)**. They remain
  blank/NA rather than being recoded to zero.
- Missing monthly rows: Colombia ADM2 375; Kenya 2010 ADM2 33; Kenya 2019 ADM2 22;
  Nigeria ADM2 644; Tanzania 2009 ADM2 1. All other files have none.
- One very small Kenya 2010 GADM polygon (`unknown 8`, 0.0015 km²) also lacks a
  full-window value. Every other boundary has a valid full-window AOD value.
- Kenya 2019 regression: all earlier monthly values were reproduced to floating-point
  precision. The annual field was intentionally corrected to match the teammate's
  full-window image calculation, and `month_end` now follows the repository's exclusive
  next-month convention.
- Final checks: all 15 files validated again after generation; all 38 repository tests
  passed.

Detailed methods, rationale, commands, and caveats are recorded in
`skills/aod_data_methods.md`. Machine-readable QA is in
`data/processed/aod/aod_qa_summary.csv`.
