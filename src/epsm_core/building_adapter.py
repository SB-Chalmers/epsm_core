"""Migration bridge from physical authoring to the existing numerical engine.

Parallel constituents are reduced to a thermal layer only here. The original
materials remain in the Building and its physical inventory.
"""

from __future__ import annotations

from types import SimpleNamespace

from epsm_data.domain import Element
from epsm_data.domain.enums import BuildingElement as Role

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


def _envelope_for_building(building):
    """Build the nominal envelope from explicit physical assignments."""
    assignments = building.construction_set.elements if building.construction_set else {}

    def construction(role, fallback=None):
        physical = next((e.construction for e in building.elements if e.role == role), None)
        value = physical or assignments.get(role)
        if value is None:
            if fallback is not None:
                return fallback
            raise ValueError(f"No construction for {role.value}")
        return thermal_construction(value)

    wall = construction(Role.EXT_WALL)
    top = construction(Role.TOP_FLOOR)
    ground = construction(Role.BASEMENT_FLOOR, construction(Role.GROUND_FLOOR))
    intermediate = construction(Role.INTERMEDIATE_FLOOR, ground)
    return EnvelopeSpec(wall=wall, top=top, ground=ground,
        intermediate_floor=intermediate,
        weather_shell=construction(Role.ROOF, top),
        basement_wall=construction(Role.BASEMENT_WALL, wall),
        basement_ceiling=construction(Role.GROUND_FLOOR, ground),
        thermal_bridge_uplift_fraction=building.thermal_bridge_uplift_fraction,
        foundation=building.foundation,
        ground_temperature=building.ground_temperature)


def _physical_element_owners(building, resolved):
    """Link thermal panes, faces and internal mass to original physical elements."""
    walls = {(e.facade_id, e.storey): e for e in building.elements if e.role == Role.EXT_WALL}
    basement = {e.facade_id: e for e in building.elements if e.role == Role.BASEMENT_WALL}
    horizontal = {(e.part_id, round(e.elevation_m, 8)): e for e in building.elements
                  if e.elevation_m is not None and e.facade_id is None}
    windows = {(element.facade_id, element.storey): element for element in building.elements
               if element.role == Role.WINDOW}
    surfaces = {}
    for face in resolved.graph.surfaces:
        role = face.construction.removesuffix("_reverse").removeprefix("unconditioned_")
        physical = None
        if face.kind == "Wall":
            physical = basement.get(face.facade_id) if role == "basement_wall" else \
                walls.get((face.facade_id, face.storey)) if role == "wall" else None
        elif len({round(vertex[2], 8) for vertex in face.vertices}) == 1:
            physical = horizontal.get((face.part_id, round(face.vertices[0][2], 8)))
        if physical is not None:
            surfaces[face.name] = physical
    mass = {item["name"]: horizontal[(item["part_id"], round(item["elevation_m"], 8))]
            for item in resolved.graph.internal_mass
            if (item["part_id"], round(item["elevation_m"], 8)) in horizontal}
    openings = {opening.name: windows[(opening.metadata["facade_id"], opening.metadata["storey"])]
                for opening in resolved.openings
                if (opening.metadata["facade_id"], opening.metadata["storey"]) in windows}
    return {"surfaces": surfaces, "internal_mass": mass, "openings": openings}


def _surface_constructions_for_building(building, geometry, facade, envelope, *, resolved=None):
    """Resolve physical surface overrides identically for adaptation and preflight."""
    from .pipeline import resolve_geometry

    if resolved is None:
        resolved = resolve_geometry(SimpleNamespace(geometry=geometry, facade=facade), panelize=True)
    owners = _physical_element_owners(building, resolved)["surfaces"]
    surface_constructions = {}
    for face in resolved.graph.surfaces:
        physical = owners.get(face.name)
        role = face.construction.removesuffix("_reverse").removeprefix("unconditioned_")
        if physical is not None:
            assembly = thermal_construction(physical.construction)
            if getattr(envelope, role, None) != assembly:
                surface_constructions[face.name] = assembly
    return surface_constructions


def to_spec(building, weather):
    """Produce the legacy validated engine specification with exact target assignments."""
    building.readiness().require()
    if isinstance(weather, Weather):
        climate = weather.climate
    elif isinstance(weather, ClimateSpec):
        climate = weather
    else:
        climate = Weather.from_epw(weather).climate
    envelope = _envelope_for_building(building)
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
        renewables=building.hvac.renewables, provenance=building.provenance)
    surface_constructions = _surface_constructions_for_building(
        building, spec.geometry, spec.facade, envelope)
    from .pipeline import resolve_geometry

    resolved = resolve_geometry(spec, panelize=True)
    owners = _physical_element_owners(building, resolved)["internal_mass"]
    mass_constructions = {}
    for mass in resolved.graph.internal_mass:
        physical = owners.get(mass["name"])
        if physical is not None:
            assembly = thermal_construction(physical.construction)
            if assembly != intermediate:
                mass_constructions[mass["name"]] = assembly
    return spec.updated(surface_constructions=surface_constructions,
                        internal_mass_constructions=mass_constructions)


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
