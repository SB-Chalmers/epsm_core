import math

import pytest
from shapely.affinity import rotate
from shapely.geometry import MultiPolygon, Polygon

from epsm_core import BuildingPart, Footprint, GeometryPolicy, PartyWall, RoofSpec, prepare_geometry
from epsm_core.compiler import EnergyPlusCompiler
from epsm_core.specs import ZoningSpec
from epsm_core.surface_checks import validate_surfaces


@pytest.mark.parametrize(
    "polygon",
    [
        Polygon([(0, 0), (10, 0), (10, 8), (0, 8)]),
        Polygon([(0, 0), (5, 0.001), (10, 0), (10, 8), (0, 8)]),
        Polygon([(0, 0), (20, 0), (20, 20), (0, 20)], [[(5, 5), (5, 15), (15, 15), (15, 5)]]),
        MultiPolygon(
            [Polygon([(0, 0), (4, 0), (4, 4), (0, 4)]), Polygon([(8, 0), (12, 0), (12, 4), (8, 4)])]
        ),
        Polygon(
            [
                (10 + 5 * math.cos(t / 30 * 2 * math.pi), 10 + 5 * math.sin(t / 30 * 2 * math.pi))
                for t in range(30)
            ]
        ),
    ],
)
def test_preparation_idempotent(polygon):
    result = prepare_geometry(polygon)
    assert result.status == "accepted"
    repeated = prepare_geometry(result.cleaned_geometry)
    assert repeated.cleaned_geometry.wkb == result.cleaned_geometry.wkb
    assert result.metrics["source_topology"] == result.metrics["cleaned_topology"]
    assert all(e.source_edges for e in result.edge_lineage)
    assert result.source_geometry.wkb == polygon.wkb
    assert result.metrics["boundary_displacement_m"] <= 0.1
    assert result.metrics["area_change_fraction"] <= 0.005
    assert result.metrics["perimeter_change_fraction"] <= 0.01


def test_invalid_and_collapsed_quarantined():
    assert prepare_geometry(Polygon([(0, 0), (10, 10), (0, 10), (10, 0)])).status != "accepted"
    assert (
        prepare_geometry(Polygon([(0, 0), (0.0001, 0), (0.0001, 2), (0, 2)])).status != "accepted"
    )
    assert (
        prepare_geometry(MultiPolygon([Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])] * 2)).status
        != "accepted"
    )


def test_protected_property_boundary():
    p = Polygon([(0, 0), (5, 0.001), (10, 0), (10, 10), (0, 10)])
    result = prepare_geometry(p, GeometryPolicy(protected_vertices=((5, 0.001),)))
    assert (5, 0.001) in result.cleaned_geometry.exterior.coords
    assert len(result.edge_lineage) == 5


def test_ordering_and_rotation(building):
    p = building.geometry.parts[0]
    fp = p.footprint
    coords = fp.exterior
    reordered = p.updated(footprint=fp.updated(exterior=tuple(reversed(coords[2:] + coords[:2]))))
    assert p == reordered
    for angle in (0, 17, 90, 180):
        clean = prepare_geometry(rotate(fp.polygon, angle))
        assert clean.cleaned_geometry.area == pytest.approx(fp.area_m2, rel=0.0002)


@pytest.mark.parametrize("zoning", ["whole_building", "per_storey"])
@pytest.mark.parametrize("roof", ["compact", "cold_attic"])
@pytest.mark.parametrize("basement", [0, 2.5])
def test_unequal_wings(building, energyplus, zoning, roof, basement):
    part = building.geometry.parts[0].updated(
        footprint=Footprint.rectangle(10, 10), storey_elevations_m=(0, 3, 6)
    )
    wing = BuildingPart(
        identifier="wing",
        footprint=Footprint(exterior=((10, 0), (18, 0), (18, 10), (10, 10))),
        storey_elevations_m=(0, 2.5, 5, 7.5, 10),
    )
    b = building.updated(
        geometry=building.geometry.updated(
            parts=(part, wing),
            zoning=ZoningSpec(mode=zoning),
            basement_depth_m=basement,
            roof=RoofSpec(topology=roof),
        ),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    assert report.data["conditioned_floor_area_m2"] == 520
    assert sum(
        f["area_m2"] for f in report.data["ground_surfaces"] if f["surface_type"] == "Floor"
    ) == pytest.approx(180)
    if zoning == "whole_building":
        assert sum(z["conditioned"] for z in report.data["zones"].values()) == 1
    validate_surfaces(model, report.data["zones"])


def test_party_wall(building, energyplus):
    party = PartyWall(
        facade_id="main.r0.e0",
        neighbor_id="neighbor",
        neighbor_conditioning="heated",
        contact_confirmed=True,
        assumption_source="review fixture",
    )
    b = building.updated(geometry=building.geometry.updated(party_walls=(party,)))
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    assert any(
        s["outside_boundary_condition"] == "Adiabatic"
        for s in model["BuildingSurface:Detailed"].values()
    )
    with pytest.raises(ValueError, match="reviewed"):
        EnergyPlusCompiler(energyplus).compile(
            b.updated(
                geometry=b.geometry.updated(
                    party_walls=(party.updated(contact_confirmed=False),)
                )
            )
        )


def test_surface_damage_detected(building, energyplus):
    model, report = EnergyPlusCompiler(energyplus).compile(building)
    model["BuildingSurface:Detailed"].pop(next(iter(model["BuildingSurface:Detailed"])))
    with pytest.raises(ValueError):
        validate_surfaces(model, report.data["zones"])


def test_basement_boundary_is_explicit(building, energyplus):
    b = building.updated(geometry=building.geometry.updated(basement_depth_m=2.5))
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    ceilings = [
        s
        for s in model["BuildingSurface:Detailed"].values()
        if s["construction_name"].startswith("basement_ceiling")
    ]
    assert len(ceilings) == 2
    with pytest.raises(ValueError, match="basement_ceiling"):
        b.updated(envelope=b.envelope.updated(basement_ceiling=None))


def test_unconditioned_part_glazing_and_loads(building, energyplus):
    part = building.geometry.parts[0]
    annex = part.updated(
        identifier="annex",
        conditioned=False,
        footprint=Footprint(exterior=((30, 0), (40, 0), (40, 20), (30, 20))),
    )
    b = building.updated(
        geometry=building.geometry.updated(
            parts=(part, annex), zoning=ZoningSpec(mode="whole_building")
        )
    )
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    zones = report.data["zones"]
    unconditioned = {name for name, z in zones.items() if not z["conditioned"]}
    assert len(unconditioned) == 1
    assert not unconditioned.intersection(model["ZoneHVAC:IdealLoadsAirSystem"])
    assert any(f["part_id"] == "annex" and f["window_area_m2"] > 0 for f in report.data["facades"])


def test_conflicting_properties_preserve_edges():
    p = Polygon([(0, 0), (5, 0.001), (10, 0), (10, 10), (0, 10)])
    result = prepare_geometry(
        p, GeometryPolicy(edge_properties=(("p0.r0.e0", "wwr=.2"), ("p0.r0.e1", "wwr=.5")))
    )
    assert len(result.edge_lineage) == 5
