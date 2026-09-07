import pytest

from epsm_core import AddInsulation, ReplaceGlazing, apply_renovation, quantity_takeoff
from epsm_core.specs import AssessmentReference, ZoningSpec


def test_nominal_quantities_and_zoning(building):
    items = quantity_takeoff(building)
    assert items == quantity_takeoff(
        building.updated(envelope=building.envelope.updated(thermal_bridge_uplift_fraction=0.25))
    )

    def role_volume(b, role):
        return sum(q.volume_m3 or 0 for q in quantity_takeoff(b) if q.role == role)

    assert role_volume(building, "intermediate_floor") == pytest.approx(240)
    assert role_volume(building, "intermediate_floor") == pytest.approx(
        role_volume(
            building.updated(
                geometry=building.geometry.updated(zoning=ZoningSpec(mode="whole_building"))
            ),
            "intermediate_floor",
        )
    )
    assert sum(q.area_m2 or 0 for q in items if q.kind == "glazing") == pytest.approx(168)
    assert all(q.mass_kg is None for q in items if q.kind != "opaque_layer")


def test_renovation_quantity_conservation(building):
    layer = building.envelope.wall.layers[0]
    renovated = apply_renovation(
        building, AddInsulation(element="wall", layer=layer), effective_date="2026-02-01"
    )
    before = sum(q.mass_kg or 0 for q in quantity_takeoff(building))
    after = sum(q.mass_kg or 0 for q in quantity_takeoff(renovated))
    event = renovated.renovations[-1]
    added = sum(c.after.mass_kg or 0 for c in event.changes if c.after)
    removed = sum(c.before.mass_kg or 0 for c in event.changes if c.before)
    assert after - before == pytest.approx(added - removed)
    assert event.targeted_element_ids and all(c.action == "added" for c in event.changes)
    assert not building.renovations
    with pytest.raises(ValueError):
        apply_renovation(
            renovated, AddInsulation(element="wall", layer=layer), effective_date="2025-01-01"
        )
    with pytest.raises(ValueError, match="targets"):
        apply_renovation(
            building,
            AddInsulation(element="wall", layer=layer),
            effective_date="2026-02-01",
            targeted_element_ids=("fiction",),
        )


def test_replacement_and_assessment_hash(building):
    renovated = apply_renovation(
        building,
        ReplaceGlazing(glazing=building.facade.glazing.updated(u_value_w_m2k=1)),
        effective_date="2026-01-01",
    )
    assert all(c.action == "replaced" for c in renovated.renovations[0].changes)
    assert (
        renovated.physical_hash()
        == renovated.updated(
            assessment_references=(
                AssessmentReference(identifier="future", currency="SEK", price_base_year=2026),
            )
        ).physical_hash()
    )
