"""Unit-aware value containers for building inputs and simulation outputs.

Every numeric result in the redesigned pipeline carries its unit explicitly so
downstream code never has to guess whether a value is kWh, kWh/m², °C, or W.
Two containers are provided:

* :class:`Quantity` — a single scalar value plus its unit.
* :class:`TimeSeries` — an ordered sequence of values on a fixed timestep plus
  its unit (e.g. hourly zone air temperature, hourly site electricity).

Both are intentionally lightweight (no third-party dependency) so they can be
created inside EnergyPlus result parsing and PySAM PV evaluation without
pulling pandas into hot paths.  :meth:`TimeSeries.to_series` is offered for
callers that *do* want a pandas object.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd


# ---------------------------------------------------------------------------
# Canonical unit strings used across the package.  Kept as plain constants so
# call sites stay greppable and typos surface quickly.
# ---------------------------------------------------------------------------
KWH = "kWh"
KWH_PER_M2 = "kWh/m2"
WH = "Wh"
J = "J"
GJ = "GJ"
W = "W"
W_PER_M2 = "W/m2"
DEG_C = "degC"
M2 = "m2"
M3 = "m3"
ACH = "1/h"
FRACTION = "-"
KW = "kW"


@dataclass(frozen=True)
class Quantity:
    """A scalar value with an explicit unit.

    Examples
    --------
    >>> Quantity(145.2, KWH_PER_M2)
    Quantity(value=145.2, unit='kWh/m2')
    """

    value: float
    unit: str

    def __post_init__(self) -> None:
        # Allow NaN/None-ish but coerce to float so arithmetic is predictable.
        object.__setattr__(self, "value", float(self.value))

    def __str__(self) -> str:
        return f"{self.value:g} {self.unit}"

    def to(self, unit: str, factor: float) -> "Quantity":
        """Return a new Quantity scaled by ``factor`` and relabelled ``unit``.

        The caller supplies the conversion factor explicitly (no hidden unit
        registry) so conversions stay auditable, e.g.::

            gj.to(KWH, 277.778)
        """
        return Quantity(self.value * factor, unit)


@dataclass(frozen=True)
class TimeSeries:
    """An ordered numeric series on a fixed timestep, with an explicit unit.

    Parameters
    ----------
    values:
        The ordered samples.  Stored as a tuple so the container is hashable
        and safe to share between objects.
    unit:
        The unit of every sample (e.g. ``"degC"``, ``"Wh"``).
    timestep:
        Human-readable cadence label, e.g. ``"hourly"``, ``"monthly"``,
        ``"timestep"``.  Used for reporting and resampling guards.
    name:
        Optional EnergyPlus/PySAM variable name this series came from.
    key:
        Optional key value (e.g. the zone/surface the variable belongs to).
    """

    values: tuple[float, ...]
    unit: str
    timestep: str = "hourly"
    name: str = ""
    key: str = ""

    def __init__(
        self,
        values: Iterable[float],
        unit: str,
        timestep: str = "hourly",
        name: str = "",
        key: str = "",
    ) -> None:
        object.__setattr__(self, "values", tuple(float(v) for v in values))
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "timestep", timestep)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "key", key)

    def __len__(self) -> int:
        return len(self.values)

    @property
    def total(self) -> float:
        """Sum of all samples (meaningful for energy flux series)."""
        return float(sum(self.values))

    @property
    def mean(self) -> float:
        """Arithmetic mean of all samples (meaningful for temperatures)."""
        return float(sum(self.values) / len(self.values)) if self.values else float("nan")

    @property
    def minimum(self) -> float:
        return min(self.values) if self.values else float("nan")

    @property
    def maximum(self) -> float:
        return max(self.values) if self.values else float("nan")

    def total_as(self, unit: str, factor: float) -> Quantity:
        """Return the series total scaled by ``factor`` and labelled ``unit``."""
        return Quantity(self.total * factor, unit)

    def to_monthly(self, hours_per_month: Sequence[int] | None = None) -> "TimeSeries":
        """Aggregate an 8760-length hourly series into 12 monthly sums.

        For non-energy series (temperatures) callers should prefer
        :meth:`to_monthly_mean`.  Raises if the series is not hourly/8760.
        """
        if self.timestep != "hourly" or len(self.values) != 8760:
            raise ValueError(
                "to_monthly requires an 8760-length hourly series; "
                f"got timestep={self.timestep!r} len={len(self.values)}"
            )
        bounds = _month_bounds(hours_per_month)
        monthly = [
            float(sum(self.values[start:end])) for start, end in bounds
        ]
        return TimeSeries(monthly, self.unit, "monthly", self.name, self.key)

    def to_monthly_mean(self, hours_per_month: Sequence[int] | None = None) -> "TimeSeries":
        """Aggregate an 8760-length hourly series into 12 monthly means."""
        if self.timestep != "hourly" or len(self.values) != 8760:
            raise ValueError(
                "to_monthly_mean requires an 8760-length hourly series; "
                f"got timestep={self.timestep!r} len={len(self.values)}"
            )
        bounds = _month_bounds(hours_per_month)
        monthly = [
            float(sum(self.values[start:end]) / (end - start))
            for start, end in bounds
        ]
        return TimeSeries(monthly, self.unit, "monthly", self.name, self.key)

    def to_series(self) -> "pd.Series":
        """Return the series as a pandas Series (lazy import)."""
        import pandas as pd

        label = self.name or "value"
        if self.key:
            label = f"{self.name}::{self.key}" if self.name else self.key
        return pd.Series(self.values, name=f"{label} [{self.unit}]")


# Standard (non-leap) month lengths in hours, summing to 8760.
_DEFAULT_HOURS_PER_MONTH = (744, 672, 744, 720, 744, 720, 744, 744, 720, 744, 720, 744)


def _month_bounds(hours_per_month: Sequence[int] | None) -> list[tuple[int, int]]:
    hpm = tuple(hours_per_month) if hours_per_month else _DEFAULT_HOURS_PER_MONTH
    if sum(hpm) != 8760:
        raise ValueError(f"hours_per_month must sum to 8760, got {sum(hpm)}")
    bounds: list[tuple[int, int]] = []
    start = 0
    for h in hpm:
        bounds.append((start, start + h))
        start += h
    return bounds


__all__ = [
    "Quantity",
    "TimeSeries",
    "KWH",
    "KWH_PER_M2",
    "WH",
    "J",
    "GJ",
    "W",
    "W_PER_M2",
    "DEG_C",
    "M2",
    "M3",
    "ACH",
    "FRACTION",
    "KW",
]
