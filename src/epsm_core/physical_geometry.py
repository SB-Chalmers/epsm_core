# SPDX-License-Identifier: MIT
# Date modified: 2026-10-19
# Changelog: retain cold-attic shells and basement interfaces in physical inventory.
"""Physical installed areas, independent of virtual thermal-zone subdivisions.

Flat compact models preserve their original element identities. Cold attics have
separate horizontal ceilings, actual roof-shell areas and opaque gable walls.
The existing validated geometry resolver owns exposure and roof tessellation;
this adapter aggregates its faces without inferring constructions or ventilation.
Shared physical walls have one material owner. No files or services are read.
"""

from math import isclose
from types import SimpleNamespace

from epsm_data.domain.enums import BuildingElement as Role


def geometry_limitations(geometry):
    issues = []
    polygons = [part.footprint.polygon for part in geometry.parts]
    for index, (part, polygon) in enumerate(zip(geometry.parts, polygons)):
        roof = part.roof or geometry.roof
        if roof.shape != "flat" and any(
            index != other and polygon.boundary.intersection(candidate.boundary).length > 1e-7
            for other, candidate in enumerate(polygons)
        ):
            issues.append("pitched roofs on touching parts require explicit roof ownership")
        if roof.shape != "flat" and any(
            wall.facade_id.startswith(part.identifier + ".") and wall.top_m is not None
            and wall.top_m > part.storey_elevations_m[-1]
            for wall in geometry.party_walls
        ):
            issues.append("pitched attic party-wall contact above the eave requires explicit roof ownership")
    if any(a.boundary.intersection(b.boundary).length > 1e-8
           for i, a in enumerate(polygons) for b in polygons[i + 1:]) and any(
               not part.conditioned for part in geometry.parts):
        issues.append("attached unconditioned parts require explicit thermal-boundary ownership")
    if any(not wall.contact_confirmed for wall in geometry.party_walls):
        issues.append("party walls require reviewed geometric contact")
    if geometry.footprint_cleanup.enabled and any(
        original.footprint.polygon.symmetric_difference(prepared.polygon).area > 1e-10
        for original, prepared in zip(geometry.parts, geometry.footprints)
    ):
        issues.append("authoring inventory requires reviewed footprint cleanup before assignment")
    if geometry.zoning.mode == "apartments":
        issues.append("apartment partitions require physical element assignments")
    return issues


def physical_geometry_mismatches(geometry, facade, elements):
    """Find manual physical metadata that the current engine bridge cannot use.

    Geometry and facade choices determine the emitted areas. Construction edits
    are independent, but changes to physical IDs, areas and locations must agree
    with those generated from geometry before a thermal calculation can proceed.
    """
    # Basement-bottom roles retain the released geometry-first assignment rule.
    # Regenerating with no role assignments would incorrectly relabel an explicit
    # BASEMENT_FLOOR as GROUND_FLOOR and reject its otherwise valid geometry.
    assigned = SimpleNamespace(elements={element.role: element.construction for element in elements
                                        if element.construction is not None})
    try:
        expected = {element.identifier: element
                    for element in physical_elements(geometry, facade, assigned)}
    except ValueError as exc:
        # Historical drafts may contain roof geometry that the new physical
        # resolver rejects. Keep the frozen draft inspectable and report the
        # same strict rejection; do not invent a replacement shell or area.
        return (f"physical geometry: {exc}",)
    actual = {element.identifier: element for element in elements}
    issues = []
    if actual.keys() != expected.keys():
        issues.append("physical geometry: element identities differ from generated geometry")
    for identifier in actual.keys() & expected.keys():
        left, right = actual[identifier], expected[identifier]
        changed = [name for name in ("role", "part_id", "facade_id", "storey", "elevation_m", "boundary")
                   if getattr(left, name) != getattr(right, name)]
        # Roundtripped finite areas may differ at machine precision; this tolerance
        # is far below any supported geometric area or physical intervention.
        if not isclose(left.area_m2, right.area_m2, rel_tol=1e-10, abs_tol=1e-8):
            changed.append("area_m2")
        if changed:
            issues.append(f"physical geometry:{identifier}: differs in {', '.join(changed)}")
    return tuple(sorted(issues))


def construction_source_role(geometry, element, constructions):
    """Select a declared assembly for one physical boundary without conflating shells.

    ``TOP_FLOOR`` remains the released physical top-boundary role. A compact
    roof may use an authored ``ROOF`` when no explicit top assembly is supplied.
    A cold-attic ceiling must have its own ``TOP_FLOOR``; its ``ROOF`` is the
    separate weather shell and is never a ceiling fallback.
    """
    role = element.role
    if role == Role.TOP_FLOOR and role not in constructions and Role.ROOF in constructions:
        part = next(part for part in geometry.parts if part.identifier == element.part_id)
        if (part.roof or geometry.roof).topology == "compact":
            return Role.ROOF
    return role


def physical_construction(geometry, element, constructions):
    """Resolve the source role, retaining layers and shared source definitions."""
    source_role = construction_source_role(geometry, element, constructions)
    construction = constructions.get(source_role)
    if construction is not None and source_role != element.role:
        construction = construction.with_changes(
            application=element.role,
            components=tuple(component.with_changes(application=element.role)
                             for component in construction.components),
        )
    return construction


def physical_elements(geometry, facade, construction_set):
    from .building import BuildingElement
    from .facades import window_rectangles

    constructions = construction_set.elements if construction_set else {}
    rows = []

    def add(identifier, role, area, **metadata):
        element = BuildingElement(identifier, role, area, **metadata)
        rows.append(element.with_changes(
            construction=physical_construction(geometry, element, constructions)))

    for part in geometry.parts:
        area = part.footprint.area_m2
        if geometry.basement_depth_m:
            bottom_role = Role.BASEMENT_FLOOR if Role.BASEMENT_FLOOR in constructions else Role.GROUND_FLOOR
            add(f"{part.identifier}.basement_floor", bottom_role, area,
                part_id=part.identifier, elevation_m=-geometry.basement_depth_m)
            add(f"{part.identifier}.ground_floor", Role.GROUND_FLOOR, area,
                part_id=part.identifier, elevation_m=0, boundary="Internal")
        else:
            # An explicit soil slab remains the soil boundary even when there is
            # no basement. GROUND_FLOOR may instead be a suspended cellar ceiling.
            bottom_role = Role.BASEMENT_FLOOR if Role.BASEMENT_FLOOR in constructions else Role.GROUND_FLOOR
            add(f"{part.identifier}.ground_floor", bottom_role, area,
                part_id=part.identifier, elevation_m=0)
        for elevation in part.storey_elevations_m[1:-1]:
            add(f"{part.identifier}.floor.{elevation:g}", Role.INTERMEDIATE_FLOOR,
                area, part_id=part.identifier, elevation_m=elevation)
        roof = part.roof or geometry.roof
        add(f"{part.identifier}.top", Role.TOP_FLOOR, area, part_id=part.identifier,
            elevation_m=part.storey_elevations_m[-1],
            boundary="Internal" if roof.topology == "cold_attic" else "Outdoors")
    polygons = [part.footprint.polygon for part in geometry.parts]
    shared = bool(geometry.party_walls) or any(
        a.boundary.intersection(b.boundary).length > 1e-8
        for i, a in enumerate(polygons) for b in polygons[i + 1:])
    cold_attic = any((part.roof or geometry.roof).topology == "cold_attic"
                     for part in geometry.parts)
    if (shared or cold_attic) and not geometry_limitations(geometry):
        from .specs import FacadeSpec, GlazingSpec

        # A temporary zero-opening view supplies no installed glazing and does
        # not assign facade assumptions to incomplete authoring state.
        opaque_view = FacadeSpec(default_wwr=0, glazing=GlazingSpec(
            u_value_w_m2k=1, solar_heat_gain_coefficient=0, visible_transmittance=0))
        _resolved_exterior_elements(geometry, facade or opaque_view, add)
        return tuple(rows)
    for face in geometry.facades():
        for storey in face.storeys:
            height = face.storey_elevations_m[storey + 1] - face.storey_elevations_m[storey]
            gross = face.length_m * height
            glazing_area = 0.0
            if facade is not None:
                rectangles, _ = window_rectangles(
                    face.length_m, height, facade.value_for("wwr", face.facade_id, storey),
                    facade.value_for("layout", face.facade_id, storey))
                glazing_area = sum((right - left) * (top - bottom)
                                   for left, bottom, right, top in rectangles)
            metadata = dict(part_id=face.part_id, facade_id=face.facade_id, storey=storey)
            prefix = f"{face.facade_id}.storey.{storey}"
            add(prefix + ".wall", Role.EXT_WALL, gross - glazing_area, **metadata)
            if glazing_area:
                add(prefix + ".window", Role.WINDOW, glazing_area, **metadata)
        if geometry.basement_depth_m:
            add(f"{face.facade_id}.basement_wall", Role.BASEMENT_WALL,
                face.length_m * geometry.basement_depth_m,
                part_id=face.part_id, facade_id=face.facade_id, elevation_m=-geometry.basement_depth_m)
    return tuple(rows)


def _resolved_exterior_elements(geometry, facade, add):
    """Use the thermal exposure/layout resolver so windows have identical areas.

    The physical inventory aggregates computational cuts, keeping one installed
    owner for shared same-Building walls. Each contact retains the ordinary wall
    construction: an adiabatic boundary does not remove its material or capacity.
    """
    from collections import defaultdict

    from .pipeline import resolve_geometry

    # Computational zone cuts must not invent walls or change installed areas.
    from .specs import ZoningSpec

    physical_geometry = geometry.updated(zoning=ZoningSpec(mode="whole_building"))
    resolved = resolve_geometry(SimpleNamespace(geometry=physical_geometry, facade=facade))
    panes = defaultdict(float)
    for opening in resolved.openings:
        panes[opening.parent] += opening.area
    groups = defaultdict(float)
    windows = defaultdict(float)
    faces = {face.name: face for face in resolved.graph.surfaces}
    roofs = defaultdict(float)
    for face in resolved.graph.surfaces:
        if face.kind == "Roof" and face.cell_kind == "attic":
            roofs[face.part_id] += face.area
        if face.kind != "Wall":
            continue
        if face.boundary == "Surface":
            other = faces[face.adjacent]
            if other.part_id == face.part_id:
                continue
            if (face.facade_id, face.storey, face.name) > (other.facade_id, other.storey, other.name):
                continue
            boundary = "Internal"
        else:
            boundary = face.boundary
        key = (face.part_id, face.facade_id, face.storey, face.cell_kind, boundary)
        groups[key] += face.area - panes[face.name]
        windows[key] += panes[face.name]
    parts = {part.identifier: part for part in geometry.parts}
    for mass in resolved.graph.internal_mass:
        if mass.get("physical_boundary") == "Internal":
            kind = ("basement" if mass["storey"] < 0 else
                    "attic" if mass["storey"] >= parts[mass["part_id"]].floors else "main")
            groups[(mass["part_id"], mass["facade_id"], mass["storey"], kind, "Internal")] += mass["area_m2"]
    suffix = {"Outdoors": "wall", "Ground": "wall", "Adiabatic": "adiabatic_wall", "Internal": "internal_wall"}
    for (part, fid, storey, kind, boundary), area in sorted(groups.items()):
        metadata = dict(part_id=part, facade_id=fid, boundary=boundary)
        role = Role.BASEMENT_WALL if kind == "basement" else Role.EXT_WALL
        if kind == "main":
            metadata["storey"] = storey
            identifier = f"{fid}.storey.{storey}.{suffix[boundary]}"
        elif kind == "basement":
            metadata["elevation_m"] = -geometry.basement_depth_m
            identifier = f"{fid}.basement_{suffix[boundary]}"
        else:
            metadata.update(storey=storey, elevation_m=parts[part].storey_elevations_m[-1])
            identifier = f"{fid}.attic_{suffix[boundary]}"
        if area > 1e-9:
            add(identifier, role, area, **metadata)
        glazing = windows[(part, fid, storey, kind, boundary)]
        if glazing > 1e-9:
            add(f"{fid}.storey.{storey}.window", Role.WINDOW, glazing, **metadata)
    for part, area in sorted(roofs.items()):
        add(f"{part}.roof", Role.ROOF, area, part_id=part, boundary="Outdoors")
