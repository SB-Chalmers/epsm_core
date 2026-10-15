"""Annual synthetic handover checks; these runs are not empirical validation.

References: source-pinned Sveby profiles in nonresidential.py. The weekday prefix
calendar below exists solely to test counts/closures; it is not a school term.
"""

from datetime import date, timedelta

import pytest
from profile_inputs import nonresidential_converter

from epsm_core import (
    AirflowSpec,
    DeliverySpec,
    EnergyPlusRunner,
    HeatingDeliverySpec,
    UseSpec,
)


@pytest.mark.energyplus
@pytest.mark.parametrize("category,days,dhw", [("office", 225, 2), ("school", 220, 10)])
def test_annual_source_loads_and_delivered_heat(
    building, energyplus, tmp_path, category, days, dhw
):
    year = building.climate.calendar_year
    active = []
    current = date(year, 1, 1)
    while len(active) < days:
        if current.weekday() < 5:
            active.append(current)
        current += timedelta(days=1)
    profile = nonresidential_converter(category)
    defaults = profile.building_assumptions(
        calendar_year=year,
        active_dates=active,
        calendar_source="synthetic integration calendar; not building evidence",
    )
    reference_area = 900
    spec = building.updated(
        use=UseSpec.model_validate(defaults["use"]),
        airflow=AirflowSpec.model_validate(
            {**building.airflow.model_dump(), **defaults["airflow"]}
        ),
        load_reference_area_m2=reference_area,
        delivery=DeliverySpec(
            heating=HeatingDeliverySpec(
                carrier="district_heat",
                net_distribution_loss_kwh_m2_year=5,
                source="synthetic downstream loss; not an empirical correction",
            )
        ),
    )
    output = EnergyPlusRunner(energyplus).run(spec, tmp_path / category)
    assert output.scalars["dhw_load_kwh"] == pytest.approx(dhw * reference_area, rel=0.005)
    assert output.scalars["space_heating_carrier_input_kwh"] == pytest.approx(
        output.scalars["space_heating_demand_kwh"] + 5 * reference_area
    )
    assert sum(
        output.diagnostics["monthly_energy_kwh"]["space_heating_demand_kwh"]
    ) == pytest.approx(output.scalars["space_heating_demand_kwh"])
    assert len(output.hourly["space_heating_carrier_input_kwh"]) == spec.climate.hours_in_year
    assert output.diagnostics["severe_count"] == 0
