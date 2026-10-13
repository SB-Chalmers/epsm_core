"""Explicit screening assumptions for unresolved non-residential programmes.

This profile is an EPSM modelling fallback, not a published normal-use standard.
It should be replaced when the actual use, calendar, and ventilation are known.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    mechanical_vent_l_s_m2: float = 0.7

    def use_spec(self) -> UseSpec:
        occupied = _weekday_schedule(8, 18)
        equipment = _weekday_schedule(8, 18, off=0.2)
        return UseSpec(
            occupancy_category="non_residential",
            heating_setpoint=ScheduleSpec.constant(21),
            cooling_setpoint=ScheduleSpec.constant(30),
            cooling_enabled=False,
            occupant_density_per_m2=0.03,
            occupant_activity_w=108,
            occupancy_fraction=occupied,
            equipment_gain_w_m2=5,
            equipment_fraction=equipment,
            lighting_gain_w_m2=5,
            lighting_fraction=occupied,
            dhw_kwh_m2_year=5,
            dhw_fraction=occupied,
        )

    def ventilation_fraction(self) -> ScheduleSpec:
        return _weekday_schedule(8, 18)


def load_generic_other_v1() -> GenericOtherProgramme:
    """Return the explicit v1 screening fallback for an unidentified programme."""
    return GenericOtherProgramme()
