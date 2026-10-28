"""Delivered energy per purchased carrier from a simulation result, with hourly PV netting.

Thermal results hold demands; the building's declared delivery turns them into
energy bought from each carrier. This module reads only result arrays and the
building's delivery declaration. It never assumes a carrier or efficiency that the
building or the caller did not state.

Carriers are ``district_heating``, ``electricity`` and ``fuel``. PV generation is
used on site in the hour it is produced, up to that hour's electricity use; the
rest is exported and kept separate from purchased energy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType

import numpy as np

CARRIERS = {"district_heat": "district_heating", "electric_direct": "electricity",
            "heat_pump": "electricity", "fuel": "fuel"}
USES = ("space_heating", "fans", "dhw")


@dataclass(frozen=True)
class DeliveredEnergy:
    """Hourly purchased and exported energy by carrier for one building state.

    ``purchased`` excludes PV used on site; ``exported`` holds surplus generation.
    ``uses`` lists the end uses covered, and ``boundary`` names them in the form
    epsm_lca compares against its assessment boundary.
    """

    state_id: str | None
    purchased: dict
    exported: dict
    pv_generation: tuple[float, ...] = ()
    pv_self_consumed: tuple[float, ...] = ()
    uses: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    def __post_init__(self):
        for name in ("purchased", "exported"):
            series = {k: tuple(float(v) for v in values)
                      for k, values in dict(getattr(self, name)).items()}
            if any(not math.isfinite(v) or v < 0 for s in series.values() for v in s):
                raise ValueError(f"{name} energy must be finite and nonnegative")
            object.__setattr__(self, name, MappingProxyType(series))

    @property
    def boundary(self):
        uses = set(self.uses)
        if uses == {"space_heating", "fans"}:
            return "space_heating_and_fans"  # epsm_lca's default boundary
        if uses == {"space_heating", "fans", "dhw"}:
            return "space_heating_fans_and_dhw"
        return "+".join(u for u in USES if u in uses)

    @property
    def annual_purchased(self):
        return {k: math.fsum(v) for k, v in self.purchased.items()}

    @property
    def annual_exported(self):
        return {k: math.fsum(v) for k, v in self.exported.items()}

    def summary(self):
        return {"state_id": self.state_id, "boundary": self.boundary,
                "purchased_kwh": self.annual_purchased, "exported_kwh": self.annual_exported,
                "pv_generation_kwh": math.fsum(self.pv_generation),
                "pv_self_consumed_kwh": math.fsum(self.pv_self_consumed),
                "notes": list(self.notes)}


def delivered_energy(result, building, *, dhw_carrier=None, dhw_efficiency=1.0,
                     fvp_backup_carrier=None, pv=True):
    """Convert one simulation result into hourly delivered energy per carrier.

    Parameters
    ----------
    result : SimulationResult
        Output of a run of ``building``'s current state.
    building : Building
        The simulated state; its HVAC delivery declares carriers and efficiencies.
    dhw_carrier : {"district_heating", "electricity", "fuel"}, optional
        Carrier supplying domestic hot water. Without it DHW is outside the
        boundary, unless an exhaust-air heat pump already supplies it.
    dhw_efficiency : float, optional
        Hot-water heat delivered per purchased kWh (above 1 for a heat pump).
    fvp_backup_carrier : {"district_heating", "electricity", "fuel"}, optional
        Carrier of the exhaust-air heat pump's backup heat; required when it is used.
    pv : bool, optional
        Net the result's PV generation against electricity hour by hour.

    Raises
    ------
    ValueError
        The result describes another state, required outputs are absent, or a
        needed carrier is not declared.
    """
    hourly = result.hourly
    state = building.snapshot().sha256
    recorded = result.diagnostics.get("building_snapshot_id") if result.diagnostics else None
    if recorded is not None and recorded != state:
        raise ValueError("The simulation result describes a different building state")
    if building.hvac is None:
        raise ValueError("Delivered energy needs the building's HVAC delivery declaration")
    delivery = building.hvac.delivery
    hours = len(hourly["space_heating_demand_kwh"])
    zero = np.zeros(hours)
    purchased, uses, notes = {}, [], []

    def add(carrier, values):
        if carrier not in set(CARRIERS.values()):
            raise ValueError(f"Unknown carrier {carrier!r}")
        purchased[carrier] = purchased.get(carrier, zero) + np.asarray(values, dtype=float)

    def require(name):
        if name not in hourly:
            raise ValueError(f"The result has no {name}; run with the declared delivery")
        return hourly[name]

    if delivery.fvp is not None:
        add("electricity", require("fvp_electricity_kwh"))
        backup = np.asarray(require("backup_input_kwh"), dtype=float)
        if backup.sum() > 0:
            if fvp_backup_carrier is None:
                raise ValueError("State fvp_backup_carrier: the heat pump's backup heat is used")
            add(fvp_backup_carrier, backup)
        uses += ["space_heating", "dhw"]
        notes.append("Exhaust-air heat pump supplies space heating and DHW; fan electricity "
                     "is not modelled with it.")
    elif delivery.heating is not None:
        add(CARRIERS[delivery.heating.carrier], require("space_heating_carrier_input_kwh"))
        uses.append("space_heating")
        if "ventilation_fan_electricity_kwh" in hourly:
            add("electricity", hourly["ventilation_fan_electricity_kwh"])
            uses.append("fans")
        else:
            notes.append("No specific fan power is declared; fan electricity is outside the boundary.")
        if dhw_carrier is not None:
            if not dhw_efficiency > 0:
                raise ValueError("dhw_efficiency must be positive")
            add(dhw_carrier, np.asarray(require("dhw_load_kwh"), dtype=float) / dhw_efficiency)
            uses.append("dhw")
        else:
            notes.append("No DHW carrier is stated; domestic hot water is outside the boundary.")
    else:
        raise ValueError("Declare heating delivery or an exhaust-air heat pump on the building")

    generation = np.asarray(hourly.get("pv_generation_kwh", zero), dtype=float) if pv else zero
    exported = {}
    self_consumed = zero
    if generation.any():
        electricity = purchased.get("electricity", zero)
        self_consumed = np.minimum(generation, electricity)
        purchased["electricity"] = electricity - self_consumed
        exported["electricity"] = generation - self_consumed
        notes.append("PV is used on site hour by hour up to the covered electricity use; "
                     "use outside the boundary is not offset.")
    return DeliveredEnergy(state, purchased, exported,
                           tuple(generation) if generation.any() else (),
                           tuple(self_consumed) if generation.any() else (),
                           tuple(dict.fromkeys(uses)), tuple(notes))
