import pytest
from epsm_core.runner import EnergyPlusRunner
from epsm_core.specs import Footprint


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
        "mass_regression",
    ],
)
def test_annual(building, energyplus, tmp_path, variant):
    g = building.geometry
    if variant == "attic":
        building = building.updated(envelope=building.envelope.updated(roof_topology="cold_attic"))
    if variant == "storeys":
        g = g.updated(zoning="per_storey")
    if variant == "basement":
        g = g.updated(basement_depth_m=2.5)
    if variant == "courtyard":
        g = g.updated(
            footprints=(
                Footprint(
                    exterior=((0, 0), (30, 0), (30, 30), (0, 30)),
                    holes=(((10, 10), (20, 10), (20, 20), (10, 20)),),
                ),
            )
        )
    if variant == "multipolygon":
        g = g.updated(
            footprints=(*g.footprints, Footprint(exterior=((40, 0), (50, 0), (50, 10), (40, 10))))
        )
    if variant == "concave":
        g = g.updated(
            footprints=(
                Footprint(exterior=((0, 0), (30, 0), (30, 10), (15, 10), (15, 20), (0, 20))),
            )
        )
    if variant == "mass_regression":
        g = g.updated(
            footprints=(
                Footprint.l_shape(51.3295122915, 14.9176585101, 27.9713555903, 6.0935970290),
            ),
            floors=3,
            floor_height_m=3.0731910256,
            orientation_deg=71.6329643048,
        )
    output = EnergyPlusRunner(energyplus).run(building.updated(geometry=g), tmp_path / variant)
    assert output.scalars["space_heating_demand_kwh"] > 0
    assert output.scalars["dhw_load_eui_kwh_m2"] == pytest.approx(21, rel=0.005)
    assert output.diagnostics["severe_count"] == 0
    assert output.diagnostics["invalid_view_factor_count"] == 0
