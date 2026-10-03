import pytest
from epsm_core.runner import EnergyPlusRunner
from epsm_core.specs import (
    BuildingPart,
    Footprint,
    GroundTemperatureSpec,
    PartyWall,
    RoofSpec,
    ZoningSpec,
)


@pytest.mark.energyplus
@pytest.mark.parametrize(
    "variant",
    [
        "compact",
        "attic",
        "storeys",
        "basement",
        "courtyard",
        "multipolygon",
        "concave",
        "unequal_wings",
        "party_wall",
    ],
)
def test_annual(building, energyplus, tmp_path, variant):
    g = building.geometry.updated(zoning=ZoningSpec(mode="whole_building"))
    part = g.parts[0]
    if variant == "attic":
        g = g.updated(roof=RoofSpec(topology="cold_attic"))
    if variant == "storeys":
        g = g.updated(zoning=ZoningSpec(mode="per_storey"))
    if variant == "basement":
        g = g.updated(basement_depth_m=2.5)
    if variant == "courtyard":
        g = g.updated(
            parts=(
                part.updated(
                    footprint=Footprint(
                        exterior=((0, 0), (30, 0), (30, 30), (0, 30)),
                        holes=(((10, 10), (20, 10), (20, 20), (10, 20)),),
                    )
                ),
            )
        )
    if variant == "multipolygon":
        g = g.updated(
            parts=(
                part,
                part.updated(
                    identifier="other",
                    footprint=Footprint(exterior=((40, 0), (50, 0), (50, 10), (40, 10))),
                ),
            )
        )
    if variant == "concave":
        g = g.updated(parts=(part.updated(footprint=Footprint.l_shape(30, 20, 15, 10)),))
    if variant == "unequal_wings":
        g = g.updated(
            parts=(
                part,
                BuildingPart(
                    identifier="wing",
                    footprint=Footprint(exterior=((30, 0), (40, 0), (40, 20), (30, 20))),
                    storey_elevations_m=(0, 3, 6),
                ),
            )
        )
    if variant == "party_wall":
        g = g.updated(
            party_walls=(
                PartyWall(
                    facade_id="main.r0.e0",
                    neighbor_id="heated",
                    neighbor_conditioning="heated",
                    contact_confirmed=True,
                    assumption_source="fixture",
                ),
            )
        )
    directory = tmp_path / variant
    b = building.updated(geometry=g)
    if variant == "courtyard":
        b = b.updated(envelope=b.envelope.updated(ground_temperature=GroundTemperatureSpec()))
    output = EnergyPlusRunner(energyplus).run(b, directory)
    scalars, diagnostics = output.scalars, output.diagnostics
    assert (directory / "result.json").exists()
    assert diagnostics["model_assumptions"]["empirical_validation"] == "not_evaluated_by_core"
    assert scalars["space_heating_demand_kwh"] > 0
    assert scalars["dhw_load_eui_kwh_m2"] == pytest.approx(21, rel=0.005)
    assert diagnostics["severe_count"] == diagnostics["invalid_view_factor_count"] == 0
    assert all(m["approved"] for m in diagnostics["messages"])


@pytest.mark.energyplus
def test_leap_year(building, energyplus, tmp_path):
    from epsm_core.weather import climate_from_epw

    lines = open(building.climate.epw_path).read().splitlines()
    lines[4] = "HOLIDAYS/DAYLIGHT SAVINGS,Yes,0,0,0"
    data = []
    for line in lines[8:]:
        row = line.split(",")
        row[0] = "2024"
        data.append(",".join(row))
        if row[1:4] == ["2", "28", "24"]:
            for source in lines[8:]:
                fields = source.split(",")
                if fields[1:3] == ["2", "28"]:
                    fields[0] = "2024"
                    fields[2] = "29"
                    data.append(",".join(fields))
    path = tmp_path / "synthetic-leap.epw"
    path.write_text("\n".join(lines[:8] + data) + "\n")
    b = building.updated(
        climate=climate_from_epw(path, calendar_year=2024),
        geometry=building.geometry.updated(zoning=ZoningSpec(mode="per_storey")),
    )
    output = EnergyPlusRunner(energyplus).run(b, tmp_path / "leap")
    assert len(output.hourly["space_heating_demand_kwh"]) == 8784
