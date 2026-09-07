"""Optional external adapter contract, with no registry or Boverket calls."""

from types import SimpleNamespace as N

import pytest


def test_complete_layer_adapter():
    adapter = pytest.importorskip("epsm_data.epsm_core_adapter")
    material = N(
        density=1000,
        specific_heat=900,
        roughness="Smooth",
        thermal_absorptance=0.9,
        solar_absorptance=0.6,
        visible_absorptance=0.6,
    )
    layer = N(
        name="test", thickness=0.2, r_value=0.4, materials=(N(area_fraction=1, material=material),)
    )
    element = N(components=(N(layers=(N(position=0, layer=layer),)),))
    output = adapter.construction_to_core(element)
    assert output.layers[0].thickness_m == 0.2
    assert output.layers[0].material.conductivity_w_mk == 0.5
    assert output.layers[0].material.density_kg_m3 == 1000
    assert output.u_value_w_m2k == pytest.approx(1 / 0.57)
