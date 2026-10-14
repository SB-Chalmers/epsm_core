# File: weather.py
# Purpose: Local EPW metadata and checksum handling. Never fetches weather implicitly.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-11
# Changelog:
#   2026-09-11 - Validate required EPW fields without climate-specific substitutions.
#   2026-09-06 - Document weather interfaces, examples, constraints and processing rationale.

"""Local EPW metadata and checksum handling. Never fetches weather implicitly.

Notes
-----
Only local EPW files are read. Location parsing and SHA-256 identity are separate from
full hourly-calendar validation. Calendar labels use local standard time with no
daylight-saving discontinuities, including the selected leap-year day when applicable.

Examples
--------
Example::

    from epsm_core.weather import hourly_axis

    assert len(hourly_axis(2024)) == 8784
"""

import csv
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

from .specs import ClimateSpec


@dataclass(frozen=True)
class Weather:
    """Explicit EPW input and content fingerprint, kept outside physical buildings."""

    climate: ClimateSpec

    @classmethod
    def from_epw(cls, path, *, calendar_year=2023):
        return cls(climate_from_epw(path, calendar_year=calendar_year))

    @property
    def path(self):
        return Path(self.climate.epw_path)

    @property
    def sha256(self):
        return self.climate.weather_sha256

    @property
    def calendar_year(self):
        return self.climate.calendar_year

    def validate(self):
        if file_sha256(self.path) != self.sha256:
            raise ValueError("Weather content changed after its fingerprint was captured")
        validate_epw_calendar(self.path, self.calendar_year)
        return self

    def to_dict(self):
        return self.climate.model_dump(mode="json")

    @classmethod
    def from_dict(cls, value):
        return cls(ClimateSpec.model_validate(value))


def file_sha256(path):
    """Hash a local file in bounded memory using SHA-256.

    Parameters
    ----------
    path : str or Path
        Local input file path; the operation never downloads missing input.

    Returns
    -------
    str
        Lowercase 64-character hexadecimal digest.

    Notes
    -----
    Reads 1 MiB blocks without modifying the file. Filesystem errors propagate; nothing is
    downloaded.

    Examples
    --------
    Example::

        from epsm_core.weather import file_sha256

        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as folder:
            path = Path(folder) / "sample"
            path.write_bytes(b"abc")
            digest = file_sha256(path)
        assert (
            digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
    """

    # 1. Hash a local file in bounded memory using SHA-256.
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def climate_from_epw(path, *, calendar_year=2023):
    """Read EPW location metadata and bind it to the file's checksum.

    Parameters
    ----------
    path : str or Path
        Local input file path; the operation never downloads missing input.
    calendar_year : int
        Gregorian year used for complete hourly calendar alignment. Default: ``2023``.

    Returns
    -------
    ClimateSpec
        Absolute weather path, location and selected calendar year.

    Raises
    ------
    ValueError
        Rejected conditions: Missing EPW LOCATION header.

    Notes
    -----
    Only the LOCATION header is parsed here. A complete hourly calendar is checked
    separately by validate_epw_calendar before simulation.

    Examples
    --------
    Replace example paths with existing local inputs; output paths must be writable.

    Example::

        from epsm_core.weather import climate_from_epw

        climate = climate_from_epw("data/weather/local.epw", calendar_year=2023)
    """

    # 1. Read EPW location metadata and bind it to the file's checksum.
    path = Path(path).resolve()
    with path.open(encoding="utf-8-sig") as stream:
        row = next(csv.reader(stream))
    if row[0] != "LOCATION":
        raise ValueError("Missing EPW LOCATION header")
    return ClimateSpec(
        epw_path=str(path),
        weather_sha256=file_sha256(path),
        latitude_deg=float(row[6]),
        longitude_deg=float(row[7]),
        time_zone_hours=float(row[8]),
        elevation_m=float(row[9]),
        calendar_year=calendar_year,
    )


def hourly_axis(year):
    """Construct a full local-standard-time axis with hour-start labels.

    Parameters
    ----------
    year : int
        Gregorian year used for complete hourly calendar alignment.

    Returns
    -------
    numpy.ndarray
        datetime64[h] labels, including 8784 hours in leap years.

    Notes
    -----
    There are no daylight-saving jumps. EPW interval-ending timestamps are aligned to these
    labels during validation.

    Examples
    --------
    Example::

        from epsm_core.weather import hourly_axis

        assert len(hourly_axis(2024)) == 8784
    """
    # 1. Construct a full local-standard-time axis with hour-start labels.
    import numpy as np

    return np.arange(
        np.datetime64(f"{year}-01-01T00", "h"),
        np.datetime64(f"{year + 1}-01-01T00", "h"),
        np.timedelta64(1, "h"),
    )


def validate_epw_calendar(path, year):
    """Require exactly one EPW interval for every hour of the chosen year.

    Parameters
    ----------
    path : str or Path
        Local input file path; the operation never downloads missing input.
    year : int
        Gregorian year used for complete hourly calendar alignment.

    Returns
    -------
    dict
        Calendar year, hour count, time basis and relevant original headers.

    Raises
    ------
    ValueError
        Rejected conditions: Malformed EPW hourly row; EPW must contain hourly interval-
        ending records (1–24, minute 0 or 60).

    Notes
    -----
    TMY source years are ignored. Month/day/hour order must match the target calendar
    exactly; EPW hours are 1-24 and minutes may be 0 or 60.

    Examples
    --------
    Replace example paths with existing local inputs; output paths must be writable.

    Example::

        from epsm_core.weather import validate_epw_calendar

        calendar = validate_epw_calendar("data/weather/local.epw", 2023)
    """
    # 1. Require exactly one EPW interval for every hour of the chosen year.
    from datetime import datetime, timedelta

    with Path(path).open(encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        headers = [next(reader) for _ in range(8)]
        axis = []
        for row_number, row in enumerate(reader, 9):
            if len(row) < 35:
                raise ValueError("Malformed EPW hourly row")
            # Required physical inputs cannot use EPW missing-value sentinels.
            # Other optional EPW fields retain their documented engine handling.
            for column, name, lower, upper in (
                (6, "dry bulb", -70, 70),
                (7, "dew point", -70, 70),
                (8, "relative humidity", 0, 110),
                (9, "pressure", 31000, 120000),
                (14, "direct normal solar", 0, 9998),
                (15, "diffuse solar", 0, 9998),
                (20, "wind direction", 0, 360),
                (21, "wind speed", 0, 40),
            ):
                try:
                    value = float(row[column])
                except ValueError as error:
                    raise ValueError(f"Invalid EPW {name} at row {row_number}") from error
                if not math.isfinite(value) or not lower <= value <= upper:
                    raise ValueError(
                        f"Missing or invalid EPW {name} at row {row_number}: {row[column]}"
                    )
            month, day, hour, minute = map(int, row[1:5])
            if not 1 <= hour <= 24 or minute not in (0, 60):
                raise ValueError(
                    "EPW must contain hourly interval-ending records (1–24, minute 0 or 60)"
                )
            axis.append(datetime(year, month, day) + timedelta(hours=hour - 1))
    import numpy as np

    expected = hourly_axis(year)
    if not np.array_equal(np.array(axis, dtype="datetime64[h]"), expected):
        raise ValueError(
            f"EPW calendar does not cover {year} exactly ({len(expected)} hourly records)"
        )
    return dict(
        calendar_year=year,
        hour_count=len(axis),
        time_basis="local_standard_time",
        leap_header=headers[4],
        data_periods=headers[7],
    )
