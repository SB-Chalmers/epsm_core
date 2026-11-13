"""A measured total air change nets off this building's envelope infiltration."""
import pytest

from epsm_core import natural_exchange_for_total, with_self_draught_total
from epsm_core.self_draught import MINIMUM_NATURAL_EXCHANGE_ACH
from epsm_core.specs.physics import AirflowSpec


def self_draught(**values):
    return AirflowSpec(**{"topology": "S", "envelope_infiltration_ach": 0, **values})


def test_ach_infiltration_is_subtracted_from_the_total():
    airflow = self_draught(envelope_infiltration_ach=0.14, natural_exchange_ach=0.5)
    assert natural_exchange_for_total(0.39, airflow, volume_m3=1000) == pytest.approx(0.25)


def test_area_infiltration_is_converted_on_the_buildings_own_volume():
    airflow = self_draught(envelope_infiltration_l_s_m2=0.1)
    natural = natural_exchange_for_total(0.39, airflow, volume_m3=2700, reference_area_m2=1000)
    assert natural == pytest.approx(0.39 - 0.1 * 3.6 / 2.7)
    with pytest.raises(ValueError, match="reference_area_m2"):
        natural_exchange_for_total(0.39, airflow, volume_m3=2700)


def test_natural_exchange_keeps_a_floor_for_a_leaky_envelope():
    airflow = self_draught(envelope_infiltration_ach=0.6)
    assert natural_exchange_for_total(0.39, airflow, volume_m3=1000) == MINIMUM_NATURAL_EXCHANGE_ACH


@pytest.mark.parametrize("total, volume", [(0, 1000), (-0.1, 1000), (0.39, 0)])
def test_total_and_volume_must_be_positive(total, volume):
    with pytest.raises(ValueError, match="positive"):
        natural_exchange_for_total(total, self_draught(), volume_m3=volume)


def test_spec_total_uses_the_geometry_and_leaves_other_systems_alone(building):
    spec = building.updated(airflow=building.airflow.updated(
        topology="S", mechanical_vent_l_s_m2=0, sensible_recovery_effectiveness=0,
        latent_recovery_effectiveness=0, envelope_infiltration_ach=0.1))
    netted = with_self_draught_total(spec, 0.39)
    assert netted.airflow.natural_exchange_ach == pytest.approx(0.29)
    assert netted.airflow.envelope_infiltration_ach == 0.1
    mechanical = spec.updated(airflow=spec.airflow.updated(topology="F"))
    assert with_self_draught_total(mechanical, 0.39) is mechanical
