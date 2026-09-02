"""Resolve the repository root for notebooks and scripts."""

from __future__ import annotations

import sys
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """
    Return the repo root containing ``data/raw/``.

    Works when the process cwd is the repo root, ``exposure_notebooks/``,
    ``covariates_notebooks/``, legacy ``notebooks/``, or a deeper path under
    the repo (walks parents).
    """
    cwd = (start or Path.cwd()).resolve()
    if cwd.name in ("exposure_notebooks", "covariates_notebooks"):
        parent = cwd.parent
        if (parent / "data" / "raw").is_dir():
            return parent
    if cwd.name == "notebooks":
        parent = cwd.parent
        if (parent / "data" / "raw").is_dir():
            return parent
    for d in [cwd, *cwd.parents][:24]:
        if (d / "utils" / "repo_paths.py").is_file() and (d / "data" / "raw").is_dir():
            return d
    for d in [cwd, *cwd.parents][:24]:
        if (d / "gee_zambia").is_dir() and (d / "data" / "raw").is_dir():
            return d
    return cwd


def ensure_repo_on_path(start: Path | None = None) -> Path:
    """Insert repo root on ``sys.path`` if missing; return ``find_repo_root()``."""
    root = find_repo_root(start)
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)
    return root
