"""Load and parse ``VACS_survey_time.csv`` (same rules as ``satellite_data_exp_v1.ipynb`` §1–§2)."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

# Logic mirrored from exposure_notebooks/satellite_data_exp_v1.ipynb (§2 parse cell).


RANGE_SPLIT = re.compile(r"\s*(?:-|–|—|to)\s*", re.I)
MONTH_NAME = "january|february|march|april|may|june|july|august|september|october|november|december"
MONTH_PAIR_YEAR = re.compile(rf"(?i)^\s*({MONTH_NAME})\s*[-–—]\s*({MONTH_NAME})\s+(\d{{4}})\s*$")
MONTH_YEAR_RANGE = re.compile(
    rf"(?i)^\s*({MONTH_NAME})\s+(\d{{4}})\s*[-–—]\s*({MONTH_NAME})\s+(\d{{4}})\s*$"
)
MONTH_ABBR_YEAR = re.compile(r"(?i)^\s*([a-z]{3,9})\s*[-/]\s*(\d{2})\s*$")
MONTH_ONLY_YEAR = re.compile(rf"(?i)^\s*({MONTH_NAME})\s+(\d{{4}})\s*$")

# GADM boundary version vs end of 12-month pre-fieldwork exposure window (gadm.org guidance).
GADM_VERSION_END_36 = date(2019, 3, 31)
GADM_VERSION_START_40 = date(2019, 4, 1)
GADM_VERSION_END_40 = date(2022, 2, 28)
GADM_VERSION_START_41 = date(2022, 3, 1)


def resolve_vacs_survey_time_csv(repo_root: Path) -> Path:
    """Prefer tracked ``data/raw/`` copy; fall back to ``skills/`` if present locally."""
    candidates = [
        repo_root / "data" / "raw" / "VACS_survey_time.csv",
        repo_root / "skills" / "VACS_survey_time.csv",
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError(
        "VACS_survey_time.csv not found. Expected one of:\n  "
        + "\n  ".join(str(c) for c in candidates)
    )


def load_survey_time_table(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    raw.columns = [c.strip() if isinstance(c, str) else c for c in raw.columns]
    if "Unnamed: 2" in raw.columns:
        raw = raw.rename(columns={"Unnamed: 2": "notes"})
    elif len(raw.columns) == 2:
        raw["notes"] = ""
    return raw.rename(
        columns={
            "Country": "country_wave",
            "Date": "field_period_raw",
        }
    ).copy()


def split_range(s: str) -> tuple[str | None, str | None]:
    s = (s or "").strip()
    if not s:
        return None, None
    parts = [p.strip() for p in RANGE_SPLIT.split(s, maxsplit=1)]
    if len(parts) == 2:
        return parts[0], parts[1]
    return s, None


def _month_number(name: str) -> int:
    key = name.strip().lower()
    for i, full in enumerate(calendar.month_name):
        if full and full.lower() == key:
            return i
    for i, abbr in enumerate(calendar.month_abbr):
        if abbr and abbr.lower() == key[:3]:
            return i
    raise ValueError(f"Unknown month name: {name!r}")


def _month_bounds(month_name: str, year: int) -> tuple[date, date]:
    m = _month_number(month_name)
    last = calendar.monthrange(year, m)[1]
    return date(year, m, 1), date(year, m, last)


def parse_month_year_range(raw_txt: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """e.g. ``October 2018 – February 2019``."""
    m = MONTH_YEAR_RANGE.match(raw_txt.strip())
    if not m:
        return None
    start = _month_bounds(m.group(1), int(m.group(2)))[0]
    end = _month_bounds(m.group(3), int(m.group(4)))[1]
    return pd.Timestamp(start), pd.Timestamp(end)


def parse_month_pair_single_year(raw_txt: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """e.g. ``June–September 2018``, ``September–October 2013``."""
    m = MONTH_PAIR_YEAR.match(raw_txt.strip())
    if not m:
        return None
    year = int(m.group(3))
    start = _month_bounds(m.group(1), year)[0]
    end = _month_bounds(m.group(2), year)[1]
    return pd.Timestamp(start), pd.Timestamp(end)


def parse_month_abbr_year(raw_txt: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """e.g. ``Jun-17`` → full month June 2017."""
    m = MONTH_ABBR_YEAR.match(raw_txt.strip())
    if not m:
        return None
    ts = pd.to_datetime(f"{m.group(1)}-{m.group(2)}", format="%b-%y", errors="coerce")
    if pd.isna(ts):
        return None
    y, mo = int(ts.year), int(ts.month)
    start = date(y, mo, 1)
    end = date(y, mo, calendar.monthrange(y, mo)[1])
    return pd.Timestamp(start), pd.Timestamp(end)


def recommend_gadm_version(exposure_end: date) -> str:
    """Recommend GADM release from exposure-window end (12 months before fieldwork).

    Rules (gadm.org version guidance, summarized):
    - ``3.6`` if exposure ends on or before 2019-03
    - ``4.0`` if exposure ends 2019-04 through 2022-02
    - ``4.1`` if exposure ends 2022-03 or later
    """
    if exposure_end <= GADM_VERSION_END_36:
        return "3.6"
    if exposure_end >= GADM_VERSION_START_41:
        return "4.1"
    if GADM_VERSION_START_40 <= exposure_end <= GADM_VERSION_END_40:
        return "4.0"
    return ""


def try_parse_date(txt: str | None) -> pd.Timestamp:
    if txt is None or not str(txt).strip():
        return pd.NaT
    t = pd.to_datetime(txt, errors="coerce", dayfirst=False)
    if pd.isna(t):
        t = pd.to_datetime(txt, errors="coerce", dayfirst=True)
    return t


def add_parsed_field_dates(survey_time: pd.DataFrame) -> pd.DataFrame:
    """Add ``field_start``, ``field_end``, ``date_parse_flag`` (mutates a copy)."""
    out = survey_time.copy()
    starts: list[pd.Timestamp] = []
    ends: list[pd.Timestamp] = []
    parse_flag: list[str] = []

    for _, row in out.iterrows():
        raw_txt = str(row.get("field_period_raw", "")).strip()
        low = raw_txt.lower()
        if not raw_txt:
            starts.append(pd.NaT)
            ends.append(pd.NaT)
            parse_flag.append("empty")
        elif (parsed := parse_month_year_range(raw_txt)) is not None:
            starts.append(parsed[0])
            ends.append(parsed[1])
            parse_flag.append("month_year_range_ok")
        elif (parsed := parse_month_pair_single_year(raw_txt)) is not None:
            starts.append(parsed[0])
            ends.append(parsed[1])
            parse_flag.append("month_pair_year_ok")
        elif (parsed := parse_month_abbr_year(raw_txt)) is not None:
            starts.append(parsed[0])
            ends.append(parsed[1])
            parse_flag.append("month_abbr_year_ok")
        elif (moy := MONTH_ONLY_YEAR.match(raw_txt.strip())) is not None:
            start, end = _month_bounds(moy.group(1), int(moy.group(2)))
            starts.append(pd.Timestamp(start))
            ends.append(pd.Timestamp(end))
            parse_flag.append("month_only_year_ok")
        else:
            a, b = split_range(raw_txt)
            ts_a, ts_b = try_parse_date(a), try_parse_date(b)
            if b is None and pd.notna(ts_a):
                starts.append(ts_a)
                ends.append(ts_a)
                parse_flag.append("single_day")
            elif pd.notna(ts_a) and pd.notna(ts_b):
                starts.append(min(ts_a, ts_b))
                ends.append(max(ts_a, ts_b))
                parse_flag.append("range_ok")
            else:
                starts.append(ts_a)
                ends.append(ts_b)
                parse_flag.append("needs_review")

    out["field_start"] = starts
    out["field_end"] = ends
    out["date_parse_flag"] = parse_flag

    BAD_YEAR = 1900

    def _year(ts: pd.Timestamp) -> int | None:
        if pd.isna(ts):
            return None
        return int(ts.year)

    for i in range(len(out)):
        ys, ye = _year(out.at[i, "field_start"]), _year(out.at[i, "field_end"])
        if ys is not None and ys < BAD_YEAR:
            out.at[i, "field_start"] = pd.NaT
            out.at[i, "field_end"] = pd.NaT
            out.at[i, "date_parse_flag"] = "month_name_pair_manual"
        elif ye is not None and ye < BAD_YEAR:
            out.at[i, "field_start"] = pd.NaT
            out.at[i, "field_end"] = pd.NaT
            out.at[i, "date_parse_flag"] = "month_name_pair_manual"

    return out


def get_country_wave_row(survey_time_parsed: pd.DataFrame, country_wave: str) -> pd.Series:
    m = survey_time_parsed["country_wave"] == country_wave
    if not m.any():
        raise KeyError(f"No row for country_wave={country_wave!r}")
    return survey_time_parsed.loc[m].iloc[0]


def field_dates_as_python_dates(row: pd.Series) -> tuple[date, date]:
    """Return ``(field_start, field_end)`` as ``datetime.date`` (raises if NaT)."""
    fs, fe = row["field_start"], row["field_end"]
    if pd.isna(fs) or pd.isna(fe):
        raise ValueError(
            f"Missing parsed dates for {row.get('country_wave')!r} "
            f"(date_parse_flag={row.get('date_parse_flag')!r})."
        )
    return fs.date(), fe.date()


def exposure_window_inclusive_before_field_start(
    field_start: date,
    *,
    years_before: int = 1,
) -> tuple[date, date]:
    """
    Match Zambia fire v3 convention: inclusive window ending the day before first field day.

    ``exposure_start`` = ``field_start`` minus ``years_before`` (calendar-safe via year arithmetic);
    ``exposure_end`` = ``field_start`` minus one day.
    """
    exposure_end = field_start - timedelta(days=1)
    exposure_start = date(field_start.year - years_before, field_start.month, field_start.day)
    return exposure_start, exposure_end


def next_day(d: date) -> date:
    return d + timedelta(days=1)


def months_df_inclusive_range(exposure_start: date, exposure_end: date) -> pd.DataFrame:
    """Month-long slices anchored on ``exposure_start`` within an inclusive interval.

    The returned ``month_end`` is inclusive, while ``filter_end_exclusive`` is the
    corresponding Earth Engine filter boundary.  Advancing each boundary from the
    original anchor (rather than from the preceding slice) avoids calendar-month
    drift when a day does not exist in a shorter month.
    """
    if exposure_end < exposure_start:
        raise ValueError(
            f"exposure_end {exposure_end} precedes exposure_start {exposure_start}"
        )

    rows: list[dict[str, Any]] = []
    interval_end_exclusive = next_day(exposure_end)
    offset = 0
    while True:
        slice_start = (
            pd.Timestamp(exposure_start) + pd.DateOffset(months=offset)
        ).date()
        if slice_start >= interval_end_exclusive:
            break
        next_anchor = (
            pd.Timestamp(exposure_start) + pd.DateOffset(months=offset + 1)
        ).date()
        filter_end_exclusive = min(next_anchor, interval_end_exclusive)
        rows.append(
            {
                "month_start": slice_start,
                "month_end": filter_end_exclusive - timedelta(days=1),
                "filter_end_exclusive": filter_end_exclusive,
            }
        )
        offset += 1
    return pd.DataFrame(rows)


def add_gadm_version_column(
    survey_time_parsed: pd.DataFrame,
    *,
    years_before: int = 1,
) -> pd.DataFrame:
    """Add ``exposure_end`` and ``gadm_version`` from parsed field dates."""
    out = survey_time_parsed.copy()
    exposure_ends: list[date | None] = []
    gadm_versions: list[str] = []

    for _, row in out.iterrows():
        if row["date_parse_flag"] not in (
            "range_ok",
            "single_day",
            "month_year_range_ok",
            "month_pair_year_ok",
            "month_abbr_year_ok",
            "month_only_year_ok",
        ):
            exposure_ends.append(None)
            gadm_versions.append("")
            continue
        try:
            fs, _ = field_dates_as_python_dates(row)
        except ValueError:
            exposure_ends.append(None)
            gadm_versions.append("")
            continue
        _, exp_end = exposure_window_inclusive_before_field_start(fs, years_before=years_before)
        exposure_ends.append(exp_end)
        gadm_versions.append(recommend_gadm_version(exp_end))

    out["exposure_end"] = exposure_ends
    out["gadm_version"] = gadm_versions
    return out


def build_survey_time_gadm_version_table(path: Path) -> pd.DataFrame:
    """Load survey CSV, parse dates, assign GADM version; return wide audit frame."""
    raw = load_survey_time_table(path)
    parsed = add_parsed_field_dates(raw)
    return add_gadm_version_column(parsed)


def write_survey_time_gadm_version_csv(
    in_path: Path,
    out_path: Path,
) -> pd.DataFrame:
    """
    Write deliverable with original columns plus ``GADM_version``.

    Matches ``VACS_survey_time.csv`` layout: ``Country``, ``Date``, ``notes``, plus new column.
    """
    full = build_survey_time_gadm_version_table(in_path)
    deliverable = pd.DataFrame(
        {
            "Country": full["country_wave"],
            "Date": full["field_period_raw"],
            "notes": full.get("notes", ""),
            "GADM_version": full["gadm_version"],
        }
    )
    deliverable.to_csv(out_path, index=False)
    return full
