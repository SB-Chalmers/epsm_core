"""Geometry invariants for virtual perimeter/core thermal partitions."""

from collections import defaultdict
from types import SimpleNamespace

import pytest
from shapely.affinity import rotate
from shapely.geometry import Polygon

from epsm_core import BuildingPart, Footprint, GeometrySpec, PartyWall, RoofSpec, ZoningSpec
from epsm_core.geometry import facade_edges, local_polygons
from epsm_core.surface_checks import validate_surfaces
from epsm_core.topology import build_surface_graph
from epsm_core.zoning import perimeter_core_partitions


def geometry(footprint=None, **changes):
    return GeometrySpec.from_footprint(
        footprint or Footprint.rectangle(30, 20),
        storey_elevations_m=(0, 3, 6, 9),
        zoning=ZoningSpec(mode="perimeter_core"),
    ).updated(**changes)


def checked_graph(geometry):
    """Use the complete closure/reciprocity validator without engine or constructions."""
    graph = build_surface_graph(SimpleNamespace(geometry=geometry), local_polygons(geometry)[0])
    model = {
        "BuildingSurface:Detailed": {
            face.name: dict(
                zone_name=face.zone,
                construction_name=face.construction,
                outside_boundary_condition=face.boundary,
                outside_boundary_condition_object=face.adjacent,
                vertices=[
                    dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z)
                    for x, y, z in face.vertices
                ],
            )
            for face in graph.surfaces
        }
    }
    validate_surfaces(model, graph.zones)
    return graph


def envelope_areas(graph):
    area = defaultdict(float)
    for face in graph.surfaces:
        if face.boundary != "Surface":
            area[(face.part_id, face.facade_id, face.kind, face.boundary)] += face.area
    return dict(area)


def test_rectangle_has_four_perimeters_and_core_at_each_real_storey():
    g = geometry()
    graph = checked_graph(g)
    assert len(graph.zones) == 15
    assert sum(z.get("zone_kind") == "core" for z in graph.zones.values()) == 3
    assert {tuple(z["elevations_m"]) for z in graph.zones.values()} == {(0, 3), (3, 6), (6, 9)}
    assert sum(z["floor_area_m2"] for z in graph.zones.values()) == pytest.approx(1800)
    assert sum(z["volume_m3"] for z in graph.zones.values()) == pytest.approx(5400)
    assert {face.part_id for face in graph.surfaces} == {"main"}
    assert {
        z["perimeter_facade_id"] for z in graph.zones.values() if "perimeter_facade_id" in z
    } == {"main.r0.e0", "main.r0.e1", "main.r0.e2", "main.r0.e3"}
    assert not graph.internal_mass
    assert {
        face.construction
        for face in graph.surfaces
        if face.kind == "Wall" and face.boundary == "Surface"
    } == {"partition"}
    baseline = checked_graph(g.updated(zoning=ZoningSpec()))
    assert envelope_areas(graph) == pytest.approx(envelope_areas(baseline))
    # Each real slab is counted once even when its cells overlap differently.
    slabs = [
        face
        for face in graph.surfaces
        if face.kind == "Floor" and face.construction.startswith("intermediate_floor")
    ]
    assert sum(face.area for face in slabs) == pytest.approx(1200)


@pytest.mark.parametrize(
    "footprint,cores_per_storey",
    [
        (Footprint.rectangle(30, 7), 0),
        (Footprint.l_shape(30, 20, 15, 10), 1),
        (Footprint.u_shape(40, 30, 10, 20), 1),
        (
            Footprint(
                exterior=((0, 0), (40, 0), (40, 40), (0, 40)),
                holes=(((10, 10), (10, 30), (30, 30), (30, 10)),),
            ),
            1,
        ),
        (
            Footprint(
                exterior=(
                    (0, 0),
                    (20, 0),
                    (20, 8),
                    (30, 8),
                    (30, 0),
                    (50, 0),
                    (50, 20),
                    (30, 20),
                    (30, 12),
                    (20, 12),
                    (20, 20),
                    (0, 20),
                )
            ),
            2,
        ),
    ],
)
@pytest.mark.parametrize("orientation", [0, 17, 133])
def test_complete_closed_partitions_for_irregular_floorplates(
    footprint, cores_per_storey, orientation
):
    graph = checked_graph(geometry(footprint, orientation_deg=orientation))
    assert sum(z.get("zone_kind") == "core" for z in graph.zones.values()) == cores_per_storey * 3
    assert sum(z["floor_area_m2"] for z in graph.zones.values()) == pytest.approx(
        footprint.area_m2 * 3
    )
    if footprint.holes:
        assert any(
            z.get("perimeter_facade_id", "").startswith("main.r1.") for z in graph.zones.values()
        )


@pytest.mark.parametrize("angle", [17, 133])
@pytest.mark.parametrize(
    "footprint", [Footprint.rectangle(30, 7), Footprint.u_shape(40, 30, 10, 20)]
)
def test_geographic_footprint_rotation_has_no_cracks(footprint, angle):
    polygon = rotate(footprint.polygon, angle, origin=(0, 0))
    rotated = Footprint(exterior=tuple(polygon.exterior.coords)[:-1])
    graph = checked_graph(geometry(rotated))
    assert sum(z["floor_area_m2"] for z in graph.zones.values()) == pytest.approx(
        footprint.area_m2 * 3
    )
    assert len(graph.zones) == len(checked_graph(geometry(footprint)).zones)


def test_ring_reordering_preserves_facade_ids_and_partitions():
    g = geometry()
    part = g.parts[0]
    ring = part.footprint.exterior
    other = g.updated(
        parts=(part.updated(footprint=Footprint(exterior=tuple(reversed(ring[2:] + ring[:2])))),)
    )
    first, second = checked_graph(g), checked_graph(other)
    assert first.zones == second.zones
    assert [(s.name, s.vertices) for s in first.surfaces] == [
        (s.name, s.vertices) for s in second.surfaces
    ]


def test_party_facade_does_not_create_a_perimeter_region():
    party = PartyWall(
        facade_id="main.r0.e0",
        neighbor_id="neighbor",
        neighbor_conditioning="heated",
        contact_confirmed=True,
        assumption_source="geometry fixture",
    )
    g = geometry(party_walls=(party,))
    graph = checked_graph(g)
    assert len(graph.zones) == 12
    assert all(z.get("perimeter_facade_id") != party.facade_id for z in graph.zones.values())
    assert sum(f.area for f in graph.surfaces if f.boundary == "Adiabatic") == pytest.approx(270)
    assert envelope_areas(graph) == pytest.approx(
        envelope_areas(checked_graph(g.updated(zoning=ZoningSpec())))
    )


def unequal_wings():
    return (
        BuildingPart(
            identifier="main", footprint=Footprint.rectangle(20, 20), storey_elevations_m=(0, 3, 6)
        ),
        BuildingPart(
            identifier="wing",
            footprint=Footprint(exterior=((20, 0), (35, 0), (35, 20), (20, 20))),
            storey_elevations_m=(0, 2.5, 5, 7.5, 10),
        ),
    )


@pytest.mark.parametrize("orientation", [0, 17])
@pytest.mark.parametrize("attic", [False, True])
def test_unequal_wings_preserve_slabs_and_exposure_bands(orientation, attic):
    g = GeometrySpec(
        parts=unequal_wings(),
        zoning=ZoningSpec(mode="perimeter_core"),
        orientation_deg=orientation,
        basement_depth_m=2.5,
        roof=RoofSpec(topology="cold_attic" if attic else "compact"),
    )
    graph = checked_graph(g)
    baseline = checked_graph(g.updated(zoning=ZoningSpec()))
    assert envelope_areas(graph) == pytest.approx(envelope_areas(baseline))
    assert sum(
        z["floor_area_m2"] for z in graph.zones.values() if z["conditioned"]
    ) == pytest.approx(2000)
    assert all(z.get("perimeter_facade_id") != "main.r0.e1" for z in graph.zones.values())
    west = [z for z in graph.zones.values() if z.get("perimeter_facade_id") == "wing.r0.e3"]
    # A compact roof leaves 5–7.5 m partly exposed; a 1.5 m attic covers it fully.
    expected = {(7.5, 10)} if attic else {(5, 7.5), (7.5, 10)}
    assert {tuple(z["elevations_m"]) for z in west} == expected
    assert sum(not z["conditioned"] for z in graph.zones.values()) == (4 if attic else 2)
    assert {tuple(z["part_ids"]) for z in graph.zones.values()} == {("main",), ("wing",)}


def test_identical_storeys_reuse_planar_partitions(monkeypatch):
    import epsm_core.topology as topology

    calls = []
    original = topology.perimeter_core_partitions

    def counted(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(topology, "perimeter_core_partitions", counted)
    checked_graph(geometry())
    assert len(calls) == 1


def test_fallback_is_explicit_and_replaces_the_whole_building(monkeypatch):
    import epsm_core.topology as topology

    def failed(*args):
        raise ValueError("Partition fixture failed")

    monkeypatch.setattr(topology, "perimeter_core_partitions", failed)
    g = GeometrySpec(parts=unequal_wings(), zoning=ZoningSpec(mode="perimeter_core"))
    with pytest.raises(ValueError, match="Partition fixture failed"):
        checked_graph(g)
    graph = checked_graph(g.updated(zoning=g.zoning.updated(on_failure="per_storey", depth_m=6)))
    assert len(graph.zones) == 6
    assert graph.zoning_report == dict(
        requested_mode="perimeter_core",
        effective_mode="per_storey",
        on_failure="per_storey",
        substituted=True,
        reason="Partition fixture failed",
        affected_parts=["main", "wing"],
    )


def test_partition_function_checks_its_inputs():
    polygon = Polygon([(0, 0), (30, 0), (30, 20), (0, 20)])
    for depth in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="finite and positive"):
            perimeter_core_partitions(polygon, list(facade_edges(polygon, "main")), depth)


def test_perimeter_workload_limits_fail_explicitly(monkeypatch):
    import epsm_core.topology as topology
    import epsm_core.zoning as zoning

    monkeypatch.setattr(zoning, "MAX_EXPOSED_FACADES", 3)
    with pytest.raises(ValueError, match="exposed facade segments"):
        checked_graph(geometry())
    monkeypatch.setattr(zoning, "MAX_EXPOSED_FACADES", 512)
    monkeypatch.setattr(zoning, "MAX_OVERLAP_PAIRS", 1)
    with pytest.raises(ValueError, match="overlapping strip pairs"):
        checked_graph(geometry())
    monkeypatch.setattr(zoning, "MAX_OVERLAP_PAIRS", 20_000)
    monkeypatch.setattr(topology, "MAX_THERMAL_CELLS", 10)
    with pytest.raises(ValueError, match="thermal cells"):
        checked_graph(geometry())
    graph = checked_graph(
        geometry(zoning=ZoningSpec(mode="perimeter_core", on_failure="per_storey"))
    )
    assert graph.zoning_report["substituted"]
    assert len(graph.zones) == 3


def test_extreme_reflex_mitre_fails_instead_of_creating_distant_cells():
    polygon = Polygon([(0, 0), (30, 0), (30, 30), (16, 30), (15, 1), (14, 30), (0, 30)])
    with pytest.raises(ValueError, match="mitre exceeds five times"):
        perimeter_core_partitions(polygon, list(facade_edges(polygon, "main")))
