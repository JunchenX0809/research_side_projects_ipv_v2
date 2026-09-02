#!/usr/bin/env python3
"""Compare approved Lesotho district labels to GADM 3.6 ADM1 names / codes.

Mirrors ``scripts/moldova_reg_gadm_match.py``. Lesotho has no GADM ADM2, and the
input labels represent the 10 districts (ADM1), so the result is a district ->
GADM ``ID_1`` crosswalk. The input must be a non-sensitive CSV containing only
the distinct geography labels approved for linkage.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from utils.gadm_boundaries import load_gadm_geojson
from utils.repo_paths import find_repo_root


def _norm(s: str) -> str:
    """Loose match key: lowercase, strip accents/punctuation."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    return re.sub(r"[^a-z0-9]", "", s)


# Source spellings that do not normalize-match GADM (same district, alternate spelling)
_DISTRICT_MANUAL: dict[str, str] = {
    "bothabotha": "Butha-Buthe",  # "Botha-Botha" == GADM "Butha-Buthe" (LSO.2_1)
}

_DISTRICT_NOTES: dict[str, str] = {
    "bothabotha": "'Botha-Botha' is an alternate spelling of GADM 'Butha-Buthe'.",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--labels-csv",
        required=True,
        type=Path,
        help="Non-sensitive CSV containing distinct approved geography labels.",
    )
    parser.add_argument("--label-column", default="District")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    root = find_repo_root()
    labels_csv = args.labels_csv.expanduser().resolve()
    if not labels_csv.is_file():
        raise SystemExit(f"Missing labels CSV: {labels_csv}")
    df = pd.read_csv(labels_csv, dtype=str, usecols=[args.label_column])
    labels = df[args.label_column].dropna().str.strip()
    dist_vals = sorted(labels.loc[labels.ne("")].unique())
    print(f"Approved district labels: {len(dist_vals)} distinct values\n")

    adm1 = load_gadm_geojson("LSO", 1, version="36", root=root)
    gadm = [
        (str(f["properties"].get("NAME_1") or ""), str(f["properties"].get("ID_1") or ""))
        for f in adm1["features"]
    ]
    gadm = [(n, gid) for n, gid in gadm if n]
    name_to_gid = {n: gid for n, gid in gadm}
    gadm_names = sorted(name_to_gid)
    print(f"GADM 3.6 ADM1: {len(gadm_names)} polygons")
    for n in gadm_names:
        print(f"  {n} ({name_to_gid[n]})")
    print()

    gadm_by_norm = {_norm(n): n for n in gadm_names}
    exact: list[tuple[str, str]] = []
    fuzzy: list[tuple[str, str]] = []
    unmatched: list[str] = []

    for d in dist_vals:
        key = _norm(d)
        if key in gadm_by_norm:
            exact.append((d, gadm_by_norm[key]))
            continue
        manual = _DISTRICT_MANUAL.get(key)
        if manual and manual in name_to_gid:
            fuzzy.append((d, manual))
            continue
        unmatched.append(d)

    print(f"Exact normalized matches: {len(exact)}")
    print(f"Manual / spelling matches: {len(fuzzy)}")
    for d, g in fuzzy:
        print(f"  District={d!r} -> GADM {g!r}")
    if unmatched:
        print(f"\nUnmatched District ({len(unmatched)}): {unmatched}")

    matched = {g for _, g in exact} | {g for _, g in fuzzy}
    extra = [n for n in gadm_names if n not in matched]
    if extra:
        print(f"\nGADM ADM1 with no source district match ({len(extra)}): {extra}")

    def _row(d: str, g: str, match_type: str) -> dict[str, str]:
        return {
            "district": d,
            "gadm_name_1": g,
            "gadm_id_1": name_to_gid.get(g, ""),
            "match_type": match_type,
            "notes": _DISTRICT_NOTES.get(_norm(d), ""),
        }

    rows = [_row(d, g, "exact") for d, g in exact]
    rows += [_row(d, g, "manual") for d, g in fuzzy]
    rows += [_row(d, "", "unmatched") for d in unmatched]

    out = args.output or (
        root / "data" / "processed" / "lesotho_district_to_gadm36_adm1.csv"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values("district").to_csv(out, index=False)
    print(f"\nWrote crosswalk: {out}")


if __name__ == "__main__":
    main()
