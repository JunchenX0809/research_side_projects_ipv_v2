"""Boundary loading and chunking for standalone AOD jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.aod.manifest import AodJob
from utils.gadm_boundaries import (
    normalize_gadm_level1_features,
    normalize_gadm_level2_features,
)

DEFAULT_CHUNK_SIZE = 40
DEFAULT_CHUNK_MAX_BYTES = 5_000_000


def _boundary_path(job: AodJob, level: int) -> Path:
    suffix = "json" if job.boundary_format == "geojson" else "shp"
    return job.boundary_dir / f"gadm{job.gadm_version}_{job.iso3}_{level}.{suffix}"


def _raw_features(path: Path, boundary_format: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Boundary file not found: {path}")
    if boundary_format == "geojson":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        import geopandas as gpd

        data = json.loads(gpd.read_file(path).to_json())
    features = data.get("features")
    if not isinstance(features, list):
        raise ValueError(f"Expected a FeatureCollection in {path}")
    return features


def _property(props: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = props.get(name)
        if value is not None:
            return value
    return None


def load_boundary_features(job: AodJob) -> list[dict[str, Any]]:
    """Load and normalize the job's explicitly configured GADM boundaries."""
    adm1_raw = _raw_features(_boundary_path(job, 1), job.boundary_format)
    if job.admin_level == 1:
        features = normalize_gadm_level1_features(adm1_raw)
    else:
        adm1_ids: dict[str, str] = {}
        for feature in adm1_raw:
            props = feature.get("properties") or {}
            name = _property(props, "NAME_1")
            gid = _property(props, "ID_1", "GID_1")
            if name is not None and gid is not None:
                adm1_ids[str(name)] = str(gid)
        adm2_raw = _raw_features(_boundary_path(job, 2), job.boundary_format)
        features = normalize_gadm_level2_features(adm2_raw, adm1_ids=adm1_ids)

    if len(features) != job.expected_units:
        raise ValueError(
            f"{job.job_id}: manifest expects {job.expected_units} boundaries; "
            f"loaded {len(features)}"
        )
    gid_key = f"ADM{job.admin_level}_CODE"
    gids = [str((feature.get("properties") or {}).get(gid_key)) for feature in features]
    if len(gids) != len(set(gids)):
        raise ValueError(f"{job.job_id}: duplicate normalized {gid_key} values")
    return features


def feature_chunks(
    features: list[dict[str, Any]],
    *,
    max_count: int = DEFAULT_CHUNK_SIZE,
    max_bytes: int = DEFAULT_CHUNK_MAX_BYTES,
) -> list[list[dict[str, Any]]]:
    """Keep inline Earth Engine boundary requests below count and byte limits."""
    if not features:
        raise ValueError("At least one boundary feature is required")
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    for feature in features:
        feature_bytes = len(json.dumps(feature, separators=(",", ":")))
        if current and (
            len(current) >= max_count or current_bytes + feature_bytes > max_bytes
        ):
            chunks.append(current)
            current = []
            current_bytes = 0
        current.append(feature)
        current_bytes += feature_bytes
    if current:
        chunks.append(current)
    return chunks
