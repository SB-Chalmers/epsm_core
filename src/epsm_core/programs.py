# SPDX-License-Identifier: MIT
# Date created: 2026-10-04
"""Conservative area-weighted operational programmes for unresolved mixed uses.

References: Honeybee ProgramType.average (conceptual precedent, no dependency):
https://www.ladybug.tools/honeybee-energy/docs/honeybee_energy.programtype.html
EnergyPlus 24.2 I/O Reference, People, ElectricEquipment and WaterUse:Equipment:
https://bigladdersoftware.com/epx/docs/24-2/input-output-reference/

Floor-area shares are explicit heated/load-reference-area fractions, never inferred
from GIS purpose order. Blending conserves hourly people, electrical loads, lighting,
ventilation and annual-normalised DHW on a common Gregorian axis. It does not
establish spatial zoning or turn thermostat averages into an exact thermal model.
Use separate ZoneUseSpec assignments when programme locations or systems are known.
"""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import Field, model_validator

from .specs import AirflowSpec, ScheduleSpec, Spec, UseSpec, ZoneUseSpec


class ProgramComponent(Spec):
    """One sourced programme and its fraction of the shared reference area."""

    name: Annotated[str, Field(min_length=1, pattern=r"\S")]
    area_fraction: Annotated[float, Field(gt=0, le=1)]
    use: UseSpec
    airflow: AirflowSpec
    source: Annotated[str, Field(min_length=1, pattern=r"\S")]


class ProgramBlend(Spec):
    """Area mixture compiled into ordinary native EPSM use and airflow specs.

    Unlike independent zones, an effective programme has one thermostat and
    ventilation topology. Different recovery efficiencies, leakage weather
    coefficients and plant availability cannot be
    collapsed faithfully by the present schema and therefore require separate zones.
    Differing setpoints require an explicit caller-selected effective use control.
    Infiltration ACH mixing additionally assumes a shared zone height; never use
    this approximation to combine spaces with materially different area/volume ratios.
    """

    components: Annotated[tuple[ProgramComponent, ...], Field(min_length=1)]
    source: Annotated[str, Field(min_length=1, pattern=r"\S")]

    @model_validator(mode="after")
    def shares(self):
        """Reject incomplete/overlapping fractions and duplicate programme names."""
        if not math.isclose(sum(c.area_fraction for c in self.components), 1, abs_tol=1e-9):
            raise ValueError("Programme area fractions must sum to one")
        if len({c.name for c in self.components}) != len(self.components):
            raise ValueError("Programme names must be unique")
        return self

    def resolve(
        self, *, calendar_year: int, control_use: UseSpec | None = None
    ) -> tuple[UseSpec, AirflowSpec]:
        """Return (UseSpec, AirflowSpec), preserving component hourly load totals.

        ``control_use`` supplies only heating/cooling setpoints and cooling enablement.
        It must be an explicit, sourced modelling assumption at the caller; its loads
        are not used. Without it, all component controls must agree hour for hour.
        DHW is weighted after normalising each input profile by its own annual sum,
        matching EPSM's annual-demand-to-flow conversion. Zero annual DHW contributes
        no flow regardless of the inactive component's declared profile.
        """
        parts = self.components
        first = parts[0]
        weights = [c.area_fraction for c in parts]
        uses = [c.use for c in parts]
        air = [c.airflow for c in parts]
        # Resolve every calendar even when its associated design load is zero.
        for c in parts:
            for obj in (c.use, c.airflow):
                for value in obj.__dict__.values():
                    if isinstance(value, ScheduleSpec):
                        value.hourly(calendar_year)
        for key in (
            "topology",
            "sensible_recovery_effectiveness",
            "latent_recovery_effectiveness",
            "infiltration_coefficients",
            "maximum_heating_supply_temperature_c",
            "minimum_cooling_supply_temperature_c",
        ):
            if any(getattr(a, key) != getattr(first.airflow, key) for a in air):
                raise ValueError(f"Different {key} requires separate zone programmes")
        for key in ("heating_availability", "cooling_availability"):
            reference = getattr(first.airflow, key).hourly(calendar_year)
            if any(getattr(a, key).hourly(calendar_year) != reference for a in air):
                raise ValueError(f"Different {key} requires separate zone programmes")
        if control_use is None:
            for key in ("heating_setpoint", "cooling_setpoint"):
                reference = getattr(first.use, key).hourly(calendar_year)
                if any(getattr(u, key).hourly(calendar_year) != reference for u in uses):
                    raise ValueError(
                        "Different setpoints require explicit control_use or separate zones"
                    )
            if any(u.cooling_enabled != first.use.cooling_enabled for u in uses):
                raise ValueError("Different cooling enablement requires explicit control_use")
        control = control_use or first.use
        controls = {
            key: getattr(control, key)
            for key in ("heating_setpoint", "cooling_setpoint", "cooling_enabled")
        }
        for key in ("heating_setpoint", "cooling_setpoint"):
            controls[key].hourly(calendar_year)
        changes = dict(controls)
        categories = {u.occupancy_category for u in uses}
        changes["occupancy_category"] = categories.pop() if len(categories) == 1 else "unspecified"

        def weighted_load(objects, rate_key, fraction_key, *, annual_normalised=False):
            rates = [getattr(o, rate_key) for o in objects]
            total = math.fsum(w * r for w, r in zip(weights, rates))
            profiles = [getattr(o, fraction_key).hourly(calendar_year) for o in objects]
            denominators = (
                [math.fsum(p) for p in profiles] if annual_normalised else [1] * len(parts)
            )
            if annual_normalised and any(r > 0 and d == 0 for r, d in zip(rates, denominators)):
                raise ValueError("Nonzero DHW demand requires nonzero annual activity")
            hourly = [
                math.fsum(
                    w * r * p[h] / d
                    for w, r, p, d in zip(weights, rates, profiles, denominators)
                    if r > 0
                )
                / total
                if total
                else 0
                for h in range(len(profiles[0]))
            ]
            # DHW schedules are normalised again by the native compiler. Multiplying
            # all values by a common factor leaves that hourly water-flow profile exact.
            if annual_normalised and max(hourly, default=0):
                peak = max(hourly)
                hourly = [v / peak for v in hourly]
            # Roundoff at one must not trip strict fractional schema bounds.
            hourly = [min(1.0, max(0.0, v)) for v in hourly]
            return total, ScheduleSpec.annual(
                hourly, calendar_year=calendar_year, source=self.source
            )

        for rate, fraction in (
            ("occupant_density_per_m2", "occupancy_fraction"),
            ("equipment_gain_w_m2", "equipment_fraction"),
            ("lighting_gain_w_m2", "lighting_fraction"),
            ("dhw_kwh_m2_year", "dhw_fraction"),
        ):
            changes[rate], changes[fraction] = weighted_load(
                uses, rate, fraction, annual_normalised=rate == "dhw_kwh_m2_year"
            )

        def effective_ratio(rate_key, fraction_key, scalar_key, schedule_key):
            rates = [getattr(u, rate_key) for u in uses]
            profiles = [getattr(u, fraction_key).hourly(calendar_year) for u in uses]
            quantities = [
                (getattr(u, schedule_key) or ScheduleSpec.constant(getattr(u, scalar_key))).hourly(
                    calendar_year
                )
                for u in uses
            ]
            values = []
            for h in range(len(profiles[0])):
                loads = [w * r * p[h] for w, r, p in zip(weights, rates, profiles)]
                denominator = math.fsum(loads)
                values.append(
                    math.fsum(load * q[h] for load, q in zip(loads, quantities)) / denominator
                    if denominator
                    else getattr(first.use, scalar_key)
                )
            return ScheduleSpec.annual(values, calendar_year=calendar_year, source=self.source)

        changes["occupant_activity_schedule"] = effective_ratio(
            "occupant_density_per_m2",
            "occupancy_fraction",
            "occupant_activity_w",
            "occupant_activity_schedule",
        )
        changes["equipment_heat_fraction_schedule"] = effective_ratio(
            "equipment_gain_w_m2",
            "equipment_fraction",
            "equipment_heat_fraction",
            "equipment_heat_fraction_schedule",
        )
        area_basis = [a.envelope_infiltration_l_s_m2 is not None for a in air]
        if any(area_basis) and not all(area_basis):
            raise ValueError("Different infiltration reference bases require separate zone programmes")
        infiltration_rate = "envelope_infiltration_l_s_m2" if all(area_basis) else "envelope_infiltration_ach"
        airflow_changes = {}
        for rate, fraction in (
            (infiltration_rate, "infiltration_fraction"),
            ("natural_exchange_ach", "natural_exchange_fraction"),
            ("mechanical_vent_l_s_m2", "mechanical_vent_fraction"),
        ):
            airflow_changes[rate], airflow_changes[fraction] = weighted_load(air, rate, fraction)
        airflow_changes["infiltration_source"] = self.source
        return first.use.updated(**changes), first.airflow.updated(**airflow_changes)

    def zone_assignment(
        self,
        *,
        calendar_year: int,
        zone_name: str | None = None,
        zone_kind: str | None = None,
        reference_area_m2: float | None = None,
        control_use: UseSpec | None = None,
    ) -> ZoneUseSpec:
        """Resolve a mixture directly into a validated native compiler zone override."""
        use, airflow = self.resolve(calendar_year=calendar_year, control_use=control_use)
        return ZoneUseSpec(
            zone_name=zone_name,
            zone_kind=zone_kind,
            use=use,
            airflow=airflow,
            reference_area_m2=reference_area_m2,
            source=self.source,
        )
