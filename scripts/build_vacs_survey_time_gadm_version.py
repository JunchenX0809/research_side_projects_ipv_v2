#!/usr/bin/env python3
"""Build ``skills/VACS_survey_time_gadm_version.csv`` from ``VACS_survey_time.csv``."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.repo_paths import find_repo_root
from utils.vacs_survey_time import (
    resolve_vacs_survey_time_csv,
    write_survey_time_gadm_version_csv,
)


def main() -> None:
    root = find_repo_root()
    in_path = resolve_vacs_survey_time_csv(root)
    out_path = root / "skills" / "VACS_survey_time_gadm_version.csv"
    full = write_survey_time_gadm_version_csv(in_path, out_path)
    print(f"Wrote {out_path}")
    cols = ["country_wave", "field_period_raw", "date_parse_flag", "exposure_end", "gadm_version"]
    print(full[cols].to_string(index=False))


if __name__ == "__main__":
    main()
