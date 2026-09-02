"""AOD exposure-window dates, matching the repository's shipped output convention."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from utils.vacs_survey_time import (
    add_parsed_field_dates,
    exposure_window_inclusive_before_field_start,
    field_dates_as_python_dates,
    get_country_wave_row,
    load_survey_time_table,
    resolve_vacs_survey_time_csv,
)

ALLOWED_DATE_FLAGS = frozenset(
    {
        "range_ok",
        "single_day",
        "month_year_range_ok",
        "month_pair_year_ok",
        "month_abbr_year_ok",
        "month_only_year_ok",
        "month_name_pair_manual",
    }
)


def resolve_exposure_window(repo_root: Path, country_wave: str) -> tuple[date, date]:
    """Resolve the exact inclusive one-year pre-fieldwork interval."""
    survey = add_parsed_field_dates(
        load_survey_time_table(resolve_vacs_survey_time_csv(repo_root))
    )
    row = get_country_wave_row(survey, country_wave)
    flag = str(row.get("date_parse_flag", ""))
    if flag not in ALLOWED_DATE_FLAGS:
        raise ValueError(
            f"{country_wave!r}: date_parse_flag={flag!r}; survey date requires review"
        )
    field_start, _ = field_dates_as_python_dates(row)
    return exposure_window_inclusive_before_field_start(field_start)


def complete_calendar_months(
    exposure_start: date, exposure_end: date
) -> pd.DataFrame:
    """Return 12 month-long slices anchored on ``exposure_start``'s day.

    ``month_end`` is exclusive, matching Earth Engine's date-filter convention.
    The inclusive exposure interval must end one day before the twelfth slice's
    exclusive boundary.
    """
    starts = [
        (pd.Timestamp(exposure_start) + pd.DateOffset(months=offset)).date()
        for offset in range(12)
    ]
    ends = [
        (pd.Timestamp(exposure_start) + pd.DateOffset(months=offset)).date()
        for offset in range(1, 13)
    ]
    expected_end = ends[-1] - pd.Timedelta(days=1)
    if expected_end != exposure_end:
        raise ValueError(
            f"Expected a 12-month inclusive interval ending {expected_end}; "
            f"got {exposure_start}..{exposure_end}"
        )
    return pd.DataFrame(
        {
            "month_start": starts,
            "month_end": ends,
        }
    )
