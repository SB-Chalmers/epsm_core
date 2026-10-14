"""Weather handoff preserves actual-year calendars and source receipts."""

from datetime import datetime, timedelta

import pytest

from epsm_core import Weather


def _actual_year_weather(source, destination, year):
    lines = source.read_text().splitlines()
    lines[4] = f"HOLIDAYS/DAYLIGHT SAVINGS,{'Yes' if year == 2024 else 'No'},0,0,0"
    lines[7] = f"DATA PERIODS,1,1,Data,Monday,1/1/{year},12/31/{year}"
    row = lines[8].split(",")
    with destination.open("w") as stream:
        stream.write("\n".join(lines[:8]) + "\n")
        stamp = datetime(year, 1, 1)
        while stamp.year == year:
            row[:4] = [str(year), str(stamp.month), str(stamp.day), str(stamp.hour + 1)]
            stream.write(",".join(row) + "\n")
            stamp += timedelta(hours=1)
    return destination


@pytest.mark.parametrize("year", [2021, 2024])
def test_actual_year_header_selects_calendar(synthetic_weather, tmp_path, year):
    path = _actual_year_weather(synthetic_weather, tmp_path / "amy.epw", year)
    weather = Weather.from_epw(path)
    assert weather.calendar_year == year
    assert weather.validate() is weather


def test_explicit_calendar_overrides_actual_year(synthetic_weather, tmp_path):
    path = _actual_year_weather(synthetic_weather, tmp_path / "amy.epw", 2021)
    weather = Weather.from_epw(path, calendar_year=2023)
    assert weather.calendar_year == 2023
    weather.validate()


def test_undated_tmy_keeps_documented_fallback(synthetic_weather):
    assert Weather.from_epw(synthetic_weather).calendar_year == 2023
