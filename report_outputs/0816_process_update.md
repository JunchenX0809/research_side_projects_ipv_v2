# 0816 Process Update: Zimbabwe survey-to-exposure geography findings


## 1. ADM1 finding — deterministic coverage is available

The combined file has 10 Zimbabwe `admin1` codes. Comparison with the original PUD shows
a one-to-one relationship between each code, its survey province name, and the GADM 3.6
ADM1 GID:

| Survey code | Survey province | GADM 3.6 GID |
|---:|---|---|
| 1 | Bulawayo | `ZWE.1_1` |
| 2 | Harare | `ZWE.2_1` |
| 3 | Manicaland | `ZWE.3_1` |
| 4 | Mash Central | `ZWE.4_1` |
| 5 | Mash East | `ZWE.5_1` |
| 6 | Mash West | `ZWE.6_1` |
| 7 | Masvingo | `ZWE.7_1` |
| 8 | Mat North | `ZWE.8_1` |
| 9 | Mat South | `ZWE.9_1` |
| 10 | Midlands | `ZWE.10_1` |

The survey abbreviations correspond to the full GADM names (for example, Mash Central =
Mashonaland Central). **ADM1 status: 10/10 survey codes and 8,715/8,715 respondents
(100%) have a deterministic GADM 3.6 ADM1 match.**

## 2. What the combined `admin2` code represents

Zimbabwe `admin2` is not missing: it contains **91 integer codes, 1–91**. These are not
GADM GIDs and do not align numerically with GADM's 60 Zimbabwe ADM2 polygons.

The original PUD contains district-name fields. Row alignment between the combined file
and PUD was checked using age and sex, which agreed on all 8,715 rows. Within those aligned
records, every combined `admin2` code maps to exactly one PUD district string. For example:

- Combined `admin1 = 2`, `admin2 = 35`
- PUD province/district = Harare / `HARARE`
- GADM ADM2 name/GID = Harare / `ZWE.2.1_1`

The original PUD variable `dcode` is not a usable substitute: many `dcode` values refer to
multiple district names, and many district names carry multiple `dcode` values.

One confirmed cleaning anomaly is that survey codes 52 and 53 represent `marondera` and
`MARONDERA`. They are separate codes because of capitalization but normalize to the same
district name and the same GADM unit.

## 3. ADM2 status

Using case-, punctuation-, and whitespace-normalized names while constraining comparisons
to the known ADM1 province gives **45 direct normalized-name matches**, covering **5,532
respondents (63.5%)**. Following the PI's `Notes_VACS.Rmd` combination annotations and
checking each proposed target against GADM 3.6 within ADM1 produces candidate coverage for
**79 of 91 survey units and 8,342 of 8,715 respondents (95.7%)**. These remain proposed
matches pending boundary-compatibility validation.

### Coverage bridge

| Coverage stage | Added survey units | Added respondents | Cumulative respondents | Cumulative coverage |
|---|---:|---:|---:|---:|
| Direct normalized-name matches | 45 | 5,532 | 5,532 | 63.5% |
| Terminal rural/urban/town suffix candidates | 28 | 2,164 | 7,696 | 88.3% |
| Four constrained name-variant candidates | 4 | 284 | 7,980 | 91.6% |
| Chitungwiza and Epworth → sole Harare ADM2 candidate | 2 | 362 | 8,342 | 95.7% |

### Candidate operations that add coverage beyond 63.5%

The table below shows only the 34 non-direct candidates responsible for the increase from
63.5% to 95.7%. “RMD support” means the survey name was explicitly marked `*combine*` in
`Notes_VACS.Rmd`; it does not mean the target GADM polygon has been validated.

| Clean CSV `admin2` code(s) and survey name(s) | Survey province | Candidate GADM 3.6 ADM2 | Candidate rule | Added respondents | RMD support |
|---|---|---|---|---:|---|
| 1 Beitbridge Rural; 2 Beitbridge Urban | Mat South | Beitbridge (`ZWE.9.1_1`) | Remove suffix | 61 | Yes |
| 4 Bindura Rural; 5 Bindura Urban | Mash Central | Bindura (`ZWE.4.1_1`) | Remove suffix | 119 | Yes |
| 10 Bulilima | Mat South | Bulilima (North) (`ZWE.9.2_1`) | Name variant | 62 | No |
| 12 Chegutu Rural; 13 Chegutu Urban | Mash West | Chegutu (`ZWE.6.1_1`) | Remove suffix | 99 | Yes |
| 17 Chipinge Rural; 18 Chipinge Urban | Manicaland | Chipinge (`ZWE.3.3_1`) | Remove suffix | 265 | Yes |
| 19 Chiredzi Rural; 20 Chiredzi Town | Masvingo | Chiredzi (`ZWE.7.2_1`) | Remove suffix | 151 | Yes |
| 22 Chitungwiza; 24 Epworth | Harare | Harare (`ZWE.2.1_1`) | Sole GADM ADM2 within ADM1 | 362 | No |
| 31 Gwanda Rural; 32 Gwanda Urban | Mat South | Gwanda (`ZWE.9.3_1`) | Remove suffix | 69 | Yes |
| 33 Gweru Rural; 34 Gweru Urban | Midlands | Gweru (`ZWE.10.4_1`) | Remove suffix | 281 | Yes |
| 36 Harare Rural | Harare | Harare (`ZWE.2.1_1`) | Remove suffix | 62 | Yes |
| 39 Hwange Urban | Mat North | Hwange (`ZWE.8.3_1`) | Remove suffix | 14 | Yes |
| 40 Hwedza | Mash East | Wedza (`ZWE.5.9_1`) | Name variant | 37 | No |
| 42 Kadoma Urban | Mash West | Kadoma (`ZWE.6.3_1`) | Remove suffix | 72 | No |
| 44 Kariba Urban | Mash West | Kariba (`ZWE.6.4_1`) | Remove suffix | 22 | Yes |
| 46 Kwekwe Rural; 47 Kwekwe Urban | Midlands | Kwekwe (`ZWE.10.5_1`) | Remove suffix | 218 | Yes |
| 51 Mangwe | Mat South | Mangwe (South) (`ZWE.9.5_1`) | Name variant | 48 | No |
| 54 Marondera Rural | Mash East | Marondera (`ZWE.5.3_1`) | Remove suffix | 72 | Yes |
| 55 Masvingo Rural; 56 Masvingo Urban | Masvingo | Masvingo (`ZWE.7.5_1`) | Remove suffix | 111 | Yes |
| 62 Mt Darwin | Mash Central | Mount Darwin (`ZWE.4.5_1`) | Name variant | 137 | No |
| 65 Mutare Rural; 66 Mutare Urban | Manicaland | Mutare (`ZWE.3.5_1`) | Remove suffix | 444 | Yes |
| 81 Shurugwi Rural; 82 Shurugwi Urban | Midlands | Shurugwi (`ZWE.10.7_1`) | Remove suffix | 66 | Yes |
| 91 Zvishavane Rural | Midlands | Zvishavane (`ZWE.10.8_1`) | Remove suffix | 38 | Yes |

### Gokwe clarification — not part of the increase to 95.7%

The RMD marks all three Gokwe labels `*check on combining*`, but the current coverage
calculation does **not** combine them. Gokwe North and Gokwe South already have separate,
direct GADM matches. Gokwe Centre remains unresolved and contributes none of the proposed
95.7% coverage.

| Clean CSV `admin2` | Survey name | Survey province | Current GADM 3.6 status |
|---:|---|---|---|
| 25 | Gokwe Centre | Midlands | Unresolved; no GADM 3.6 ADM2 named Gokwe Centre |
| 26 | Gokwe North | Midlands | Direct: Gokwe North (`ZWE.10.2_1`) |
| 27 | Gokwe South | Midlands | Direct: Gokwe South (`ZWE.10.3_1`) |

## 4. Areas still unresolved

Twelve survey areas remain without a defensible local GADM 3.6 match, covering **373
respondents (4.3%)**:

| Survey code | Survey area | ADM1 | Respondents |
|---:|---|---|---:|
| 16 | Chinhoyi | Mash West | 46 |
| 25 | Gokwe Centre | Midlands | 27 |
| 45 | Karoi | Mash West | 16 |
| 60 | Mbire | Mash Central | 67 |
| 61 | Mhondoro Ngezi | Mash West | 43 |
| 71 | Norton | Mash West | 19 |
| 73 | Plumtree | Mat South | 8 |
| 74 | Redcliff | Midlands | 32 |
| 75 | Rusape | Manicaland | 24 |
| 77 | Ruwa | Mash East | 27 |
| 78 | Sanyati | Mash West | 47 |
| 87 | Vic Falls | Mat North | 17 |

These may reflect municipalities or local authorities nested in differently named
districts, or a taxonomy/granularity difference between the survey and GADM 3.6. The local
files do not establish the target GADM polygon.
