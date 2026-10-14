"""Compile auditable Kiva foundations without changing envelope constructions.

The exterior perimeter is taken from the union of resolved building footprints;
shared zone edges are not exterior. Courtyard/disconnected floors within one zone
are rejected explicitly rather than repaired or assigned a different method.
"""

from __future__ import annotations

from collections import defaultdict
from math import hypot

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from .failures import GEOMETRY_INVARIANT_FAILURE, CompilationError
from .vertex_order import clean_generated_ring, serialize_vertices


def apply_kiva(model, envelope, footprints):
    """Return the foundation report after converting emitted ground surfaces."""
    cfg = envelope.foundation
    surfaces = model["BuildingSurface:Detailed"]
    ground = {n: s for n, s in surfaces.items() if s["outside_boundary_condition"] == "Ground"}
    by_zone = defaultdict(list)
    for name, obj in ground.items():
        if obj["surface_type"] == "Floor":
            by_zone[obj["zone_name"]].append((name, obj))
    if not by_zone:
        raise CompilationError(GEOMETRY_INVARIANT_FAILURE, "Kiva requires a ground-contact floor")

    checked = check_kiva_floor_geometry(by_zone, envelope)

    def polygon(obj):
        return Polygon(
            [(v["vertex_x_coordinate"], v["vertex_y_coordinate"]) for v in obj["vertices"]]
        )

    # Use the resolved footprint, not the tessellated-floor union: floating-point
    # slivers between rotated partitions must never become exposed perimeter.
    exterior = unary_union(footprints).boundary
    assignments, removed = [], []
    for zone, floors in sorted(by_zone.items()):
        merged, heights = checked[zone]
        z = next(iter(heights))
        name, floor = floors[0]
        if len(floors) > 1:
            # Preserve the downward normal, area and zone volume.
            vertices = serialize_vertices(
                clean_generated_ring(
                    (x, y, z) for x, y in list(orient(merged, sign=-1).exterior.coords)[:-1]
                )
            )
            floor["vertices"] = [
                dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=h)
                for x, y, h in vertices
            ]
            floor["number_of_vertices"] = len(vertices)
            for other, _ in floors[1:]:
                del surfaces[other]
                removed.append(other)
        # A 10 nm matching tolerance handles rotated collinear edges. It changes
        # only boundary matching; no surface vertex or footprint is moved.
        exterior_length = exterior.intersection(merged.buffer(1e-8)).length
        if exterior_length < 1e-6:
            exterior_length = 0.0
        # Matching tolerance may make the measured exterior slightly longer
        # than the emitted floor perimeter. Kiva rejects an exposed value above
        # that exact serialized floor boundary.
        exposed = min(exterior_length * cfg.exposed_perimeter_fraction, polygon(floor).length)
        ground_wall_length = 0.0
        for wall in ground.values():
            if wall["zone_name"] != zone or wall["surface_type"] != "Wall":
                continue
            xy = [
                (v["vertex_x_coordinate"], v["vertex_y_coordinate"])
                for v in wall["vertices"]
            ]
            ground_wall_length += max(
                hypot(b[0] - a[0], b[1] - a[1])
                for a, b in zip(xy, xy[1:] + xy[:1])
            )
        # Rotated, segmented basement walls can differ from the exterior by a
        # fraction of a millimetre. When they agree physically, use the emitted
        # wall lengths so Kiva's instance weights sum to one without warnings.
        if ground_wall_length and abs(exposed - ground_wall_length) <= 0.001:
            exposed = min(ground_wall_length, polygon(floor).length)
        foundation = zone + "_kiva"
        fields = dict(
            wall_height_above_grade=cfg.wall_height_above_grade_m,
            wall_depth_below_slab=cfg.wall_depth_below_slab_m,
        )
        if cfg.footing_material is not None:
            fields["footing_depth"] = cfg.footing_depth_m
            material = cfg.footing_material
            material_name = "kiva_footing"
            model.setdefault("Material", {})[material_name] = dict(
                roughness=material.roughness,
                thickness=cfg.footing_width_m,
                conductivity=material.conductivity_w_mk,
                density=material.density_kg_m3,
                specific_heat=material.specific_heat_j_kgk,
                thermal_absorptance=material.thermal_absorptance,
                solar_absorptance=material.solar_absorptance,
                visible_absorptance=material.visible_absorptance,
            )
            fields["footing_material_name"] = material_name
        if cfg.footing_wall is not None:
            names = []
            for i, layer in enumerate(cfg.footing_wall.layers):
                n = f"kiva_footing_wall_{i}"
                m = layer.material
                model.setdefault("Material", {})[n] = dict(
                    roughness=m.roughness,
                    thickness=layer.thickness_m,
                    conductivity=m.conductivity_w_mk,
                    density=m.density_kg_m3,
                    specific_heat=m.specific_heat_j_kgk,
                    thermal_absorptance=m.thermal_absorptance,
                    solar_absorptance=m.solar_absorptance,
                    visible_absorptance=m.visible_absorptance,
                )
                names.append(n)
            model.setdefault("Construction", {})["kiva_footing_wall"] = {
                ("outside_layer" if i == 0 else f"layer_{i + 1}"): n for i, n in enumerate(names)
            }
            fields["footing_wall_construction_name"] = "kiva_footing_wall"
        model.setdefault("Foundation:Kiva", {})[foundation] = fields
        model.setdefault("SurfaceProperty:ExposedFoundationPerimeter", {})[name + "_perimeter"] = (
            dict(
                surface_name=name,
                exposed_perimeter_calculation_method="TotalExposedPerimeter",
                total_exposed_perimeter=exposed,
            )
        )
        for obj in ground.values():
            if obj["zone_name"] == zone:
                obj["outside_boundary_condition"] = "Foundation"
                obj["outside_boundary_condition_object"] = foundation
        assignments.append(
            dict(
                foundation=foundation,
                zone=zone,
                floor=name,
                floor_area_m2=merged.area,
                geometric_exterior_perimeter_m=exterior_length,
                exposed_perimeter_m=exposed,
            )
        )
    if any(obj["outside_boundary_condition"] == "Ground" for obj in surfaces.values()):
        raise CompilationError(GEOMETRY_INVARIANT_FAILURE, "Kiva has unassigned ground surfaces")
    model.pop("Site:GroundTemperature:BuildingSurface", None)
    settings = dict(
        soil_conductivity=cfg.soil_conductivity_w_mk,
        soil_density=cfg.soil_density_kg_m3,
        soil_specific_heat=cfg.soil_specific_heat_j_kgk,
        ground_solar_absorptivity=0.9,
        ground_thermal_absorptivity=0.9,
        ground_surface_roughness=0.03,
        far_field_width=cfg.far_field_width_m,
        deep_ground_boundary_condition=cfg.deep_ground_boundary,
        deep_ground_depth=cfg.deep_ground_depth_m,
        minimum_cell_dimension=0.02,
        maximum_cell_growth_coefficient=1.5,
        simulation_timestep="Hourly",
    )
    model["Foundation:Kiva:Settings"] = {"foundation_settings": settings}
    return dict(
        method="kiva",
        source=cfg.source,
        inputs=cfg.model_dump(mode="json"),
        settings=settings,
        assignments=assignments,
        merged_ground_faces=sorted(removed),
        perimeter_matching_tolerance_m=1e-8,
        generated_ring_cleanup_tolerance_m=1e-8,
        assumptions=[
            "Soil is unmeasured unless source states otherwise",
            "Exterior perimeter is fully exposed unless scaled explicitly; neighbouring foundations are not inferred",
            "No footing block is added unless a material is supplied; unspecified foundation wall uses EnergyPlus 24.2 defaults",
        ],
        legacy_18c_boundary_inactive=True,
    )


def check_kiva_floor_geometry(by_zone, envelope):
    """Validate Kiva floor unions shared by preflight and compiler mutation.

    ``by_zone`` maps zone names to ``(name, surface)`` pairs. Surfaces use the same
    dictionary shape as emitted ``BuildingSurface:Detailed`` objects.
    """
    if not by_zone:
        raise CompilationError(GEOMETRY_INVARIANT_FAILURE, "Kiva requires a ground-contact floor")

    def polygon(obj):
        return Polygon(
            [(v["vertex_x_coordinate"], v["vertex_y_coordinate"]) for v in obj["vertices"]]
        )

    checked = {}
    for zone, floors in sorted(by_zone.items()):
        constructions = {obj["construction_name"] for _, obj in floors}
        heights = {round(v["vertex_z_coordinate"], 7) for _, obj in floors for v in obj["vertices"]}
        if len(constructions) != 1 or len(heights) != 1:
            raise CompilationError(
                GEOMETRY_INVARIANT_FAILURE,
                f"Kiva floor in {zone} must be coplanar with one construction",
            )
        pieces = [polygon(obj) for _, obj in floors]
        merged = unary_union(pieces).simplify(1e-8)
        if merged.geom_type != "Polygon" or merged.interiors:
            raise CompilationError(
                GEOMETRY_INVARIANT_FAILURE,
                f"Kiva floor in {zone} cannot contain holes or disconnected components; use explicit prescribed temperatures",
            )
        if abs(merged.area - sum(piece.area for piece in pieces)) > 1e-6:
            raise CompilationError(GEOMETRY_INVARIANT_FAILURE, f"Overlapping Kiva floors in {zone}")
        z = next(iter(heights))
        if envelope.foundation.deep_ground_depth_m <= max(0, -z) + sum(
            layer.thickness_m for layer in envelope.ground.layers
        ):
            raise CompilationError(
                GEOMETRY_INVARIANT_FAILURE, "Kiva deep boundary must be below the slab bottom"
            )
        checked[zone] = (merged, heights)
    return checked
