# Process update — 2026-05-02

## Context (1 line)

PI asked for **MODIS / VIIRS**-based, **globally comparable** fire exposure ahead of VACS field periods; product choice and spatial unit remain open.

---

## This week — completed

**Formats & exploration**

| Format / path | Role |
|---------------|------|
| **FIRMS `api/area/csv`** (`MODIS_SP`, lon/lat bbox) | Live pull for bounded windows; documents **`DAY_RANGE` 1–5** only. |
| **FIRMS Archive bulk** (email request → **CSV / TXT** etc.) | Full-season / full-country extracts without chaining dozens of API calls. |
| **Notebook** `exposure_notebooks/zambia_modis_fire_v1.ipynb` | Zambia pilot: paths, **12-month pre-survey** window **2013-08-04 → 2014-08-03** (survey **2014-08-04 → 2014-10-05**), whole-country bbox, optional API smoke test + **`BULK_DIR`** ingest scaffold. |

**Zambia — measured API behavior (Zambia bbox, `EXPOSURE_START` = 2013-08-04)**

- `DAY_RANGE = 10` → **HTTP 400 Bad Request** (matches FIRMS area-API spec: max 5 days).
- `DAY_RANGE = 5` → **HTTP 200**, **9,726** MODIS hotspot rows for that call (full-country box; count reflects dense detection sampling, not “errors”).
- Sample rows: **`acq_date` 2013-08-04**, Terra / MODIS, coordinates inside Zambia — consistent with a valid 5-day window anchored on `day0`.

**Bulk data**

- **FIRMS Archive Download** used to request **MODIS** coverage for **Zambia** over the **full exposure year** (and/or months spanning **2013-08-04 → 2014-08-03**); delivery is **NASA email / async** — awaiting files into `data/raw/exposure_firms/zambia/`.

---

## Roadmap — next steps

1. **Data availability matrix (executable):** for **each VACS country–wave** in `data/raw/VACS_survey_time.csv` (**21 rows** today, mixed date-string quality), test **FIRMS archive / API coverage** **one country at a time** across **each needed time range** (at minimum: **survey field window** and **prior-season / pre-survey exposure window** once defined per wave). Log pass/fail, product (`MODIS_SP` vs VIIRS variants), and date limits.
2. **Phased delivery:** take countries **in priority order** as the project proceeds; do not parallelize until templates are stable.

---

## Parking lot

- Normalize survey date strings in the CSV; fix typos (e.g. Lesotho) where they affect automation.
- Burned-area track (**MCD64A1** / GEE) remains separate from FIRMS **hotspot** points.
