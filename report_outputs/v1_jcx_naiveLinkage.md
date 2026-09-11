# VACS survey → GADM exposure linkage: status checkpoint (v1)

## Headline

| Bucket | Count | Waves |
| ------ | ----: | ----- |
| Completed | 18 | Nigeria 2014, Zambia 2014, Haiti 2012, Rwanda 2016, El Salvador 2018, Honduras 2017, Cambodia 2013, Colombia 2018 (both levels or ADM2 100%); Côte d'Ivoire 2019, Malawi 2013 (ADM2 100%); Kenya 2019, Eswatini 2007, Eswatini 2022, Lesotho 2018, Moldova 2013, Namibia 2019, Tanzania 2024, Mozambique 2019 (ADM1 100%, ADM2 n/a or absent) |
| Partial | 1 | Zimbabwe 2017 (ADM2 99.9%, Plumtree straddles two GADM units) |
| Discussion needed | 2 | Kenya 2010 (county to province aggregation); Uganda 2015 (naming solved; GADM is ~13 years older and one level offset, re-slot proposed) |
| Not completed | 0 | every wave has been attempted |
| Data issue | 3 | Côte d'Ivoire: cleaned data frame is keyed `year` = 2019, but the survey year is 2018 (codebook and user guide); exposure files already use the correct 2018 window, so only the label is wrong. Haiti: cleaned `admin1` is defective and unusable, 15 of 17 codes are sex-pure because the two PUDs spell `Domaine` differently. **GADM version choice:** versions were picked by release date as a proxy for boundary vintage, but the two do not track each other (GADM 3.6, released 2018, holds ~2002 boundaries for Uganda), so the version should be chosen by comparing each candidate's unit list against the survey's. **Acted on:** Cambodia and Colombia both reach 100% on GADM 4.1 but 87.1% and 97.7% on 3.6, so their exposure files need re-running on 4.1. Uganda was tested and 4.1 is identical to 3.6 |

## What we found

| Prior notes at the level that carries the linkage | Waves | Respondents |
| ------------------------------------------------- | ----: | ----------: |
| Established a usable linkage | 3 | 14,913 (17%) |
| Names only, no ordering | 8 | 39,954 (46%) |
| Nothing usable | 10 | 32,058 (37%) |

The 10 waves with nothing usable absorbed most of the effort. Eight are now
complete: Cambodia, Colombia, Haiti, Honduras, Kenya 2019, Nigeria, Rwanda,
Zambia. Two need a decision from you rather than more research, Kenya 2010 and
Uganda 2015, both because the survey sits at a level coarser than any GADM
layer.

### Waves with names but no ordering

Eight waves listed the right unit names but left the code order open. Official
national sources closed all eight, and seven are complete.

Two produced findings worth knowing. In **Eswatini 2007** the notes assumed the
2007 ordering matched 2022; it does not, and the survey file itself settles it.
In **Malawi** the ordering was recovered from the data's own internal
constraints after both available name lists proved to have gaps.

### Waves the notes already established

Three waves came with a working linkage: Eswatini 2022, Moldova, Namibia. We did
not re-research these. We took the proposed linkage and checked it against the
survey data and the boundary files on both sides.

**All three held.** Two carried a detail the notes could not have known, both on
the boundary side rather than the survey side: GADM has one fewer region than
Namibia's survey, and two Moldovan codes resolve to the same unit. Together
that affects 294 respondents and neither is a linkage error.

---


## Status

| #   | Country       | Wave | Joint   | GADM ver. | ADM1 linkage     | ADM2 in file | ADM2 linkage        | Prior Notes                            | Adm-areas file |
| --- | ------------- | ---- | ------- | --------- | ---------------- | ------------ | ------------------- | -------------------------------------- | -------------- |
| 1   | Cambodia      | 2013 | **yes** | 3.6→4.1   | **found** (100%) | yes          | **found** (100%)    | ADM1 `established` · ADM2 `none`       | `none`         |
| 2   | Colombia      | 2018 | **yes** | 3.6→4.1   | n/a (via ADM2)   | yes          | **found** (100%)    | ADM1 `names only` · ADM2 `none`        | `codes align`  |
| 3   | Côte d'Ivoire | 2019 | **yes** | 3.6       | n/a (via ADM2)   | yes          | **found** (100%)    | ADM1 `names only` · ADM2 `names only`  | `codes align`  |
| 4   | El Salvador   | 2018 | **yes** | 3.6       | n/a (via ADM2)   | yes          | **found** (100%)    | ADM1 `names only` · ADM2 `names only`  | `codes align`  |
| 5   | Eswatini      | 2007 |         | 3.6       | **found** (100%) | yes          | n/a                 | ADM1 `names only` · ADM2 `none`        | `codes align`  |
| 6   | Eswatini      | 2022 |         | 4.1       | **found** (100%) | yes          | n/a                 | ADM1 `established` · ADM2 `none`       | `none`         |
| 7   | Haiti         | 2012 | **yes** | 3.6       | n/a (defective)  | yes          | **found** (100%)    | ADM1 `names only` · ADM2 `none`        | `none`         |
| 8   | Honduras      | 2017 | **yes** | 3.6       | n/a (via ADM2)   | yes          | **found** (100%)    | ADM1 `none` · ADM2 `none`              | `codes differ` |
| 9   | Kenya         | 2010 |         | 3.6       | **discussion**   | **no**       | n/a                 | ADM1 `none` · ADM2 `n/a`               | `codes align`  |
| 10  | Kenya         | 2019 | **yes** | 3.6       | **found** (100%) | yes          | n/a                 | ADM1 `none` · ADM2 `none`              | `codes differ` |
| 11  | Lesotho       | 2018 | **yes** | 3.6       | **found** (100%) | **no**       | n/a                 | ADM1 `names only` · ADM2 `n/a`         | `codes align`  |
| 12  | Malawi        | 2013 |         | 3.6       | n/a (via ADM2)   | yes          | **found** (100%)    | ADM1 `names only` · ADM2 `names only`  | `codes align`  |
| 13  | Moldova       | 2013 |         | 3.6       | **found** (100%) | yes          | n/a                 | ADM1 `established` · ADM2 `names only` | `codes align`  |
| 14  | Mozambique    | 2019 | **yes** | 4.0       | **found** (100%) | **no**       | n/a                 | ADM1 `names only` · ADM2 `n/a`         | `codes differ` |
| 15  | Namibia       | 2019 |         | 3.6       | **found** (100%) | **no**       | n/a                 | ADM1 `established` · ADM2 `n/a`         | `codes align`  |
| 16  | Nigeria       | 2014 | **yes** | 3.6       | **found** (100%) | **no**       | n/a                 | ADM1 `none` · ADM2 `n/a`               | `none`         |
| 17  | Rwanda        | 2016 |         | 3.6       | **found** (100%) | yes          | **found** (100%)    | ADM1 `none` · ADM2 `none`              | `codes align`  |
| 18  | Tanzania      | 2024 | **yes** | 4.1       | **found** (100%) | **no**       | n/a                 | ADM1 `names only` · ADM2 `n/a`         | `codes differ` |
| 19  | Uganda        | 2015 | **yes** | 3.6       | **discussion**   | yes          | **discussion**      | ADM1 `names only` · ADM2 `none`        | `none`         |
| 20  | Zambia        | 2014 |         | 3.6       | **found** (100%) | yes          | **found** (100%)    | ADM1 `none` · ADM2 `none`              | `codes align`  |
| 21  | Zimbabwe      | 2017 | **yes** | 3.6       | **found** (100%) | yes          | **partial** (99.9%) | ADM1 `names only` · ADM2 `names only`  | `codes align`  |

---


---

## Count reconciliation

Survey unit counts against GADM polygon counts. `survey coarser` means exposure must be
aggregated up (Kenya 2010 is the worked example). A match is necessary but not sufficient;
it does not prove the units correspond.

| Country | Wave | Survey ADM1 | GADM ADM1 | ADM1 | Survey ADM2 | GADM ADM2 | ADM2 |
|---|---:|---:|---:|---|---:|---:|---|
| Cambodia | 2013 | 20 | 25 | survey coarser | 16 | 178 | survey coarser |
| Colombia | 2018 | 33 | 32 | survey finer | 58 | 1065 | survey coarser |
| Côte d'Ivoire | 2019 | 6 | 14 | survey coarser | 33 | 33 | **match** |
| El Salvador | 2018 | 14 | 14 | **match** | 22 | 266 | survey coarser |
| Eswatini | 2007 | 4 | 4 | **match** | 40 | 55 | survey coarser |
| Eswatini | 2022 | 4 | 4 | **match** | 353 | 55 | survey finer |
| Haiti | 2012 | 17 | 10 | survey finer | 77 | 41 | survey finer |
| Honduras | 2017 | 16 | 18 | survey coarser | 26 | 298 | survey coarser |
| Kenya | 2010 | 8 | 47 | survey coarser | - | 301 | n/a |
| Kenya | 2019 | 47 | 47 | **match** | 243 | 300 | survey coarser |
| Lesotho | 2018 | 10 | 10 | **match** | - | - | n/a |
| Malawi | 2013 | 3 | 28 | survey coarser | 27 | 256 | survey coarser |
| Moldova | 2013 | 36 | 37 | survey coarser | 132 | - | no exposure |
| Mozambique | 2019 | 10 | 11 | survey coarser | - | 129 | n/a |
| Namibia | 2019 | 14 | 13 | survey finer | - | 107 | n/a |
| Nigeria | 2014 | 37 | 37 | **match** | - | 775 | n/a |
| Rwanda | 2016 | 5 | 5 | **match** | 8 | 30 | survey coarser |
| Tanzania | 2024 | 31 | 31 | **match** | - | 186 | n/a |
| Uganda | 2015 | 4 | 58 | survey coarser | 112 | 166 | survey coarser |
| Zambia | 2014 | 10 | 10 | **match** | 72 | 72 | **match** |
| Zimbabwe | 2017 | 10 | 10 | **match** | 91 | 60 | survey finer |

---

*Status date: 2026-09-08.*