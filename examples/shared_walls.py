"""Inspect partial neighbouring contact without weather or an engine."""
from epsm_core import Building, Footprint, GeometrySpec, PartyWallNeighbor


def main():
    building = Building(preset="illustrative-reference")
    building.geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3,
    )
    neighbor = PartyWallNeighbor(
        identifier="next",
        footprint=Footprint(exterior=((2, -5), (8, -5), (8, 0), (2, 0))),
        top_m=4,
    )
    building.geometry = building.geometry.with_party_wall_contacts(
        (neighbor,), assumption_source="example wall outlines and eave heights; adiabatic assumption",
    )
    contact_area = sum(e.area_m2 for e in building.elements if e.boundary == "Adiabatic")
    assert contact_area == 24
    assert all(e.boundary == "Outdoors" for e in building.elements if e.role.value == "WINDOW")
    captured = building.snapshot()
    assert captured.to_building().snapshot().sha256 == captured.sha256
    print(f"Adiabatic wall area: {contact_area:g} m²; windows remain on outdoor walls.")


if __name__ == "__main__":
    main()
