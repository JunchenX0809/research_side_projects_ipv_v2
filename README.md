# VACS satellite exposure and linkage

Code to build administrative satellite exposure measures and link them to VACS respondents using approved survey dates and geography.

## How the code fits together

`scripts/` contains entry points, `utils/` contains reusable calculations, and `config/` records run and product choices.

```mermaid
flowchart LR
  subgraph Scripts["scripts/"]
    GEO["admin_geography"]
    FIRE["fire_exposure"]
    CLUSTER["fire_clusters"]
    AOD["aod_exposure"]
    LINK["respondent_linkage"]
  end
  subgraph Utils["utils/"]
    BOUND["gadm_boundaries"]
    TIME["vacs_survey_time"]
    FIREUTIL["adam_* / gee_fire_zonal / indonesia_viirs"]
    AODUTIL["aod/*"]
  end
  GEO --> BOUND
  GEO --> TIME
  FIRE --> BOUND
  FIRE --> TIME
  FIRE --> FIREUTIL
  CLUSTER --> BOUND
  CLUSTER --> FIREUTIL
  AOD --> AODUTIL
  LINK --> TIME
```

## Exposure measures

FRP means fire radiative power; AOD means aerosol optical depth. The fire-cluster branch counts connected VNP64A1 burn patches, not verified ignitions.

```mermaid
flowchart LR
  MODIS["MODIS products + FIRMS"] -->|"fire count, FRP, burned area"| FIRE["fire_exposure scripts"]
  V14["VIIRS VNP14A1"] -->|"unique fire count, FRP"| FIRE
  V64["VIIRS VNP64A1"] -->|"burned area"| FIRE
  V64 -->|"burn dates"| CLUSTER["fire_clusters scripts"]
  FIRE -.->|"VIIRS unit/month keys"| CLUSTER
  MAIAC["MODIS MAIAC AOD"] --> AOD["aod_exposure scripts"]
  FIRE --> PANEL["Administrative-month exposure tables"]
  CLUSTER --> PANEL
  AOD --> PANEL
```

## Respondent linkage

A wave's exposure products are selected by `config/wave_exposure_products.csv`; the linked file keeps the source respondents and records join status.

```mermaid
flowchart LR
  LABELS["Survey geography"] --> CROSS["GADM crosswalks"]
  CROSS --> WORKBOOK["build_vacs_gadm_linkage_workbook"]
  WORKBOOK --> MASTER["VACS-GADM master linkage"]
  OUTCOME["VACS outcomes"] --> BUILD["build_wave_exposure_demo"]
  MASTER --> BUILD
  REGISTRY["Product registry"] --> BUILD
  PANEL["Administrative-month exposure tables"] --> BUILD
  BUILD --> DEMO["Linked respondents + monthly panel + logs"]
  DEMO --> VERIFY["verify_wave_exposure_demo"]
```

## Review guides

| Topic | Guide |
| --- | --- |
| Script folder map | [Script entry points](scripts/README.md) |
| Fire metrics | [Fire exposure](skills/fire_exposure.md), [fire clusters](skills/fire_clusters.md), [country demos](skills/country_demos.md) |
| AOD | [AOD exposure](skills/aod_exposure.md), [AOD utilities](skills/utils_aod.md) |
| Geography and linkage | [Admin geography](skills/admin_geography.md), [respondent linkage](skills/respondent_linkage.md) |
| Shared code and checks | [Shared utilities](skills/utils_shared.md), [quality checks](skills/quality_checks.md) |

`exposure_notebooks/` contains exploratory examples; `gee_zambia/` holds the Hansen forest-change pilot.

## Running locally

Use Python 3.11 or newer, install `requirements.txt`, and configure Earth Engine access. Run entry points from the repository root as `.venv/bin/python -m scripts.<folder>.<module>`. Study inputs and generated data belong in local paths; credentials belong in the environment, not in source files.

`build_vacs_gadm_linkage_workbook.py` writes outputs at import time, including when called with `--help`. Its guide describes its role; inspect the script before running it.
