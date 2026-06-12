from __future__ import annotations

from pathlib import Path

from honeybee.model import Model
from honeybee.shade import Shade
from honeybee_energy.simulation.parameter import SimulationParameter
from honeybee_energy.simulation.output import SimulationOutput
from honeybee_energy.simulation.runperiod import RunPeriod
from honeybee_energy.simulation.control import SimulationControl
from honeybee_energy.writer import energyplus_idf_version
from ladybug_geometry.geometry3d.pointvector import Point3D
from ladybug_geometry.geometry3d.face import Face3D

from .building_params import BuildingParams
from .constructions import apply_constructions
from .geometry import build_rooms, BuildingRooms
from .hvac import apply_hvac
from .programs import blend_building_program, sveby_basement


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Simulation parameters via Honeybee
# ---------------------------------------------------------------------------

_OUTPUT_VARIABLES = [
    "Zone Ideal Loads Zone Total Heating Energy",
    "Zone Ideal Loads Zone Total Cooling Energy",
    "Zone Mean Air Temperature",
    "Zone Windows Total Transmitted Solar Radiation Energy",
    "Zone People Total Heating Energy",
    "Zone Electric Equipment Total Heating Energy",
    "Zone Lights Total Heating Energy",
    "Water Use Equipment Heating Energy",
    "Site Outdoor Air Drybulb Temperature",
]


def _make_sim_par() -> SimulationParameter:
    """Build a SimulationParameter with the outputs we need."""
    sim_output = SimulationOutput()
    sim_output.include_sqlite = True
    sim_output.include_html = True
    sim_output.reporting_frequency = "Hourly"
    sim_output.add_zone_energy_use()
    sim_output.add_gains_and_losses()
    sim_output.add_summary_report("AnnualBuildingUtilityPerformanceSummary")
    # extras not covered by the helpers above
    for var in _OUTPUT_VARIABLES:
        sim_output.add_output(var)

    sim_par = SimulationParameter(
        output=sim_output,
        run_period=RunPeriod(),
        timestep=4,
        terrain_type="Suburbs",
        simulation_control=SimulationControl(
            do_zone_sizing=False,
            do_system_sizing=False,
            do_plant_sizing=False,
        ),
    )
    return sim_par


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def context_shades_from_footprints(
    context_footprints,
    origin_x: float,
    origin_y: float,
) -> list[Shade]:
    """Create Honeybee Shade objects from context building footprints.

    Each context footprint is extruded into walls + a roof cap.
    Coordinates are shifted by (origin_x, origin_y) to match the
    target building's local coordinate system.
    """
    shades: list[Shade] = []
    for i, cf in enumerate(context_footprints):
        pts = cf.footprint_pts
        h = cf.height
        if len(pts) < 3 or h <= 0:
            continue

        local = [(p[0] - origin_x, p[1] - origin_y) for p in pts]
        n = len(local)

        # Walls
        for j in range(n):
            x0, y0 = local[j]
            x1, y1 = local[(j + 1) % n]
            wall_pts = [
                Point3D(x0, y0, 0), Point3D(x1, y1, 0),
                Point3D(x1, y1, h), Point3D(x0, y0, h),
            ]
            shades.append(Shade(f"ctx_{i}_wall_{j}", Face3D(wall_pts)))

        # Roof cap
        roof_pts = [Point3D(x, y, h) for x, y in local]
        shades.append(Shade(f"ctx_{i}_roof", Face3D(roof_pts)))

    return shades


def build_model(
    name: str,
    footprint_pts: list[list[float]],
    params: BuildingParams,
    context_shades: list[Shade] | None = None,
) -> Model:
    """Build a Honeybee Model from a footprint polygon and building parameters."""
    model, _rooms = build_model_with_rooms(
        name, footprint_pts, params, context_shades=context_shades
    )
    return model


def build_model_with_rooms(
    name: str,
    footprint_pts: list[list[float]],
    params: BuildingParams,
    context_shades: list[Shade] | None = None,
) -> tuple[Model, BuildingRooms]:
    """Build a Honeybee Model and return it alongside its :class:`BuildingRooms`.

    Identical model assembly to :func:`build_model`, but also surfaces the
    perimeter/core room decomposition so callers (e.g. the ``Building``
    aggregate) can derive the heated floor area without rebuilding geometry.
    """
    p = params
    floor_height = _clamp(p.floor_height, 2.2, 6.0)
    num_floors = max(1, p.num_floors)

    # If cold_attic, add one extra floor for the unconditioned attic zone.
    geom_floors = num_floors + 1 if p.cold_attic else num_floors

    bldg = build_rooms(
        footprint_pts=footprint_pts,
        floor_height=floor_height,
        num_floors=geom_floors,
        wwr=p.wwr,
        apartment_depth=max(0.0, p.apartment_depth),
        identifier=name,
        num_basement_floors=p.num_basement_floors,
        basement_floor_height=p.basement_floor_height,
        basement_depth_below_grade=p.basement_depth_below_grade,
        basement_wwr=p.basement_wwr,
    )

    # -- cold attic: move top-floor rooms to core (unconditioned) ----------
    if p.cold_attic:
        max_z = max(
            max(v.z for v in face.vertices)
            for room in bldg.all for face in room.faces
        )
        attic_rooms = [
            r for r in bldg.perimeter
            if max(max(v.z for v in f.vertices) for f in r.faces) > max_z - 0.1
        ]
        for r in attic_rooms:
            bldg.perimeter.remove(r)
            bldg.core.append(r)

    # -- constructions (all rooms, including core) -------------------------
    apply_constructions(bldg.all, p)

    # -- blended program for perimeter (conditioned) rooms -----------------
    program = blend_building_program(
        f"{name}_Program",
        residential_pct=p.residential_pct,
        garage_pct=p.garage_pct,
        occupant_density=max(0.0, p.occupant_density),
        lighting_w_m2=_clamp(p.lighting_w_m2, 0.0, 50.0),
        equipment_w_m2=_clamp(p.equipment_w_m2, 0.0, 80.0),
        dhw_kwh_m2=p.dhw_kwh_m2,
    )
    bsmt_program = sveby_basement()
    for room in bldg.perimeter:
        if "basement" in room.identifier.lower():
            room.properties.energy.program_type = bsmt_program
        else:
            room.properties.energy.program_type = program

    # -- HVAC for perimeter (dwelling) rooms at p.t_heating ----------------
    apply_hvac(bldg.perimeter, p)

    # -- Optional second HVAC pass for the core zone (stair/corridor) ------
    # When ``core_setpoint_C`` is set, the core is treated as a semi-heated
    # buffer zone (e.g. 18 °C) rather than fully unconditioned.  This matches
    # the typical 1960s lamellhus stair-shaft with a small radiator.  The
    # core's heating energy still shows up in ``heating_kwh``, but BBR's
    # A-temp excludes it from the denominator, so kWh/m² is reported on the
    # perimeter (dwelling) area only.
    if p.core_setpoint_C is not None and bldg.core:
        from dataclasses import replace as _dc_replace
        p_core = _dc_replace(p, t_heating=float(p.core_setpoint_C))
        apply_hvac(bldg.core, p_core, zone_label="CORE")

    return Model(name, rooms=bldg.all, orphaned_shades=context_shades), bldg


def build_idf_text(
    name: str,
    footprint_pts: list[list[float]],
    params: BuildingParams,
    context_shades: list[Shade] | None = None,
    model: Model | None = None,
) -> str:
    """Generate complete IDF text ready for EnergyPlus.

    Pass a prebuilt ``model`` (e.g. from :func:`build_model_with_rooms`) to
    avoid reconstructing the geometry; otherwise one is built internally.
    """
    if model is None:
        model = build_model(name, footprint_pts, params, context_shades=context_shades)
    sim_par = _make_sim_par()
    version = energyplus_idf_version()
    idf_text = "\n\n".join([version, sim_par.to_idf(name), model.to.idf(model)]) + "\n"
    # Honeybee emits lowercase field comments but the Spider IDF
    # Viewer relies on title-case matches for geometry parsing.
    idf_text = idf_text.replace("!- number of vertices", "!- Number of Vertices")
    idf_text = idf_text.replace("!- surface type", "!- Surface Type")
    idf_text = idf_text.replace("!- zone name", "!- Zone Name")

    # Ground temperature: E+ manual recommends indoor temp minus 2 °C for
    # Site:GroundTemperature:BuildingSurface (under a conditioned basement).
    ground_t = params.t_heating - 2.0
    gt = f"{ground_t:.1f}"
    idf_text += (
        "\n\nSite:GroundTemperature:BuildingSurface,\n"
        f"  {gt},{gt},{gt},{gt},{gt},{gt},"
        f"{gt},{gt},{gt},{gt},{gt},{gt};\n"
    )

    # Basement infiltration: Honeybee's Infiltration only supports
    # flow_per_exterior_area which is 0 for fully-buried basements.
    # Inject raw IDF ZoneInfiltration objects using AirChanges/Hour.
    basement_zones = [
        r.identifier.upper()
        for r in model.rooms
        if "basement" in r.identifier.lower()
    ]
    if basement_zones and params.infiltration_ach > 0:
        bsmt_ach = params.infiltration_ach
        for zone_id in basement_zones:
            idf_text += (
                f"\n\nZoneInfiltration:DesignFlowRate,\n"
                f"  Inf_Basement_{zone_id},  !- Name\n"
                f"  {zone_id},               !- Zone Name\n"
                f"  INF_SCH,                 !- Schedule Name\n"
                f"  AirChanges/Hour,         !- Design Flow Rate Calculation Method\n"
                f"  ,                        !- Design Flow Rate {{m3/s}}\n"
                f"  ,                        !- Flow per Zone Floor Area {{m3/s-m2}}\n"
                f"  ,                        !- Flow per Exterior Surface Area {{m3/s-m2}}\n"
                f"  {bsmt_ach};              !- Air Changes per Hour {{1/hr}}\n"
            )

    # Natural ventilation: ZoneVentilation:WindandStackOpenArea
    if params.nat_vent_t_open_c is not None:
        idf_text += _nat_vent_idf_snippet(model, params)

    return idf_text


def _nat_vent_idf_snippet(model: "Model", params: BuildingParams) -> str:
    """Build ZoneVentilation:WindandStackOpenArea IDF text for all heated zones.

    Windows open when ALL conditions hold simultaneously:
    - Indoor temp ≥ ``nat_vent_t_open_c``            (room is warm enough to benefit)
    - Outdoor temp ≤ ``nat_vent_max_outdoor_t_c``     (outdoor air is actually cooler)
    - Indoor − outdoor ≥ 0 °C                         (only cool, never heat by opening)
    - Wind speed ≤ ``nat_vent_max_wind_ms``

    Opening area per zone = floor_area × ``nat_vent_opening_frac``
    (default 0.06 ≈ WWR 15% × 40% operable).
    """
    t_open = params.nat_vent_t_open_c
    t_min_out = params.nat_vent_min_outdoor_t_c
    t_max_out = params.nat_vent_max_outdoor_t_c
    max_wind = params.nat_vent_max_wind_ms
    opening_frac = params.nat_vent_opening_frac
    h_diff = params.floor_height / 2.0  # height diff used for stack-effect calc [m]

    parts: list[str] = [
        "\n\nSchedule:Constant,",
        "  NatVent_AlwaysOn,    !- Name",
        "  Fraction,            !- Schedule Type Limits Name",
        "  1.0;                 !- Hourly Value",
    ]

    for room in model.rooms:
        zone_id = room.identifier
        if "basement" in zone_id.lower():
            continue
        opening_area = max(0.1, room.floor_area * opening_frac)
        parts += [
            f"\n\nZoneVentilation:WindandStackOpenArea,",
            f"  NatVent_{zone_id},   !- Name",
            f"  {zone_id},            !- Zone Name",
            f"  {opening_area:.3f},   !- Opening Area {{m2}}",
            f"  NatVent_AlwaysOn,     !- Opening Area Fraction Schedule Name",
            f"  Autocalculate,        !- Opening Effectiveness",
            f"  0.0,                  !- Effective Angle {{deg}}",
            f"  {h_diff:.2f},         !- Height Difference {{m}}",
            f"  Autocalculate,        !- Discharge Coefficient for Opening",
            f"  {t_open:.1f},         !- Minimum Indoor Temperature {{C}}",
            f"  ,                     !- Minimum Indoor Temperature Schedule Name",
            f"  100.0,                !- Maximum Indoor Temperature {{C}}",
            f"  ,                     !- Maximum Indoor Temperature Schedule Name",
            f"  0.0,                  !- Delta Temperature {{C}}",
            f"  ,                     !- Delta Temperature Schedule Name",
            f"  {t_min_out:.1f},       !- Minimum Outdoor Temperature {{C}}",
            f"  ,                     !- Minimum Outdoor Temperature Schedule Name",
            f"  {t_max_out:.1f},      !- Maximum Outdoor Temperature {{C}}",
            f"  ,                     !- Maximum Outdoor Temperature Schedule Name",
            f"  {max_wind:.1f};       !- Maximum Wind Speed {{m/s}}",
        ]

    return "\n".join(parts)


def write_idf(
    path: Path,
    name: str,
    footprint_pts: list[list[float]],
    params: BuildingParams,
    context_shades: list[Shade] | None = None,
    model: Model | None = None,
) -> None:
    """Write IDF file to disk."""
    path.write_text(build_idf_text(name, footprint_pts, params,
                                   context_shades=context_shades, model=model))
