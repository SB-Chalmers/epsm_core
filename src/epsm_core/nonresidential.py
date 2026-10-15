# File: nonresidential.py
# Purpose: Source-pinned Sveby office and school operation profiles.
# SPDX-License-Identifier: MIT
# Date created: 2026-10-03
# References: Sveby Brukarindata kontor 1.0 (2012), Table 2.2, chapters 5/8/10;
# Sveby Brukarindata undervisningsbyggnader 1.0 (2016), Table 2.2, chapter 9.
"""Published normal-use inputs with explicit project calendars and completion choices.

Office 2.0 was advertised as a draft at source review; this module deliberately
loads the published 2012 release. School means primary/secondary school, not
preschool or university. Normal-use calendars need 225 office days or 220 school
days; their dates come from the caller. No eight-week vacation is invented.

Business electrical input and zone heat are distinguished: the office's 50
kWh/m2/year electrical input is represented by one combined equivalent equipment
load, with 70% transferred to the zone as the Table 2.2 thermal approximation.
This is not a measured split between lighting and equipment or a full HVAC model.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from functools import partial

from epsm_data import load_operating_profile

from .specs import ScheduleSpec, UseSpec
from .standards import _freeze


def _active_schedule(year, dates, start, hours, *, on=1.0, off=0.0, source=None):
    """Resolve caller dates to local-standard-time hour-start intervals."""
    if not 0 <= start <= 23 or not 1 <= hours <= 24 or start + hours > 24:
        raise ValueError("Daily operating interval must lie within [00:00,24:00]")
    active = set(dates)
    values = []
    current = date(year, 1, 1)
    while current.year == year:
        values.extend(
            on if current in active and start <= h < start + hours else off for h in range(24)
        )
        current += timedelta(days=1)
    return ScheduleSpec.annual(values, calendar_year=year, source=source)


class SvebyNonResidentialSpec:
    """Versioned normal-use source data; caller observations remain separate.

    Data's loaders select definitions and validate packaged source identities.
    Calendar dates, standby fraction and clock placement are explicit assumptions,
    not additional values claimed to be published by Sveby.
    """

    def __init__(self, data):
        """Copy a supported office/school layout, leaving selection to Data."""
        self.data = _freeze(deepcopy(data))
        self.building_use = self.data["building_use"]
        if self.building_use not in {"office", "school"}:
            raise ValueError("Unsupported Sveby non-residential use")
        if self.data["schema_version"] != 1:
            raise ValueError("Unsupported non-residential input schema")

    @property
    def profile_id(self):
        """Versioned source identity recorded in run provenance."""
        return self.data["profile_id"]

    @property
    def source_uri(self):
        """Official published source PDF URI."""
        return self.data["source_uri"]

    def building_assumptions(
        self,
        *,
        calendar_year,
        active_dates,
        calendar_source,
        zone_role="classrooms",
        normal_use=True,
        fixed_solar_shading_calculated=False,
        cooling_enabled=None,
        standby_fraction=None,
    ):
        """Build a partial, reproducible operation profile on a caller calendar.

        Parameters
        ----------
        calendar_year : int
            Gregorian simulation year; exact dates must belong to this year.
        active_dates : sequence of ISO date strings or dates
            Distinct active dates. Normal-use calendars must have the reference
            count and weekdays only. Actual-use calendars can differ when
            ``normal_use=False``; their source must document that distinction.
        calendar_source : str
            Nonempty evidence/assumption description; dates are stored in schedules.
        zone_role : str
            School classrooms, service, kitchen_dining or sports. Office uses one
            whole-office equivalent load. Other activities require explicit inputs.
        normal_use : bool
            Enforce Sveby's aggregate active-day count, not a guessed holiday list.
        standby_fraction : float
            Office off-hour electrical fraction relative to on-hour input. 0.2
            is an EPSM completion assumption, not a Sveby prescribed value.

        Notes
        -----
        Calendar and source are required even for a default profile. School
        operation is 07:00-17:00, occupancy 09:00-15:00: these clock placements
        are EPSM choices; Table 2.2 prescribes durations only. Kitchen/sport
        base/boost phases split the ten operating hours equally. Heating stays
        enabled year-round, including holidays; ventilation closure does not
        disable the thermostat. No fan electricity or window-airing addition is
        silently included. School cooling is absent unless explicitly supplied.
        """
        dates = tuple(date.fromisoformat(x) if isinstance(x, str) else x for x in active_dates)
        if any(type(d) is not date for d in dates):
            raise ValueError("Active dates must be Gregorian dates without a time component")
        if not calendar_source or not calendar_source.strip():
            raise ValueError("A project calendar source is required")
        if (
            not dates
            or len(set(dates)) != len(dates)
            or any(d.year != calendar_year for d in dates)
        ):
            raise ValueError("Active dates must be distinct, nonempty and in the simulation year")
        if normal_use and (
            len(dates) != self.data["reference_active_days"] or any(d.weekday() > 4 for d in dates)
        ):
            raise ValueError("Normal-use calendar must match the source weekday/day count")
        completion = self.data["completion_inputs"]
        inputs = self.data["operation_inputs"]
        if cooling_enabled is None:
            cooling_enabled = completion["cooling_enabled"]
        if standby_fraction is None:
            standby_fraction = completion.get("standby_fraction", 0)
        if not 0 <= standby_fraction <= 1:
            raise ValueError("Standby fraction must lie in [0,1]")
        make = partial(_active_schedule, calendar_year, dates, source=calendar_source)
        data = self.data["use"]
        if self.building_use == "office":
            start, hours = inputs["occupancy_start_hour"], inputs["occupancy_hours"]
            occupancy = make(start, hours, on=inputs["occupancy_on_fraction"])
            equipment = make(start, hours, off=standby_fraction)
            # Preserve source annual electrical input under every explicit calendar.
            watts = data["business_electricity_kwh_m2_year"] * 1000 / sum(equipment.annual_values)
            use = UseSpec(
                occupancy_category=inputs["occupancy_category"],
                heating_setpoint=ScheduleSpec.constant(data["heating_setpoint_c"]),
                cooling_setpoint=ScheduleSpec.constant(data["cooling_setpoint_c"]),
                cooling_enabled=cooling_enabled,
                occupancy_fraction=occupancy,
                occupant_density_per_m2=inputs["occupant_density_per_m2"],
                occupant_activity_w=inputs["occupant_activity_w"],
                equipment_gain_w_m2=watts,
                equipment_heat_fraction=data["available_heat_fraction"],
                equipment_fraction=equipment,
                dhw_kwh_m2_year=data["dhw_kwh_m2_year"],
                dhw_fraction=make(start, hours),
            )
            flow = data["mechanical_vent_l_s_m2"]
            ventilation = make(inputs["ventilation_start_hour"], inputs["ventilation_hours"])
        else:
            if zone_role not in inputs["zone_roles"]:
                raise ValueError("Unknown school zone role")
            service = zone_role == "service"
            operating = make(completion["operating_start_hour"], completion["operating_hours"])
            use = UseSpec(
                occupancy_category=inputs["occupancy_category"],
                heating_setpoint=ScheduleSpec.constant(inputs["service_heating_setpoint_c"]
                                                       if service else data["heating_setpoint_c"]),
                cooling_setpoint=ScheduleSpec.constant(completion["cooling_setpoint_c"]),
                cooling_enabled=cooling_enabled,
                occupant_density_per_m2=0 if service else inputs["occupant_density_per_m2"],
                occupant_activity_w=inputs["occupant_activity_w"],
                occupancy_fraction=make(completion["occupancy_start_hour"],
                                        completion["occupancy_hours"]),
                equipment_gain_w_m2=0 if service else inputs["equipment_gain_w_m2"],
                lighting_gain_w_m2=0 if service else inputs["lighting_gain_w_m2"],
                equipment_fraction=operating,
                lighting_fraction=operating,
                dhw_kwh_m2_year=data["dhw_kwh_m2_year"],
                dhw_fraction=operating,
            )
            flow = inputs["service_mechanical_vent_l_s_m2"] if service else inputs["mechanical_vent_l_s_m2"]
            ventilation = operating
            if zone_role in ("kitchen_dining", "sports"):
                flow = inputs["boost_mechanical_vent_l_s_m2"]
                base = make(completion["operating_start_hour"], completion["base_hours"],
                            on=inputs["base_mechanical_vent_l_s_m2"] / flow)
                boost = make(completion["boost_start_hour"], completion["boost_hours"])
                ventilation = ScheduleSpec.annual(
                    tuple(a + b for a, b in zip(base.annual_values, boost.annual_values)),
                    calendar_year=calendar_year,
                    source=calendar_source,
                )
        return {
            "use": use.model_dump(mode="json"),
            "airflow": {
                "mechanical_vent_l_s_m2": flow,
                "mechanical_vent_fraction": ventilation.model_dump(mode="json"),
            },
            "facade": {
                "solar_shading_factor": (
                    (completion["solar_shading_behavior_factor"] if fixed_solar_shading_calculated
                     else completion["solar_shading_total_factor"])
                    if self.building_use == "office"
                    else completion["solar_shading_behavior_factor"]
                )
            },
        }


def _load(name):
    """Read bundled source data without a network or external dataset lookup."""
    return SvebyNonResidentialSpec(load_operating_profile(name.removesuffix(".json")).to_dict()["values"])


def load_sveby_office_v1():
    """Load published office 1.0; revised chapter 5 selects 1.3 L/s/m2 Atemp.

    Table 2.2 retains 1.5. Both values and their discrepancy are recorded in the
    resource; callers can override the flow when building/source evidence applies.
    """
    return _load("sveby_office_v1.json")


def load_sveby_school_v1():
    """Load primary/secondary school 1.0, Table 2.2 and chapter 9."""
    return _load("sveby_school_v1.json")
