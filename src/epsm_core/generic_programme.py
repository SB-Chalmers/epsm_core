"""Explicit screening assumptions for unresolved non-residential programmes.

This profile is an EPSM modelling fallback, not a published normal-use standard.
It should be replaced when the actual use, calendar, and ventilation are known.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from epsm_data import load_generic_other_template

from .specs import ScheduleSpec, UseSpec


def _weekday_schedule(start: int, end: int, *, off: float = 0.0) -> ScheduleSpec:
    active = tuple(1.0 if start <= hour < end else off for hour in range(24))
    inactive = (off,) * 24
    return ScheduleSpec(
        values=active,
        weekday_values=(active,) * 5 + (inactive,) * 2,
        source="epsm.generic_other.v1: assumed weekday operation",
    )


@dataclass(frozen=True)
class GenericOtherProgramme:
    """Versioned placeholder for unknown heated non-residential uses.

    Values represent an ordinary daytime activity for screening simulations.
    Restaurant, healthcare, hotel, retail and other specific uses can differ
    substantially; the caller must retain this fallback in result provenance.
    """

    profile_id: str = "epsm.generic_other.v1"
    mechanical_vent_l_s_m2: float = field(
        default_factory=lambda: load_generic_other_template()["mechanical_vent_l_s_m2"])
    _data: dict | None = field(default=None, repr=False, compare=False)

    def use_spec(self) -> UseSpec:
        data = self._data if self._data is not None else load_generic_other_template()
        start, end = data["weekday_start_hour"], data["weekday_end_hour"]
        occupied = _weekday_schedule(start, end)
        equipment = _weekday_schedule(start, end, off=data["equipment_off_fraction"])
        return UseSpec(
            occupancy_category=data["occupancy_category"],
            heating_setpoint=ScheduleSpec.constant(data["heating_setpoint_c"]),
            cooling_setpoint=ScheduleSpec.constant(data["cooling_setpoint_c"]),
            cooling_enabled=data["cooling_enabled"],
            occupant_density_per_m2=data["occupant_density_per_m2"],
            occupant_activity_w=data["occupant_activity_w"],
            occupancy_fraction=occupied,
            equipment_gain_w_m2=data["equipment_gain_w_m2"],
            equipment_fraction=equipment,
            lighting_gain_w_m2=data["lighting_gain_w_m2"],
            lighting_fraction=occupied,
            dhw_kwh_m2_year=data["dhw_kwh_m2_year"],
            dhw_fraction=occupied,
        )

    def ventilation_fraction(self) -> ScheduleSpec:
        data = self._data if self._data is not None else load_generic_other_template()
        return _weekday_schedule(data["weekday_start_hour"], data["weekday_end_hour"])
