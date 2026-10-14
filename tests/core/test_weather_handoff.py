"""Weather handoff preserves actual-year calendars and source receipts."""

import json
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


def test_provenance_is_copied_and_survives_portable_roundtrip(synthetic_weather):
    receipt = {"result": {"report": {"warnings": ["reconstructed weather"]}}}
    weather = Weather.from_epw(synthetic_weather, provenance=receipt)
    receipt["result"]["report"]["warnings"].clear()
    shown = weather.provenance
    shown["result"]["report"]["warnings"].clear()
    assert weather.provenance["result"]["report"]["warnings"] == ["reconstructed weather"]
    portable = weather.to_dict()
    restored = Weather.from_dict(json.loads(json.dumps(portable)))
    portable["provenance"].clear()
    assert restored.provenance == weather.provenance
    assert restored.validate() is restored


def test_receipt_is_bound_to_epw_content(synthetic_weather, tmp_path):
    sha256 = Weather.from_epw(synthetic_weather).sha256
    receipt = tmp_path / "weather.epw.json"
    receipt.write_text(json.dumps({"epw_sha256": sha256, "result": {"report": {}}}))
    weather = Weather.from_epw(synthetic_weather, provenance_path=receipt)
    assert weather.provenance["epw_sha256"] == sha256
    receipt.write_text(json.dumps({"epw_sha256": "0" * 64}))
    with pytest.raises(ValueError, match="fingerprint"):
        Weather.from_epw(synthetic_weather, provenance_path=receipt)


def test_receipt_path_requires_fingerprint(synthetic_weather, tmp_path):
    receipt = tmp_path / "weather.epw.json"
    receipt.write_text('{"result": {}}')
    with pytest.raises(ValueError, match="epw_sha256"):
        Weather.from_epw(synthetic_weather, provenance_path=receipt)


@pytest.mark.parametrize("metadata", [{"value": float("nan")}, {"value": {1: "not a JSON key"}}, []])
def test_provenance_requires_portable_json(synthetic_weather, metadata):
    with pytest.raises((TypeError, ValueError)):
        Weather.from_epw(synthetic_weather, provenance=metadata)


def test_legacy_climate_serialization_remains_readable(synthetic_weather):
    weather = Weather.from_epw(synthetic_weather)
    assert Weather.from_dict(weather.climate.model_dump()).provenance == {}
