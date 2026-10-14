"""Physical areas from original footprints, independent of thermal discretisation.

The first authoring adapter supports detached, flat, compact parts. Existing
pitched/attached/apartment thermal APIs remain available, but their physical
inventories require an explicit future geometry adapter and are reported unready.
"""

from epsm_data.domain.enums import BuildingElement as Role


def geometry_limitations(geometry):
    issues = []
    if any((part.roof or geometry.roof).shape != "flat"
           or (part.roof or geometry.roof).topology != "compact" for part in geometry.parts):
        issues.append("authoring inventory currently requires flat compact roofs")
    polygons = [part.footprint.polygon for part in geometry.parts]
    if any(a.boundary.intersection(b.boundary).length > 1e-8
           for i, a in enumerate(polygons) for b in polygons[i + 1:]):
        issues.append("attached parts require a shared physical-wall inventory adapter")
    if geometry.party_walls:
        issues.append("party walls require explicit physical ownership before inventory")
    if geometry.footprint_cleanup.enabled and any(
        original.footprint.polygon.symmetric_difference(prepared.polygon).area > 1e-10
        for original, prepared in zip(geometry.parts, geometry.footprints)
    ):
        issues.append("authoring inventory requires reviewed footprint cleanup before assignment")
    if geometry.zoning.mode == "apartments":
        issues.append("apartment partitions require physical element assignments")
    return issues


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
