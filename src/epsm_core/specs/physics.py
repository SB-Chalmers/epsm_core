# File: specs/physics.py
# Purpose: Physics input specifications.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-10-03
# Changelog:
#   2026-10-03 - Add calendar schedules, scheduled ventilation and explicit gain fractions.
#   2026-09-06 - Document physics interfaces, examples, constraints and processing rationale.

"""Physics input specifications.

Notes
-----
Physical parameters include their dimensions in field names. Daily schedules repeat
across the selected calendar; coupled validators enforce fraction, thermostat and
airflow constraints. Optional delivery/PV records describe later accounting rather than
implicit simulation execution.

Examples
--------
Example::

    from epsm_core.specs.physics import ScheduleSpec

    schedule = ScheduleSpec.constant(21)
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import Fraction, Nonnegative, Positive, Spec
from .schedules import ScheduleSpec


class ClimateSpec(Spec):
    """Local EPW identity, site metadata and requested simulation calendar.

    Attributes
    ----------
    epw_path : str
        Local EPW path; contents are identified separately by weather_sha256.  Required at
        construction.
    weather_sha256 : str
        Expected lowercase SHA-256 weather-file digest. Must match pattern '^[0-9a-f]{64}$'.
        Required at construction.
    latitude_deg : float
        Site latitude or longitude in geographic degrees. At least -90. At most 90. Required
        at construction.
    longitude_deg : float
        Site latitude or longitude in geographic degrees. At least -180. At most 180.
        Required at construction.
    elevation_m : float
        Elevation above the scene datum or sea level for climate metadata, in metres.
        Required at construction.
    time_zone_hours : float
        Local standard time offset from UTC, in hours; no daylight-saving policy is
        inferred. At least -12. At most 14. Required at construction.
    calendar_year : int
        Gregorian simulation year used for exact hourly coverage checks. At least 1900. At
        most 2200. Default: ``2023``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    The checksum has exactly 64 lowercase hexadecimal characters. Construction validates
    metadata but does not read the file; checksum and full hourly coverage are verified by
    downstream workflows.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import ClimateSpec

        climate = ClimateSpec(
            epw_path="example.epw",
            weather_sha256="0" * 64,
            latitude_deg=57,
            longitude_deg=12,
            elevation_m=0,
            time_zone_hours=1,
        )
    """

    epw_path: str
    weather_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    latitude_deg: Annotated[float, Field(ge=-90, le=90)]
    longitude_deg: Annotated[float, Field(ge=-180, le=180)]
    elevation_m: float
    time_zone_hours: Annotated[float, Field(ge=-12, le=14)]
    calendar_year: Annotated[int, Field(ge=1900, le=2200)] = 2023

    @property
    def hours_in_year(self):
        """Count hours in the selected Gregorian calendar year.

        Returns
        -------
        int
            8760 in an ordinary year or 8784 in a leap year.

        Notes
        -----
        This describes the requested calendar; it does not verify the EPW records.

        Examples
        --------
        Example::

            from epsm_core.specs.physics import ClimateSpec

            climate = ClimateSpec(
                epw_path="example.epw",
                weather_sha256="0" * 64,
                latitude_deg=57,
                longitude_deg=12,
                elevation_m=0,
                time_zone_hours=1,
                calendar_year=2024,
            )
            assert climate.hours_in_year == 8784
        """

        import calendar

        return (366 if calendar.isleap(self.calendar_year) else 365) * 24


class MaterialSpec(Spec):
    """Nominal opaque-material transport, storage and surface properties.

    Attributes
    ----------
    name : str
        Identifier or field name interpreted by the current operation.  Required at
        construction.
    conductivity_w_mk : Positive
        Nominal thermal conductivity in W/(m K). Strictly positive when supplied. Required
        at construction.
    density_kg_m3 : Positive
        Nominal bulk density in kg/m3 for heat capacity and physical quantities. Strictly
        positive when supplied. Required at construction.
    specific_heat_j_kgk : float
        Specific heat capacity in J/(kg K), with a minimum of 100. At least 100. Required at
        construction.
    solar_absorptance : Fraction
        Dimensionless surface absorptance in the named radiation band. In [0, 1] when
        supplied. Default: ``0.7``.
    thermal_absorptance : Fraction
        Dimensionless surface absorptance in the named radiation band. In [0, 1] when
        supplied. Default: ``0.9``.
    visible_absorptance : Fraction
        Dimensionless surface absorptance in the named radiation band. In [0, 1] when
        supplied. Default: ``0.7``.
    roughness : Literal['VeryRough', 'Rough', 'MediumRough', 'MediumSmooth', 'Smooth', 'VerySmooth']
        EnergyPlus surface roughness category.  Default: ``'MediumRough'``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Conductivity and density are positive; specific heat is at least 100 J/(kg K).
    Absorptances are dimensionless fractions. Nominal values remain the basis for quantity
    takeoffs.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import MaterialSpec

        material = MaterialSpec(
            name="concrete",
            conductivity_w_mk=1.7,
            density_kg_m3=2300,
            specific_heat_j_kgk=880,
        )
    """

    name: str
    conductivity_w_mk: Positive
    density_kg_m3: Positive
    specific_heat_j_kgk: Annotated[float, Field(ge=100)]
    solar_absorptance: Fraction = 0.7
    thermal_absorptance: Fraction = 0.9
    visible_absorptance: Fraction = 0.7
    roughness: Literal[
        "VeryRough", "Rough", "MediumRough", "MediumSmooth", "Smooth", "VerySmooth"
    ] = "MediumRough"


class LayerSpec(Spec):
    """One homogeneous material layer with positive physical thickness.

    Attributes
    ----------
    material : MaterialSpec
        Nominal homogeneous material properties.  Required at construction.
    thickness_m : Positive
        Positive physical layer thickness in metres. Strictly positive when supplied.
        Required at construction.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Thickness is in metres. Layer order comes from the containing construction; the layer
    itself has no orientation.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import LayerSpec
        from epsm_core.specs.physics import MaterialSpec

        material = MaterialSpec(
            name="concrete",
            conductivity_w_mk=1.7,
            density_kg_m3=2300,
            specific_heat_j_kgk=880,
        )
        layer = LayerSpec(material=material, thickness_m=0.2)
    """

    material: MaterialSpec
    thickness_m: Positive


class ConstructionSpec(Spec):
    """Opaque assembly with layers ordered outside to inside.

    Attributes
    ----------
    layers : tuple[LayerSpec, ...]
        One to ten layers ordered outside to inside. Minimum length 1. Maximum length 10.
        Required at construction.
    surface_resistance_m2k_w : Nonnegative
        Combined reporting film resistance in m2 K/W; not an emitted material layer.
        Nonnegative when supplied. Default: ``0.17``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Contains one to ten layers. Film resistance is reporting metadata; EnergyPlus determines
    surface heat transfer separately. Reciprocal faces use reversed layer order.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import ConstructionSpec
        from epsm_core.specs.physics import LayerSpec
        from epsm_core.specs.physics import MaterialSpec

        material = MaterialSpec(
            name="concrete",
            conductivity_w_mk=1.7,
            density_kg_m3=2300,
            specific_heat_j_kgk=880,
        )
        assembly = ConstructionSpec(
            layers=(LayerSpec(material=material, thickness_m=0.2),)
        )
    """

    layers: Annotated[tuple[LayerSpec, ...], Field(min_length=1, max_length=10)]
    surface_resistance_m2k_w: Nonnegative = 0.17

    @property
    def u_value_w_m2k(self):
        """Calculate steady-state conductance including reporting film resistance.

        Returns
        -------
        float
            U-value in W/(m2 K).

        Notes
        -----
        Layers contribute thickness/conductivity. EnergyPlus applies its own surface heat
        transfer; surface_resistance_m2k_w is reporting metadata, not a separately emitted
        material layer.

        Examples
        --------
        Example::

            from epsm_core.specs.physics import ConstructionSpec
            from epsm_core.specs.physics import LayerSpec
            from epsm_core.specs.physics import MaterialSpec

            material = MaterialSpec(
                name="concrete",
                conductivity_w_mk=1.7,
                density_kg_m3=2300,
                specific_heat_j_kgk=880,
            )
            assembly = ConstructionSpec(
                layers=(LayerSpec(material=material, thickness_m=0.2),)
            )
            assert assembly.u_value_w_m2k > 0
        """

        return 1 / (
            self.surface_resistance_m2k_w
            + sum(x.thickness_m / x.material.conductivity_w_mk for x in self.layers)
        )


class GroundTemperatureSpec(Spec):
    """Monthly temperatures outside ground-contact constructions.

    Attributes
    ----------
    monthly_temperatures_c : tuple[float, ...]
        Twelve ground-contact outside-boundary temperatures in Celsius, January through
        December. Minimum length 12. Maximum length 12. Default: ``(18.0,) * 12``.
    source : str
        Evidence source assigned to supplied leaves. Minimum length 1. Default:
        ``'energyplus_24_2_default_18C_uncalibrated'``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Exactly twelve Celsius values are required. The explicit 18 C default is an uncalibrated
    EnergyPlus boundary assumption, not Swedish soil calibration; undisturbed EPW soil
    temperatures are not interchangeable.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import GroundTemperatureSpec

        ground = GroundTemperatureSpec()
    """

    monthly_temperatures_c: Annotated[tuple[float, ...], Field(min_length=12, max_length=12)] = (
        18.0,
    ) * 12
    source: Annotated[str, Field(min_length=1, pattern=r"\S")] = "energyplus_24_2_default_18C_uncalibrated"


class FoundationSpec(Spec):
    """Ground heat-transfer method and explicit, uncalibrated Kiva assumptions.

    Kiva uses existing envelope constructions and geometry. The default soil and
    footing properties are EnergyPlus 24.2 defaults, not site measurements. The
    exposed fraction scales the geometric exterior perimeter, never zone partitions.
    Optional footing material thickness defines its width in EnergyPlus.
    """

    method: Literal["kiva", "prescribed_temperature"] = "kiva"
    soil_conductivity_w_mk: Positive = 1.73
    soil_density_kg_m3: Positive = 1842.0
    soil_specific_heat_j_kgk: Positive = 419.0
    exposed_perimeter_fraction: Fraction = 1.0
    wall_height_above_grade_m: Nonnegative = 0.0
    wall_depth_below_slab_m: Nonnegative = 0.0
    footing_depth_m: Positive = 0.3
    footing_material: MaterialSpec | None = None
    footing_width_m: Positive = 0.3
    footing_wall: ConstructionSpec | None = None
    deep_ground_boundary: Literal["ZeroFlux", "GroundWater"] = "ZeroFlux"
    deep_ground_depth_m: Positive = 40.0
    far_field_width_m: Positive = 40.0
    source: Annotated[str, Field(min_length=1, pattern=r"\S")] = "energyplus_24_2_kiva_unmeasured_defaults"


class EnvelopeSpec(Spec):
    """Explicit nominal assemblies for each thermal boundary role.

    Attributes
    ----------
    wall : ConstructionSpec
        Nominal assembly for the named envelope or partition role; optional roles must be
        supplied when the selected topology requires them.  Required at construction.
    top : ConstructionSpec
        Nominal assembly for the named envelope or partition role; optional roles must be
        supplied when the selected topology requires them.  Required at construction.
    ground : ConstructionSpec
        Nominal assembly for the named envelope or partition role; optional roles must be
        supplied when the selected topology requires them.  Required at construction.
    intermediate_floor : ConstructionSpec
        Nominal assembly for the named envelope or partition role; optional roles must be
        supplied when the selected topology requires them.  Required at construction.
    weather_shell : ConstructionSpec
        Nominal assembly for the named envelope or partition role; optional roles must be
        supplied when the selected topology requires them.  Required at construction.
    basement_wall : ConstructionSpec
        Nominal assembly for the named envelope or partition role; optional roles must be
        supplied when the selected topology requires them.  Required at construction.
    basement_ceiling : ConstructionSpec | None
        Nominal assembly for the named envelope or partition role; optional roles must be
        supplied when the selected topology requires them.  Default: ``None``.
    dwelling_partition : ConstructionSpec | None
        Nominal assembly for the named envelope or partition role; optional roles must be
        supplied when the selected topology requires them.  Default: ``None``.
    common_partition : ConstructionSpec | None
        Nominal assembly for the named envelope or partition role; optional roles must be
        supplied when the selected topology requires them.  Default: ``None``.
    thermal_bridge_uplift_fraction : Nonnegative
        Nonnegative fractional U-value increase represented through equivalent
        conductivities. Nonnegative when supplied. Default: ``0``.
    foundation : FoundationSpec
        Ground heat-transfer method and assumptions. Default: Kiva.
    ground_temperature : GroundTemperatureSpec | None
        Explicit legacy monthly boundary; supplying it selects prescribed temperatures.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Basement ceiling and residential partition assemblies are optional until required by
    building topology. Thermal-bridge uplift is an equivalent conductance adjustment;
    weather-shell and unconditioned roles are handled separately by the compiler.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import ConstructionSpec
        from epsm_core.specs.physics import EnvelopeSpec
        from epsm_core.specs.physics import LayerSpec
        from epsm_core.specs.physics import MaterialSpec

        material = MaterialSpec(
            name="concrete",
            conductivity_w_mk=1.7,
            density_kg_m3=2300,
            specific_heat_j_kgk=880,
        )
        assembly = ConstructionSpec(
            layers=(LayerSpec(material=material, thickness_m=0.2),)
        )
        envelope = EnvelopeSpec(
            wall=assembly,
            top=assembly,
            ground=assembly,
            intermediate_floor=assembly,
            weather_shell=assembly,
            basement_wall=assembly,
        )
    """

    wall: ConstructionSpec
    top: ConstructionSpec
    ground: ConstructionSpec
    intermediate_floor: ConstructionSpec
    weather_shell: ConstructionSpec
    basement_wall: ConstructionSpec
    basement_ceiling: ConstructionSpec | None = None
    dwelling_partition: ConstructionSpec | None = None
    common_partition: ConstructionSpec | None = None
    thermal_bridge_uplift_fraction: Nonnegative = 0
    foundation: FoundationSpec = Field(default_factory=FoundationSpec)
    ground_temperature: GroundTemperatureSpec | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_ground_boundary(cls, values):
        if isinstance(values, dict):
            values = dict(values)
            if values.get("ground_temperature") is not None and "foundation" not in values:
                values["foundation"] = {"method": "prescribed_temperature"}
        return values

    @model_validator(mode="after")
    def validate_ground_boundary(self):
        if self.foundation.method == "kiva" and self.ground_temperature is not None:
            raise ValueError("Kiva conflicts with prescribed ground temperatures")
        if self.foundation.method == "prescribed_temperature" and self.ground_temperature is None:
            raise ValueError("Prescribed ground treatment requires ground_temperature")
        return self

    def updated(self, **changes):
        # An explicit legacy profile continues to select the legacy method.
        if changes.get("ground_temperature") is not None and "foundation" not in changes:
            changes["foundation"] = FoundationSpec(method="prescribed_temperature")
        return super().updated(**changes)


class AirflowSpec(Spec):
    """Separate envelope leakage, ventilation and air-to-air recovery inputs.

    Attributes
    ----------
    topology : Literal['S', 'F', 'FT', 'FTX']
        Thermal or airflow topology selected from the annotated supported values.  Required
        at construction.
    envelope_infiltration_ach : Nonnegative
        Nonnegative air changes per hour for envelope leakage or natural self-draught
        exchange. Nonnegative when supplied. Required at construction.
    natural_exchange_ach : Nonnegative
        Nonnegative air changes per hour for envelope leakage or natural self-draught
        exchange. Nonnegative when supplied. Default: ``0``.
    mechanical_vent_l_s_m2 : Nonnegative
        Mechanical outdoor-air volume flow per conditioned area, in litres/(second m2).
        Nonnegative when supplied. Default: ``0``.
    sensible_recovery_effectiveness : Fraction
        Dimensionless air-to-air heat-recovery effectiveness; only FTX permits nonzero
        values. In [0, 1] when supplied. Default: ``0``.
    latent_recovery_effectiveness : Fraction
        Dimensionless air-to-air heat-recovery effectiveness; only FTX permits nonzero
        values. In [0, 1] when supplied. Default: ``0``.
    maximum_heating_supply_temperature_c : float
        Ideal-loads supply-air temperature limit in degrees Celsius.  Default: ``50``.
    minimum_cooling_supply_temperature_c : float
        Ideal-loads supply-air temperature limit in degrees Celsius.  Default: ``13``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    S is natural self-draught, F exhaust, FT supply/exhaust and FTX supply/exhaust with
    recovery. Only FTX accepts recovery; S rejects mechanical flow and other topologies
    reject natural_exchange_ach.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import AirflowSpec

        airflow = AirflowSpec(
            topology="FTX",
            envelope_infiltration_ach=0.2,
            mechanical_vent_l_s_m2=0.35,
            sensible_recovery_effectiveness=0.7,
        )
    """

    # Schedule fractions modulate outdoor air only, never background leakage.
    # EnergyPlus 24.2 I/O Reference, ZoneInfiltration:DesignFlowRate:
    # rate = design * schedule * (C + T*abs(deltaT) + V*wind + W*wind**2).
    # Effective coefficients are scenario inputs, never inferred leakage tests.
    infiltration_fraction: ScheduleSpec = ScheduleSpec.constant(1)
    natural_exchange_fraction: ScheduleSpec = ScheduleSpec.constant(1)
    infiltration_coefficients: tuple[Nonnegative, Nonnegative, Nonnegative, Nonnegative] = (1, 0, 0, 0)
    infiltration_source: str | None = None
    mechanical_vent_fraction: ScheduleSpec = ScheduleSpec.constant(1)
    heating_availability: ScheduleSpec = ScheduleSpec.constant(1)
    cooling_availability: ScheduleSpec = ScheduleSpec.constant(1)
    topology: Literal["S", "F", "FT", "FTX"]
    envelope_infiltration_ach: Nonnegative
    natural_exchange_ach: Nonnegative = 0
    mechanical_vent_l_s_m2: Nonnegative = 0
    sensible_recovery_effectiveness: Fraction = 0
    latent_recovery_effectiveness: Fraction = 0
    maximum_heating_supply_temperature_c: float = 50
    minimum_cooling_supply_temperature_c: float = 13

    @model_validator(mode="after")
    def compatible(self):
        """Require ventilation and heat-recovery values consistent with topology.

        Returns
        -------
        Self
            Validated airflow specification.

        Raises
        ------
        ValueError
            Rejected conditions: S cannot have mechanical outdoor air; Natural self-draught
            exchange is specific to S; Air-to-air recovery requires FTX.

        Notes
        -----
        S disallows mechanical outdoor air; natural self-draught exchange is specific to S.
        Sensible or latent air-to-air recovery requires FTX. Envelope infiltration remains
        independent.

        Examples
        --------
        Example::

            from epsm_core.specs.physics import AirflowSpec

            airflow = AirflowSpec(topology="S", envelope_infiltration_ach=0.2)
            assert airflow.compatible() is airflow
        """

        for name in ("infiltration_fraction", "natural_exchange_fraction", "mechanical_vent_fraction", "heating_availability", "cooling_availability"):
            if any(not 0 <= v <= 1 for v in getattr(self, name).all_values):
                raise ValueError(f"{name} must lie in [0,1]")
        if self.infiltration_coefficients != (1, 0, 0, 0) and (
            not self.infiltration_source or not self.infiltration_source.strip()
        ):
            raise ValueError("Weather-dependent infiltration requires a documented source")
        # 1. Require ventilation and heat-recovery values consistent with topology.
        if self.topology == "S" and self.mechanical_vent_l_s_m2:
            raise ValueError("S cannot have mechanical outdoor air")
        if self.topology != "S" and self.natural_exchange_ach:
            raise ValueError("Natural self-draught exchange is specific to S")
        if self.topology != "FTX" and (
            self.sensible_recovery_effectiveness or self.latent_recovery_effectiveness
        ):
            raise ValueError("Air-to-air recovery requires FTX")
        return self


class UseSpec(Spec):
    """Occupancy, gains, thermostat profiles and annual hot-water demand.

    Attributes
    ----------
    occupancy_category : Literal['unspecified', 'residential', 'non_residential']
        Explicit building-use classification; apartment generation requires residential.
        Default: ``'unspecified'``.
    heating_setpoint : ScheduleSpec
        Daily thermostat temperatures in Celsius; heating must remain strictly below
        cooling.  Required at construction.
    cooling_setpoint : ScheduleSpec
        Daily thermostat temperatures in Celsius; heating must remain strictly below
        cooling.  Default: ``ScheduleSpec.constant(30)``.
    cooling_enabled : bool
        Enable ideal cooling availability; thermostat consistency is still validated when
        false.  Default: ``False``.
    occupancy_fraction : ScheduleSpec
        Daily activity fractions constrained to [0, 1] by UseSpec.  Default:
        ``ScheduleSpec.constant(1)``.
    equipment_fraction : ScheduleSpec
        Daily activity fractions constrained to [0, 1] by UseSpec.  Default:
        ``ScheduleSpec.constant(1)``.
    lighting_fraction : ScheduleSpec
        Daily activity fractions constrained to [0, 1] by UseSpec.  Default:
        ``ScheduleSpec.constant(1)``.
    dhw_fraction : ScheduleSpec
        Daily activity fractions constrained to [0, 1] by UseSpec.  Default:
        ``ScheduleSpec.constant(1)``.
    occupant_density_per_m2 : Nonnegative
        Occupant count per conditioned floor square metre. Nonnegative when supplied.
        Required at construction.
    occupant_activity_w : Positive
        Heat release per occupant in watts. Strictly positive when supplied. Default:
        ``120``.
    equipment_gain_w_m2 : Nonnegative
        Design equipment electrical input per load-reference square metre, in watts.
        equipment_heat_fraction gives the zone heat share; its default of one preserves
        the legacy available-heat interpretation. Required at construction.
    lighting_gain_w_m2 : Nonnegative
        Design internal heat gain per conditioned square metre, in watts. Nonnegative when
        supplied. Default: ``0``.
    dhw_kwh_m2_year : Nonnegative
        Annual domestic hot-water thermal demand per conditioned square metre, in kWh.
        Nonnegative when supplied. Required at construction.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Fraction schedules must remain in [0, 1]; positive DHW demand needs an active schedule.
    Heating stays below cooling at every hour. occupancy_category must be residential for
    apartment zoning.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import ScheduleSpec
        from epsm_core.specs.physics import UseSpec

        use = UseSpec(
            heating_setpoint=ScheduleSpec.constant(21),
            occupant_density_per_m2=0.02,
            equipment_gain_w_m2=2,
            dhw_kwh_m2_year=20,
        )
    """

    # EnergyPlus ElectricEquipment Fraction Lost distinguishes electrical input from
    # zone heat (Sveby office 1.0 Table 2.2: 70% available heat). Default preserves API.
    equipment_heat_fraction: Fraction = 1
    occupancy_category: Literal["unspecified", "residential", "non_residential"] = "unspecified"
    heating_setpoint: ScheduleSpec
    cooling_setpoint: ScheduleSpec = ScheduleSpec.constant(30)
    cooling_enabled: bool = False
    occupancy_fraction: ScheduleSpec = ScheduleSpec.constant(1)
    equipment_fraction: ScheduleSpec = ScheduleSpec.constant(1)
    lighting_fraction: ScheduleSpec = ScheduleSpec.constant(1)
    dhw_fraction: ScheduleSpec = ScheduleSpec.constant(1)
    occupant_density_per_m2: Nonnegative
    occupant_activity_w: Positive = 120
    equipment_gain_w_m2: Nonnegative
    lighting_gain_w_m2: Nonnegative = 0
    dhw_kwh_m2_year: Nonnegative

    @model_validator(mode="after")
    def schedules(self):
        """Validate fractional schedules, DHW activity and the thermostat deadband.

        Returns
        -------
        Self
            Validated use specification.

        Raises
        ------
        ValueError
            Rejected conditions: Nonzero DHW demand requires a nonzero schedule; Heating
            setpoint must remain below cooling setpoint.

        Notes
        -----
        Fraction profiles must remain in [0, 1]. Nonzero annual DHW requires a nonzero daily
        profile. Heating must remain strictly below cooling even when cooling is disabled.

        Examples
        --------
        Example::

            from epsm_core.specs.physics import ScheduleSpec
            from epsm_core.specs.physics import UseSpec

            use = UseSpec(
                heating_setpoint=ScheduleSpec.constant(21),
                occupant_density_per_m2=0.02,
                equipment_gain_w_m2=2,
                dhw_kwh_m2_year=20,
            )
            assert use.schedules() is use
        """

        # 1. Validate fractional schedules, DHW activity and the thermostat deadband.
        for name in (
            "occupancy_fraction",
            "equipment_fraction",
            "lighting_fraction",
            "dhw_fraction",
        ):
            if any(not 0 <= v <= 1 for v in getattr(self, name).all_values):
                raise ValueError(f"{name} must lie in [0,1]")
        if self.dhw_kwh_m2_year and not sum(self.dhw_fraction.all_values):
            raise ValueError("Nonzero DHW demand requires a nonzero schedule")
        years = self.heating_setpoint.declared_years | self.cooling_setpoint.declared_years
        if len(years) > 1:
            raise ValueError("Setpoint calendars must refer to the same year")
        # Undated profiles need only seven aligned weekdays; dated/annual
        # profiles are checked on their actual Gregorian axis (including leap day).
        if years:
            year = next(iter(years))
            pairs = zip(self.heating_setpoint.hourly(year), self.cooling_setpoint.hourly(year))
        else:
            heat = self.heating_setpoint.weekday_values or (self.heating_setpoint.values,) * 7
            cool = self.cooling_setpoint.weekday_values or (self.cooling_setpoint.values,) * 7
            pairs = ((h, c) for hd, cd in zip(heat, cool) for h, c in zip(hd, cd))
        for h, c in pairs:
            if h >= c:
                raise ValueError("Heating setpoint must remain below cooling setpoint")
        return self


class FVPSpec(Spec):
    """Constant-COP exhaust-air heat-pump delivery assumptions.

    Attributes
    ----------
    cop : float
        Constant heating coefficient of performance, strictly greater than one. Greater than
        1. Required at construction.
    capacity_kw : Positive
        Maximum heat-pump thermal output in kW. Strictly positive when supplied. Required at
        construction.
    exhaust_min_temperature_c : float
        Minimum exhaust temperature after sensible extraction, in Celsius.  Default: ``5``.
    dhw_priority : bool
        Serve hot-water demand before space heating when true.  Default: ``True``.
    backup_efficiency : float
        Useful heat divided by backup input energy, in (0, 1]. Greater than 0. At most 1.
        Default: ``1``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    COP exceeds one, capacity is positive and backup efficiency is in (0, 1]. Source heat is
    sensible-only in fvp_delivery; a complete BuildingSpec requires F ventilation.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import FVPSpec

        fvp = FVPSpec(cop=3, capacity_kw=5)
    """

    cop: Annotated[float, Field(gt=1)]
    capacity_kw: Positive
    exhaust_min_temperature_c: float = 5
    dhw_priority: bool = True
    backup_efficiency: Annotated[float, Field(gt=0, le=1)] = 1


class HeatingDeliverySpec(Spec):
    """Declared space-heat carrier model with separately reported net losses.

    Constant efficiency is useful thermal output / carrier input. Heat-pump COP
    is an explicit caller curve in local standard time, not inferred from EPC
    electricity. Net distribution losses exclude heat already represented in the
    building demand. See heating_delivery.py for dimensions and energy boundary.
    This does not claim detailed HVAC or fan-heat coupling.
    """

    carrier: Literal["district_heat", "electric_direct", "fuel", "heat_pump"]
    efficiency: Annotated[float, Field(gt=0, le=1)] = 1
    heat_pump_cop: ScheduleSpec | None = None
    net_distribution_loss_kwh_m2_year: Nonnegative = 0
    loss_fraction: ScheduleSpec = ScheduleSpec.constant(1)
    specific_fan_power_w_per_l_s: Nonnegative | None = None
    source: Annotated[str, Field(min_length=1, pattern=r"\S")]

    @model_validator(mode="after")
    def boundary(self):
        """Require a COP only for heat pumps and a physical loss fraction."""
        if (self.carrier == "heat_pump") != (self.heat_pump_cop is not None):
            raise ValueError("Heat-pump delivery requires an explicit COP; other carriers forbid it")
        if self.heat_pump_cop is not None and min(self.heat_pump_cop.all_values) <= 0:
            raise ValueError("Declared heat-pump COP must be positive")
        if any(not 0 <= v <= 1 for v in self.loss_fraction.all_values):
            raise ValueError("Loss fraction must lie in [0,1]")
        if self.net_distribution_loss_kwh_m2_year and not sum(self.loss_fraction.all_values):
            raise ValueError("Net distribution losses require an active schedule")
        return self


class DeliverySpec(Spec):
    """Optional downstream conversion from ideal loads to delivered energy.

    Attributes
    ----------
    fvp : FVPSpec | None
        Optional exhaust-air heat-pump delivery model; None disables this accounting.
        Default: ``None``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    An absent FVP leaves ideal demand without a heat-pump accounting model. Delivery
    calculations occur after validated EnergyPlus results.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import DeliverySpec
        from epsm_core.specs.physics import FVPSpec

        delivery = DeliverySpec(fvp=FVPSpec(cop=3, capacity_kw=5))
    """

    fvp: FVPSpec | None = None
    heating: HeatingDeliverySpec | None = None

    @model_validator(mode="after")
    def exclusive(self):
        """Do not apply two incompatible delivery conversions to the same heat."""
        if self.fvp is not None and self.heating is not None:
            raise ValueError("FVP and general heating delivery are mutually exclusive")
        return self


class PVSpec(Spec):
    """Explicit system-design inputs forwarded to PVWatts V8.

    Attributes
    ----------
    dc_capacity_kw : Positive
        Positive installed DC PV capacity in kW. Strictly positive when supplied. Required
        at construction.
    tilt_deg : float
        PV inclination from horizontal in degrees. At least 0. At most 90. Default: ``30``.
    azimuth_deg : float
        Clockwise azimuth from north in degrees; 180 faces south. At least 0. Less than 360.
        Default: ``180``.
    dc_ac_ratio : Positive
        DC nameplate capacity divided by inverter AC rating. Strictly positive when
        supplied. Default: ``1.15``.
    inverter_efficiency_pct : float
        PVWatts inverter efficiency or system loss input in percent, not fraction. Greater
        than 0. At most 100. Default: ``96``.
    system_losses_pct : float
        PVWatts inverter efficiency or system loss input in percent, not fraction. At least
        0. Less than 100. Default: ``14.08``.
    array_type : int
        PVWatts categorical integer selecting mounting or module technology. At least 0. At
        most 4. Default: ``1``.
    module_type : int
        PVWatts categorical integer selecting mounting or module technology. At least 0. At
        most 2. Default: ``0``.
    ground_coverage_ratio : float
        PV array ground-coverage fraction in (0, 1]. Greater than 0. At most 1. Default:
        ``0.4``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Capacity is DC kW. Efficiencies/losses are percentages, while ground coverage is a
    fraction. Integer array/module categories follow the PVWatts interface; evaluating
    output requires epsm_core[pv].

    Examples
    --------
    Example::

        from epsm_core.specs.physics import PVSpec

        pv = PVSpec(dc_capacity_kw=5, tilt_deg=30, azimuth_deg=180)
    """

    dc_capacity_kw: Positive
    tilt_deg: Annotated[float, Field(ge=0, le=90)] = 30
    azimuth_deg: Annotated[float, Field(ge=0, lt=360)] = 180
    dc_ac_ratio: Positive = 1.15
    inverter_efficiency_pct: Annotated[float, Field(gt=0, le=100)] = 96
    system_losses_pct: Annotated[float, Field(ge=0, lt=100)] = 14.08
    array_type: Annotated[int, Field(ge=0, le=4)] = 1
    module_type: Annotated[int, Field(ge=0, le=2)] = 0
    ground_coverage_ratio: Annotated[float, Field(gt=0, le=1)] = 0.4


class RenewablesSpec(Spec):
    """Collection of independent PV systems sharing the building weather input.

    Attributes
    ----------
    pv_systems : tuple[PVSpec, ...]
        PV systems evaluated independently and summed on the shared hourly calendar.
        Default: ``()``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    The runner evaluates each system and sums hourly generation. An empty tuple disables PV
    evaluation without requiring the optional backend.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import PVSpec
        from epsm_core.specs.physics import RenewablesSpec

        renewables = RenewablesSpec(pv_systems=(PVSpec(dc_capacity_kw=5),))
    """

    pv_systems: tuple[PVSpec, ...] = ()
