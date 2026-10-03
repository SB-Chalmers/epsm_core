# File: standards.py
# Purpose: Stored, versioned operational standards for batteries-included model assembly.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-15

"""Load explicit operational standards bundled with EPSM Core.

The default residential profile is Sveby Brukarindata bostader 2.0. It supplies
standardised normal-use assumptions while leaving weather, fabric, leakage,
ventilation topology and installed-system performance to the building source.

Notes
-----
The bundled JSON is read only when a loader or the no-argument ``BuildingBuilder`` is
called. Importing :mod:`epsm_core` does not read the resource or contact the network.
The stored standard contains more information than the current compiler can emit so
unsupported requirements remain visible instead of being silently approximated.

Examples
--------
Example::

    from epsm_core import load_sveby_spec

    standard = load_sveby_spec()
    use = standard.use_spec()
    assert use.occupant_activity_w == 80
"""

from __future__ import annotations

import json
import math
from calendar import monthrange
from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType
from typing import Any, Mapping

from .specs import ScheduleSpec, UseSpec


def _monthly_energy_schedule(monthly, year):
    """Conserve monthly source energies on the actual Gregorian calendar.

    Reference: bundled Sveby residential 2.0 Tables 8.1/9.1. Source monthly
    kWh/m2 values define timing, normalized to the separately declared annual
    total because rounded monthly values need not sum exactly to that total.
    The returned fraction is <=1; its peak power is returned separately.
    """
    rates = [energy * 1000 / (24 * monthrange(year, month)[1])
             for month, energy in enumerate(monthly, 1)]
    peak = max(rates)
    values = tuple(rate / peak for month, rate in enumerate(rates, 1)
                   for _ in range(24 * monthrange(year, month)[1]))
    return ScheduleSpec.annual(values, calendar_year=year,
                              source="Sveby residential 2.0 Tables 8.1/9.1"), peak


def _freeze(value: Any) -> Any:
    """Recursively make loaded JSON mappings immutable while retaining scalar values."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class SvebyResidentialSpec:
    """Stored Sveby residential normal-use inputs and EPSM completion assumptions.

    Attributes
    ----------
    data : Mapping[str, Any]
        Immutable decoded profile containing identity, official source values, EPSM
        completion assumptions and explicitly unsupported requirements.

    Raises
    ------
    ValueError
        If the resource schema, standard identity, version or pinned reviewed values do not
        match the implementation.

    Notes
    -----
    ``model_completion_defaults`` are not Sveby values. They exist so a caller without
    apartment counts or an explicit cooling system can still obtain a valid ``UseSpec``.
    The two classes of value remain separate in the resource and through
    ``completion_default_fields``.

    Examples
    --------
    Example::

        from epsm_core import load_sveby_residential_v2

        standard = load_sveby_residential_v2()
        assert standard.data["area_basis"] == "Atemp"
    """

    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Freeze and validate the bundled resource before exposing any defaults."""
        object.__setattr__(self, "data", _freeze(self.data))
        if self.data.get("schema_version") != 1:
            raise ValueError("Unsupported Sveby profile schema version")
        if self.data.get("standard_name") != "Sveby Brukarindata bostader":
            raise ValueError("Unexpected operational standard")
        if self.data.get("version") != "2.0":
            raise ValueError("Unsupported Sveby residential version")
        use = self.data.get("use", {})
        expected = {
            "heating_setpoint_c": 21.0,
            "cooling_setpoint_c": 25.0,
            "occupancy_hours_per_day": 14,
            "occupant_activity_total_w": 80.0,
            "household_electricity_kwh_m2_year": 21.0,
            "household_electricity_internal_gain_fraction": 0.70,
            "household_electricity_internal_gain_w_m2": 1.68,
            "dhw_kwh_m2_year": 21.0,
        }
        if any(use.get(key) != value for key, value in expected.items()):
            raise ValueError("Bundled Sveby values do not match the reviewed v2.0 profile")
        monthly_pairs = (
            ("dhw_monthly_kwh_m2", use["dhw_kwh_m2_year"]),
            (
                "household_electricity_internal_gain_monthly_kwh_m2",
                use["household_electricity_internal_gain_kwh_m2_year"],
            ),
        )
        if any(
            len(use.get(field, ())) != 12
            or not math.isclose(sum(use[field]), annual, rel_tol=0, abs_tol=0.02)
            for field, annual in monthly_pairs
        ):
            raise ValueError("Bundled Sveby monthly values do not reconcile with annual totals")

    @property
    def profile_id(self) -> str:
        """Return the stable profile identifier recorded in provenance.

        Returns
        -------
        str
            Versioned identity of the bundled standard and publication date.
        """
        return str(self.data["profile_id"])

    @property
    def source_uri(self) -> str:
        """Return the official Sveby source document URI.

        Returns
        -------
        str
            HTTPS location recorded in the bundled resource; no request is made.
        """
        return str(self.data["source_uri"])

    @property
    def completion_default_fields(self) -> tuple[str, ...]:
        """Identify EPSM fallbacks that are not values supplied by Sveby.

        Returns
        -------
        tuple[str, ...]
            Sorted field names beneath ``model_completion_defaults``.
        """
        return tuple(sorted(self.data["model_completion_defaults"]))

    @property
    def unsupported_fields(self) -> tuple[str, ...]:
        """Identify stored requirements the current compiler does not emit faithfully.

        Returns
        -------
        tuple[str, ...]
            Sorted keys beneath ``unsupported_in_epsm_core``.

        Notes
        -----
        The associated explanations remain available through ``data``. Presence in this
        collection prevents loading the profile from being mistaken for full regulatory
        compliance.
        """
        return tuple(sorted(self.data["unsupported_in_epsm_core"]))

    def use_spec(
        self,
        *,
        occupant_density_per_m2: float | None = None,
        cooling_enabled: bool | None = None,
        calendar_year: int | None = None,
    ) -> UseSpec:
        """Create the residential Core use specification.

        Parameters
        ----------
        occupant_density_per_m2 : float or None
            Aggregate occupants per square metre of the Core conditioned area. Supply a
            value derived from Sveby's apartment-size table and the building Atemp whenever
            those inputs are available. ``None`` selects the labelled EPSM completion
            fallback. Default: ``None``.
        cooling_enabled : bool or None
            Whether Core emits ideal cooling. ``None`` retains the 25 C setpoint but selects
            the labelled no-cooling-system completion fallback. Default: ``None``.

        calendar_year : int or None
            Emit source monthly timing for this simulation year. None retains the
            backward-compatible repeated daily profile.

        Returns
        -------
        UseSpec
            Validated residential operations with 21/25 C setpoints, a 17:00--07:00
            occupancy schedule, 80 W/person, 1.68 W/m2 available household-electricity heat
            and 21 kWh/(m2 year) DHW.

        Raises
        ------
        pydantic.ValidationError
            If a caller override violates ``UseSpec`` bounds or schedule relationships.

        Notes
        -----
        The 1.68 W/m2 field represents the 70% of household electricity available as heat,
        not the complete 21 kWh/(m2 year) electrical end use. Supplying calendar_year
        emits the official monthly timing on the actual Gregorian calendar and preserves
        separately declared annual totals (Tables 8.1/9.1). Omitting it retains the
        legacy daily profile. Sveby values use Atemp; supply load_reference_area_m2
        when this differs from verified geometric conditioned area.
        """
        use = self.data["use"]
        completion = self.data["model_completion_defaults"]
        density = (
            completion["occupant_density_per_m2"]["value"]
            if occupant_density_per_m2 is None
            else occupant_density_per_m2
        )
        enabled = (
            completion["cooling_enabled"]["value"]
            if cooling_enabled is None
            else cooling_enabled
        )
        start, end = use["occupancy_start_hour"], use["occupancy_end_hour"]
        # ScheduleSpec labels hours by their start. This half-open union produces exactly
        # fourteen occupied hours: 17:00--24:00 and 00:00--07:00.
        occupied = ScheduleSpec(
            values=tuple(
                1.0 if hour >= start or hour < end else 0.0 for hour in range(24)
            )
        )
        equipment = ScheduleSpec.constant(1)
        dhw = ScheduleSpec.constant(1)
        gain = use["household_electricity_internal_gain_w_m2"]
        if calendar_year is not None:
            equipment, peak = _monthly_energy_schedule(
                use["household_electricity_internal_gain_monthly_kwh_m2"], calendar_year)
            hours = sum(equipment.annual_values)
            gain = use["household_electricity_internal_gain_kwh_m2_year"] * 1000 / hours
            dhw, _ = _monthly_energy_schedule(use["dhw_monthly_kwh_m2"], calendar_year)
        return UseSpec(
            occupancy_category="residential",
            heating_setpoint=ScheduleSpec.constant(use["heating_setpoint_c"]),
            cooling_setpoint=ScheduleSpec.constant(use["cooling_setpoint_c"]),
            cooling_enabled=enabled,
            occupancy_fraction=occupied,
            equipment_fraction=equipment,
            dhw_fraction=dhw,
            occupant_density_per_m2=density,
            occupant_activity_w=use["occupant_activity_total_w"],
            # Core currently models the thermally available 70% as a gain; the complete
            # electrical end use stays in the source profile for downstream accounting.
            equipment_gain_w_m2=gain,
            lighting_gain_w_m2=0,
            dhw_kwh_m2_year=use["dhw_kwh_m2_year"],
        )

    def compiler_coverage(self, *, calendar_year=None):
        """Expose emitted and unsupported source fields for this chosen mapping.

        Historical ``unsupported_fields`` describes the original daily mapping.
        With a year, monthly DHW and household gain profiles are emitted natively.
        """
        unsupported = set(self.unsupported_fields)
        if calendar_year is not None:
            unsupported -= {"monthly_dhw_profile", "monthly_household_electricity_profile"}
        return {"profile_id": self.profile_id, "calendar_year": calendar_year,
                "unsupported": sorted(unsupported)}

    def common_use_spec(self) -> UseSpec:
        """Create the standard unoccupied common/stairwell use specification.

        Returns
        -------
        UseSpec
            Residential-compatible common-area use with an 18 C heating setpoint and zero
            people, DHW, lighting and equipment gains.

        Notes
        -----
        Sveby allocates household electricity over all Atemp. The current apartment compiler
        instead conserves whole-building residential loads while concentrating them in
        dwelling zones. The stored profile records this spatial-allocation limitation.
        Refuse rooms require a distinct 10 C zone use and are not represented by this shared
        common-area specification.
        """
        use = self.use_spec(occupant_density_per_m2=0)
        return use.updated(
            heating_setpoint=ScheduleSpec.constant(
                self.data["common_spaces"]["stair_storage_plant_heating_setpoint_c"]
            ),
            equipment_gain_w_m2=0,
            lighting_gain_w_m2=0,
            dhw_kwh_m2_year=0,
        )

    def building_assumptions(
        self,
        *,
        occupant_density_per_m2: float | None = None,
        cooling_enabled: bool | None = None,
        fixed_solar_shading_calculated: bool = False,
        calendar_year: int | None = None,
    ) -> dict[str, Any]:
        """Return partial BuildingBuilder assumptions for standard residential use.

        Parameters
        ----------
        occupant_density_per_m2 : float or None
            Optional building-specific aggregate occupancy density forwarded to
            ``use_spec``. Default: ``None``.
        cooling_enabled : bool or None
            Optional explicit ideal-cooling availability forwarded to ``use_spec``.
            Default: ``None``.
        fixed_solar_shading_calculated : bool
            Use only Sveby's 0.71 occupant-behaviour factor when fixed shading is calculated
            geometrically; otherwise use the 0.50 total fallback. Default: ``False``.

        Returns
        -------
        dict[str, Any]
            Partial nested ``BuildingSpec`` input containing use, common use, facade shading
            and minimum mechanical outdoor-air flow.

        Raises
        ------
        pydantic.ValidationError
            If occupant density or cooling overrides cannot form a valid ``UseSpec``.

        Notes
        -----
        The mapping intentionally omits ventilation topology, leakage, recovery, weather,
        fabric and system delivery. Callers selecting natural ventilation must override the
        incompatible mechanical flow explicitly. The profile stores but does not emit the
        kitchen-boost duration or window-airing result correction.

        Examples
        --------
        Example::

            from epsm_core import BuildingBuilder, load_sveby_spec

            standard = load_sveby_spec()
            assumptions = standard.building_assumptions(
                occupant_density_per_m2=0.021,
                fixed_solar_shading_calculated=True,
            )
            builder = BuildingBuilder(
                assumption_profile=standard.profile_id,
                assumptions=assumptions,
            )
        """
        shading = self.data["solar_shading"]
        # Do not multiply a geometric fixed-shading calculation by Sveby's total fallback;
        # retain only the behavioural component in that case.
        factor = (
            shading["occupant_behavior_factor"]
            if fixed_solar_shading_calculated
            else shading["total_default_factor"]
        )
        return {
            "use": self.use_spec(
                occupant_density_per_m2=occupant_density_per_m2,
                cooling_enabled=cooling_enabled,
                calendar_year=calendar_year,
            ).model_dump(mode="json"),
            "common_use": self.common_use_spec().model_dump(mode="json"),
            "facade": {"solar_shading_factor": factor},
            "airflow": {
                "mechanical_vent_l_s_m2": self.data["airflow"][
                    "minimum_outdoor_air_l_s_m2"
                ]
            },
        }


def load_sveby_residential_v2() -> SvebyResidentialSpec:
    """Load the bundled, version-pinned Sveby residential specification.

    Returns
    -------
    SvebyResidentialSpec
        Immutable, validated version 2.0 profile.

    Raises
    ------
    FileNotFoundError
        If package installation omitted the required JSON resource.
    ValueError
        If the stored schema, identity, version or pinned values fail validation.

    Notes
    -----
    Reads package data only. It never downloads or refreshes the official document.

    Examples
    --------
    Example::

        from epsm_core import load_sveby_residential_v2

        standard = load_sveby_residential_v2()
        assert standard.data["version"] == "2.0"
    """
    resource = files("epsm_core").joinpath("standards_data/sveby_residential_v2.json")
    with resource.open("r", encoding="utf-8") as handle:
        return SvebyResidentialSpec(json.load(handle))


def load_sveby_spec() -> SvebyResidentialSpec:
    """Load EPSM Core's current default Sveby residential specification.

    Returns
    -------
    SvebyResidentialSpec
        Current default profile; presently identical to
        ``load_sveby_residential_v2()``.

    Notes
    -----
    This unversioned convenience name may select a later reviewed profile in a future Core
    release. Use the versioned loader when reproducibility across releases is required.
    """
    return load_sveby_residential_v2()
