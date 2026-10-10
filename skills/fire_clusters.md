# Fire-cluster scripts

These scripts count connected VNP64A1 **burn patches**. The count is a grouping measure, not a verified ignition count.

| Script | High-level goal | Main technical tools |
| --- | --- | --- |
| [`build_zambia_viirs_fire_clusters_v1.py`](../scripts/fire_clusters/build_zambia_viirs_fire_clusters_v1.py) | Build the Zambia demonstration: join touching burned pixels with burn dates at most 5 days apart, then count patch activity by district and month. | Earth Engine, GeoPandas, NumPy/SciPy for raster and connected-patch work. |
| [`build_vacs_viirs_fire_clusters_v1.py`](../scripts/fire_clusters/build_vacs_viirs_fire_clusters_v1.py) | Apply the Zambia patch rules to one country and survey period, producing an area-month panel. | Reuses the Zambia builder; Earth Engine, GeoPandas, NumPy, Shapely. |
| [`run_vacs_viirs_fire_cluster_waves_v1.py`](../scripts/fire_clusters/run_vacs_viirs_fire_cluster_waves_v1.py) | Run the approved queue of countries and survey periods, recording each result. | Python CSV and subprocess utilities; calls the burned-area and VACS cluster modules. |
| [`audit_vacs_viirs_fire_cluster_waves_v1.py`](../scripts/fire_clusters/audit_vacs_viirs_fire_cluster_waves_v1.py) | Independently check the finished VACS cluster panels. | pandas and NumPy check dates, units, rows, and metric values. |
| [`build_indonesia_viirs_clusters_v3.py`](../scripts/fire_clusters/build_indonesia_viirs_clusters_v3.py) | Add cluster counts to Indonesia's existing v2 VIIRS files to create v3. | Reuses VACS/Zambia patch logic; `utils.indonesia_viirs`, GeoPandas, NumPy, Shapely. |
| [`__init__.py`](../scripts/fire_clusters/__init__.py) | Let Python import this folder as a package. | Empty marker; no processing. |
