"""Resolve sourced and authored profiles offline, without selecting HVAC or geometry."""

from epsm_data import OperatingProfile, select_dhw_profile, select_operating_profile

from epsm_core import resolve_operating_profile


def main():
    residential = resolve_operating_profile(
        select_operating_profile("multi_family"), calendar={"calendar_year": 2024},
    )
    ben = resolve_operating_profile(
        select_dhw_profile("multi_family", purpose="epc_normal_use"),
        previous=residential.operation,
    )
    assert ben.operation.dhw_fraction == residential.operation.dhw_fraction
    print(residential)
    print("BEN source:", ben.source_records[0].source)
    authored = OperatingProfile("project:quiet-home", {"building_assumptions": {
        "use": {"heating_setpoint": {"values": [19] * 24},
                "occupant_density_per_m2": 0.02, "equipment_gain_w_m2": 2,
                "dhw_kwh_m2_year": 15},
    }}, source_references=("project:research-protocol",))
    custom = resolve_operating_profile(authored)
    assert type(custom.operation) is type(residential.operation)
    print(custom)
    school = resolve_operating_profile(select_operating_profile("school"))
    assert school.operation is None and "calendar" in school.requirements
    print("School requirements:", school.requirements)


if __name__ == "__main__":
    main()
