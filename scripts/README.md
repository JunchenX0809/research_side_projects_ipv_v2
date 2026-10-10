# Script entry points

Run from the repository root with `.venv/bin/python -m scripts.<folder>.<script_name>`.
Shared functions are in `utils/`.
The [repository overview](../README.md) shows how these roles connect for one country and survey period.

```mermaid
flowchart TB
  subgraph PREP["Prepare geography"]
    direction LR
    GEO["admin_geography/"] --> GEO_ROLE["GADM areas, survey dates, geography matches"]
  end
  subgraph MEASURES["Build exposure measures"]
    direction LR
    FIRE["fire_exposure/"] --> FIRE_ROLE["Fire count, FRP, burned area"]
    CLUSTER["fire_clusters/"] --> CLUSTER_ROLE["VIIRS burn-patch counts"]
    AOD["aod_exposure/"] --> AOD_ROLE["MAIAC AOD"]
  end
  subgraph LINKAGE["Link outcomes"]
    direction LR
    LINK["respondent_linkage/"] --> LINK_ROLE["Attach measures to VACS respondents"]
  end
  subgraph REVIEW["Check and demonstrate"]
    direction LR
    QUALITY["quality_checks/"] --> AUDIT["Audit measures and compare sensors"]
    DEMOS["country_demos/"] --> CASES["Run scoped country examples"]
  end
```

| Folder | Purpose |
| --- | --- |
| `admin_geography/` | Prepare GADM boundaries, survey timing, and geography matches. |
| `fire_exposure/` | Export and assemble MODIS, FIRMS, and VIIRS exposure tables. |
| `aod_exposure/` | Export and check MAIAC AOD tables. |
| `fire_clusters/` | Build and audit VIIRS burn-patch counts. |
| `respondent_linkage/` | Map VACS geography and join or verify respondent exposures. |
| `quality_checks/` | Check exposure summaries and compare sensors. |
| `country_demos/` | Run scoped Uganda and Zimbabwe examples. |

`build_vacs_gadm_linkage_workbook.py` runs at import time; invoking it with `--help` also writes its workbook. Review the source before running it.
