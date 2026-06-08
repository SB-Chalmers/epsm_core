"""Location, city, and weather metadata for a :class:`~pbgenerator.building.Building`.

Splits the "where is this building" concern out of ``BuildingParams`` (which is
purely a simulation-parameter bundle).  A :class:`Location` may describe either
a real building sourced from the Swedish EPC database or a hypothetical building
placed at an arbitrary site for what-if studies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class WeatherSite:
    """The EPW weather file selected for a building plus its station metadata."""

    epw_path: Path
    station_name: str = ""
    wmo: str = ""
    station_lat: float | None = None
    station_lon: float | None = None
    period: str = ""                     # e.g. TMY period "2011-2025"
    distance_km: float | None = None     # distance from building centroid

    def __post_init__(self) -> None:
        object.__setattr__(self, "epw_path", Path(self.epw_path))


@dataclass(frozen=True)
class EPCSource:
    """Provenance for a building drawn from the Swedish EPC / footprint DB.

    All fields are optional so a hypothetical building can carry an empty
    source.  Mirrors the columns surfaced by
    :class:`pbgenerator.epc_io.FootprintRecord`.
    """

    objektidentitet: str | None = None
    formular_id: int | None = None
    kommun: str | None = None
    andamal: str | None = None
    byggnads_kat: str | None = None
    construction_year: int | None = None
    atemp_epc_m2: float | None = None
    energi_prestanda: int | None = None      # kWh/m²/yr
    fastighet_kwh: int | None = None
    # Optional full EPC energy breakdown (FjvVV, Fastighet, ...), as loaded by
    # epc_io.load_epc_energy().  Kept as a plain dict for round-tripping.
    energy_breakdown: dict | None = None


@dataclass(frozen=True)
class Location:
    """Where a building sits, plus its weather and (optional) EPC provenance.

    Parameters
    ----------
    footprint_pts:
        Polygon vertices ``[[x, y], ...]`` in EPSG:3006 (SWEREF99 TM) metres.
    centroid_lat / centroid_lon:
        WGS-84 centroid coordinates, when known.
    city:
        Human-readable city/municipality name (``kommun``).
    hypothetical:
        ``True`` for a synthetic building not tied to a real EPC record.
    weather:
        The selected :class:`WeatherSite` (EPW + station metadata).
    epc:
        Optional :class:`EPCSource` provenance for real buildings.
    """

    footprint_pts: list[list[float]]
    centroid_lat: float | None = None
    centroid_lon: float | None = None
    city: str = ""
    hypothetical: bool = False
    weather: WeatherSite | None = None
    epc: EPCSource | None = None

    @property
    def footprint_area_m2(self) -> float:
        """Footprint area in m² (shoelace formula)."""
        pts = self.footprint_pts
        n = len(pts)
        a = 0.0
        for i in range(n):
            j = (i + 1) % n
            a += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1]
        return abs(a) / 2.0

    @property
    def epw_path(self) -> Path | None:
        return self.weather.epw_path if self.weather else None

    # -- constructors ------------------------------------------------------

    @classmethod
    def hypothetical_site(
        cls,
        footprint_pts: list[list[float]],
        *,
        city: str = "",
        centroid_lat: float | None = None,
        centroid_lon: float | None = None,
        weather: WeatherSite | None = None,
    ) -> "Location":
        """Build a :class:`Location` for a synthetic/what-if building."""
        return cls(
            footprint_pts=[[float(c) for c in pt] for pt in footprint_pts],
            centroid_lat=centroid_lat,
            centroid_lon=centroid_lon,
            city=city,
            hypothetical=True,
            weather=weather,
            epc=None,
        )

    @classmethod
    def from_footprint_record(cls, record, weather: WeatherSite | None = None) -> "Location":
        """Build a :class:`Location` from an :class:`epc_io.FootprintRecord`."""
        epc = EPCSource(
            objektidentitet=getattr(record, "objektidentitet", None),
            formular_id=getattr(record, "formular_id", None),
            kommun=getattr(record, "kommun", None),
            andamal=getattr(record, "andamal", None),
            byggnads_kat=getattr(record, "byggnads_kat", None),
            construction_year=getattr(record, "construction_year", None),
            atemp_epc_m2=getattr(record, "atemp", None),
            energi_prestanda=getattr(record, "energi_prestanda", None),
            fastighet_kwh=getattr(record, "fastighet_kwh", None),
        )
        return cls(
            footprint_pts=[[float(c) for c in pt] for pt in record.footprint_pts],
            centroid_lat=getattr(record, "centroid_lat", None),
            centroid_lon=getattr(record, "centroid_lon", None),
            city=getattr(record, "kommun", "") or "",
            hypothetical=False,
            weather=weather,
            epc=epc,
        )


__all__ = ["Location", "WeatherSite", "EPCSource"]
