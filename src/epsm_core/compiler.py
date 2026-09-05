"""EnergyPlus 24.2 epJSON compilation; no IDF or third-party building schema."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import jsonschema
from shapely.affinity import translate
from shapely.geometry import LineString

from .constructions import bridge_equivalent, internal_mass_halves
from .geometry import (
    cardinal,
    exposed_segments,
    facade_edges,
    horizontal_patches,
    horizontal_vertices,
    local_polygons,
    wall_vertices,
)
from .specs import BuildingSpec, Spec
from .weather import file_sha256

COMPILER_VERSION = "2.0.1"


class CompilationReport(Spec):
    run_id: str
    compiler_version: str
    engine_version: str
    engine_sha256: str
    schema_sha256: str
    spec_sha256: str
    report_json: str

    @property
    def data(self):
        return json.loads(self.report_json)


class EnergyPlusCompiler:
    def __init__(self, energyplus=None):
        executable = energyplus or os.environ.get("ENERGYPLUS_EXE") or shutil.which("energyplus")
        if not executable:
            raise FileNotFoundError("Set ENERGYPLUS_EXE to EnergyPlus 24.2 or pass energyplus=")
        self.executable = Path(executable).resolve()
        self.version = subprocess.check_output(
            [str(self.executable), "--version"], text=True
        ).strip()
        if "Version 24.2." not in self.version:
            raise ValueError(f"Only EnergyPlus 24.2 is supported; found {self.version}")
        self.schema_path = self.executable.parent / "Energy+.schema.epJSON"
        self.schema = json.loads(self.schema_path.read_text())
        self.validator = jsonschema.Draft7Validator(self.schema)
        self.engine_hash = file_sha256(self.executable)
        self.schema_hash = file_sha256(self.schema_path)

    def run_id(self, spec):
        payload = [
            spec.physical_hash(),
            COMPILER_VERSION,
            self.version,
            self.engine_hash,
            self.schema_hash,
        ]
        return hashlib.sha256(json.dumps(payload).encode()).hexdigest()

    def compile(self, spec: BuildingSpec):
        spec = BuildingSpec.model_validate(spec.model_dump())
        if file_sha256(spec.climate.epw_path) != spec.climate.weather_sha256:
            raise ValueError("EPW checksum differs from ClimateSpec")
        model = {}

        def add(kind, name, **fields):
            objects = model.setdefault(kind, {})
            if name in objects:
                raise ValueError(f"Duplicate EnergyPlus object {kind}:{name}")
            objects[name] = fields

        add("Version", "version", version_identifier="24.2")
        add(
            "Building",
            "building",
            north_axis=0,
            terrain="Suburbs",
            solar_distribution="FullExterior",
            loads_convergence_tolerance_value=0.04,
            temperature_convergence_tolerance_value=0.4,
            maximum_number_of_warmup_days=50,
        )
        add(
            "SimulationControl",
            "control",
            do_zone_sizing_calculation="No",
            do_system_sizing_calculation="No",
            do_plant_sizing_calculation="No",
            run_simulation_for_sizing_periods="No",
            run_simulation_for_weather_file_run_periods="Yes",
        )
        add("Timestep", "timestep", number_of_timesteps_per_hour=6)
        add(
            "GlobalGeometryRules",
            "geometry",
            starting_vertex_position="UpperLeftCorner",
            vertex_entry_direction="Counterclockwise",
            coordinate_system="World",
        )
        add("HeatBalanceAlgorithm", "heat_balance", algorithm="ConductionTransferFunction")
        c = spec.climate
        add(
            "Site:Location",
            "site",
            latitude=c.latitude_deg,
            longitude=c.longitude_deg,
            time_zone=c.time_zone_hours,
            elevation=c.elevation_m,
        )
        add(
            "RunPeriod",
            "annual",
            begin_month=1,
            begin_day_of_month=1,
            end_month=12,
            end_day_of_month=31,
            begin_year=c.calendar_year,
            end_year=c.calendar_year,
            use_weather_file_daylight_saving_period="No",
            use_weather_file_holidays_and_special_days="No",
        )
        add("Output:SQLite", "sql", option_type="SimpleAndTabular")
        add(
            "OutputControl:Files",
            "files",
            output_eso="No",
            output_mtr="No",
            output_sqlite="Yes",
            output_tabular="No",
            output_csv="No",
        )
        add("Output:Table:SummaryReports", "summaries", reports=[{"report_name": "AllSummary"}])
        add("Output:VariableDictionary", "dictionary", key_field="IDF")
        for index, variable in enumerate(OUTPUT_VARIABLES):
            if variable.startswith("Zone Ventilation") and spec.airflow.topology != "S":
                continue
            add(
                "Output:Variable",
                f"hourly_{index}",
                key_value="*",
                variable_name=variable,
                reporting_frequency="Hourly",
            )
        for i, variable in enumerate(ENERGY_VARIABLES):
            add(
                "Output:Variable",
                f"annual_{i}",
                key_value="*",
                variable_name=variable,
                reporting_frequency="RunPeriod",
            )

        def constant(name, value):
            add(
                "Schedule:Constant",
                name,
                hourly_value=value,
                schedule_type_limits_name="any_number",
            )

        constant("on", 1)
        constant("off", 0)
        constant("thermostat_control", 4)
        constant("activity", spec.use.occupant_activity_w)
        constant("water_hot", 55)
        constant("water_cold", 10)
        add("ScheduleTypeLimits", "any_number", numeric_type="Continuous")
        for name in (
            "heating_setpoint",
            "cooling_setpoint",
            "occupancy_fraction",
            "equipment_fraction",
            "lighting_fraction",
            "dhw_fraction",
        ):
            data = [{"field": "Through: 12/31"}, {"field": "For: AllDays"}]
            for hour, value in enumerate(getattr(spec.use, name).values, 1):
                data.extend([{"field": f"Until: {hour:02}:00"}, {"field": value}])
            add("Schedule:Compact", name, schedule_type_limits_name="any_number", data=data)

        construction_report = {}
        assemblies = {
            role: getattr(spec.envelope, role)
            for role in (
                "wall",
                "top",
                "ground",
                "intermediate_floor",
                "weather_shell",
                "basement_wall",
            )
        }
        if spec.geometry.zoning == "whole_building" and spec.geometry.floors > 1:
            assemblies.update(
                zip(
                    ("internal_slab_face_a", "internal_slab_face_b"),
                    internal_mass_halves(spec.envelope.intermediate_floor),
                )
            )
        for role, nominal in assemblies.items():
            uplift = (
                spec.envelope.thermal_bridge_uplift_fraction
                if role in ("wall", "top", "ground", "basement_wall")
                else 0
            )
            applied = bridge_equivalent(nominal, uplift)
            construction_report[role] = dict(
                nominal=nominal.model_dump(mode="json"),
                applied=applied.model_dump(mode="json"),
                nominal_u_w_m2k=nominal.u_value_w_m2k,
                applied_u_w_m2k=applied.u_value_w_m2k,
            )
            names = []
            for i, layer in enumerate(applied.layers):
                name = f"{role}_layer_{i}"
                material = layer.material
                add(
                    "Material",
                    name,
                    roughness=material.roughness,
                    thickness=layer.thickness_m,
                    conductivity=material.conductivity_w_mk,
                    density=material.density_kg_m3,
                    specific_heat=material.specific_heat_j_kgk,
                    thermal_absorptance=material.thermal_absorptance,
                    solar_absorptance=material.solar_absorptance,
                    visible_absorptance=material.visible_absorptance,
                )
                names.append(name)
            for label, sequence in ((role, names), (role + "_reverse", names[::-1])):
                add(
                    "Construction",
                    label,
                    **{
                        ("outside_layer" if i == 0 else f"layer_{i + 1}"): name
                        for i, name in enumerate(sequence)
                    },
                )
        glazing = spec.facade.glazing
        add(
            "WindowMaterial:SimpleGlazingSystem",
            "glazing",
            u_factor=glazing.u_value_w_m2k,
            solar_heat_gain_coefficient=glazing.solar_heat_gain_coefficient,
            visible_transmittance=glazing.visible_transmittance,
        )
        add("Construction", "window", outside_layer="glazing")

        k = spec.envelope.foundation
        add(
            "Foundation:Kiva:Settings",
            "soil",
            soil_conductivity=k.soil_conductivity_w_mk,
            soil_density=k.soil_density_kg_m3,
            soil_specific_heat=k.soil_specific_heat_j_kgk,
            ground_solar_absorptivity=k.ground_solar_absorptivity,
            ground_thermal_absorptivity=k.ground_thermal_absorptivity,
            ground_surface_roughness=k.ground_surface_roughness_m,
            far_field_width=k.far_field_width_m,
            deep_ground_boundary_condition=k.deep_ground_boundary_condition,
            deep_ground_depth=k.deep_ground_depth_m,
            minimum_cell_dimension=k.minimum_cell_dimension_m,
            maximum_cell_growth_coefficient=k.maximum_cell_growth_coefficient,
            simulation_timestep=k.simulation_timestep,
        )

        def surface(name, zone, vertices, kind, construction, boundary, adjacent=""):
            exterior = boundary == "Outdoors"
            add(
                "BuildingSurface:Detailed",
                name,
                surface_type=kind,
                construction_name=construction,
                zone_name=zone,
                outside_boundary_condition=boundary,
                outside_boundary_condition_object=adjacent,
                sun_exposure="SunExposed" if exterior else "NoSun",
                wind_exposure="WindExposed" if exterior else "NoWind",
                number_of_vertices=len(vertices),
                vertices=[
                    dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z)
                    for x, y, z in vertices
                ],
            )

        polygons, origin = local_polygons(spec.geometry)
        zone_report, facade_report, ground_report = {}, [], []
        valid_facades = set()
        g = spec.geometry
        for ci, polygon in enumerate(polygons):
            patches = horizontal_patches(polygon)
            zones = []  # name, bottom, top, conditioned, floor-area multiplier
            if g.basement_depth_m:
                zones.append((f"c{ci}_basement", -g.basement_depth_m, 0, g.basement_conditioned, 1))
            if g.zoning == "whole_building":
                zones.append((f"c{ci}_main", 0, g.floors * g.floor_height_m, True, g.floors))
            else:
                zones.extend(
                    (f"c{ci}_floor{i}", i * g.floor_height_m, (i + 1) * g.floor_height_m, True, 1)
                    for i in range(g.floors)
                )
            if spec.envelope.roof_topology == "cold_attic":
                roof_z = g.floors * g.floor_height_m
                zones.append((f"c{ci}_attic", roof_z, roof_z + g.attic_height_m, False, 1))
            # Each actual floor patch needs a distinct Kiva object in EnergyPlus 24.2.
            foundations = []
            for pi, patch in enumerate(patches):
                foundation = f"c{ci}_foundation{pi}"
                add(
                    "Foundation:Kiva",
                    foundation,
                    wall_height_above_grade=0,
                    wall_depth_below_slab=0,
                    footing_wall_construction_name="basement_wall",
                )
                foundations.append(foundation)
            for zi, (zone, bottom, top, conditioned, multiplier) in enumerate(zones):
                area = polygon.area * multiplier
                volume = polygon.area * (top - bottom)
                add(
                    "Zone",
                    zone,
                    ceiling_height=top - bottom,
                    floor_area=area,
                    volume=volume,
                    part_of_total_floor_area="Yes" if conditioned else "No",
                )
                zone_report[zone] = dict(
                    floor_area_m2=area, volume_m3=volume, conditioned=conditioned
                )
                if conditioned:
                    self._loads(add, zone, area, volume, spec)
                    if multiplier > 1:
                        # Never aggregate all storeys into one dominant radiating
                        # surface: EnergyPlus cannot close those view factors.
                        for storey in range(multiplier - 1):
                            for face in ("a", "b"):
                                add(
                                    "InternalMass",
                                    f"{zone}_slab_{storey}_{face}",
                                    construction_name=f"internal_slab_face_{face}",
                                    zone_or_zonelist_name=zone,
                                    surface_area=polygon.area,
                                )
                for pi, patch in enumerate(patches):
                    floor_name = f"{zone}_floor_{pi}"
                    if zi == 0:
                        boundary, adjacent, role = "Foundation", foundations[pi], "ground"
                        flags = exposed_segments(patch, polygon)
                        add(
                            "SurfaceProperty:ExposedFoundationPerimeter",
                            floor_name + "_perimeter",
                            surface_name=floor_name,
                            exposed_perimeter_calculation_method="BySegment",
                            total_exposed_perimeter=patch.boundary.intersection(
                                polygon.boundary
                            ).length,
                            exposed_perimeter_fraction=1,
                            surfaces=[
                                {"surface_segment_exposed": "Yes" if flag else "No"}
                                for flag in flags
                            ],
                        )
                        ground_report.append(
                            dict(
                                surface=floor_name,
                                foundation=adjacent,
                                area_m2=patch.area,
                                exposed_perimeter_m=patch.boundary.intersection(
                                    polygon.boundary
                                ).length,
                            )
                        )
                    else:
                        boundary, adjacent = "Surface", f"{zones[zi - 1][0]}_ceiling_{pi}"
                        role = "top_reverse" if zone.endswith("attic") else "intermediate_floor"
                    surface(
                        floor_name,
                        zone,
                        horizontal_vertices(patch, bottom, False),
                        "Floor",
                        role,
                        boundary,
                        adjacent,
                    )
                    if zi == len(zones) - 1:
                        boundary, adjacent = "Outdoors", ""
                        role = "weather_shell" if zone.endswith("attic") else "top"
                    else:
                        boundary, adjacent = "Surface", f"{zones[zi + 1][0]}_floor_{pi}"
                        role = (
                            "top"
                            if zones[zi + 1][0].endswith("attic")
                            else "intermediate_floor_reverse"
                        )
                    surface(
                        f"{zone}_ceiling_{pi}",
                        zone,
                        horizontal_vertices(patch, top),
                        "Roof" if boundary == "Outdoors" else "Ceiling",
                        role,
                        boundary,
                        adjacent,
                    )
                for facade_id, a, b in facade_edges(polygon, ci):
                    valid_facades.add(facade_id)
                    name = f"{zone}_{facade_id}"
                    verts = wall_vertices(a, b, bottom, top)
                    if bottom < 0:
                        edge = LineString([a, b])
                        pi = next(
                            i
                            for i, patch in enumerate(patches)
                            if patch.boundary.intersection(edge).length >= edge.length - 1e-6
                        )
                        surface(
                            name,
                            zone,
                            verts,
                            "Wall",
                            "basement_wall",
                            "Foundation",
                            foundations[pi],
                        )
                    else:
                        surface(
                            name,
                            zone,
                            verts,
                            "Wall",
                            "weather_shell" if zone.endswith("attic") else "wall",
                            "Outdoors",
                        )
                        if conditioned:
                            wwr = spec.facade.wwr_for(facade_id)
                            gross = math.dist(a, b) * (top - bottom)
                            facade_report.append(
                                dict(
                                    facade_id=facade_id,
                                    zone=zone,
                                    local_wwr=wwr,
                                    cardinal=cardinal(a, b),
                                    gross_area_m2=gross,
                                    window_area_m2=gross * wwr,
                                )
                            )
                            if wwr:
                                center = tuple(sum(v[i] for v in verts) / 4 for i in range(3))
                                windows = [
                                    tuple(
                                        center[i] + math.sqrt(wwr) * (v[i] - center[i])
                                        for i in range(3)
                                    )
                                    for v in verts
                                ]
                                fields = {
                                    f"vertex_{j + 1}_{axis}_coordinate": xyz[i]
                                    for j, xyz in enumerate(windows)
                                    for i, axis in enumerate("xyz")
                                }
                                add(
                                    "FenestrationSurface:Detailed",
                                    name + "_window",
                                    surface_type="Window",
                                    construction_name="window",
                                    building_surface_name=name,
                                    number_of_vertices=4,
                                    **fields,
                                )
                                add(
                                    "SurfaceProperty:IncidentSolarMultiplier",
                                    name + "_solar",
                                    surface_name=name + "_window",
                                    incident_solar_multiplier=spec.facade.solar_shading_factor,
                                )
        unknown = {o.facade_id for o in spec.facade.overrides} - valid_facades
        if unknown:
            raise ValueError(f"Overrides reference unknown facades: {sorted(unknown)}")

        for bi, context in enumerate(spec.context.buildings):
            for pi, footprint in enumerate(context.footprints):
                p = translate(footprint.polygon, -origin[0], -origin[1])
                z, h = context.base_elevation_m, context.height_m
                shapes = [wall_vertices(a, b, z, z + h) for _, a, b in facade_edges(p, pi)]
                shapes += [horizontal_vertices(patch, z + h) for patch in horizontal_patches(p)]
                for si, vertices in enumerate(shapes):
                    add(
                        "Shading:Building:Detailed",
                        f"context_{bi}_{pi}_{si}",
                        number_of_vertices=len(vertices),
                        vertices=[
                            dict(
                                vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z
                            )
                            for x, y, z in vertices
                        ],
                    )

        errors = sorted(self.validator.iter_errors(model), key=lambda e: str(e.path))
        if errors:
            raise ValueError(
                "epJSON schema errors:\n"
                + "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:20])
            )
        area = g.conditioned_floor_area_m2
        volume = g.conditioned_volume_m3
        report = dict(
            origin_m=origin,
            zones=zone_report,
            facades=facade_report,
            foundations=ground_report,
            constructions=construction_report,
            footprint_coordinates=[p.model_dump(mode="json") for p in g.footprints],
            footprint_area_m2=g.footprint_area_m2,
            perimeter_m=sum(p.length for p in polygons),
            compactness=4 * math.pi * g.footprint_area_m2 / sum(p.length for p in polygons) ** 2,
            outer_aspect_ratios=[
                max(
                    p.polygon.bounds[2] - p.polygon.bounds[0],
                    p.polygon.bounds[3] - p.polygon.bounds[1],
                )
                / min(
                    p.polygon.bounds[2] - p.polygon.bounds[0],
                    p.polygon.bounds[3] - p.polygon.bounds[1],
                )
                for p in g.footprints
            ],
            conditioned_floor_area_m2=area,
            conditioned_volume_m3=volume,
            effective_outdoor_air_ach=spec.airflow.envelope_infiltration_ach
            + spec.airflow.natural_exchange_ach
            + 3.6 * spec.airflow.mechanical_vent_l_s_m2 * area / volume,
            kiva=spec.envelope.foundation.model_dump(mode="json"),
            approximations=[
                "Kiva courtyard tessellation uses separate foundation instances per floor patch"
            ]
            if any(p.interiors for p in polygons)
            else [],
        )
        return model, CompilationReport(
            run_id=self.run_id(spec),
            compiler_version=COMPILER_VERSION,
            engine_version=self.version,
            engine_sha256=self.engine_hash,
            schema_sha256=self.schema_hash,
            spec_sha256=spec.physical_hash(),
            report_json=json.dumps(report, sort_keys=True),
        )

    @staticmethod
    def _loads(add, zone, area, volume, spec):
        u, a = spec.use, spec.airflow
        add(
            "People",
            zone + "_people",
            zone_or_zonelist_or_space_or_spacelist_name=zone,
            number_of_people_schedule_name="occupancy_fraction",
            number_of_people_calculation_method="People",
            number_of_people=area * u.occupant_density_per_m2,
            fraction_radiant=0.3,
            activity_level_schedule_name="activity",
        )
        for obj, label, watts in (
            ("ElectricEquipment", "equipment", u.equipment_gain_w_m2),
            ("Lights", "lighting", u.lighting_gain_w_m2),
        ):
            add(
                obj,
                zone + "_" + label,
                zone_or_zonelist_or_space_or_spacelist_name=zone,
                schedule_name=label + "_fraction",
                design_level_calculation_method="LightingLevel"
                if obj == "Lights"
                else "EquipmentLevel",
                **(
                    {"lighting_level": watts * area}
                    if obj == "Lights"
                    else {"design_level": watts * area}
                ),
                fraction_radiant=0.3,
            )
        add(
            "ZoneInfiltration:DesignFlowRate",
            zone + "_envelope_leakage",
            zone_or_zonelist_or_space_or_spacelist_name=zone,
            schedule_name="on",
            design_flow_rate_calculation_method="AirChanges/Hour",
            air_changes_per_hour=a.envelope_infiltration_ach,
            constant_term_coefficient=1,
            temperature_term_coefficient=0,
            velocity_term_coefficient=0,
            velocity_squared_term_coefficient=0,
        )
        if a.topology == "S":
            add(
                "ZoneVentilation:DesignFlowRate",
                zone + "_natural_exchange",
                zone_or_zonelist_or_space_or_spacelist_name=zone,
                schedule_name="on",
                design_flow_rate_calculation_method="AirChanges/Hour",
                air_changes_per_hour=a.natural_exchange_ach,
                ventilation_type="Natural",
                minimum_indoor_temperature=-100,
                maximum_indoor_temperature=100,
                delta_temperature=-100,
                maximum_wind_speed=40,
                constant_term_coefficient=1,
                temperature_term_coefficient=0,
                velocity_term_coefficient=0,
                velocity_squared_term_coefficient=0,
            )
        add(
            "ThermostatSetpoint:DualSetpoint",
            zone + "_setpoints",
            heating_setpoint_temperature_schedule_name="heating_setpoint",
            cooling_setpoint_temperature_schedule_name="cooling_setpoint",
        )
        add(
            "ZoneControl:Thermostat",
            zone + "_thermostat",
            zone_or_zonelist_name=zone,
            control_type_schedule_name="thermostat_control",
            control_1_object_type="ThermostatSetpoint:DualSetpoint",
            control_1_name=zone + "_setpoints",
        )
        add(
            "ZoneHVAC:EquipmentConnections",
            zone + "_connections",
            zone_name=zone,
            zone_conditioning_equipment_list_name=zone + "_equipment_list",
            zone_air_inlet_node_or_nodelist_name=zone + "_supply",
            zone_air_node_name=zone + "_air",
            zone_return_air_node_or_nodelist_name=zone + "_return",
        )
        add(
            "ZoneHVAC:EquipmentList",
            zone + "_equipment_list",
            equipment=[
                dict(
                    zone_equipment_object_type="ZoneHVAC:IdealLoadsAirSystem",
                    zone_equipment_name=zone + "_ideal",
                    zone_equipment_cooling_sequence=1,
                    zone_equipment_heating_or_no_load_sequence=1,
                )
            ],
        )
        add(
            "DesignSpecification:OutdoorAir",
            zone + "_outdoor_air",
            outdoor_air_method="Flow/Zone",
            outdoor_air_flow_per_zone=area * a.mechanical_vent_l_s_m2 / 1000,
            outdoor_air_schedule_name="on",
        )
        add(
            "ZoneHVAC:IdealLoadsAirSystem",
            zone + "_ideal",
            availability_schedule_name="on",
            zone_supply_air_node_name=zone + "_supply",
            heating_availability_schedule_name="on",
            cooling_availability_schedule_name="on" if u.cooling_enabled else "off",
            maximum_heating_supply_air_temperature=a.maximum_heating_supply_temperature_c,
            minimum_cooling_supply_air_temperature=a.minimum_cooling_supply_temperature_c,
            heating_limit="NoLimit",
            cooling_limit="NoLimit",
            dehumidification_control_type="None",
            humidification_control_type="None",
            design_specification_outdoor_air_object_name=zone + "_outdoor_air",
            outdoor_air_inlet_node_name=zone + "_outdoor_node",
            outdoor_air_economizer_type="NoEconomizer",
            heat_recovery_type="Enthalpy"
            if a.latent_recovery_effectiveness
            else "Sensible"
            if a.sensible_recovery_effectiveness
            else "None",
            sensible_heat_recovery_effectiveness=a.sensible_recovery_effectiveness,
            latent_heat_recovery_effectiveness=a.latent_recovery_effectiveness,
        )
        add("OutdoorAir:Node", zone + "_outdoor_node", height_above_ground=0)
        # Fixed 10/55 C water temperatures make the specified thermal DHW load explicit.
        mean = sum(u.dhw_fraction.values) / 24
        flow = (
            u.dhw_kwh_m2_year * area * 3.6e6 / (8760 * 3600 * mean * 998.2 * 4180 * 45)
            if mean
            else 0
        )
        add(
            "WaterUse:Equipment",
            zone + "_dhw",
            peak_flow_rate=flow,
            flow_rate_fraction_schedule_name="dhw_fraction",
            target_temperature_schedule_name="water_hot",
            hot_water_supply_temperature_schedule_name="water_hot",
            cold_water_supply_temperature_schedule_name="water_cold",
        )

    def write(self, spec, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        model, report = self.compile(spec)
        for name, data in (
            ("model.epJSON", model),
            ("building.json", spec.model_dump(mode="json")),
            ("compilation.json", report.model_dump(mode="json")),
        ):
            (directory / name).write_text(json.dumps(data, indent=2, allow_nan=False))
        return report


ENERGY_VARIABLES = (
    "Zone Ideal Loads Supply Air Total Heating Energy",
    "Zone Ideal Loads Supply Air Total Cooling Energy",
    "Water Use Equipment Heating Energy",
)
OUTPUT_VARIABLES = ENERGY_VARIABLES + (
    "Zone Mean Air Temperature",
    "Zone Air Humidity Ratio",
    "Zone Infiltration Sensible Heat Loss Energy",
    "Zone Infiltration Sensible Heat Gain Energy",
    "Zone Ventilation Sensible Heat Loss Energy",
    "Zone Ventilation Sensible Heat Gain Energy",
    "Zone Ideal Loads Outdoor Air Sensible Heating Energy",
    "Zone Ideal Loads Heat Recovery Sensible Heating Energy",
    "Zone Ideal Loads Heat Recovery Latent Heating Energy",
    "Zone Ideal Loads Outdoor Air Mass Flow Rate",
    "Surface Inside Face Temperature",
    "Surface Outside Face Temperature",
    "Surface Inside Face Conduction Heat Transfer Energy",
    "Enclosure Windows Total Transmitted Solar Radiation Energy",
    "Zone People Total Heating Energy",
    "Zone Electric Equipment Total Heating Energy",
    "Zone Lights Total Heating Energy",
)
