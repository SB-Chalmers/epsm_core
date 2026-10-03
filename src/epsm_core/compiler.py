# File: compiler.py
# Purpose: EnergyPlus 24.2 epJSON compilation; no IDF or third-party building schema.
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
#   2026-10-03 - Compile explicit calendars, zone operations and load-area accounting.
#   2026-09-13 - Cache unchanged EPW verification and share generated-edge margins.
#   2026-09-12 - Raise validated polygon shadow workspace capacity for dense contexts.
#   2026-09-11 - Serialize without geometry repair; pin simulation settings and lean outputs.
#   2026-09-06 - Document compiler interfaces, examples, constraints and processing rationale.

"""EnergyPlus 24.2 epJSON compilation; no IDF or third-party building schema.

Notes
-----
Compilation verifies weather identity, resolves shared geometry, emits explicit loads
and constructions, then validates surface invariants and the installed engine schema.
Ideal-load output represents demand. Source bytes and input-schema descriptions
contribute to run identity.

Examples
--------
Replace example paths with existing local inputs; output paths must be writable.

Example::

    from epsm_core.compiler import EnergyPlusCompiler

    compiler = EnergyPlusCompiler(energyplus="/path/to/EnergyPlus/energyplus")
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import jsonschema
from shapely import maximum_inscribed_circle
from shapely.geometry import Polygon

from ._version import __version__ as COMPILER_VERSION
from .constructions import bridge_equivalent, internal_mass_halves
from .context import mirror_suppression_eligibility, resolve_context, visible_context_surfaces
from .failures import ENERGYPLUS_SCHEMA_FAILURE, GEOMETRY_INVARIANT_FAILURE, CompilationError
from .footprint_cleanup import prepared_footprints
from .foundations import apply_kiva
from .pipeline import resolve_geometry
from .roofs import backend_versions
from .settings import CompilerSettings
from .specs import BuildingSpec, Spec
from .surface_checks import MIN_GENERATED_EDGE_M, validate_surfaces
from .vertex_order import serialize_vertices
from .weather import climate_from_epw, file_sha256

# PolygonClipping's 15,000-figure EnergyPlus default is too small for validated dense
# contexts. One million is the capacity used by the archived dense-context campaign;
# it changes only workspace capacity, not the clipping algorithm or emitted geometry.
_MAX_SHADOW_OVERLAP_FIGURES = 1_000_000
_SHADOW_OVERLAP_VERTEX_HINT_COUNT = 16


def _shadow_overlap_vertex_capacity_hint(surfaces):
    """Create a solar-inert polygon that enlarges EnergyPlus's vertex workspace.

    Parameters
    ----------
    surfaces : iterable of Surface
        Resolved target thermal surfaces in the local metric frame.

    Returns
    -------
    tuple[tuple[float, float, float], ...] or None
        Sixteen vertices inside a horizontal Ground floor, or ``None`` when no
        suitable ground receiver exists.

    Notes
    -----
    EnergyPlus 24.2 ``InitSolarCalculations`` derives its private ``MaxHCV``
    shadow-overlap capacity from ``MaxVerticesPerSurface``, rounded so that the
    allocation plus one is a multiple of 16. With ordinary triangles and quads
    the capacity remains 15; one 16-sided polygon advances it to 31. Dense
    overlaps can exceed 15 even when every physical input face is a valid quad.

    The hint is placed coplanar with and strictly inside a Ground surface. Ground
    surfaces are not solar receivers, and an upward ray from any above-grade
    receiver cannot meet this contained plane. It therefore changes engine
    workspace only, not the physical shadow field. The object is emitted as
    Shading:Site:Detailed so it remains separate from physical context counts.
    """
    candidates = []
    for face in surfaces:
        vertices = tuple(tuple(map(float, point)) for point in face.vertices)
        if face.kind != "Floor" or face.boundary != "Ground" or len(vertices) < 3:
            continue
        elevations = [point[2] for point in vertices]
        if max(elevations) - min(elevations) > 1e-6:
            continue
        polygon = Polygon([(point[0], point[1]) for point in vertices])
        if polygon.is_valid and polygon.area > 0:
            candidates.append((polygon.area, polygon, elevations[0]))
    if not candidates:
        return None

    _, polygon, elevation = max(candidates, key=lambda item: item[0])
    radius_line = maximum_inscribed_circle(polygon)
    center, boundary = tuple(radius_line.coords)
    clearance = math.dist(center, boundary)
    radius = min(1.0, clearance * 0.5)
    # A 16-gon needs this radius to keep every chord above EnergyPlus's
    # 0.01 m detailed-surface edge tolerance. Refuse an unsafe hint rather
    # than silently placing it outside the physical Ground polygon.
    minimum_radius = MIN_GENERATED_EDGE_M / (
        2 * math.sin(math.pi / _SHADOW_OVERLAP_VERTEX_HINT_COUNT)
    )
    if radius < minimum_radius:
        return None
    return tuple(
        (
            center[0] + radius * math.cos(2 * math.pi * i / _SHADOW_OVERLAP_VERTEX_HINT_COUNT),
            center[1] + radius * math.sin(2 * math.pi * i / _SHADOW_OVERLAP_VERTEX_HINT_COUNT),
            elevation,
        )
        for i in range(_SHADOW_OVERLAP_VERTEX_HINT_COUNT)
    )


def compiler_source_hash(directory=None):
    """Hash sorted Python source paths and raw bytes for compiler provenance.

    Parameters
    ----------
    directory : str or Path or None
        Python source root; None selects the epsm_core package directory. Default: ``None``.

    Returns
    -------
    str
        SHA-256 digest of the source tree.

    Notes
    -----
    Comments and docstrings intentionally affect the digest and resulting run IDs. Relative
    POSIX paths and NUL separators make file boundaries explicit.

    Examples
    --------
    Example::

        from epsm_core.compiler import compiler_source_hash

        digest = compiler_source_hash()
        assert len(digest) == 64
    """

    # 1. Hash sorted Python source paths and raw bytes for compiler provenance.
    root = Path(directory or Path(__file__).parent)
    # NOTE: Raw-byte provenance deliberately changes after comments/docstrings are edited.
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


class CompilationReport(Spec):
    """Immutable compilation identity with a JSON-encoded detailed audit.

    Attributes
    ----------
    run_id : str
        Content-derived run identity including compiler, engine and physical inputs.
        Required at construction.
    compiler_version : str
        Reported compiler release or EnergyPlus version.  Required at construction.
    compiler_sha256 : str
        SHA-256 identity of compiler source, engine executable, engine schema or physical
        specification.  Required at construction.
    engine_version : str
        Reported compiler release or EnergyPlus version.  Required at construction.
    engine_sha256 : str
        SHA-256 identity of compiler source, engine executable, engine schema or physical
        specification.  Required at construction.
    schema_sha256 : str
        SHA-256 identity of compiler source, engine executable, engine schema or physical
        specification.  Required at construction.
    spec_sha256 : str
        SHA-256 identity of compiler source, engine executable, engine schema or physical
        specification.  Required at construction.
    report_json : str
        JSON-encoded detailed audit mapping decoded by the data property.  Required at
        construction.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    The data property parses report_json into a fresh mapping. Hashes distinguish physical
    inputs, raw compiler sources, engine binary and engine schema; run_id also includes
    settings and input-schema metadata.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``; an initialized EnergyPlusCompiler as
    ``compiler`` (EnergyPlus 24.2 required).

    Example::

        report = compiler.write(building, "output/compiled")
    """

    run_id: str
    compiler_version: str
    compiler_sha256: str
    engine_version: str
    engine_sha256: str
    schema_sha256: str
    spec_sha256: str
    report_json: str

    @property
    def data(self):
        """Decode the stored report JSON into a fresh mutable mapping.

        Returns
        -------
        dict
            Geometry, construction, validation and provenance report data.

        Notes
        -----
        Each access parses report_json again. Mutating the result does not change this immutable
        report.

        Examples
        --------
        Supply the matching CompilationReport as ``report``.

        Example::

            data = report.data
        """

        return json.loads(self.report_json)


class EnergyPlusCompiler:
    """Compile explicit BuildingSpec inputs to validated EnergyPlus 24.2 epJSON.

    Attributes
    ----------
    settings : CompilerSettings
        Validated engine controls included in run identity.
    executable : Path
        Resolved EnergyPlus 24.2 executable.
    version : str
        Engine version-command output.
    schema_path : Path
        Engine-adjacent Energy+.schema.epJSON path.
    schema : dict
        Loaded engine schema.
    validator : jsonschema.Draft7Validator
        Validator used on emitted epJSON.
    engine_hash : str
        SHA-256 of executable bytes.
    schema_hash : str
        SHA-256 of engine-schema bytes.
    compiler_hash : str
        SHA-256 of package Python paths and source bytes.

    Notes
    -----
    Initialization executes --version and reads local schema/source files. Compilation
    checks weather content but does not simulate; write emits artifacts. Requires an
    installed EnergyPlus 24.2 executable and adjacent schema.

    Examples
    --------
    Replace example paths with existing local inputs; output paths must be writable.

    Example::

        from epsm_core.compiler import EnergyPlusCompiler

        compiler = EnergyPlusCompiler(energyplus="/path/to/EnergyPlus/energyplus")
    """

    def __init__(self, energyplus=None, *, settings=None):
        """Resolve EnergyPlus 24.2 and initialize its schema validator and source identities.

        Parameters
        ----------
        energyplus : str or Path or None
            EnergyPlus 24.2 executable; None uses ENERGYPLUS_EXE then PATH. Default: ``None``.
        settings : CompilerSettings or None
            Explicit engine controls; None uses CompilerSettings defaults. Default: ``None``.

        Returns
        -------
        None
            Initializes executable, settings, schema validator and hashes.

        Raises
        ------
        FileNotFoundError
            Rejected conditions: Set ENERGYPLUS_EXE to EnergyPlus 24.2 or pass energyplus=.
        ValueError
            If the input or generated result violates the constraints described in Notes.

        Notes
        -----
        Lookup order is explicit path, ENERGYPLUS_EXE, then PATH. Executes --version and reads
        the adjacent Energy+.schema.epJSON; other engine versions are rejected.

        Examples
        --------
        Replace example paths with existing local inputs; output paths must be writable.

        Example::

            from epsm_core.compiler import EnergyPlusCompiler

            compiler = EnergyPlusCompiler(energyplus="/path/to/EnergyPlus/energyplus")
        """

        # 1. Resolve EnergyPlus 24.2 and initialize its schema validator and source identities.
        self.settings = settings or CompilerSettings()
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
        self.compiler_hash = compiler_source_hash()
        self._weather_cache = {}

    def _verified_weather(self, climate):
        """Read and verify an EPW once while the local file stays unchanged.

        Parameters
        ----------
        climate : ClimateSpec
            Expected local path, checksum and site metadata.

        Returns
        -------
        ClimateSpec
            Location metadata and checksum read from the EPW.

        Raises
        ------
        OSError
            If the EPW changes while Core is reading it.
        ValueError
            If the EPW checksum does not match the input specification.

        Notes
        -----
        The cache belongs to this compiler instance. A file is read again after its
        identity, size or timestamps change. If it changes during the read, compilation
        stops instead of caching uncertain weather metadata.
        """
        path = Path(climate.epw_path).resolve()

        def signature():
            stat = path.stat()
            return (
                stat.st_dev,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
            )

        before = signature()
        cached = self._weather_cache.get(path)
        if cached is not None and cached[0] == before:
            weather = cached[1]
        else:
            weather = climate_from_epw(path)
            after = signature()
            if after != before:
                raise OSError(f"EPW changed while it was being verified: {path}")
            self._weather_cache[path] = (after, weather)
        if weather.weather_sha256 != climate.weather_sha256:
            raise ValueError("EPW checksum differs from ClimateSpec")
        return weather

    def run_id(self, spec):
        """Compile and bind the identity to the actual serialized model.

        Invalid specifications cannot receive an executable run identity. Use
        CompilationReport.run_id after compile/write to avoid duplicate compilation.
        """
        return self.compile(spec)[1].run_id

    def _input_identity(self, spec):
        """Bind physical inputs to exact compiler, engine, schema and backend identities.

        Parameters
        ----------
        spec : BuildingSpec
            Validated building input; geometry-only helpers also accept an object exposing the
            fields they consume.

        Returns
        -------
        str
            SHA-256 run identifier.

        Notes
        -----
        Includes compiler controls and the generated BuildingSpec schema. Class documentation
        affects schema descriptions, and source documentation affects compiler_hash; both can
        change run identity without changing physics.

        Examples
        --------
        Supply a validated BuildingSpec as ``building``; an initialized EnergyPlusCompiler as
        ``compiler`` (EnergyPlus 24.2 required).

        Example::

            run_id = compiler.run_id(building)
        """

        # 1. Bind physical inputs to exact compiler, engine, schema and backend identities.
        payload = [
            spec.physical_hash(),
            COMPILER_VERSION,
            self.compiler_hash,
            self.version,
            self.engine_hash,
            self.schema_hash,
            backend_versions(),
            self.settings.model_dump(mode="json"),
            BuildingSpec.model_json_schema(),
        ]
        return hashlib.sha256(json.dumps(payload).encode()).hexdigest()

    def compile(self, spec: BuildingSpec):
        """Compile a validated building into checked EnergyPlus epJSON and an audit report.

        Parameters
        ----------
        spec : BuildingSpec
            Validated building input; geometry-only helpers also accept an object exposing the
            fields they consume.

        Returns
        -------
        tuple
            epJSON model dictionary and CompilationReport.

        Raises
        ------
        ValueError
            Rejected conditions: EPW checksum differs from ClimateSpec.

        Notes
        -----
        Reads and verifies the EPW checksum but does not run a simulation or write artifacts.
        Revalidates the building, resolves shared geometry, emits loads and checks surfaces and
        engine schema. Ideal loads represent demand; downstream delivery computes equipment
        energy.

        Examples
        --------
        Supply a validated BuildingSpec as ``building``; an initialized EnergyPlusCompiler as
        ``compiler`` (EnergyPlus 24.2 required).

        Example::

            model, report = compiler.compile(building)
        """

        # 1. Compile a validated building into checked EnergyPlus epJSON and an audit report.
        spec = BuildingSpec.model_validate(spec.model_dump())
        weather_location = self._verified_weather(spec.climate)
        for field in ("latitude_deg", "longitude_deg", "time_zone_hours", "elevation_m"):
            if getattr(spec.climate, field) != getattr(weather_location, field):
                raise ValueError(f"Site:Location differs from EPW: {field}")
        model = {}

        def add(kind, name, **fields):
            """Insert one uniquely named EnergyPlus object into the enclosing model.

            Parameters
            ----------
            kind : str
                Surface, object or region classification consumed by the enclosing builder.
            name : str
                Identifier or field name interpreted by the current operation.
            **fields : dict
                EnergyPlus object fields forwarded unchanged to the enclosing model.

            Returns
            -------
            None
                Updates the model mapping in place.

            Raises
            ------
            ValueError
                If the input or generated result violates the constraints described in Notes.

            Notes
            -----
            Names must be unique within an EnergyPlus object type. Duplicate insertion raises
            ValueError rather than replacing an existing object.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                add("Schedule:Constant", "example", hourly_value=1)
            """

            objects = model.setdefault(kind, {})
            if name in objects:
                raise ValueError(f"Duplicate EnergyPlus object {kind}:{name}")
            objects[name] = fields

        # 2. Establish engine, coordinate and annual-calendar conventions explicitly.
        add("Version", "version", version_identifier="24.2")
        add(
            "Building",
            "building",
            north_axis=0,
            terrain="Suburbs",
            solar_distribution="FullExterior",
            loads_convergence_tolerance_value=0.04,
            temperature_convergence_tolerance_value=0.4,
            maximum_number_of_warmup_days=25,
            minimum_number_of_warmup_days=1,
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
        add("Output:SQLite", "sql", option_type="Simple")
        add(
            "OutputControl:Files",
            "files",
            output_eso="No",
            output_mtr="No",
            output_sqlite="Yes",
            output_tabular="No",
            output_csv="No",
        )
        requests = {(variable.upper(), "*"): (variable, "*") for variable in OUTPUT_VARIABLES}
        for request in self.settings.hourly_outputs:
            requests.setdefault((request.name, request.key), (request.name, request.key))
        for index, (variable, key) in enumerate(sorted(requests.values())):
            add(
                "Output:Variable",
                f"hourly_{index}",
                key_value=key,
                variable_name=variable,
                reporting_frequency="Hourly",
            )
        for i, variable in enumerate(ENERGY_VARIABLES + (SOLAR_VARIABLE,)):
            add(
                "Output:Variable",
                f"monthly_{i}",
                key_value="*",
                variable_name=variable,
                reporting_frequency="Monthly",
            )
            add(
                "Output:Variable",
                f"annual_{i}",
                key_value="*",
                variable_name=variable,
                reporting_frequency="RunPeriod",
            )
        for index, variable in enumerate(
            ("Zone Heating Setpoint Not Met Time", "Zone Cooling Setpoint Not Met Time")
        ):
            add(
                "Output:Variable",
                f"unmet_{index}",
                key_value="*",
                variable_name=variable,
                reporting_frequency="RunPeriod",
            )

        def constant(name, value):
            """Emit an unrestricted numeric constant schedule into the enclosing model.

            Parameters
            ----------
            name : str
                Identifier or field name interpreted by the current operation.
            value : object
                Scalar or JSON-compatible value consumed by this operation.

            Returns
            -------
            None
                Adds one Schedule:Constant object.

            Notes
            -----
            Uses the shared any_number schedule type; duplicate names are rejected by add.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                constant("example_schedule", 1)
            """

            # 1. Emit an unrestricted numeric constant schedule into the enclosing model.
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
            data = getattr(spec.use, name).compact_data(spec.climate.calendar_year)
            add("Schedule:Compact", name, schedule_type_limits_name="any_number", data=data)

        def emit_airflow_schedules(airflow, prefix=""):
            """Keep outdoor-air and HVAC availability controls independent."""
            for name in ("infiltration_fraction", "natural_exchange_fraction", "mechanical_vent_fraction", "heating_availability", "cooling_availability"):
                add("Schedule:Compact", prefix + name, schedule_type_limits_name="any_number",
                    data=getattr(airflow, name).compact_data(spec.climate.calendar_year))

        emit_airflow_schedules(spec.airflow)

        # 3. Preserve nominal assemblies in the audit while emitting equivalent thermal
        # properties.
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
        for role in ("dwelling_partition", "common_partition"):
            if getattr(spec.envelope, role) is not None:
                assemblies[role] = getattr(spec.envelope, role)
        if spec.envelope.basement_ceiling is not None:
            assemblies["basement_ceiling"] = spec.envelope.basement_ceiling
        assemblies.update(
            {
                "unconditioned_" + role: assemblies[role]
                for role in ("wall", "top", "ground", "basement_wall")
            }
        )
        if spec.geometry.zoning.mode == "whole_building":
            assemblies.update(
                zip(
                    ("internal_slab_face_a", "internal_slab_face_b"),
                    internal_mass_halves(spec.envelope.intermediate_floor),
                )
            )
        for role, nominal in assemblies.items():
            uplift = (
                spec.envelope.thermal_bridge_uplift_fraction
                if role in ("wall", "top", "ground", "basement_wall", "basement_ceiling")
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

        # 4. Prescribed temperatures are an explicit legacy mode; Kiva is emitted
        # after all ground faces exist and before geometric/schema validation.
        ground_temperature = spec.envelope.ground_temperature
        foundation_report = dict(method="prescribed_temperature")
        if ground_temperature is not None:
            months = ("january", "february", "march", "april", "may", "june",
                      "july", "august", "september", "october", "november", "december")
            add("Site:GroundTemperature:BuildingSurface", "ground_temperature",
                **{f"{month}_ground_temperature": value for month, value in
                   zip(months, ground_temperature.monthly_temperatures_c)})
            foundation_report.update(ground_temperature.model_dump(mode="json"))

        def surface(name, zone, vertices, kind, construction, boundary, adjacent=""):
            """Encode a graph face with world coordinates and explicit exposure settings.

            Parameters
            ----------
            name : str
                Identifier or field name interpreted by the current operation.
            zone : str
                Resolved thermal-zone name used by emitted objects.
            vertices : array_like
                Ordered three-dimensional metric surface vertices; winding controls the normal.
            kind : str
                Surface, object or region classification consumed by the enclosing builder.
            construction : str
                Construction role or emitted construction name, including reverse suffix where
                needed.
            boundary : str
                EnergyPlus outside boundary condition such as Outdoors, Ground or Surface.
            adjacent : str
                Related surface identity; reciprocal neighbour or thermal parent according to the
                operation. Default: ``''``.

            Returns
            -------
            None
                Adds a BuildingSurface:Detailed object.

            Notes
            -----
            Only Outdoors boundaries receive sun and wind exposure. Reciprocal adjacency and vertex
            orientation are supplied by the shared graph, then checked after emission.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                surface(
                    "wall",
                    "zone",
                    wall_vertices((0, 0), (2, 0), 0, 3),
                    "Wall",
                    "wall",
                    "Outdoors",
                )
            """

            # 1. Encode a graph face with world coordinates and explicit exposure settings.
            exterior = boundary == "Outdoors"
            add(
                "BuildingSurface:Detailed",
                name,
                surface_type=kind,
                construction_name=construction,
                zone_name=zone,
                space_name=zone + "_space",
                outside_boundary_condition=boundary,
                outside_boundary_condition_object=adjacent,
                sun_exposure="SunExposed" if exterior else "NoSun",
                wind_exposure="WindExposed" if exterior else "NoWind",
                number_of_vertices=len(vertices),
                vertices=[
                    dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z)
                    for x, y, z in serialize_vertices(vertices)
                ],
            )

        add("Construction:AirBoundary", "partition")
        # 5. Share physical geometry with preview/takeoff, then bound shaded-wall complexity.
        try:
            resolved = resolve_geometry(spec, panelize=True)
        except ValueError as error:
            raise CompilationError(GEOMETRY_INVARIANT_FAILURE, str(error)) from error
        polygons, origin, graph = resolved.polygons, resolved.origin, resolved.graph
        openings, facade_report, shades = (
            resolved.openings,
            resolved.facades,
            list(resolved.shading),
        )
        if not openings:
            model["Output:Variable"] = {
                key: obj
                for key, obj in model["Output:Variable"].items()
                if obj["variable_name"] != SOLAR_VARIABLE
            }
        try:
            context = resolve_context(spec.geometry, spec.context, origin=origin)
        except ValueError as error:
            raise CompilationError(GEOMETRY_INVARIANT_FAILURE, str(error)) from error
        visible_context, visibility = visible_context_surfaces(
            context, [v for face in graph.surfaces for v in face.vertices]
        )
        visible_context_names = {face.name for face in visible_context}
        for face in context.surfaces:
            shades.append(
                dict(
                    name=face.name,
                    vertices=face.vertices,
                    kind="context",
                    building_id=face.building_id,
                    footprint_index=face.footprint_index,
                    surface_type=face.kind,
                )
            )
        add(
            "ShadowCalculation",
            "detailed_geometry",
            shading_calculation_method="PolygonClipping",
            polygon_clipping_algorithm="SutherlandHodgman",
            shading_calculation_update_frequency_method="Periodic",
            shading_calculation_update_frequency=20,
            maximum_figures_in_shadow_overlap_calculations=_MAX_SHADOW_OVERLAP_FIGURES,
            sky_diffuse_modeling_algorithm="SimpleSkyDiffuseModeling",
        )
        # The global flag requires a proof over all detached shading. Qualified
        # closed opaque shells retain their first ray intersections after pruning;
        # standalone facade planes require automatic mirroring.
        mirror_proof = mirror_suppression_eligibility(context, resolved.shading)
        context_mirroring_disabled = mirror_proof["mirror_suppression_eligible"]
        if context_mirroring_disabled:
            add(
                "Output:Diagnostics",
                "oriented_opaque_context",
                diagnostics=[dict(key="DoNotMirrorDetachedShading")],
            )
        zone_report, ground_report = graph.zones, []
        g = spec.geometry
        common_use = spec.common_use or spec.use.updated(
            heating_setpoint=spec.use.heating_setpoint.constant(
                g.zoning.apartments.common_heating_setpoint_c
            ),
            occupant_density_per_m2=0,
            equipment_gain_w_m2=0,
            lighting_gain_w_m2=0,
            dhw_kwh_m2_year=0,
        )
        has_common = any(
            z.get("zone_kind") in ("common", "stairwell") for z in zone_report.values()
        )
        if has_common:
            constant("common_activity", common_use.occupant_activity_w)
            for name in (
                "heating_setpoint",
                "cooling_setpoint",
                "occupancy_fraction",
                "equipment_fraction",
                "lighting_fraction",
                "dhw_fraction",
            ):
                data = getattr(common_use, name).compact_data(spec.climate.calendar_year)
                add(
                    "Schedule:Compact",
                    "common_" + name,
                    schedule_type_limits_name="any_number",
                    data=data,
                )
        if has_common:
            emit_airflow_schedules(spec.common_airflow or spec.airflow, "common_")
        # Reject misspelled zone selectors rather than quietly using building defaults.
        for assignment in spec.zone_uses:
            matches = [name for name, z in zone_report.items() if z["conditioned"] and
                       (name == assignment.zone_name if assignment.zone_name is not None else
                        z.get("zone_kind", z.get("physical_zone_kind")) == assignment.zone_kind)]
            if not matches:
                raise ValueError(f"Zone-use selector matches no conditioned zone: {assignment}")
        for exchange in spec.unconditioned_exchange:
            if not any(not z["conditioned"] and z.get("physical_zone_kind") == exchange.zone_kind
                       for z in zone_report.values()):
                raise ValueError(f"Exchange selector matches no unconditioned {exchange.zone_kind}")
        # 6. Separate common circulation area before optionally conserving residential loads.
        residential_area = sum(
            z["floor_area_m2"]
            for z in zone_report.values()
            if z["conditioned"] and z.get("zone_kind") not in ("common", "stairwell")
        )
        load_scale = (
            g.conditioned_floor_area_m2 / residential_area
            if has_common and g.zoning.apartments.conserve_residential_loads
            else 1
        )
        residential_use = spec.use.updated(
            **{
                name: getattr(spec.use, name) * load_scale
                for name in (
                    "occupant_density_per_m2",
                    "equipment_gain_w_m2",
                    "lighting_gain_w_m2",
                    "dhw_kwh_m2_year",
                )
            }
        )
        # 7. Assign explicit area and volume so zoning does not silently change building totals.
        for zone, data in zone_report.items():
            height = max(data["elevations_m"]) - min(data["elevations_m"])
            add(
                "Zone",
                zone,
                ceiling_height=height,
                floor_area=data["floor_area_m2"],
                volume=data["volume_m3"],
                part_of_total_floor_area="Yes" if data["conditioned"] else "No",
            )
            add(
                "Space",
                zone + "_space",
                zone_name=zone,
                ceiling_height=height,
                floor_area=data["floor_area_m2"],
                volume=data["volume_m3"],
            )
            if data["conditioned"]:
                common = data.get("zone_kind") in ("common", "stairwell")
                use = common_use if common else residential_use
                airflow = (spec.common_airflow or spec.airflow) if common else spec.airflow
                prefix = "common_" if common else ""
                scale = (spec.load_reference_area_m2 / g.conditioned_floor_area_m2
                         if spec.load_reference_area_m2 is not None else 1)
                load_area = data["floor_area_m2"] * scale
                assignments = sorted(
                    (x for x in spec.zone_uses if x.zone_name == zone or
                     (x.zone_kind is not None and x.zone_kind ==
                      data.get("zone_kind", data.get("physical_zone_kind")))),
                    key=lambda x: x.zone_name is not None)
                for assignment in assignments:
                    use = assignment.use or use
                    airflow = assignment.airflow or airflow
                    if assignment.reference_area_m2 is not None:
                        load_area = assignment.reference_area_m2
                if assignments:
                    prefix = zone + "_operation_"
                    constant(prefix + "activity", use.occupant_activity_w)
                    for name in ("heating_setpoint", "cooling_setpoint", "occupancy_fraction",
                                 "equipment_fraction", "lighting_fraction", "dhw_fraction"):
                        add("Schedule:Compact", prefix + name, schedule_type_limits_name="any_number",
                            data=getattr(use, name).compact_data(spec.climate.calendar_year))
                    emit_airflow_schedules(airflow, prefix)
                mean_fraction = sum(airflow.mechanical_vent_fraction.hourly(spec.climate.calendar_year)) / spec.climate.hours_in_year
                data["mean_outdoor_air_m3_s"] = (
                    (airflow.envelope_infiltration_ach * sum(airflow.infiltration_fraction.hourly(spec.climate.calendar_year)) / spec.climate.hours_in_year
                     + airflow.natural_exchange_ach * sum(airflow.natural_exchange_fraction.hourly(spec.climate.calendar_year)) / spec.climate.hours_in_year) * data["volume_m3"] / 3600
                    + load_area * airflow.mechanical_vent_l_s_m2 * mean_fraction / 1000)
                # The design/schedule mean above excludes weather multipliers.
                # It is an actual constant-flow mean only for the default coefficients.
                data["outdoor_air_mean_basis"] = "design_schedule_excludes_weather_multiplier"
                data["airflow_input"] = airflow.model_dump(mode="json")
                data["load_reference_area_m2"] = load_area
                data["operation_sources"] = [x.source for x in assignments]
                self._loads(add, zone, load_area, data["volume_m3"], spec,
                            use=use, airflow=airflow, schedule_prefix=prefix)
            else:
                for exchange in spec.unconditioned_exchange:
                    if data.get("physical_zone_kind") == exchange.zone_kind:
                        schedule = zone + "_unconditioned_exchange"
                        add("Schedule:Compact", schedule, schedule_type_limits_name="any_number",
                            data=exchange.fraction.compact_data(spec.climate.calendar_year))
                        add("ZoneInfiltration:DesignFlowRate", schedule,
                            zone_or_zonelist_or_space_or_spacelist_name=zone,
                            schedule_name=schedule, design_flow_rate_calculation_method="AirChanges/Hour",
                            air_changes_per_hour=exchange.outdoor_air_ach,
                            constant_term_coefficient=1, temperature_term_coefficient=0,
                            velocity_term_coefficient=0, velocity_squared_term_coefficient=0)
                        data["exchange_source"] = exchange.source
        assigned_area = sum(z.get("load_reference_area_m2", 0) for z in zone_report.values())
        if spec.load_reference_area_m2 is not None and abs(assigned_area - spec.load_reference_area_m2) > 1e-6:
            raise ValueError("Zone reference areas must sum to the declared building load reference area")
        # 8. Expose both slab halves while preserving one physical slab's heat capacity.
        for mass in graph.internal_mass:
            for face in ("a", "b"):
                add(
                    "InternalMass",
                    mass["name"] + "_" + face,
                    construction_name="internal_slab_face_" + face,
                    zone_or_zonelist_name=mass["zone"],
                    surface_area=mass["area_m2"],
                )
        for face in graph.surfaces:
            surface(
                face.name,
                face.zone,
                face.vertices,
                face.kind,
                face.construction,
                face.boundary,
                face.adjacent,
            )
            if face.boundary == "Ground":
                ground_report.append(
                    dict(surface=face.name, surface_type=face.kind, area_m2=face.area)
                )
        vertex_capacity_hint = (
            _shadow_overlap_vertex_capacity_hint(graph.surfaces) if visible_context else None
        )
        if vertex_capacity_hint is not None:
            # EnergyPlus sizes its private per-overlap vertex arrays from the
            # largest input polygon. This contained Ground-plane hint raises
            # that allocation without modifying any physical context face.
            add(
                "Shading:Site:Detailed",
                "epsm_shadow_overlap_vertex_capacity",
                number_of_vertices=len(vertex_capacity_hint),
                vertices=[
                    dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z)
                    for x, y, z in serialize_vertices(vertex_capacity_hint)
                ],
            )
        # 9. Reuse identical glazing systems and attach each thermal pane to its actual wall.
        glazing_names = {spec.facade.glazing.model_dump_json(): "window"}
        for opening in openings:
            glazing = spec.facade.value_for(
                "glazing", opening.metadata["facade_id"], opening.metadata["storey"]
            )
            key = glazing.model_dump_json()
            if key not in glazing_names:
                name = f"window_{len(glazing_names)}"
                glazing_names[key] = name
                add(
                    "WindowMaterial:SimpleGlazingSystem",
                    name + "_glazing",
                    u_factor=glazing.u_value_w_m2k,
                    solar_heat_gain_coefficient=glazing.solar_heat_gain_coefficient,
                    visible_transmittance=glazing.visible_transmittance,
                )
                add("Construction", name, outside_layer=name + "_glazing")
            fields = {
                f"vertex_{j + 1}_{axis}_coordinate": xyz[i]
                for j, xyz in enumerate(serialize_vertices(opening.vertices))
                for i, axis in enumerate("xyz")
            }
            add(
                "FenestrationSurface:Detailed",
                opening.name,
                surface_type="Window",
                construction_name=glazing_names[key],
                building_surface_name=opening.parent,
                number_of_vertices=4,
                **fields,
            )
            add(
                "SurfaceProperty:IncidentSolarMultiplier",
                opening.name + "_solar",
                surface_name=opening.name,
                incident_solar_multiplier=spec.facade.solar_shading_factor,
            )
        for shade in shades:
            if shade["kind"] == "context" and shade["name"] not in visible_context_names:
                continue
            add(
                "Shading:Building:Detailed",
                shade["name"],
                number_of_vertices=len(shade["vertices"]),
                vertices=[
                    dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z)
                    for x, y, z in serialize_vertices(shade["vertices"])
                ],
            )
        unknown = {o.facade_id for o in spec.facade.overrides} - graph.valid_facades
        if unknown:
            raise ValueError(f"Overrides reference unknown facades: {sorted(unknown)}")
        if spec.envelope.foundation.method == "kiva":
            foundation_report = apply_kiva(model, spec.envelope, polygons)
            removed = set(foundation_report["merged_ground_faces"])
            ground_report = [f for f in ground_report if f["surface"] not in removed]
            for item in foundation_report["assignments"]:
                for face in ground_report:
                    if face["surface"] == item["floor"]:
                        face["area_m2"] = item["floor_area_m2"]

        # 10. Validate geometric closure and reciprocal boundaries before schema validation.
        try:
            validation = validate_surfaces(model, zone_report)
        except ValueError as error:
            raise CompilationError(GEOMETRY_INVARIANT_FAILURE, str(error)) from error
        validation["vertex_order"] = dict(
            convention="UpperLeftCorner/Counterclockwise", operation="cyclic_rotation_only"
        )
        # Only emit referenced constructions/materials: unused warnings are avoidable.
        used = {
            o["construction_name"]
            for kind in ("BuildingSurface:Detailed", "FenestrationSurface:Detailed", "InternalMass")
            for o in model.get(kind, {}).values()
        }
        used.update(o["footing_wall_construction_name"] for o in model.get("Foundation:Kiva", {}).values() if "footing_wall_construction_name" in o)
        for kind in ("Construction", "Construction:AirBoundary"):
            if kind in model:
                model[kind] = {n: o for n, o in model[kind].items() if n in used}
                if not model[kind]:
                    del model[kind]
        used_materials = {v for o in model.get("Construction", {}).values() for v in o.values()}
        used_materials.update(o["footing_material_name"] for o in model.get("Foundation:Kiva", {}).values() if "footing_material_name" in o)
        for kind in ("Material", "WindowMaterial:SimpleGlazingSystem"):
            model[kind] = {n: o for n, o in model.get(kind, {}).items() if n in used_materials}
            if not model[kind]:
                del model[kind]

        # 11. Reject invalid engine input before returning an auditable compilation result.
        errors = sorted(self.validator.iter_errors(model), key=lambda e: str(e.path))
        if errors:
            raise CompilationError(
                ENERGYPLUS_SCHEMA_FAILURE,
                "epJSON schema errors:\n"
                + "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:20]),
            )
        area = sum(z["floor_area_m2"] for z in zone_report.values() if z["conditioned"])
        volume = sum(z["volume_m3"] for z in zone_report.values() if z["conditioned"])
        report = dict(
            footprint_cleanup=prepared_footprints(g)[1],
            origin_m=origin,
            orientation_deg=g.orientation_deg,
            zones=zone_report,
            facades=facade_report,
            ground_surfaces=ground_report,
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
            gross_floor_area_m2=g.conditioned_floor_area_m2,
            residential_load_scale=load_scale,
            conditioned_floor_area_m2=area,
            conditioned_volume_m3=volume,
            effective_outdoor_air_ach=3600 * sum(
                z.get("mean_outdoor_air_m3_s", 0) for z in zone_report.values()) / volume,
            load_reference_area_m2=sum(z.get("load_reference_area_m2", 0) for z in zone_report.values()),
            foundation=foundation_report,
            ground_temperature=(ground_temperature.model_dump(mode="json") if ground_temperature is not None else None),
            approximations=graph.approximations,
            validation=validation,
            surfaces={
                f.name: dict(
                    part_id=f.part_id,
                    part_ids=f.part_id.split("+"),
                    facade_id=f.facade_id,
                    zone=f.zone,
                    storey=f.storey,
                    area_m2=f.area,
                    annotations=f.annotations,
                )
                for f in graph.surfaces
            },
            openings={o.name: o.metadata for o in openings},
            shading={o["name"]: {k: v for k, v in o.items() if k != "vertices"} for o in shades},
            layout=graph.layout_report,
            zoning=getattr(graph, "zoning_report", {}),
            context={
                **context.report,
                "visibility": visibility,
                "detached_mirroring_disabled": context_mirroring_disabled,
                "shadow_overlap_vertex_capacity": (
                    {
                        "method": "contained_ground_polygon",
                        "surface": "epsm_shadow_overlap_vertex_capacity",
                        "input_vertices": _SHADOW_OVERLAP_VERTEX_HINT_COUNT,
                        "energyplus_24_2_capacity": 31,
                    }
                    if vertex_capacity_hint is not None
                    else None
                ),
                **mirror_proof,
            },
            logical_window_count=resolved.logical_window_count,
            thermal_pane_count=len(openings),
            compiler_settings=self.settings.model_dump(mode="json"),
            input_schema_sha256=hashlib.sha256(
                json.dumps(BuildingSpec.model_json_schema(), sort_keys=True).encode()
            ).hexdigest(),
            geometry_backends=backend_versions(),
            serialized_geometry_sha256=hashlib.sha256(
                json.dumps(
                    {
                        kind: model.get(kind, {})
                        for kind in (
                            "BuildingSurface:Detailed",
                            "FenestrationSurface:Detailed",
                            "Shading:Building:Detailed",
                            "Shading:Site:Detailed",
                        )
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            simulation_configuration={
                kind: model.get(kind, {})
                for kind in (
                    "Building",
                    "Timestep",
                    "HeatBalanceAlgorithm",
                    "ShadowCalculation",
                    "RunPeriod",
                    "Output:SQLite",
                    "Output:Variable",
                    "Output:Diagnostics",
                )
            },
            internal_mass=graph.internal_mass,
            parts=[p.model_dump(mode="json") for p in g.parts],
        )
        if spec.envelope.foundation.method == "kiva":
            for name in foundation_report["merged_ground_faces"]:
                report["surfaces"].pop(name)
            for item in foundation_report["assignments"]:
                report["surfaces"][item["floor"]]["area_m2"] = item["floor_area_m2"]
        return model, CompilationReport(
            run_id=hashlib.sha256(
                json.dumps(
                    [self._input_identity(spec), model], sort_keys=True, allow_nan=False
                ).encode()
            ).hexdigest(),
            compiler_version=COMPILER_VERSION,
            compiler_sha256=self.compiler_hash,
            engine_version=self.version,
            engine_sha256=self.engine_hash,
            schema_sha256=self.schema_hash,
            spec_sha256=spec.physical_hash(),
            report_json=json.dumps(report, sort_keys=True),
        )

    @staticmethod
    def _loads(add, zone, area, volume, spec, *, use=None, airflow=None, schedule_prefix=""):
        """Emit per-zone schedules references, internal gains, airflow and ideal loads.

        Parameters
        ----------
        add : callable
            Object insertion callback accepting kind, name and keyword fields.
        zone : str
            Resolved thermal-zone name used by emitted objects.
        area : float
            Resolved zone floor area in square metres, used to scale per-area loads and
            ventilation.
        volume : float
            Resolved zone volume in cubic metres; retained by the callback interface but
            currently unused in this emitter.
        spec : BuildingSpec
            Validated building input; geometry-only helpers also accept an object exposing the
            fields they consume.
        use : UseSpec or None
            Per-zone occupancy and load controls; None uses the building defaults. Default:
            ``None``.
        airflow : AirflowSpec or None
            Per-zone leakage and ventilation controls; None uses the building defaults. Default:
            ``None``.
        schedule_prefix : str
            Prefix selecting ordinary or common-zone schedule names. Default: ``''``.

        Returns
        -------
        None
            Adds objects through the supplied add callback.

        Notes
        -----
        Outdoor air converts L/s/m2 to m3/s. Infiltration and natural exchange remain separate.
        DHW flow is calibrated to annual thermal demand using fixed 10/55 C water temperatures;
        no fan or heat-pump electricity is inferred here.

        Examples
        --------
        Supply a validated BuildingSpec as ``building``; an EnergyPlus object insertion callback
        as ``add``.

        Example::

            from epsm_core.compiler import EnergyPlusCompiler

            EnergyPlusCompiler._loads(add, "zone", 80, 240, building)
        """

        # 1. Emit per-zone schedules references, internal gains, airflow and ideal loads.
        u, a = use or spec.use, airflow or spec.airflow
        add(
            "People",
            zone + "_people",
            zone_or_zonelist_or_space_or_spacelist_name=zone,
            number_of_people_schedule_name=schedule_prefix + "occupancy_fraction",
            number_of_people_calculation_method="People",
            number_of_people=area * u.occupant_density_per_m2,
            fraction_radiant=0.3,
            activity_level_schedule_name=schedule_prefix + "activity",
        )
        for obj, label, watts in (
            ("ElectricEquipment", "equipment", u.equipment_gain_w_m2),
            ("Lights", "lighting", u.lighting_gain_w_m2),
        ):
            add(
                obj,
                zone + "_" + label,
                zone_or_zonelist_or_space_or_spacelist_name=zone,
                schedule_name=schedule_prefix + label + "_fraction",
                design_level_calculation_method="LightingLevel"
                if obj == "Lights"
                else "EquipmentLevel",
                **(
                    {"lighting_level": watts * area}
                    if obj == "Lights"
                    else {"design_level": watts * area}
                ),
                fraction_radiant=0.3,
                **({"fraction_lost": 1 - u.equipment_heat_fraction} if obj == "ElectricEquipment" else {}),
            )
        add(
            "ZoneInfiltration:DesignFlowRate",
            zone + "_envelope_leakage",
            zone_or_zonelist_or_space_or_spacelist_name=zone,
            schedule_name=schedule_prefix + "infiltration_fraction",
            design_flow_rate_calculation_method="AirChanges/Hour",
            air_changes_per_hour=a.envelope_infiltration_ach,
            constant_term_coefficient=a.infiltration_coefficients[0],
            temperature_term_coefficient=a.infiltration_coefficients[1],
            velocity_term_coefficient=a.infiltration_coefficients[2],
            velocity_squared_term_coefficient=a.infiltration_coefficients[3],
        )
        if a.topology == "S":
            add(
                "ZoneVentilation:DesignFlowRate",
                zone + "_natural_exchange",
                zone_or_zonelist_or_space_or_spacelist_name=zone,
                schedule_name=schedule_prefix + "natural_exchange_fraction",
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
            heating_setpoint_temperature_schedule_name=schedule_prefix + "heating_setpoint",
            cooling_setpoint_temperature_schedule_name=schedule_prefix + "cooling_setpoint",
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
            outdoor_air_schedule_name=schedule_prefix + "mechanical_vent_fraction",
        )
        add(
            "ZoneHVAC:IdealLoadsAirSystem",
            zone + "_ideal",
            availability_schedule_name="on",
            zone_supply_air_node_name=zone + "_supply",
            heating_availability_schedule_name=schedule_prefix + "heating_availability",
            cooling_availability_schedule_name=schedule_prefix + "cooling_availability" if u.cooling_enabled else "off",
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
        # 2. Calibrate peak water flow so the repeated daily schedule integrates to annual
        # demand.
        mean = sum(u.dhw_fraction.hourly(spec.climate.calendar_year)) / spec.climate.hours_in_year
        flow = (
            u.dhw_kwh_m2_year
            * area
            * 3.6e6
            / (spec.climate.hours_in_year * 3600 * mean * 998.2 * 4180 * 45)
            if mean
            else 0
        )
        add(
            "WaterUse:Equipment",
            zone + "_dhw",
            peak_flow_rate=flow,
            flow_rate_fraction_schedule_name=schedule_prefix + "dhw_fraction",
            target_temperature_schedule_name="water_hot",
            hot_water_supply_temperature_schedule_name="water_hot",
            cold_water_supply_temperature_schedule_name="water_cold",
        )

    def write(self, spec, directory):
        """Compile and write the model, building specification and compilation report.

        Parameters
        ----------
        spec : BuildingSpec
            Validated building input; geometry-only helpers also accept an object exposing the
            fields they consume.
        directory : str or Path or None
            Local artifact directory; consult Notes for creation, overwrite and default-path
            behavior.

        Returns
        -------
        CompilationReport
            Audit report for the emitted model.

        Notes
        -----
        Creates directory and overwrites the three named JSON files if present. Callers needing
        isolation must enforce an empty directory, as EnergyPlusRunner does. Writes are
        sequential, not transactional.

        Examples
        --------
        Supply a validated BuildingSpec as ``building``; an initialized EnergyPlusCompiler as
        ``compiler`` (EnergyPlus 24.2 required).

        Example::

            report = compiler.write(building, "output/compiled")
        """

        # 1. Compile and write the model, building specification and compilation report.
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
SOLAR_VARIABLE = "Enclosure Windows Total Transmitted Solar Radiation Energy"
OUTPUT_VARIABLES = ENERGY_VARIABLES + (
    "Zone Mean Air Temperature",
    SOLAR_VARIABLE,
)
