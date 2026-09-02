# Process update


## 1. Context

GEE is our **catalog + cloud compute** layer (no full-country raster downloads). **Zambia:** Hansen admin‑2 loss + fire pilots (2013–14 window). **Zimbabwe:** same fire **EDA** pattern for the **2016** exposure year ahead of **2017** survey

## 2. Progress

EE auth and project setup are working; Hansen admin‑2 CSV for Zambia is in place; **Zambia** and **Zimbabwe** fire notebooks run the same MODIS / FIRMS zonal template on **GAUL 2015 admin‑2** 

## 3. Findings

### Hansen 
- **Source:** Hansen GFC 2025 v1.13, `lossyear` = 2013; **regions:** FAO GAUL 2015 level 2, Zambia
- **Table:** **72** rows (one ADM2); national **~158k ha** summed `loss_area_ha` (30 m loss mask; **not** fire)
- **Use:** reasonable for **relative** district comparison until linked to survey geography with an explicit rule

### Fire — Zambia (`zambia_gee_v3.ipynb` + 2014 PUD)

- **GEE:** zonal stats to **GAUL 2015 admin‑2**; **`burn_area_ha`** = MCD64A1 burned mask summed to ha per district; **`hot_area_ha`** = FIRMS T21 proxy (ha).
- **Survey link:** **`prov`** / **`dist`** etc.; **72** GAUL ADM2 vs **61** / **53** distinct **`dist`** (male / female PUD)—reconcile with a crosswalk before merging.
- **Still need:** **`dist` → GAUL names** or official code → **`ADM2_CODE`** for a clean join.

**Zambia snapshot — August 2013 MODIS burn (one month):** province-level “top district per ADM1” below (nine ADM1 labels in this GAUL extract). **National sum** of district **`burn_area_ha`** that month ≈ **8.0M ha** (order-of-magnitude headline from the pilot run).

| ADM1 (province) | ADM2 (max burn in province) | burn_area_ha |
|-----------------|-----------------------------|-------------:|
| Central | Serenje | 631,504.6 |
| Copperbelt | Mpongwe | 136,534.4 |
| Eastern | Chama | 231,592.1 |
| Luapula | Mwense | 388,950.6 |
| Lusaka | Chongwe | 120,989.5 |
| North-Western | Kasempa | 238,272.9 |
| Northern | Mpika | 525,815.5 |
| Southern | Kazungula | 187,299.6 |
| Western | Sesheke | 394,425.0 |

| ADM1 (province) | ADM2 (max hot-area proxy in province) | hot_area_ha |
|-----------------|----------------------------------------|------------:|
| Central | Serenje | 614,581.4 |
| Copperbelt | Lufwanyama | 250,912.2 |
| Eastern | Chama | 303,184.3 |
| Luapula | Mwense | 313,396.7 |
| Lusaka | Chongwe | 175,103.1 |
| North-Western | Solwezi | 497,378.5 |
| Northern | Mpika | 682,904.0 |
| Southern | Kazungula | 255,246.2 |
| Western | Sesheke | 609,776.6 |

### Fire — Zimbabwe

**January 2016** (first month of the exposure year in the notebook): **~701 ha** summed over **62** GAUL districts for **`burn_area_ha`**—same MCD64→ha definition as Zambia, **different country and month** than the Zambia table above, so totals are **not** directly comparable as a “Zambia vs Zimbabwe” scorecard.

| ADM1_NAME | ADM2_NAME | burn_area_ha (sample) |
|------------|-----------|----------------------:|
| Mashonaland East | Chikomba | 94.2 |
| Bulawayo | Bulawayo | 0.0 |
