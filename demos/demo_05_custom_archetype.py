"""Demo 5 — Custom archetypes.

`cmf_1960` (used in the earlier demos) is just a *factory* that returns a
fully-populated :class:`~pbgenerator.building_params.BuildingParams`.  Nothing
forces you to use it — a "custom archetype" is simply a `BuildingParams` you
assemble yourself.  This demo shows the two ways to do that:

  A. Tweak an existing archetype with ``dataclasses.replace`` (quickest).
  B. Build a `BuildingParams` from scratch, wrapped in your own factory
     function — including a custom parametric construction set.

No EnergyPlus run happens here; like Demo 1 this is only about *defining* the
building.  Run it with::

    PYTHONPATH=src python demos/demo_05_custom_archetype.py
"""
from __future__ import annotations

import dataclasses

from pbgenerator import (
    Building,
    BuildingParams,
    FacadeWWR,
    Location,
    WeatherSite,
    cmf_1960,
    make_construction_set_from_spec,
)


# ----------------------------------------------------------------------
# A. Tweak an existing archetype
# ----------------------------------------------------------------------
# Start from the 1960s archetype and override just the fields you care
# about.  `BuildingParams` is a frozen dataclass, so use `replace` to get a
# new, modified copy.  Here: a "deep-retrofit" variant of CMF 1960 with
# FTX heat recovery, a tighter envelope, and a lower DHW demand.
def cmf_1960_retrofit(num_floors: int) -> BuildingParams:
    base = cmf_1960(num_floors=num_floors, ventilation_system="FTX", seed=0)
    return dataclasses.replace(
        base,
        infiltration_ach=0.20,        # blower-door tightened envelope
        dhw_kwh_m2=18.0,              # low-flow fixtures
        vent_recovery_eff=0.80,      # high-efficiency HRV core
        thermal_bridge_fraction=0.10,  # insulated balcony/slab edges
    )


# ----------------------------------------------------------------------
# B. A fully custom archetype, built from scratch
# ----------------------------------------------------------------------
# Define your own envelope as an epsm_data *spec* — the same provenance-backed
# path the built-in archetypes use.  You describe only the *composition*
# (which materials, how thick); epsm_data resolves the thermal properties from
# its material registry (and, unless skip_api, embodied-carbon from Boverket).
# `make_construction_set_from_spec` turns the spec into a registered
# construction set whose id you hand to `BuildingParams`.
#
# Materials are referenced by their honeybee id (with the matching Boverket
# id).  These come from epsm_data's curated registry — see
# pbgenerator.constructions._MAT for the available keys.
_MATERIALS = {
    "concrete":   ("4 in. Normalweight Concrete Wall",  "6000000026"),
    "conc_floor": ("100mm Normalweight concrete floor", "6000000026"),
    "conc_roof":  ("6 in. Heavyweight Concrete Roof",   "6000000026"),
    "conc_bsmt":  ("8 in. Concrete Block Basement Wall", "6000000026"),
    "mineral_wool": ("Mineral Wool Old (created)",      "6000000123"),
    "gypsum":     ("G01 13mm gypsum board",             "6000000020"),
    "eps":        ("I02 50mm insulation board",         "6000000131"),
    "roof_felt":  ("Built-up Roofing",                  "6000000132"),
}


def _layer(material: str, thickness: float) -> dict:
    """One spec layer: a registry material at a given thickness [m]."""
    hb_id, bov_id = _MATERIALS[material]
    return {"honeybee_id": hb_id, "boverket_id": bov_id, "thickness": thickness}


def _opaque(*layers: dict, shearing: str = "Skin") -> dict:
    return {"components": [{"shearing_layer": shearing, "layers": list(layers)}]}


def custom_envelope() -> str:
    spec = {
        "archetype_id": "CUSTOM_LOWENERGY_2020",
        "display_name": "Custom low-energy MFH (2020)",
        "construction_year": 2020,
        "building_typology": "multi_family",
        "elements": {
            # Exterior wall: render-less concrete sandwich, 300 mm mineral wool.
            "EXT_WALL": _opaque(
                _layer("concrete", 0.080),
                _layer("mineral_wool", 0.300),
                _layer("concrete", 0.150),
                _layer("gypsum", 0.013),
            ),
            # Compact flat roof: 400 mm mineral wool between deck and membrane.
            "ROOF": _opaque(
                _layer("roof_felt", 0.010),
                _layer("mineral_wool", 0.400),
                _layer("conc_roof", 0.150),
            ),
            # Cold-side ceiling slab (required role) — bare interzone concrete.
            "TOP_FLOOR": _opaque(_layer("conc_floor", 0.200), shearing="Structure"),
            "INTERMEDIATE_FLOOR": _opaque(_layer("conc_floor", 0.200), shearing="Structure"),
            # Ground floor: slab + 250 mm EPS.
            "GROUND_FLOOR": _opaque(
                _layer("conc_floor", 0.160),
                _layer("eps", 0.250),
                shearing="Structure",
            ),
            "BASEMENT_FLOOR": _opaque(
                _layer("eps", 0.050),
                _layer("conc_floor", 0.150),
                shearing="Structure",
            ),
            "BASEMENT_WALL": _opaque(
                _layer("conc_bsmt", 0.200),
                _layer("mineral_wool", 0.120),
                shearing="Structure",
            ),
            # Triple glazing.
            "WINDOW": {"u_value": 0.90, "shgc": 0.50, "vt": 0.60},
        },
    }
    # skip_api=True resolves thermal properties only (no Boverket network call).
    return make_construction_set_from_spec(spec, skip_api=True)


def passivhus_2020(num_floors: int) -> BuildingParams:
    cset = custom_envelope()
    return BuildingParams(
        num_floors=num_floors,
        floor_height=3.0,
        wwr=FacadeWWR(north=0.20, east=0.25, south=0.40, west=0.25),
        construction_set=cset,
        apartment_depth=6.0,          # > 0 → adds a heated core/corridor zone
        t_heating=21.0,
        t_cooling=26.0,
        ventilation_system="FTX",
        infiltration_ach=0.10,        # Passivhaus-class airtightness
        mech_vent_l_s_m2=0.35,
        occupant_density=0.020,
        lighting_w_m2=4.0,
        equipment_w_m2=3.0,
        infiltration_on=1.0,
        dhw_kwh_m2=20.0,
        bldg_services_w_m2=0.5,
        vent_recovery_eff=0.85,       # certified HRV
        dhw_vvc_kwh_m2=2.0,
    )


def _summary(tag: str, params: BuildingParams) -> None:
    print(f"\n{tag}")
    print("  construction_set:", params.construction_set)
    print("  ventilation:     ", params.ventilation_system)
    print("  infiltration ACH:", params.infiltration_ach)
    print("  HRV recovery:    ", params.vent_recovery_eff)
    print("  DHW kWh/m2:      ", params.dhw_kwh_m2)


def main() -> None:
    footprint = [[0, 0], [24, 0], [24, 14], [0, 14]]
    weather = WeatherSite(
        epw_path="epw/SWE_BL_Hano.Island.026280_TMYx.2004-2018.epw",
        station_name="Hano Island",
    )
    location = Location.hypothetical_site(city="Demoville", weather=weather)

    # A — retrofit variant
    retrofit_params = cmf_1960_retrofit(num_floors=4)
    _summary("A. CMF-1960 deep-retrofit (replace):", retrofit_params)

    # B — from-scratch modern archetype
    modern_params = passivhus_2020(num_floors=6)
    _summary("B. Passivhus-2020 (from scratch):", modern_params)

    # Either one drops straight into a Building, exactly like cmf_1960 did.
    building = Building(
        name="passivhus_demo",
        params=modern_params,
        footprint_pts=footprint,
        location=location,
    )

    # Confirm the custom params produce a valid, buildable geometry.
    building.build_model()
    print("\nBuilt Building:", building.name)
    print("  footprint area: ", round(building.footprint_area_m2, 1), "m2")
    print("  zones:          ", len(building.rooms.all))
    print("  heated area:    ", round(building.heated_floor_area_m2, 1), "m2")
    print("\nCustom archetypes are just BuildingParams. Next: building.simulate(...).")


if __name__ == "__main__":
    main()
