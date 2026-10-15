"""Apply resolved inputs to explicit geometry, offline and without an engine."""

from epsm_core import Building, Footprint


def main():
    reference = Building(preset="illustrative-reference")
    building = Building.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3,
        facade=reference.facade,
    )
    before = building.geometry
    report = building.assign_inputs(
        construction_set=reference.construction_set,
        operation=reference.operation,
        mode="fill_missing",
    )
    assert building.geometry == before
    assert building.hvac is None
    assert building.readiness("quantities")
    print(report)
    print("Still required:", building.readiness().missing)


if __name__ == "__main__":
    main()
