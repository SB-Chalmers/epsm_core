"""Public footprint and simple-ground contracts, independent of shape tessellation."""

import pytest
from shapely.geometry import MultiPolygon, Polygon

from epsm_core import (
    AddInsulation,
    EnergyPlusCompiler,
    Footprint,
    GeometrySpec,
    GroundTemperatureSpec,
    apply_renovation,
    quantity_takeoff,
)


def test_polygon_and_multipolygon_preserve_geometry():
    courtyard = Polygon(
        [(0, 0), (30, 0), (30, 30), (0, 30)], [[(10, 10), (20, 10), (20, 20), (10, 20)]]
    )
    other = Polygon([(40, 0), (50, 0), (50, 10), (40, 10)])
    first = GeometrySpec.from_footprint(
        MultiPolygon([courtyard, other]), storey_elevations_m=(0, 3, 6)
    )
    second = GeometrySpec.from_footprint(
        MultiPolygon([other, courtyard]), storey_elevations_m=(0, 3, 6)
    )
    assert first == second
    assert first.footprint_area_m2 == 900
    assert first.conditioned_floor_area_m2 == 1800
    assert sum(len(f.holes) for f in first.footprints) == 1
    assert (
        GeometrySpec.from_footprint(Footprint.rectangle(2, 3), storey_elevations_m=(0, 3))
        .parts[0]
        .identifier
        == "main"
    )
    for invalid in (
        Polygon(),
        Polygon([(0, 0), (2, 2), (0, 2), (2, 0)]),
        Polygon([(0, 0, 0), (2, 0, 0), (2, 2, 0)]),
    ):
        with pytest.raises(ValueError):
            GeometrySpec.from_footprint(invalid, storey_elevations_m=(0, 3))


def test_monthly_ground_boundary_includes_basement(building, energyplus):
    temperatures = tuple(range(4, 16))
    b = building.updated(
        geometry=building.geometry.updated(basement_depth_m=2.5),
        envelope=building.envelope.updated(
            ground_temperature=GroundTemperatureSpec(
                monthly_temperatures_c=temperatures, source="test-specific profile"
            )
        ),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    fields = model["Site:GroundTemperature:BuildingSurface"]["ground_temperature"]
    assert tuple(fields.values()) == temperatures
    assert not any("Kiva" in key or "FoundationPerimeter" in key for key in model)
    ground = report.data["ground_surfaces"]
    assert {f["surface_type"] for f in ground} == {"Floor", "Wall"}
    assert sum(f["area_m2"] for f in ground) == pytest.approx(600 + 100 * 2.5)
    assert all(
        model["BuildingSurface:Detailed"][f["surface"]]["outside_boundary_condition"] == "Ground"
        for f in ground
    )
    assert b.physical_hash() != building.physical_hash()
    for values in ((18,) * 11, (18,) * 13, (float("nan"),) * 12):
        with pytest.raises(ValueError):
            GroundTemperatureSpec(monthly_temperatures_c=values)


def test_basement_ceiling_renovation_targets_thermal_boundary(building):
    b = building.updated(geometry=building.geometry.updated(basement_depth_m=2.5))
    updated = apply_renovation(
        b,
        AddInsulation(element="basement_ceiling", layer=building.envelope.wall.layers[0]),
        effective_date="2027-01-01",
    )
    event = updated.renovations[-1]
    assert event.changes and all(c.after.role == "basement_ceiling" for c in event.changes)
    assert updated.envelope.ground == b.envelope.ground
    before = sum(q.mass_kg or 0 for q in quantity_takeoff(b))
    after = sum(q.mass_kg or 0 for q in quantity_takeoff(updated))
    layer = building.envelope.wall.layers[0]
    assert after - before == pytest.approx(600 * layer.thickness_m * layer.material.density_kg_m3)


def test_facade_catalog_preserves_ids_and_reports_rotated_outward_azimuths():
    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(30, 20), storeys=3, storey_height_m=3
    )
    original = geometry.facades()
    rotated = geometry.updated(orientation_deg=90).facades()
    assert len(original) == 4
    assert [f.facade_id for f in original] == [f.facade_id for f in rotated]
    assert [f.length_m for f in original] == [30, 20, 30, 20]
    assert [f.azimuth_deg for f in original] == [180, 90, 0, 270]
    assert [f.azimuth_deg for f in rotated] == [270, 180, 90, 0]
    assert all(f.storeys == (0, 1, 2) for f in original)
    assert all(f.storey_elevations_m == (0, 3, 6, 9) for f in original)
