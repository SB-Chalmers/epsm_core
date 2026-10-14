"""Offline physical inventory and ordered renovation example; no engine or weather needed."""

from epsm_data import SystemOperation, reference_hvac_template

from epsm_core import Building


def main():
    building = Building()
    print(building)
    print(building.quantities().by_material())
    child = building.renovate(SystemOperation("replace_hvac", reference_hvac_template()))
    print("Installed:", child.material_flows[-1].installed.to_dict())
    print("Removed:", child.material_flows[-1].removed.to_dict())
    print("Snapshot:", child.snapshot().sha256)


if __name__ == "__main__":
    main()
