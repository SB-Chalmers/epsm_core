"""Hourly supplied heat budgets are shared without inferring engine-only inputs."""
import pytest

from epsm_core import GainPartitionSpec, ScheduleSpec, UseSpec
from epsm_core.gains import resolve_internal_gains


def use(**changes):
    values = dict(
        heating_setpoint=ScheduleSpec.constant(21), occupant_density_per_m2=.01,
        occupant_activity_w=100, equipment_gain_w_m2=4, lighting_gain_w_m2=2,
        dhw_kwh_m2_year=0, occupancy_fraction=ScheduleSpec.constant(.5),
        equipment_fraction=ScheduleSpec.constant(.5),
        equipment_heat_fraction_schedule=ScheduleSpec(values=(.5, .8) * 12),
        gain_partitions=GainPartitionSpec(
            policy="explicit", people_fraction_radiant=.25, people_sensible_heat_fraction=.6,
            equipment_fraction_radiant=.2, equipment_fraction_latent=.1,
            lighting_fraction_radiant=.3, lighting_fraction_visible=.2,
            lighting_return_air_fraction=.1))
    values.update(changes)
    return UseSpec(**values)


def test_hourly_budget_uses_schedules_and_reference_area():
    result = resolve_internal_gains(use(), reference_area_m2=100, calendar_year=2023)
    # People: 50 W input, 30 W sensible. Equipment: 200 W input.
    assert result.convective_w[:2] == pytest.approx((22.5 + 40 + 80, 22.5 + 100 + 80))
    assert result.radiant_w[:2] == pytest.approx((7.5 + 40 + 100,) * 2)
    assert result.latent_w[:2] == pytest.approx((20 + 20,) * 2)
    assert result.lost_w[:2] == pytest.approx((100, 40))
    assert result.return_air_w[:2] == pytest.approx((20, 20))
    assert len(result.convective_w) == 8760
    for hour in (0, 1):
        assert sum(getattr(result, field)[hour] for field in (
            "convective_w", "radiant_w", "latent_w", "lost_w", "return_air_w")) == pytest.approx(450)
    assert resolve_internal_gains(use(), reference_area_m2=50, calendar_year=2023).radiant_w[0] == pytest.approx(result.radiant_w[0] / 2)
    with pytest.raises(TypeError):
        result.convective_w[0] = 1


def test_unresolved_people_heat_remains_visible():
    configured = use()
    configured = configured.updated(gain_partitions=configured.gain_partitions.updated(
        people_sensible_heat_fraction=None))
    result = resolve_internal_gains(configured, reference_area_m2=100, calendar_year=2023)
    assert result.unresolved_people_w[0] == 50
    assert result.latent_w[0] == 20  # Only the known equipment latent contribution.


def test_resolver_requires_explicit_partitions_and_finite_area():
    with pytest.raises(ValueError, match="explicit"):
        resolve_internal_gains(use(gain_partitions=None), reference_area_m2=100, calendar_year=2023)
    for area in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            resolve_internal_gains(use(), reference_area_m2=area, calendar_year=2023)
