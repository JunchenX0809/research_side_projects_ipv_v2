# 0706 Process Update - VIIRS Demo 1

## MODIS/FIRMS/VIIRS distinction

| Source | Current metric | What it represents |
|---|---|---|
| MODIS MCD64A1 | `monthly_burned_area_km2` | Burned area mapped after the fact. Useful for fire extent, but can miss small/short/cropland burns. |
| MODIS FIRMS | `monthly_fire_count` | MODIS active-fire pixel-days from the EE `FIRMS` layer. Useful for fire occurrence/presence, not burned area. |
| VIIRS VNP14A1 | `monthly_fire_count`, `monthly_max_frp_mw` | VIIRS active-fire pixel-days and monthly maximum FRP from active-fire pixels. Useful as a sensitivity comparison to MODIS active fire/FRP. |

Historical VIIRS `VNP14A1` is not count-only: it also includes `FireMask` confidence classes and `MaxFRP` (MW). The regenerated Zimbabwe demo now exports active-fire counts plus `monthly_max_frp_mw`. MODIS Max FRP was not deleted from prior FRP generations: the summed-FRP files retain `monthly_max_frp_mw`, and the legacy max-FRP files retain `avg12_max_frp_mw`, so radiative-power sensitivity can be incorporated later if needed.

VIIRS is feasible for the 2013+ sensitivity subset using historical 1 km `VNP14A1`, not the newer 375 m near-real-time LANCE layer. Excluded from the enabled dry-run set because their windows begin before VIIRS coverage: Eswatini 2007, Haiti 2012, and Kenya 2010.

For the PI question, VIIRS gives us a same-format active-fire comparison point for ADM1/ADM2 monthly exposure and 12-month average exposure.

## Smoke and fire-derivative discovery

Fornacca et al. (2017) supports using MODIS burned-area and active-fire products, but it does not identify a MODIS smoke-cover metric; smoke is mentioned only as a factor that can obstruct active-fire detection.

No clean historical MODIS smoke-cover layer was identified. The closest GEE-ready MODIS candidate is MAIAC `MCD19A2`: daily 1 km AOD with smoke/dust aerosol-model QA and smoke injection height, usable only as an aerosol/smoke-proxy sensitivity layer. Other feasible but less direct options are coarse MERRA-2 aerosol components from 1980 onward, and CAMS NRT aerosol/PM fields for recent years only.

Brief implication: for the current VACS windows, FRP and VIIRS active fire are stronger fire-derivative sensitivity additions than smoke; MAIAC AOD could be scoped later if the PI wants a cautious aerosol proxy.

## Demo status

Tested Zimbabwe VIIRS active-fire extraction for the same 12-month pre-fieldwork window used in the current fire pipeline.

| Grain | Output | Rows | Units | Months |
|---|---:|---:|---:|---:|
| ADM2 | `data/processed/viirs/zimbabwe_viirs_vnp14a1_gadm36_2016.csv` | 720 | 60 | 12 |
| ADM1 | `data/processed/viirs/zimbabwe_viirs_vnp14a1_gadm36_adm1_2016.csv` | 120 | 10 | 12 |

Window: `2016-01-01` through `2016-12-31`, the 12 months before Zimbabwe 2017 fieldwork.

Both VIIRS files include `monthly_max_frp_mw` for FRP sensitivity.

## Zimbabwe ADM2 comparison

All three Zimbabwe ADM2 files have 720 rows, 60 districts, and 12 exposure months.

| Metric | VIIRS active fire | MODIS FIRMS active fire | MODIS burned area |
|---|---:|---:|---:|
| Annual total | 17,345.64 fire pixel-days | 94,019.38 fire pixel-days | 22,712.15 km2 |
| Nonzero district-months | 386 / 720 | 382 / 720 | 273 / 720 |
| Districts with any nonzero value | 59 / 60 | 58 / 60 | 53 / 60 |
| Peak month | September 2016 | October 2016 | September 2016 |

Correlation across district-months:

| Pair | Correlation |
|---|---:|
| VIIRS active fire vs FIRMS active fire | 0.984 |
| VIIRS active fire vs MODIS burned area | 0.922 |
| FIRMS active fire vs MODIS burned area | 0.910 |

FRP sensitivity note: Zimbabwe ADM2 VIIRS peak `monthly_max_frp_mw` is 1,221.1 MW; the comparable MODIS Terra/Aqua peak is 2,144.1 MW. The district-month correlation between VIIRS and MODIS monthly max FRP is 0.729.

Brief observations:

- VIIRS and FIRMS agree strongly on where/when active fire appears.
- VIIRS detects active fire where MODIS burned area is zero in 130 district-months.
- MODIS burned area is sparser, as expected for a burned-scar product.
