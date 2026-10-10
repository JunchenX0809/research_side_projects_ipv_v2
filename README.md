# VACS satellite exposure and linkage

Code to build administrative satellite exposure measures and link them to VACS respondents using approved survey dates and geography.

## Workflow at a glance

For each country and survey period, the survey window and selected GADM geography define the exposure keys. `scripts/` runs the workflows, `utils/` supplies shared calculations, and `config/` records product and run choices.

**Terminology:** Some script and config names use `wave` to mean one country and survey period, such as Eswatini 2007 or Eswatini 2022. This README uses “country and survey period” for that unit of work.

```mermaid
flowchart TB
  PERIOD["Country and survey period: 12-month window + ADM level + GADM version"]
  PERIOD --> MEASURES["Generate or receive exposure tables"]
  MEASURES --> PANEL["GADM unit × month measures"]
  PANEL --> INPUTS["Join inputs: product registry + geography crosswalk + VACS outcomes"]
  INPUTS --> BUILD["Respondent linkage: validate keys, derive window summaries, join respondents"]
  BUILD --> OUTPUTS["Linked respondents + monthly panel + provenance logs"]
  OUTPUTS --> VERIFY["Verify linked output"]
```

## Exposure measures

FRP means fire radiative power; AOD means aerosol optical depth. The fire-cluster branch counts connected VNP64A1 burn patches, not verified ignitions.

```mermaid
flowchart TB
  subgraph MODIS["MODIS fire measures"]
    direction LR
    M_INPUT["MODIS products + FIRMS"] --> M_SCRIPT["fire_exposure/"] --> M_OUTPUT["Fire count, FRP, burned area"]
  end
  subgraph VIIRS["VIIRS fire measures"]
    direction LR
    V_INPUT["VNP14A1 + VNP64A1"] --> V_SCRIPT["fire_exposure/"] --> V_OUTPUT["Unique fire count, FRP, burned area"]
  end
  subgraph PATCHES["VIIRS burn patches"]
    direction LR
    P_INPUT["VNP64A1 burn dates"] --> P_SCRIPT["fire_clusters/"] --> P_OUTPUT["Patch counts"]
  end
  subgraph AOD["Air quality"]
    direction LR
    A_INPUT["MAIAC AOD"] --> A_SCRIPT["aod_exposure/"] --> A_OUTPUT["AOD measures"]
  end
```

Each branch produces administrative-month exposure tables.

## Respondent linkage

For each country and survey period, `config/wave_exposure_products.csv` selects the exposure products. The linked file keeps the source respondents and records join status.

```mermaid
flowchart LR
  GEO["Survey geography + GADM crosswalks"] --> MASTER["VACS-GADM master linkage"]
  MASTER --> INPUTS["Linkage inputs: outcomes, exposure tables, product registry"]
  INPUTS --> BUILD["build_wave_exposure_demo"]
  BUILD --> DEMO["Linked files + logs"]
  DEMO --> VERIFY["verify_wave_exposure_demo"]
```

## Review guides

| Topic | Guide |
| --- | --- |
| Folder maps | [Script entry points](scripts/README.md), [utility map](utils/README.md), [guide index](skills/README.md) |
| Fire metrics | [Fire exposure](skills/fire_exposure.md), [fire clusters](skills/fire_clusters.md), [country demos](skills/country_demos.md) |
| AOD | [AOD exposure](skills/aod_exposure.md), [AOD utilities](skills/utils_aod.md) |
| Geography and linkage | [Admin geography](skills/admin_geography.md), [respondent linkage](skills/respondent_linkage.md) |
| Shared code and checks | [Shared utilities](skills/utils_shared.md), [quality checks](skills/quality_checks.md) |

`exposure_notebooks/` contains exploratory examples; `gee_zambia/` holds the Hansen forest-change pilot.

## Running locally

Use Python 3.11 or newer, install `requirements.txt`, and configure Earth Engine access. Run entry points from the repository root as `.venv/bin/python -m scripts.<folder>.<module>`. Study inputs and generated data belong in local paths; credentials belong in the environment, not in source files.

`build_vacs_gadm_linkage_workbook.py` writes outputs at import time, including when called with `--help`. Its guide describes its role; inspect the script before running it.
