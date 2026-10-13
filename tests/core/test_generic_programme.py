"""The generic programme is a valid, clearly identified screening fallback."""

from epsm_core import load_generic_other_v1


def test_generic_other_profile_has_valid_weekday_and_leap_year_schedules():
    profile = load_generic_other_v1()
    use = profile.use_spec()
    ventilation = profile.ventilation_fraction()

    assert profile.profile_id == "epsm.generic_other.v1"
    assert use.occupancy_category == "non_residential"
    assert use.dhw_kwh_m2_year == 5
    assert profile.mechanical_vent_l_s_m2 == 0.7
    for year, hours in ((2023, 8760), (2024, 8784)):
        occupancy = use.occupancy_fraction.hourly(year)
        flow = ventilation.hourly(year)
        assert len(occupancy) == len(flow) == hours
        assert occupancy == flow
        assert all(0 <= value <= 1 for value in flow)
        assert 0 in flow and 1 in flow
