"""Physical areas from original footprints, independent of thermal discretisation.

The authoring adapter supports flat compact conditioned parts and explicit
adiabatic neighbouring contacts. Same-building attached walls have one physical
owner. Pitched roofs, apartment assignments and ambiguous unconditioned shared
boundaries retain their explicit readiness limitations.
"""

from math import isclose

from epsm_data.domain.enums import BuildingElement as Role


def geometry_limitations(geometry):
    issues = []
    if any((part.roof or geometry.roof).shape != "flat"
           or (part.roof or geometry.roof).topology != "compact" for part in geometry.parts):
        issues.append("authoring inventory currently requires flat compact roofs")
    polygons = [part.footprint.polygon for part in geometry.parts]
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
    if geometry.basement_depth_m and geometry.party_walls:
        issues.append("physical party-wall inventory currently excludes basements")
    if geometry.zoning.mode == "apartments":
        issues.append("apartment partitions require physical element assignments")
    return issues


def physical_geometry_mismatches(geometry, facade, elements):
    """Find manual physical metadata that the current engine bridge cannot use.

    Geometry and facade choices determine the emitted areas. Construction edits
    are independent, but changes to physical IDs, areas and locations must agree
    with those generated from geometry before a thermal calculation can proceed.
    """
    expected = {element.identifier: element
                for element in physical_elements(geometry, facade, None)}
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


def physical_elements(geometry, facade, construction_set):
    from .building import BuildingElement
    from .facades import window_rectangles

    constructions = construction_set.elements if construction_set else {}
    rows = []

    def add(identifier, role, area, **metadata):
        # No guessed assignment between unlike roles. Missing is visible in readiness.
        rows.append(BuildingElement(identifier, role, area, constructions.get(role), **metadata))

    for part in geometry.parts:
        area = part.footprint.area_m2
        if geometry.basement_depth_m:
            bottom_role = Role.BASEMENT_FLOOR if Role.BASEMENT_FLOOR in constructions else Role.GROUND_FLOOR
            add(f"{part.identifier}.basement_floor", bottom_role, area,
                part_id=part.identifier, elevation_m=-geometry.basement_depth_m)
            add(f"{part.identifier}.ground_floor", Role.GROUND_FLOOR, area,
                part_id=part.identifier, elevation_m=0)
        else:
            add(f"{part.identifier}.ground_floor", Role.GROUND_FLOOR, area,
                part_id=part.identifier, elevation_m=0)
        for elevation in part.storey_elevations_m[1:-1]:
            add(f"{part.identifier}.floor.{elevation:g}", Role.INTERMEDIATE_FLOOR,
                area, part_id=part.identifier, elevation_m=elevation)
        add(f"{part.identifier}.top", Role.TOP_FLOOR, area, part_id=part.identifier,
            elevation_m=part.storey_elevations_m[-1])
    polygons = [part.footprint.polygon for part in geometry.parts]
    shared = bool(geometry.party_walls) or any(
        a.boundary.intersection(b.boundary).length > 1e-8
        for i, a in enumerate(polygons) for b in polygons[i + 1:])
    if shared and not geometry_limitations(geometry):
        from .specs import FacadeSpec, GlazingSpec

        # A temporary zero-opening view supplies no installed glazing and does
        # not assign facade assumptions to incomplete authoring state.
        opaque_view = FacadeSpec(default_wwr=0, glazing=GlazingSpec(
            u_value_w_m2k=1, solar_heat_gain_coefficient=0, visible_transmittance=0))
        _shared_wall_elements(geometry, facade or opaque_view, add)
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


def _shared_wall_elements(geometry, facade, add):
    """Use the thermal exposure/layout resolver so windows have identical areas.

    The physical inventory aggregates computational cuts, keeping one installed
    owner for shared same-Building walls. Each contact retains the ordinary wall
    construction: an adiabatic boundary does not remove its material or capacity.
    """
    from collections import defaultdict
    from types import SimpleNamespace

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
    for face in resolved.graph.surfaces:
        if face.kind != "Wall" or face.cell_kind != "main":
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
        key = (face.part_id, face.facade_id, face.storey, boundary)
        groups[key] += face.area - panes[face.name]
        windows[key] += panes[face.name]
    for mass in resolved.graph.internal_mass:
        if mass.get("physical_boundary") == "Internal":
            groups[(mass["part_id"], mass["facade_id"], mass["storey"], "Internal")] += mass["area_m2"]
    suffix = {"Outdoors": ".wall", "Adiabatic": ".adiabatic_wall", "Internal": ".internal_wall"}
    for (part, fid, storey, boundary), area in sorted(groups.items()):
        metadata = dict(part_id=part, facade_id=fid, storey=storey, boundary=boundary)
        prefix = f"{fid}.storey.{storey}"
        if area > 1e-9:
            add(prefix + suffix[boundary], Role.EXT_WALL, area, **metadata)
        glazing = windows[(part, fid, storey, boundary)]
        if glazing > 1e-9:
            add(prefix + ".window", Role.WINDOW, glazing, **metadata)
    if geometry.basement_depth_m:
        for face in geometry.facades():
            add(f"{face.facade_id}.basement_wall", Role.BASEMENT_WALL,
                face.length_m * geometry.basement_depth_m,
                part_id=face.part_id, facade_id=face.facade_id, elevation_m=-geometry.basement_depth_m)
