"""The single, immutable simulation input schema. All numerical units are explicit."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import MultiPolygon, Polygon

Positive = Annotated[float, Field(gt=0)]
Nonnegative = Annotated[float, Field(ge=0)]
Fraction = Annotated[float, Field(ge=0, le=1)]
Point = tuple[float, float]
Ring = tuple[Point, ...]


class Spec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    def updated(self, **changes) -> Self:
        """Validated replacement; unlike model_copy(update=...), checks changed values."""
        return type(self).model_validate({**self.model_dump(), **changes})


class Footprint(Spec):
    exterior: Ring
    holes: tuple[Ring, ...] = ()

    @model_validator(mode="after")
    def valid_polygon(self):
        for ring in (self.exterior, *self.holes):
            if len(ring) < 3 or len(set(ring)) < 3:
                raise ValueError("A ring needs at least three distinct vertices")
        if not self.polygon.is_valid or self.polygon.area <= 1e-6:
            raise ValueError("Footprint must be a valid polygon with nonintersecting rings")
        return self

    @property
    def polygon(self) -> Polygon:
        return Polygon(self.exterior, self.holes)

    @classmethod
    def rectangle(cls, length_m: float, width_m: float):
        if min(length_m, width_m) <= 0:
            raise ValueError("Rectangle dimensions must be positive")
        return cls(exterior=((0, 0), (length_m, 0), (length_m, width_m), (0, width_m)))

    def scaled_to_area(self, area_m2: float):
        if area_m2 <= 0:
            raise ValueError("Area must be positive")
        scale = (area_m2 / self.polygon.area) ** 0.5
        return Footprint(
            exterior=tuple((x * scale, y * scale) for x, y in self.exterior),
            holes=tuple(tuple((x * scale, y * scale) for x, y in r) for r in self.holes),
        )

    @property
    def area_m2(self):
        return self.polygon.area

    @property
    def perimeter_m(self):
        return self.polygon.length

    @classmethod
    def l_shape(cls, length_m, width_m, cut_length_m, cut_width_m):
        if not (0 < cut_length_m < length_m and 0 < cut_width_m < width_m):
            raise ValueError("L cuts must lie strictly inside the outer rectangle")
        inner_x, inner_y = length_m - cut_length_m, width_m - cut_width_m
        return cls(
            exterior=(
                (0, 0),
                (length_m, 0),
                (length_m, inner_y),
                (inner_x, inner_y),
                (inner_x, width_m),
                (0, width_m),
            )
        )

    @classmethod
    def u_shape(cls, length_m, width_m, notch_length_m, notch_depth_m):
        if not (0 < notch_length_m < length_m and 0 < notch_depth_m < width_m):
            raise ValueError("U notch must leave positive wings and base")
        left, right = (length_m - notch_length_m) / 2, (length_m + notch_length_m) / 2
        base = width_m - notch_depth_m
        return cls(
            exterior=(
                (0, 0),
                (length_m, 0),
                (length_m, width_m),
                (right, width_m),
                (right, base),
                (left, base),
                (left, width_m),
                (0, width_m),
            )
        )


class GeometrySpec(Spec):
    footprints: tuple[Footprint, ...]
    floors: Annotated[int, Field(ge=1)]
    floor_height_m: Positive
    orientation_deg: Annotated[float, Field(ge=0, lt=360)] = 0
    zoning: Literal["whole_building", "per_storey"] = "whole_building"
    attic_height_m: Positive = 1.5
    basement_depth_m: Nonnegative = 0
    basement_conditioned: bool = False
    source_crs: str = "local_metres"

    @model_validator(mode="after")
    def valid_parts(self):
        if not self.footprints or not MultiPolygon([p.polygon for p in self.footprints]).is_valid:
            raise ValueError("Components must be nonoverlapping valid polygons")
        if self.basement_conditioned and not self.basement_depth_m:
            raise ValueError("Conditioned basement requires positive basement depth")
        return self

    @property
    def footprint_area_m2(self):
        return sum(p.polygon.area for p in self.footprints)

    @property
    def conditioned_floor_area_m2(self):
        return self.footprint_area_m2 * (self.floors + int(self.basement_conditioned))

    @property
    def conditioned_volume_m3(self):
        return self.footprint_area_m2 * (
            self.floors * self.floor_height_m + self.basement_depth_m * self.basement_conditioned
        )


class GlazingSpec(Spec):
    u_value_w_m2k: Positive
    solar_heat_gain_coefficient: Fraction
    visible_transmittance: Fraction = 0.65


class FacadeOverride(Spec):
    facade_id: str
    wwr: Fraction


class FacadeSpec(Spec):
    default_wwr: Fraction
    glazing: GlazingSpec
    overrides: tuple[FacadeOverride, ...] = ()
    solar_shading_factor: Fraction = 1

    @model_validator(mode="after")
    def unique(self):
        ids = [o.facade_id for o in self.overrides]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate facade overrides")
        if max([self.default_wwr, *(o.wwr for o in self.overrides)]) >= 0.95:
            raise ValueError("WWR must be < 0.95 to retain an opaque frame")
        return self

    def wwr_for(self, facade_id: str):
        return next((o.wwr for o in self.overrides if o.facade_id == facade_id), self.default_wwr)


class ContextBuilding(Spec):
    identifier: str
    footprints: tuple[Footprint, ...]
    height_m: Positive
    base_elevation_m: float = 0


class ContextSpec(Spec):
    buildings: tuple[ContextBuilding, ...] = ()


class ClimateSpec(Spec):
    epw_path: str
    weather_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    latitude_deg: Annotated[float, Field(ge=-90, le=90)]
    longitude_deg: Annotated[float, Field(ge=-180, le=180)]
    elevation_m: float
    time_zone_hours: Annotated[float, Field(ge=-12, le=14)]
    calendar_year: Annotated[int, Field(ge=1900, le=2200)] = 2023

    @model_validator(mode="after")
    def nonleap(self):
        import calendar

        if calendar.isleap(self.calendar_year):
            raise ValueError("The annual 8760-hour contract requires a non-leap calendar")
        return self


class MaterialSpec(Spec):
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
    material: MaterialSpec
    thickness_m: Positive


class ConstructionSpec(Spec):
    """Layers ordered outside to inside; film resistance is reporting metadata."""

    layers: Annotated[tuple[LayerSpec, ...], Field(min_length=1, max_length=10)]
    surface_resistance_m2k_w: Nonnegative = 0.17

    @property
    def u_value_w_m2k(self):
        return 1 / (
            self.surface_resistance_m2k_w
            + sum(x.thickness_m / x.material.conductivity_w_mk for x in self.layers)
        )


class KivaSpec(Spec):
    profile: str = "energyplus_24_2_default_soil"
    soil_conductivity_w_mk: Positive = 1.73
    soil_density_kg_m3: Positive = 1842
    soil_specific_heat_j_kgk: Positive = 419
    ground_solar_absorptivity: Fraction = 0.9
    ground_thermal_absorptivity: Fraction = 0.9
    ground_surface_roughness_m: Positive = 0.03
    far_field_width_m: Positive = 40
    deep_ground_boundary_condition: Literal["Autoselect", "GroundWater", "ZeroFlux"] = "Autoselect"
    deep_ground_depth_m: Positive | Literal["Autocalculate"] = "Autocalculate"
    minimum_cell_dimension_m: Positive = 0.02
    maximum_cell_growth_coefficient: Annotated[float, Field(gt=1)] = 1.5
    simulation_timestep: Literal["Hourly", "Timestep"] = "Hourly"


class EnvelopeSpec(Spec):
    wall: ConstructionSpec
    top: ConstructionSpec
    ground: ConstructionSpec
    intermediate_floor: ConstructionSpec
    weather_shell: ConstructionSpec
    basement_wall: ConstructionSpec
    roof_topology: Literal["compact", "cold_attic"]
    thermal_bridge_uplift_fraction: Nonnegative = 0
    foundation: KivaSpec = KivaSpec()


class AirflowSpec(Spec):
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
        if self.topology == "S" and self.mechanical_vent_l_s_m2:
            raise ValueError("S cannot have mechanical outdoor air")
        if self.topology != "S" and self.natural_exchange_ach:
            raise ValueError("Natural self-draught exchange is specific to S")
        if self.topology != "FTX" and (
            self.sensible_recovery_effectiveness or self.latent_recovery_effectiveness
        ):
            raise ValueError("Air-to-air recovery requires FTX")
        return self


class ScheduleSpec(Spec):
    """One daily hourly profile, repeated for every calendar day."""

    values: Annotated[tuple[float, ...], Field(min_length=24, max_length=24)]

    @classmethod
    def constant(cls, value: float):
        return cls(values=(value,) * 24)


class UseSpec(Spec):
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
        for name in (
            "occupancy_fraction",
            "equipment_fraction",
            "lighting_fraction",
            "dhw_fraction",
        ):
            if any(not 0 <= v <= 1 for v in getattr(self, name).values):
                raise ValueError(f"{name} must lie in [0,1]")
        if self.dhw_kwh_m2_year and not sum(self.dhw_fraction.values):
            raise ValueError("Nonzero DHW demand requires a nonzero schedule")
        if any(h >= c for h, c in zip(self.heating_setpoint.values, self.cooling_setpoint.values)):
            raise ValueError("Heating setpoint must remain below cooling setpoint")
        return self


class FVPSpec(Spec):
    cop: Annotated[float, Field(gt=1)]
    capacity_kw: Positive
    exhaust_min_temperature_c: float = 5
    dhw_priority: bool = True
    backup_efficiency: Annotated[float, Field(gt=0, le=1)] = 1


class DeliverySpec(Spec):
    fvp: FVPSpec | None = None


class PVSpec(Spec):
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
    pv_systems: tuple[PVSpec, ...] = ()


class SourceRecord(Spec):
    field_path: str
    status: Literal["measured", "inferred", "assumed"]
    source: str
    confidence: Fraction | None = None
    assumption_profile: str | None = None


class ProvenanceSpec(Spec):
    records: tuple[SourceRecord, ...] = ()


class RenovationRecord(Spec):
    measure: str
    before_sha256: str
    after_sha256: str
    parameters_json: str


class BuildingSpec(Spec):
    schema_version: Literal[2] = 2
    identifier: str
    geometry: GeometrySpec
    facade: FacadeSpec
    climate: ClimateSpec
    envelope: EnvelopeSpec
    airflow: AirflowSpec
    use: UseSpec
    context: ContextSpec = ContextSpec()
    delivery: DeliverySpec = DeliverySpec()
    renewables: RenewablesSpec = RenewablesSpec()
    provenance: ProvenanceSpec = ProvenanceSpec()
    renovations: tuple[RenovationRecord, ...] = ()

    @model_validator(mode="after")
    def compatible(self):
        if self.delivery.fvp and self.airflow.topology != "F":
            raise ValueError("FVP delivery requires F ventilation")
        if (
            max(self.use.heating_setpoint.values)
            >= self.airflow.maximum_heating_supply_temperature_c
        ):
            raise ValueError("Heating supply limit must exceed the heating setpoint")
        return self

    def physical_dict(self):
        data = self.model_dump(mode="json", exclude={"identifier", "provenance", "renovations"})
        data["climate"].pop("epw_path")
        return data

    def physical_hash(self):
        return hashlib.sha256(
            json.dumps(self.physical_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
