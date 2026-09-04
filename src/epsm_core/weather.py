"""Local EPW metadata and checksum handling. Never fetches weather implicitly."""

import csv
import hashlib
from pathlib import Path

from .specs import ClimateSpec


def file_sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def climate_from_epw(path, *, calendar_year=2023):
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
