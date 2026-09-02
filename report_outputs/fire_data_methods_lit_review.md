# Fire-exposure methods — literature summary (MODIS / FIRMS / GEE)

summary for justifying the current Google Earth Engine fire-exposure choices
and deciding whether to offer additional layers.

## Bottom line

Keep the core GEE pipeline:

- **MODIS burned area:** `MODIS/061/MCD64A1`, `BurnDate`, summarized as `monthly_burned_area_km2`.
- **MODIS active fire:** EE `FIRMS`, `T21`, summarized as `monthly_fire_count` fire pixel-days.
- **Area-normalized metrics:** useful derived variables, but **not new GEE layers**.

**Now built beyond presence/area:** **MODIS FRP intensity** from `MODIS/061/MOD14A1` +
`MODIS/061/MYD14A1`, shipped as **summed FRP** (`avg12_sum_frp_mw`) for all country-waves at
ADM1+ADM2. A **VIIRS active-fire** sensitivity layer (`NASA/VIIRS/002/VNP14A1`) is also
implemented (Zimbabwe demo), usable for exposure windows from 2012 onward.

No clean MODIS **smoke-cover** layer was identified from the Fornacca et al. article.
The closest MODIS-family candidate is MAIAC aerosol optical depth, which should be
framed as an aerosol/smoke-proxy sensitivity layer, not direct fire-smoke exposure.

## Should we offer more GEE layers?

| Option | What it adds | Peer-reviewed support | Status |
|---|---|---|---|
| **Fire density / percent burned** | Normalizes current outputs by admin area, e.g. fire pixel-days per km2 or percent burned. | [Giglio 2016](https://www.sciencedirect.com/science/article/pii/S0034425716300827); [Giglio 2018](https://www.sciencedirect.com/science/article/pii/S0034425718303705). No density-specific source found. | **Offer as derived fields**, not as separate GEE layers. |
| **MODIS FRP intensity** | Adds fire energetic intensity beyond burned area or active-fire presence. | [Giglio 2016](https://www.sciencedirect.com/science/article/pii/S0034425716300827); [Li 2018](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2017jd027823); [Wooster 2005](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2005JD006318); [Kaiser 2012](https://bg.copernicus.org/articles/9/527/2012/). | **BUILT** — shipped as summed FRP (`avg12_sum_frp_mw`); per-district max kept as a secondary column. |
| **FRP density** | Normalizes FRP by admin area after the FRP layer is added. | Same FRP support as above; no source found that specifically prescribes admin-level FRP per km2 for our exposure design. | **Offer as derived field** if FRP is added. |
| **MODIS MAIAC AOD / smoke QA** | Aerosol burden proxy; `MCD19A2` includes AOD, aerosol model QA with smoke/dust classes, and smoke injection height. | [Lyapustin 2018](https://amt.copernicus.org/articles/11/5741/2018/); EE `MCD19A2` catalog. | **Possible sensitivity layer only**; not direct smoke cover and not fire-attributed without extra assumptions. |
| **MERRA-2 aerosol components** | Coarse reanalysis option for black carbon, organic carbon, AOT, and surface mass concentration over the full survey period. | EE `NASA/GSFC/MERRA/aer/2` catalog checked; peer-reviewed fire-attribution support not reviewed here. | **Feasible but coarse**; useful only as broad aerosol context unless paired with fire attribution logic. |
| **CAMS NRT aerosol / PM2.5** | Recent atmospheric-composition option with AOD and PM fields. | EE `ECMWF/CAMS/NRT` catalog checked. | **Not suitable for full study window**; starts in 2016 and is near-real-time/forecast oriented. |
| **VIIRS active fire** | Sensitivity layer for smaller/cooler fires that MODIS can miss. | [Schroeder 2014](https://www.sciencedirect.com/science/article/abs/pii/S0034425713004483); [Zhu 2017](https://www.nature.com/articles/s41598-017-03739-0); [Fornacca 2017](https://www.mdpi.com/2072-4292/9/11/1131). | **BUILT (demo)** — `NASA/VIIRS/002/VNP14A1` 1 km; full coverage from 2012-01-19, so pre-2012 waves are excluded. |
| **FireCCI / alternate burned area** | Sensitivity check for burned-area omission, especially small/cropland burns. | [Fornacca 2017](https://www.mdpi.com/2072-4292/9/11/1131). Product/coverage source still needed. | **Possible later sensitivity layer**. |
| **Forest loss / vegetation layers** | Contextual environmental covariates, not direct fire exposure. | Not reviewed here as fire-exposure methods. | **Keep separate** from fire layer presentation. |

## Current pipeline map

| Output | Current code/source | Main citation |
|---|---|---|
| `monthly_burned_area_km2` | `MODIS/061/MCD64A1`, `BurnDate > 0`, zonal sum at 500 m | Giglio et al. (2018) |
| `monthly_fire_count` | EE `FIRMS`, `T21.mask().unmask(0)`, zonal sum at 1000 m | Giglio, Schroeder & Justice (2016) |
| `monthly_sum_frp_mw` / `monthly_max_frp_mw` / `frp_pixel_days` / `avg12_sum_frp_mw` | `MODIS/061/MOD14A1`+`MYD14A1`, `MaxFRP`×0.1 on `FireMask≥7`, zonal **sum** at 1000 m | Wooster (2005); Kaiser (2012); Li (2018) |
| VIIRS `monthly_fire_count` / `monthly_max_frp_mw` | `NASA/VIIRS/002/VNP14A1`, `FireMask≥7`, zonal sum at 1000 m (2012+ only) | Schroeder et al. (2014) |
| `avg12_*` | Mean over the 12-month pre-fieldwork exposure window | Project exposure design |
| `% burned` / fire density | Current output divided by `adm{level}_area_km2` | Derived from current metrics |

## FRP metric choice (summed vs max)

The shipped FRP exposure metric is **summed FRP** (`monthly_sum_frp_mw`, averaged over the
12-month window as `avg12_sum_frp_mw`). This is the literature-anchored choice: Li et al.
(2018) uses summed FRP and mean FRP per detection, and the physical standard — fire radiative
energy (**FRE**), the temporal integral of FRP — is proportional to biomass burned (Wooster
et al. 2005; operationalized globally in GFAS, Kaiser et al. 2012). The per-district monthly
**maximum** FRP is retained only as a secondary column (`monthly_max_frp_mw`): it is a
peak-intensity project choice, not a cited exposure metric. **Caveat:** our
`monthly_sum_frp_mw` is summed *observed* FRP (an MW accumulation at satellite overpass),
**not FRE in MJ** — no diurnal or time-integration correction — so it should be presented as
intensity/dose, not energy.

## Core citations

| Study | Link | Use |
|---|---|---|
| Gorelick et al. (2017). *Google Earth Engine: planetary-scale geospatial analysis for everyone.* Remote Sens. Environ. 202, 18-27. | https://www.sciencedirect.com/science/article/pii/S0034425717302900 | GEE platform citation. |
| Giglio, Schroeder & Justice (2016). *The Collection 6 MODIS active fire detection algorithm and fire products.* Remote Sens. Environ. 178, 31-41. | https://www.sciencedirect.com/science/article/pii/S0034425716300827 | MODIS active-fire / FIRMS basis; FRP product basis. |
| Giglio, Boschetti, Roy, Humber & Justice (2018). *The Collection 6 MODIS burned area mapping algorithm and product.* Remote Sens. Environ. 217, 72-85. | https://www.sciencedirect.com/science/article/pii/S0034425718303705 | MCD64A1 burned-area basis; small-fire limitation. |
| Randerson et al. (2012). *Global burned area and biomass burning emissions from small fires.* J. Geophys. Res. Biogeosciences 117, G04012. | https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2012jg002128 | Complementarity of active-fire and burned-area products. |
| Li et al. (2018). *Comparison of fire radiative power estimates from VIIRS and MODIS observations.* J. Geophys. Res. Atmos. | https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2017jd027823 | FRP / intensity support; uses summed FRP + mean FRP per detection. |
| Wooster, Roberts, Perry & Kaufman (2005). *Retrieval of biomass combustion rates and totals from fire radiative power observations.* J. Geophys. Res. Atmos. 110, D24311. | https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2005JD006318 | FRE = time-integrated FRP ∝ biomass burned; physical basis for the summed-FRP metric. |
| Kaiser et al. (2012). *Biomass burning emissions estimated with a global fire assimilation system (GFAS) based on observed FRP.* Biogeosciences 9, 527-554. | https://bg.copernicus.org/articles/9/527/2012/ | Operational summed/assimilated FRP → emissions; supports FRP accumulation as an exposure proxy. |
| Lyapustin, Wang, Korkin & Huang (2018). *MODIS Collection 6 MAIAC algorithm.* Atmos. Meas. Tech. 11, 5741-5765. | https://amt.copernicus.org/articles/11/5741/2018/ | MAIAC AOD and aerosol-type support; useful for smoke-proxy discussion, not direct smoke exposure validation. |
| Schroeder, Oliva, Giglio & Csiszar (2014). *The new VIIRS 375 m active fire detection data product.* Remote Sens. Environ. 143, 85-96. | https://www.sciencedirect.com/science/article/abs/pii/S0034425713004483 | VIIRS smaller-fire sensitivity rationale. |
| Zhu, Kobayashi, Kanaya & Saito (2017). *Size-dependent validation of MODIS MCD64A1 burned area ... large underestimation in croplands.* Sci. Rep. 7, 4181. | https://www.nature.com/articles/s41598-017-03739-0 | Cropland/small-fire under-detection. |
| Fornacca, Ren & Xiao (2017). *Performance of three MODIS fire products and ESA Fire_CCI in an area of frequent small fires.* Remote Sensing 9(11), 1131. | https://www.mdpi.com/2072-4292/9/11/1131 | Product comparison in a small-fire setting. Side note: supports MODIS burned-area and active-fire products, but does not identify a MODIS smoke-cover metric; smoke is mentioned only as a factor that can obstruct active-fire detection. |
| van der Werf et al. (2017). *Global fire emissions estimates during 1997-2016 (GFED4).* Earth Syst. Sci. Data 9, 697-720. | https://essd.copernicus.org/articles/9/697/2017/ | Community-standard use of MODIS fire inputs in GFED. |

## Implementation references

Official Earth Engine catalog pages checked:

- `MODIS/061/MCD64A1`: https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD64A1
- EE `FIRMS`: https://developers.google.com/earth-engine/datasets/catalog/FIRMS
- `MODIS/061/MOD14A1`: https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD14A1
- `MODIS/061/MYD14A1`: https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MYD14A1
- `NASA/VIIRS/002/VNP14A1`: https://developers.google.com/earth-engine/datasets/catalog/NASA_VIIRS_002_VNP14A1
- `NASA/LANCE/SNPP_VIIRS/C2`: https://developers.google.com/earth-engine/datasets/catalog/NASA_LANCE_SNPP_VIIRS_C2
- `MODIS/061/MCD19A2_GRANULES`: https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD19A2_GRANULES
- `MODIS/061/MCD19A1_GRANULES`: https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD19A1_GRANULES
- `NASA/GSFC/MERRA/aer/2`: https://developers.google.com/earth-engine/datasets/catalog/NASA_GSFC_MERRA_aer_2
- `ECMWF/CAMS/NRT`: https://developers.google.com/earth-engine/datasets/catalog/ECMWF_CAMS_NRT
