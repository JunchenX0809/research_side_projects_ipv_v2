# 0723 Process Update

Two investigations for the team email: (1) whether the leap year affects our averages, and
(2) how the GADM boundary version changes for countries surveyed at two time periods.
Section 3 (satellite data-source write-up) is stubbed for later. Everything below is grounded
in the pipeline code (`utils/`) and the delivered CSVs — no assumptions.

---

## Section 1 — Leap year is **not** a concern for our averages

**Bottom line: no correction and no re-rendering are needed.** The pipeline never divides by a
fixed day count, so a 366-day window cannot distort any average. Verified in the code and in
every flagged output file.

**How the numbers are built** (`utils/vacs_survey_time.py`, `utils/adam_*_export.py`):

- The exposure window is the **12 calendar months before fieldwork** (`field_start − 1 year` …
  `field_start − 1 day`). It is always exactly **12 monthly buckets**, whether the year spans 365
  or 366 days.
- Each monthly value is a **sum/count over the days in that calendar month**. February is pulled
  with the filter `[Feb 1, Mar 1)`, so **Feb 29 is automatically and correctly included** when it
  exists — nothing dropped, nothing double-counted.
- The annual value `avg12_*` is the **arithmetic mean of the 12 monthly values (÷ 12 months)** — it
  is *not* a per-day rate and never divides by 365/366. Confirmed `avg12 == mean(monthly)` to
  floating-point precision in all flagged files.
- Net effect of a leap day: February simply reflects one extra day of satellite observation
  opportunity (29 vs 28). This is the same kind of variation months already have (28–31 days) and
  is fully absorbed by the equal-weight monthly average. It is not an error.

**The three flagged waves** (windows and February buckets read from the delivered CSVs):

| Wave | Exposure window (delivered) | Leap day in window? | Feb bucket | Products delivered |
|---|---|---|---|---|
| Tanzania 2024 | 2023-03-01 → 2024-02-29 | **Yes** — Feb 29 2024 | 29 days, included | MODIS, FIRMS, FRP, VIIRS, AOD |
| Haiti 2012 | 2011-04-01 → 2012-03-31 | **Yes** — Feb 29 2012 | 29 days, included | FRP only |
| Cambodia 2013 | 2012-03-01 → 2013-02-28 (12 whole months) | **No** — leap Feb 2012 is dropped; only Feb 2013 (non-leap) is in the window | 28 days | FRP, VIIRS |

- **Tanzania 2024 & Haiti 2012:** the 29th *is* in the February monthly count, and because the
  annual is the mean of the 12 monthly counts, it flows into the annual automatically. ✔
- **Cambodia 2013:** fieldwork started **mid-month** (2013-02-10), so the nominal window
  (2012-02-10 → 2013-02-09) does span Feb 29 2012 — but the pipeline keys buckets to whole calendar
  months and keeps a month only if its `month_start ≥ exposure_start`. The Feb-2012 bucket (starts
  02-01, before 02-10) is dropped and the field-start month is kept whole, so the realized window is
  **12 whole months, March 2012 → February 2013**. The leap day therefore is **not in the delivered
  data at all**, and the only February present (Feb 2013) is a normal 28-day month. No concern.
  *(Note: Eswatini 2022 was originally mentioned in this group; it is also not affected — 2022 is not
  a leap year.)*

→ **Team action item ("was the 29th included in the monthly and annual counts?") — answered: yes
wherever a 29th exists in the window; no re-render is required for leap-year reasons.**

**Side note (a separate, non-leap issue — mid-month field starts):** for waves whose fieldwork starts
mid-month (e.g. Cambodia), the window is realized as **12 whole calendar months ending in the
field-start month** — the partial leading month is dropped and the field-start month is kept whole. So
the delivered exposure dates do not exactly equal the team's "12 months before the survey day"
(previous-365-days) definition. **If we ever re-render these cohorts, it is for this date-alignment
reason, not for the leap year.** This affects only waves whose field start is not on the 1st of a month
(field-start-on-the-1st waves already match); the specific rerun set is tracked separately.

---

## Section 2 — GADM version changes across the two survey periods

Three countries were collected at two time periods. By our version rule (GADM release keyed to the
end of the exposure window) the earlier period maps to **GADM 3.6** and the later to **GADM 4.1**,
so all three cross a version boundary. I compared the authoritative GADM 3.6 vs 4.1 boundaries at
ADM1 and ADM2 and cross-checked against the delivered CSVs — **delivered unit counts match the GADM
source exactly in every case.**

| Country | Periods | Version | ADM1 | ADM2 | Structure change? |
|---|---|---|---|---|---|
| **Tanzania** | 2009 → 2024 | 3.6 → 4.1 | 30 → **31** | 183 → **186** | **Yes — material** |
| **Kenya** | 2010 → 2019 | 3.6 → 4.1 | 47 → 47 | 301 → 300 | Minor (1 cleanup) |
| **Eswatini** | 2007 → 2022 | 3.6 → 4.1 | 4 → 4 | 55 → 55 | **None** |

**Tanzania — the one to watch.**
- **New region Songwe** (`TZA.31_1`), carved out of **Mbeya** in 2016; present in 4.1 only
  (ADM1 30→31, and a matching new ADM2 district).
- **Mbeya keeps the same code (`TZA.13_1`) but its area shrank 61,686 → 37,903 km²** once Songwe
  (23,773 km²) split off. So *the same GID does not mean the same territory* across the two periods —
  a longitudinal Mbeya comparison is comparing two different footprints. (Country total is unchanged,
  ~940,000 km².)
- **5 Zanzibar regions were relabeled English→Swahili at the same GID** — e.g. Zanzibar West →
  Mjini Magharibi, Pemba North → Kaskazini Pemba, Zanzibar South and Central → Kusini Unguja. Same
  polygons, different `NAME_1`. → **join across periods by GID, never by name.**
- ADM2 also has "Township Authority"→"Town" relabels (7 districts), a "Magharibi" → "Magharibi A/B"
  split, a spelling fix (Nyang'wale → Nyang'hwale), and minor lake-polygon changes. Net ADM2 +3.

**Kenya — essentially stable, but one version inconsistency to reconcile.**
- ADM1 identical (the 47 counties). ADM2 301 → 300: the only difference is a spurious unnamed 3.6
  polygon ("unknown 8") that was cleaned out in 4.1.
- **Flag:** for the 2019 wave the products were rendered on *different* versions — **FRP and VIIRS on
  GADM 3.6, AOD on GADM 4.1**. Recommend standardizing that wave on a single version.

**Eswatini — no change.** ADM1 (4) and ADM2 (55) are identical across 3.6 and 4.1; the two periods
are directly comparable.

**Recommendations**
1. Link the two periods by **GID**, not by name — the Tanzania Zanzibar relabels would otherwise look
   like 5 dropped + 5 new units when the areas are unchanged.
2. Treat **Tanzania Mbeya/Songwe** explicitly in any 2009↔2024 comparison (same GID, different area).
3. Reconcile the **Kenya 2019** cross-product version mismatch (3.6 vs 4.1).
4. Eswatini (both levels) and Kenya (ADM1) are stable and directly comparable across periods.

---

## Section 3 — Satellite data-source write-up (to be written)

To be drafted with Junchen's sources and APA citations (regularity of collection, accuracy,
sensor/product background). Grounded methods already in the repo: `skills/fire_data_methods.md`
(MODIS/FIRMS/FRP/VIIRS) and `skills/aod_data_methods.md` (MAIAC AOD).

**Quick assessment of `skills/exposure_datasets.xlsx`** (flagged as possibly authored by someone else):
useful skeleton and generally correct generic facts, **but it has material errors versus the specific
Earth Engine assets we actually use, and it omits two of our delivered layers.** It should not be used
as-is for Section 3:

- **VIIRS row is wrong for us:** it lists "VIIRS Burned Area (VNP64A1), 375 m." We actually use
  **VNP14A1 active fire at 1 km** (not the VNP64A1 burned-area product; and VNP64A1 is 500 m, while
  the 375 m VIIRS active-fire product is VNP14IMG).
- **FIRMS row is wrong for us:** it lists "MODIS + VIIRS, 375 m–1 km." The Earth Engine `FIRMS` asset
  we pull is **MODIS MOD14/MYD14 only, 1 km** (no VIIRS feed, no FRP band).
- **Missing our layers:** **MAIAC AOD (MCD19A2, 1 km)** and **FRP intensity (MOD14A1/MYD14A1 MaxFRP)**
  are delivered products but are absent from the table.
- MODIS MCD64A1 row is broadly correct (500 m, 2000–present, under-detects small fires).

Verdict: reuse the structure and the generic descriptions, but correct the dataset identities against
the repo methods docs before Section 3 relies on it.
