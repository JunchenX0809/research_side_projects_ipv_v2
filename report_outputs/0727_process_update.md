# 0727 Process Update — Satellite exposure data sources (VACS)
---

## 1. MODIS, FIRMS, VIIRS — what they are

- **MODIS — Moderate Resolution Imaging Spectroradiometer.** A NASA **sensor** carried on two
  satellites, **Terra** (2000+) and **Aqua** (2002+). Four of our five layers are MODIS products.
- **VIIRS — Visible Infrared Imaging Radiometer Suite.** A newer NASA **sensor** on the
  **Suomi-NPP** satellite (2012+). It measures fire the same way MODIS does but at finer detail, so
  it catches smaller/cooler fires — at the cost of a shorter record, starting only in 2012
  (Schroeder et al., 2014).
- **FIRMS — Fire Information for Resource Management System.** **Not a satellite and not a sensor** —
  a NASA **system** that distributes active-fire detections. The Earth Engine "FIRMS" layer we use
  is built entirely from the **MODIS** active-fire product (MOD14/MYD14), so in our pipeline "FIRMS"
  is simply MODIS active-fire data under a different name — a naming distinction, not a separate
  satellite. *(Verified on the EE FIRMS catalog: MODIS-only; bands `T21`, `confidence`,
  `line_number`;)*

**What these layers actually measure:**

- **Burned area** (MODIS MCD64A1) — how much land *actually burned*, mapped after the fire (500 m).
- **Active fire** (MODIS MOD14/MYD14 = our "FIRMS"; and VIIRS VNP14A1) — a "hotspot" flagged where
  the sensor sees fire *at the moment it passes overhead* (1 km). Burned area and active fire are
  **complementary**: active fire catches small/short fires that burned-area mapping misses, and
  vice-versa (Randerson et al., 2012).
- **Fire radiative power (FRP)** — the heat output (MW) reported *inside* the active-fire products
  (MOD14A1/MYD14A1, VNP14A1); an intensity measure. The EE "FIRMS" layer carries no FRP, so we take
  FRP from those daily active-fire products.

---

## 2. Layers in use (what each is for)

| Deliverable | Earth Engine source (band) | What it is / used for | Citation |
|---|---|---|---|
| `monthly_burned_area_km2` | MODIS `MCD64A1` (`BurnDate`), 500 m | Area burned (km²) per unit-month — "how much land burned" | Giglio et al. (2018) |
| `monthly_fire_count` (FIRMS) | EE `FIRMS` = MODIS `MOD14/MYD14` (`T21`), 1 km | Active-fire detections (fire pixel-days) — "how often/where fire was seen at overpass" | Giglio, Schroeder & Justice (2016) |
| `monthly_sum_frp_mw` (+ max, pixel-days) | MODIS `MOD14A1`+`MYD14A1` (`MaxFRP`), 1 km | Fire intensity (MW) — energetic dose beyond mere presence | Wooster et al. (2005); Kaiser et al. (2012); Li et al. (2018) |
| VIIRS `monthly_fire_count` / FRP | `VNP14A1` (`FireMask`, `MaxFRP`), 1 km, 2012+ | Same active-fire/FRP signal from a finer sensor — sensitivity to smaller fires | Schroeder et al. (2014) |
| `monthly_mean_aod`, `avg12_mean_aod` | MODIS `MCD19A2` (`Optical_Depth_055`), 1 km | Total-column aerosol loading — an aerosol/smoke-proxy layer (not fire-attributed, not ground PM₂.₅) | Lyapustin et al. (2018) |

All layers are pulled via Google Earth Engine (Gorelick et al., 2017). Each value is aggregated
over the 12 months before fieldwork; the annual `avg12_*` is the mean of those 12 monthly values.

---

## 3. Corrections to `skills/exposure_datasets.xlsx`

The workbook is a useful skeleton but does not match the layers we actually run, and omits two
delivered products:

| xlsx row | Problem | Correct |
|---|---|---|
| VIIRS Burned Area (`VNP64A1`), 375 m | Wrong product & resolution | We use VIIRS **active fire `VNP14A1`** (1 km), not a burned-area product |
| FIRMS = MODIS + VIIRS, 375 m–1 km | Conflates sensors | EE `FIRMS` = **MODIS only, 1 km** (`T21`); no VIIRS, no FRP |
| FireCCI51 (250 m) | Not used | Candidate/sensitivity product only; not delivered |
| Hansen (Landsat, 30 m) | Not a fire-exposure layer | Forest-loss context only |
| MODIS Burned Area (`MCD64A1`), 500 m | — | Correct |
| *(missing)* | Two delivered layers absent | Add MODIS **FRP** (`MOD14A1`/`MYD14A1` `MaxFRP`) and **MAIAC AOD** (`MCD19A2`) |

---

## References (APA)

- Giglio, L., Schroeder, W., & Justice, C. O. (2016). The Collection 6 MODIS active fire detection algorithm and fire products. *Remote Sensing of Environment, 178*, 31–41.
- Giglio, L., Boschetti, L., Roy, D. P., Humber, M. L., & Justice, C. O. (2018). The Collection 6 MODIS burned area mapping algorithm and product. *Remote Sensing of Environment, 217*, 72–85.
- Gorelick, N., Hancher, M., Dixon, M., Ilyushchenko, S., Thau, D., & Moore, R. (2017). Google Earth Engine: Planetary-scale geospatial analysis for everyone. *Remote Sensing of Environment, 202*, 18–27.
- Kaiser, J. W., Heil, A., Andreae, M. O., Benedetti, A., Chubarova, N., Jones, L., … van der Werf, G. R. (2012). Biomass burning emissions estimated with a global fire assimilation system based on observed fire radiative power. *Biogeosciences, 9*(1), 527–554.
- Li, F., Zhang, X., Kondragunta, S., & Csiszar, I. (2018). Comparison of fire radiative power estimates from VIIRS and MODIS observations. *Journal of Geophysical Research: Atmospheres, 123*(9), 4545–4563.
- Lyapustin, A., Wang, Y., Korkin, S., & Huang, D. (2018). MODIS Collection 6 MAIAC algorithm. *Atmospheric Measurement Techniques, 11*(10), 5741–5765.
- Randerson, J. T., Chen, Y., van der Werf, G. R., Rogers, B. M., & Morton, D. C. (2012). Global burned area and biomass burning emissions from small fires. *Journal of Geophysical Research: Biogeosciences, 117*, G04012.
- Schroeder, W., Oliva, P., Giglio, L., & Csiszar, I. A. (2014). The New VIIRS 375 m active fire detection data product. *Remote Sensing of Environment, 143*, 85–96.
- Wooster, M. J., Roberts, G., Perry, G. L. W., & Kaufman, Y. J. (2005). Retrieval of biomass combustion rates and totals from fire radiative power observations. *Journal of Geophysical Research: Atmospheres, 110*, D24311.
