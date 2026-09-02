# 0822 Process Update: Cambodia and Colombia survey-to-exposure geography findings

## 1. Cambodia — 2013

The combined file contains **2,376 respondents**, all with `admin1` and `admin2`. It has
20 observed province codes, 16 repeating `admin2` suffixes, and **114 distinct four-digit
province-district keys**. Therefore, `admin2` must never be joined by itself.

The intended linkage is **clean survey → approved crosswalk → GADM exposure**. For
example, survey values `admin1 = 1` and `admin2 = 2` identify composite key `0102`
(Mongkol Borei); the crosswalk maps `0102` to GADM `adm2_gid = KHM.1.2_1`; and that GID
links to the Cambodia exposure rows. The composite survey key is therefore an intermediate
crosswalk key, while the exposure join itself uses `adm2_gid`.

### ADM1 finding

Eighteen of the 20 survey province codes map directly to one GADM 3.6 ADM1. The other two
require special handling:

| Survey field(s) | Respondents | ADM1 result |
|---|---:|---|
| `admin1=03` | 148 | Use `admin2` to assign 70 respondents to Kampong Cham and 78 to Tboung Khmum, which was created after the survey |
| `admin1=09, admin2=04` | 8 | Unresolved: these clean-survey values correspond to Khemara Phoumin in Koh Kong. However, the official NIS Cambodia VACS metadata lists Stung Treng—not Koh Kong—among the 20 surveyed provinces. Confirm the original survey province name before assigning a GADM area |

**ADM1 status: 2,368/2,376 respondents (99.7%) have a GADM 3.6 ADM1 candidate; eight
remain unresolved.**

### ADM2 coverage bridge

| Coverage stage | Added units | Added respondents | Cumulative respondents | Cumulative coverage |
|---|---:|---:|---:|---:|
| Direct normalized name within compatible parent(s) | 95 | 1,972 | 1,972 | 83.0% |
| Spelling/transliteration candidates | 3 | 95 | 2,067 | 87.0% |
| Strong historical/spatial-equivalence candidates | 4 | 77 | 2,144 | 90.2% |
| Survey units nested within broader GADM 3.6 units | 3 | 45 | 2,189 | 92.1% |
| Three central Phnom Penh khans → dominant old GADM polygon | 3 | 90 | 2,279 | 95.9% |

One concrete example of each linkage method is shown below. The latter four remain
candidate operations rather than approved joins.

| Linkage method | Survey key and recovered name | Candidate GADM 3.6 ADM2 | Respondents | Why it fits the method |
|---|---|---|---:|---|
| Direct normalized name within parent | `0102` Mongkol Borei | Mongkol Borei (`KHM.1.2_1`) | 26 | Same normalized district name within Banteay Meanchey |
| Spelling/transliteration | `1003` Prek Prasab | Preaek Prasab (`KHM.11.3_1`) | 14 | Constrained transliteration difference within Kratie |
| Historical/spatial equivalence | `0202` Thma Koul | Bat Dambang (`KHM.2.3_1`) | 18 | Legacy GADM label with near-complete diagnostic spatial equivalence |
| Nested survey unit | `0110` Paoy Paet | Ou Chrov (`KHM.1.3_1`) | 13 | Newer survey unit is nested in the broader GADM 3.6 polygon; coarsening approval is required |
| Central Phnom Penh aggregation | `1201` Chamkar Mon | Phnom Penh (`KHM.16.3_1`) | 18 | Survey khan falls mainly in GADM 3.6's older central-city polygon; manual review is required |

This gives a **candidate ceiling of 108/114 units and 2,279/2,376 respondents (95.9%)**.
The six unresolved keys cover 97 respondents: `0904` Khemara Phoumin/Stung Treng (8),
`1208` Saensokh (15), `1209` Pur SenChey (42), `1411` Pur Rieng (9), `1801` Preah
Sihanouk Municipality (13), and `2205` Trapeang Prasat (10). Their survey-era footprints
cross or disagree with GADM 3.6 polygons, so they should not be assigned to the largest
overlap without an explicit analytic decision.

## 2. Colombia — 2018

The combined file contains **2,705 respondents**, all with `admin1` and `admin2`. It has
33 department/District codes, 58 repeating `admin2` suffixes, and **92 distinct
`(admin1, admin2)` pairs**. An external administrative lookup recovered a unique area name
for every pair and respondent; it was used for validation only and is not a linkage field.
This is **100% survey-area name recovery**, not 100% GADM boundary agreement.

The same linkage direction applies here: **clean survey → approved crosswalk → GADM
exposure**. For example, survey values `(admin1 = 5, admin2 = 1)` identify Medellín; the
crosswalk maps that survey pair to GADM `adm2_gid = COL.2.68_1`; and that GID links to the
Colombia exposure rows. `admin2` is not unique without `admin1`, but the final exposure
join uses the mapped GADM GID.

### ADM1 finding

All 33 official department/District codes are recoverable. GADM 3.6 has only 32 Colombian
ADM1 units because Bogotá is nested inside Cundinamarca. Bogotá's 116 respondents must be
linked through the Bogotá ADM2 candidate (`COL.14.79_1`), not assigned the whole
Cundinamarca ADM1 exposure.

### ADM2 coverage bridge

| Coverage stage | Added units | Added respondents | Cumulative respondents | Cumulative coverage |
|---|---:|---:|---:|---:|
| Direct normalized `NAME_2` match within department | 80 | 2,068 | 2,068 | 76.5% |
| Exact GADM `VARNAME_2` alias | 7 | 280 | 2,348 | 86.8% |
| Constrained title/article normalization | 2 | 180 | 2,528 | 93.5% |
| Bogotá ADM2 candidate | 1 | 116 | 2,644 | 97.7% |

The examples below show the actual operation represented by each stage. The title/article
stage is split into its two component operations for clarity.

| Linkage method | Clean-survey fields and validated area name | Candidate GADM 3.6 ADM2 | Respondents | Why it fits the method |
|---|---|---|---:|---|
| Direct normalized `NAME_2` | `(admin1=5, admin2=1)` Medellín | Medellín (`COL.2.68_1`) | 114 | Same normalized municipality name within Antioquia |
| Exact `VARNAME_2` alias | `(admin1=52, admin2=1)` Pasto | San Juan de Pasto (`COL.21.50_1`) | 31 | GADM records Pasto as an exact alternate name |
| Remove administrative title | `(admin1=8, admin2=1)` Distrito Especial, Industrial y Portuario de Barranquilla | Barranquilla (`COL.4.2_1`) | 165 | Removing the official title leaves the GADM name within Atlántico |
| Article variant | `(admin1=50, admin2=370)` Uribe | La Uribe (`COL.20.13_1`) | 15 | Names differ only by the article within Meta |
| Bogotá hierarchy/name candidate | `(admin1=11, admin2=1)` Bogotá, D.C. | Santafé de Bogotá (`COL.14.79_1`) | 116 | Historical GADM name and ADM1-parent mismatch; manual boundary approval is required |

This gives **90/92 GADM name candidates and 2,644/2,705 respondents (97.7%)**. The two
survey pairs absent from GADM 3.6 are Zapayán (`admin1=47, admin2=960`, 31 respondents)
and Mapiripana (`admin1=94, admin2=663`, 30 respondents). Both appear in GADM 4.1, but
that cannot be mixed directly with the current GADM 3.6 exposure outputs.

Name recovery still overstates geographic compatibility. Among the 90 name candidates,
only 21 have at least 90% survey-to-GADM polygon overlap, 45 have at least 80%, and 84 have
at least 50%. Six same-name candidates fall below 50%. The external boundary comparison
was diagnostic only; the current linkage remains tied to GADM 3.6 and therefore requires
documented candidate approval and sensitivity treatment.
