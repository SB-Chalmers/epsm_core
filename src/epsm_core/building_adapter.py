"""Migration bridge from physical authoring to the existing numerical engine.

Parallel constituents are reduced to a thermal layer only here. The original
materials remain in the Building and its physical inventory.
"""

from __future__ import annotations

from types import SimpleNamespace

from epsm_data.domain import Element
from epsm_data.domain.enums import BuildingElement as Role

from epsm_core._logging import operation as logged_operation

from .specs import (
    BuildingSpec,
    ClimateSpec,
    ConstructionSpec,
    EnvelopeSpec,
    FacadeOverride,
    GlazingSpec,
    LayerSpec,
    MaterialSpec,
)
from .weather import Weather


def thermal_construction(element):
    """Reduce a supplied physical assembly without changing its material inventory."""
    if not isinstance(element, Element):
        raise ValueError("Opaque thermal construction requires a layered Element")
    layers = []
    for component in element.components:
        for slot in component.layers:
            layer = slot.layer
            if any(abs(share.thickness - layer.thickness) > 1e-9 for share in layer.materials):
                raise ValueError("Thermal reduction currently requires equal parallel path depths")
            density = sum(s.area_fraction * s.material.density for s in layer.materials)
            capacity = sum(s.area_fraction * s.material.density * s.material.specific_heat
                           for s in layer.materials)
            def mean(field):
                return sum(s.area_fraction * getattr(s.material, field) for s in layer.materials)

            layers.append(LayerSpec(thickness_m=layer.thickness, material=MaterialSpec(
                name=layer.name, conductivity_w_mk=layer.thickness / layer.r_value,
                density_kg_m3=density, specific_heat_j_kgk=capacity / density,
                thermal_absorptance=mean("thermal_absorptance"),
                solar_absorptance=mean("solar_absorptance"),
                visible_absorptance=mean("visible_absorptance"),
                roughness=layer.materials[0].material.roughness.value,
            )))
    return ConstructionSpec(layers=tuple(layers))


def _glazing(window):
    return GlazingSpec(u_value_w_m2k=window.u_value,
                      solar_heat_gain_coefficient=window.shgc,
                      visible_transmittance=window.vt)


def _envelope_for_building(building, *, convert=thermal_construction):
    """Build the nominal envelope from explicit physical assignments."""
    assignments = building.construction_set.elements if building.construction_set else {}

    def construction(role, fallback=None):
        physical = next((e.construction for e in building.elements if e.role == role), None)
        value = physical or assignments.get(role)
        if value is None:
            if fallback is not None:
                return fallback
            raise ValueError(f"No construction for {role.value}")
        return convert(value)

    wall = construction(Role.EXT_WALL)
    top = construction(Role.TOP_FLOOR)
    ground = construction(Role.BASEMENT_FLOOR, construction(Role.GROUND_FLOOR))
    intermediate = construction(Role.INTERMEDIATE_FLOOR, ground)
    return EnvelopeSpec(wall=wall, top=top, ground=ground,
        intermediate_floor=intermediate,
        weather_shell=construction(Role.ROOF, top),
        basement_wall=construction(Role.BASEMENT_WALL, wall),
        basement_ceiling=construction(Role.GROUND_FLOOR, ground),
        thermal_bridge_uplift_fraction=(building.thermal_bridge_uplift_fraction or 0)
        if building.thermal_bridge_delta_u_w_m2k is not None else building.thermal_bridge_uplift_fraction,
        thermal_bridge_delta_u_w_m2k=building.thermal_bridge_delta_u_w_m2k,
        foundation=building.foundation,
        ground_temperature=building.ground_temperature)


def _physical_element_owners(building, resolved):
    """Link thermal panes, faces and internal mass to original physical elements."""
    walls = {(e.facade_id, e.storey, e.boundary): e for e in building.elements if e.role == Role.EXT_WALL}
    basement = {(e.facade_id, e.boundary): e for e in building.elements if e.role == Role.BASEMENT_WALL}
    roofs = {e.part_id: e for e in building.elements if e.role == Role.ROOF}
    horizontal = {(e.part_id, round(e.elevation_m, 8)): e for e in building.elements
                  if e.elevation_m is not None and e.facade_id is None}
    windows = {(element.facade_id, element.storey): element for element in building.elements
               if element.role == Role.WINDOW}
    surfaces = {}
    faces = {face.name: face for face in resolved.graph.surfaces}
    for face in resolved.graph.surfaces:
        physical = None
        if face.kind == "Wall":
            collection = basement if face.cell_kind == "basement" else walls
            key = (face.facade_id, face.boundary) if face.cell_kind == "basement" else \
                (face.facade_id, face.storey, face.boundary)
            physical = collection.get(key)
            if face.boundary == "Surface" and physical is None:
                other = faces[face.adjacent]
                key = (face.facade_id, "Internal") if face.cell_kind == "basement" else \
                    (face.facade_id, face.storey, "Internal")
                other_key = (other.facade_id, "Internal") if face.cell_kind == "basement" else \
                    (other.facade_id, other.storey, "Internal")
                physical = collection.get(key) or collection.get(other_key)
        elif face.kind == "Roof" and face.cell_kind == "attic":
            physical = roofs.get(face.part_id)
        elif len({round(vertex[2], 8) for vertex in face.vertices}) == 1:
            physical = horizontal.get((face.part_id, round(face.vertices[0][2], 8)))
        if physical is not None:
            surfaces[face.name] = physical
    mass = {}
    for item in resolved.graph.internal_mass:
        if item.get("physical_boundary") == "Internal":
            physical = basement.get((item["facade_id"], "Internal")) if item["storey"] < 0 else \
                walls.get((item["facade_id"], item["storey"], "Internal"))
        else:
            physical = horizontal.get((item["part_id"], round(item["elevation_m"], 8)))
        if physical is not None:
            mass[item["name"]] = physical
    openings = {opening.name: windows[(opening.metadata["facade_id"], opening.metadata["storey"])]
                for opening in resolved.openings
                if (opening.metadata["facade_id"], opening.metadata["storey"]) in windows}
    return {"surfaces": surfaces, "internal_mass": mass, "openings": openings}


def _surface_constructions_for_building(building, geometry, facade, envelope, *, resolved=None,
                                       owners=None, convert=thermal_construction):
    """Resolve physical surface overrides identically for adaptation and preflight."""
    from .pipeline import resolve_geometry

    if resolved is None:
        resolved = resolve_geometry(SimpleNamespace(geometry=geometry, facade=facade), panelize=True)
    owners = (owners if owners is not None else _physical_element_owners(building, resolved))["surfaces"]
    surface_constructions = {}
    for face in resolved.graph.surfaces:
        physical = owners.get(face.name)
        role = face.construction.removesuffix("_reverse").removeprefix("unconditioned_")
        if physical is not None:
            assembly = convert(physical.construction)
            if getattr(envelope, role, None) != assembly:
                surface_constructions[face.name] = assembly
    return surface_constructions


@logged_operation("model.convert", level=10)
def to_spec(building, weather, *, geometry_cache=None):
    """Produce the legacy validated engine specification with exact target assignments."""
    spec, _, _ = _prepare_spec(building, weather, geometry_cache=geometry_cache)
    return spec


def _prepare_spec(building, weather, *, geometry_cache=None, engine=None):
    """Convert and validate once, retaining geometry and owners for resolved export."""
    building.readiness(engine=engine, weather=weather).require()
    if isinstance(weather, Weather):
        climate = weather.climate
    elif isinstance(weather, ClimateSpec):
        climate = weather
    else:
        climate = Weather.from_epw(weather).climate
    assemblies = {}

    def convert(assembly):
        # Repeated faces often have the same immutable physical assignment.
        # Keep thermal conversion local to this captured Building preparation.
        key = id(assembly)
        if key not in assemblies:
            assemblies[key] = thermal_construction(assembly)
        return assemblies[key]

    envelope = _envelope_for_building(building, convert=convert)
    intermediate = envelope.intermediate_floor
    # Preserve explicit zero-window and shading choices, including facade-wide
    # overrides that have no corresponding physical window instance.
    overrides = {(override.facade_id, override.storey): override
                 for override in building.facade.overrides}
    for element in building.elements:
        if element.role != Role.WINDOW:
            continue
        overrides[(element.facade_id, element.storey)] = FacadeOverride(
            facade_id=element.facade_id, storey=element.storey,
            glazing=_glazing(element.construction),
            **{field: building.facade.value_for(field, element.facade_id, element.storey)
               for field in ("wwr", "layout", "reveal_depth_m", "overhang")},
        )
    facade = building.facade.updated(overrides=tuple(overrides.values()))
    spec = BuildingSpec(identifier=building.identifier, geometry=building.geometry,
        facade=facade, climate=climate, envelope=envelope, airflow=building.hvac.airflow,
        load_reference_area_m2=building.effective_load_reference_area_m2,
        use=building.operation, context=building.context, delivery=building.hvac.delivery,
        renewables=building.hvac.renewables, provenance=building.provenance,
        zone_uses=building.zone_uses, unconditioned_exchange=building.unconditioned_exchange)
    from .pipeline import resolve_geometry

    resolved = resolve_geometry(spec, panelize=True, cache=geometry_cache)
    owners = _physical_element_owners(building, resolved)
    surface_constructions = _surface_constructions_for_building(
        building, spec.geometry, spec.facade, envelope, resolved=resolved,
        owners=owners, convert=convert)
    mass_constructions = {}
    for mass in resolved.graph.internal_mass:
        physical = owners["internal_mass"].get(mass["name"])
        if physical is not None:
            assembly = convert(physical.construction)
            if assembly != intermediate:
                mass_constructions[mass["name"]] = assembly
    # Every override is a validated ConstructionSpec associated with a name in
    # this resolved graph. Only these newly created assignment maps change;
    # repeating all BuildingSpec validators would recheck unchanged inputs.
    spec = spec.model_copy(update={"surface_constructions": surface_constructions,
                                  "internal_mass_constructions": mass_constructions})
    return spec, resolved, owners


@logged_operation("simulation.building")
def run_building(building, *, weather, directory, energyplus=None, settings=None, **options):
    """Run the real EnergyPlus adapter against an automatically captured snapshot."""
    from .building import BuildingSnapshot
    from .preflight import preflight_energyplus
    from .runner import EnergyPlusRunner

    snapshot = building if isinstance(building, BuildingSnapshot) else building.snapshot()
    snapshot.to_building().readiness(engine="energyplus").require()
    weather = weather if isinstance(weather, Weather) else Weather.from_epw(weather)
    weather.validate()
    spec = snapshot.to_spec(weather)
    preflight_energyplus(spec).require()
    result = EnergyPlusRunner(energyplus, settings=settings).run(spec, directory, **options)
    result.diagnostics["building_snapshot_id"] = snapshot.sha256
    result.diagnostics["weather_sha256"] = weather.sha256
    return result
