"""Friendly, typed access to simulation time series — no string keys required.

The raw outputs live in :class:`~pbgenerator.results.BuildingResults` as two flat
dicts keyed by ``"<VariableName>::<Zone>"``.  That is the single source of
truth, but typing those keys by hand is error-prone.  This module layers a
discoverable, autocomplete-friendly view on top::

    res.lighting.hourly            # whole-building lighting, hourly TimeSeries
    res.air_temperature.monthly    # building mean air temp, 12 monthly values
    res.heating_load.annual        # annual heating as a unit-tagged Quantity

    res.zones[0].air_temperature.hourly      # first zone, by index
    res.zones["FLOOR1_ROOM_..."].lighting    # a zone by name
    res.floors[0].zones[1].air_temperature   # navigate floor -> zone

Each named attribute returns a :class:`Signal` (or ``None`` if the variable was
not requested in the IDF).  A ``Signal`` exposes ``.hourly``, ``.monthly`` and
``.annual`` with explicit units, aggregating across the relevant zones (energy
flows are summed, temperatures are averaged).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from .units import J, KWH, WH, Quantity, TimeSeries

_J_TO_KWH = 1.0 / 3.6e6

# Friendly attribute name -> (EnergyPlus VariableName, aggregation across zones).
#   "sum"  -> energy flows are added together
#   "mean" -> intensive quantities (temperatures) are averaged
_VARMAP: dict[str, tuple[str, str]] = {
    "air_temperature": ("Zone Mean Air Temperature", "mean"),
    "heating_load": ("Zone Ideal Loads Zone Total Heating Energy", "sum"),
    "cooling_load": ("Zone Ideal Loads Zone Total Cooling Energy", "sum"),
    "lighting": ("Zone Lights Total Heating Energy", "sum"),
    "equipment": ("Zone Electric Equipment Total Heating Energy", "sum"),
    "occupancy_heat": ("Zone People Total Heating Energy", "sum"),
    "solar_gains": ("Zone Windows Total Transmitted Solar Radiation Energy", "sum"),
    "dhw_energy": ("Water Use Equipment Heating Energy", "sum"),
}

_FLOOR_RE = re.compile(r"FLOOR(\d+)", re.IGNORECASE)


def _key_belongs_to_zone(key: str, zone: str) -> bool:
    """Whether a series ``key`` belongs to ``zone``.

    EnergyPlus reports some variables under the zone name itself (e.g. air
    temperature) and others under a child object named ``"<ZONE> IDEAL LOADS
    AIR SYSTEM"``.  Matching the zone name as a space-delimited prefix covers
    both without cross-matching sibling zones.
    """
    return key == zone or key.startswith(zone + " ")


@dataclass(frozen=True)
class Signal:
    """One variable, aggregated for a building / floor / zone, with units.

    Use :attr:`hourly`, :attr:`monthly`, and :attr:`annual` to read the data.
    """

    friendly_name: str
    variable: str
    unit: str
    _agg: str
    _hourly: TimeSeries

    @property
    def hourly(self) -> TimeSeries:
        """The 8760-length hourly series in its native unit."""
        return self._hourly

    @property
    def monthly(self) -> TimeSeries | None:
        """12 monthly values (summed for energy, averaged for temperature)."""
        if len(self._hourly) != 8760:
            return None
        return (
            self._hourly.to_monthly()
            if self._agg == "sum"
            else self._hourly.to_monthly_mean()
        )

    @property
    def annual(self) -> Quantity:
        """The annual value: a kWh total for energy, a mean for temperature."""
        if self._agg == "sum":
            total = self._hourly.total
            if self.unit == J:
                return Quantity(total * _J_TO_KWH, KWH)
            if self.unit == WH:
                return Quantity(total / 1000.0, KWH)
            return Quantity(total, self.unit)
        return Quantity(self._hourly.mean, self.unit)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Signal({self.friendly_name!r}, unit={self.unit!r}, annual={self.annual})"

    @classmethod
    def build(
        cls, friendly: str, variable: str, series: list[TimeSeries], agg: str
    ) -> "Signal | None":
        if not series:
            return None
        unit = series[0].unit
        if len(series) == 1:
            values = series[0].values
        else:
            columns = zip(*(s.values for s in series))
            if agg == "sum":
                values = [float(sum(col)) for col in columns]
            else:
                values = [float(sum(col) / len(col)) for col in columns]
        hourly = TimeSeries(values, unit, series[0].timestep, name=variable)
        return cls(friendly, variable, unit, agg, hourly)


class _SignalHost:
    """Mixin exposing one friendly property per entry in ``_VARMAP``.

    Subclasses provide :meth:`_series_for`, which returns the matching
    per-zone :class:`TimeSeries` objects for one EnergyPlus variable.
    """

    def _series_for(self, variable: str) -> list[TimeSeries]:  # pragma: no cover
        raise NotImplementedError

    def _signal(self, friendly: str) -> Signal | None:
        variable, agg = _VARMAP[friendly]
        return Signal.build(friendly, variable, self._series_for(variable), agg)

    # -- named, autocomplete-friendly accessors ---------------------------

    @property
    def air_temperature(self) -> Signal | None:
        return self._signal("air_temperature")

    @property
    def heating_load(self) -> Signal | None:
        return self._signal("heating_load")

    @property
    def cooling_load(self) -> Signal | None:
        return self._signal("cooling_load")

    @property
    def lighting(self) -> Signal | None:
        return self._signal("lighting")

    @property
    def equipment(self) -> Signal | None:
        return self._signal("equipment")

    @property
    def occupancy_heat(self) -> Signal | None:
        return self._signal("occupancy_heat")

    @property
    def solar_gains(self) -> Signal | None:
        return self._signal("solar_gains")

    @property
    def dhw_energy(self) -> Signal | None:
        return self._signal("dhw_energy")

    def available(self) -> list[str]:
        """Friendly names that actually have data for this host."""
        return [name for name in _VARMAP if self._signal(name) is not None]


class ZoneResults(_SignalHost):
    """Per-zone view of the time series for a single thermal zone."""

    def __init__(self, name: str, hourly: dict[str, TimeSeries]) -> None:
        self.name = name
        self._hourly = hourly

    @property
    def floor(self) -> int | None:
        """1-based floor number parsed from the zone name, if present."""
        m = _FLOOR_RE.search(self.name)
        return int(m.group(1)) if m else None

    def _series_for(self, variable: str) -> list[TimeSeries]:
        return [
            ts for ts in self._hourly.values()
            if ts.name == variable and _key_belongs_to_zone(ts.key, self.name)
        ]

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ZoneResults({self.name!r}, floor={self.floor})"


class ZoneCollection:
    """Ordered, name- and index-addressable collection of :class:`ZoneResults`."""

    def __init__(self, zones: list[ZoneResults]) -> None:
        self._zones = zones
        self._by_name = {z.name: z for z in zones}

    def __getitem__(self, key: int | str) -> ZoneResults:
        if isinstance(key, int):
            return self._zones[key]
        return self._by_name[key]

    def __iter__(self) -> Iterator[ZoneResults]:
        return iter(self._zones)

    def __len__(self) -> int:
        return len(self._zones)

    def names(self) -> list[str]:
        return list(self._by_name)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ZoneCollection({self.names()!r})"


class FloorResults(_SignalHost):
    """A floor-level view that aggregates across all zones on one storey."""

    def __init__(self, number: int, zones: list[ZoneResults],
                 hourly: dict[str, TimeSeries]) -> None:
        self.number = number
        self.zones = ZoneCollection(zones)
        self._hourly = hourly
        self._zone_names = {z.name for z in zones}

    def _series_for(self, variable: str) -> list[TimeSeries]:
        return [
            ts for ts in self._hourly.values()
            if ts.name == variable
            and any(_key_belongs_to_zone(ts.key, z) for z in self._zone_names)
        ]

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"FloorResults(floor={self.number}, n_zones={len(self.zones)})"


def zone_names(hourly: dict[str, TimeSeries]) -> list[str]:
    """Discover the thermal-zone names present in an hourly store."""
    temp_var = _VARMAP["air_temperature"][0]
    names = {ts.key for ts in hourly.values() if ts.name == temp_var and ts.key}
    if not names:  # fall back to any keyed series
        names = {ts.key for ts in hourly.values() if ts.key}
    return sorted(names)


def build_zones(hourly: dict[str, TimeSeries]) -> ZoneCollection:
    return ZoneCollection([ZoneResults(n, hourly) for n in zone_names(hourly)])


def build_floors(hourly: dict[str, TimeSeries]) -> list[FloorResults]:
    zones = [ZoneResults(n, hourly) for n in zone_names(hourly)]
    by_floor: dict[int, list[ZoneResults]] = {}
    for z in zones:
        by_floor.setdefault(z.floor if z.floor is not None else 0, []).append(z)
    return [FloorResults(num, by_floor[num], hourly) for num in sorted(by_floor)]


__all__ = [
    "Signal",
    "ZoneResults",
    "ZoneCollection",
    "FloorResults",
    "build_zones",
    "build_floors",
    "zone_names",
]
