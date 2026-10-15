# File: gains.py
# Purpose: Resolve declared internal-gain budgets for reporting and emission.
# SPDX-License-Identifier: MIT
# License: MIT; see the project-root LICENSE.
# Date created: 2026-10-14

"""Resolve gain fractions without weather I/O or an engine installation.

Equipment fractions reference electrical input, while people radiant fractions
reference sensible heat. Engine-derived people sensible/latent treatment remains
explicitly identified rather than estimated by Core.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .specs import GainPartitionSpec, UseSpec


@dataclass(frozen=True)
class InternalGainSeries:
    """Immutable hourly watts; unresolved people heat is never assigned a guessed split.

    Radiant includes visible lighting energy deposited on room surfaces. Latent,
    lost and return-air channels remain separate from room sensible heat.
    """

    convective_w: tuple[float, ...]
    radiant_w: tuple[float, ...]
    latent_w: tuple[float, ...]
    lost_w: tuple[float, ...]
    return_air_w: tuple[float, ...]
    unresolved_people_w: tuple[float, ...]


def resolve_internal_gains(
    use: UseSpec, *, reference_area_m2: float, calendar_year: int,
) -> InternalGainSeries:
    """Resolve supplied gain channels without weather, engine I/O or defaults.

    Requires the explicit partition policy. People fractions refer to sensible
    metabolic heat; equipment fractions refer to electrical input. A missing
    people sensible fraction leaves active metabolic heat in ``unresolved_people_w``.
    Consumers must handle or reject that channel rather than treating it as known.
    """
    if not math.isfinite(reference_area_m2) or reference_area_m2 <= 0:
        raise ValueError("reference_area_m2 must be finite and positive")
    config = use.gain_partitions
    if config is None or config.policy != "explicit":
        raise ValueError("Hourly gain resolution requires explicit gain partitions")

    def annual(schedule):
        return np.asarray(schedule.hourly(calendar_year), dtype=float)

    people = (reference_area_m2 * use.occupant_density_per_m2
              * annual(use.occupancy_fraction)
              * (annual(use.occupant_activity_schedule) if use.occupant_activity_schedule is not None
                 else use.occupant_activity_w))
    equipment = reference_area_m2 * use.equipment_gain_w_m2 * annual(use.equipment_fraction)
    lights = reference_area_m2 * use.lighting_gain_w_m2 * annual(use.lighting_fraction)
    channels = equipment_partition_fractions(use, calendar_year)
    unresolved = people if config.people_sensible_heat_fraction is None else np.zeros_like(people)
    sensible = (np.zeros_like(people) if config.people_sensible_heat_fraction is None
                else people * config.people_sensible_heat_fraction)
    convective = (sensible * (1 - config.people_fraction_radiant)
                  + equipment * channels["convective"]
                  + lights * (1 - config.lighting_fraction_radiant
                              - config.lighting_fraction_visible - config.lighting_return_air_fraction))
    radiant = (sensible * config.people_fraction_radiant + equipment * channels["radiant"]
               + lights * (config.lighting_fraction_radiant + config.lighting_fraction_visible))
    latent = equipment * channels["latent"] + people - sensible - unresolved
    return InternalGainSeries(*(tuple(float(value) for value in values) for values in (
        convective, radiant, latent, equipment * channels["lost"],
        lights * config.lighting_return_air_fraction, unresolved,
    )))


def equipment_partition_fractions(use: UseSpec, calendar_year: int) -> dict[str, list[float]]:
    """Return hourly radiant, latent, convective and lost shares of electrical input.

    The named legacy policy caps scheduled radiation at available heat. Explicit
    partitions have already been validated against the heat budget and are never
    capped. Fractions exclude the activity schedule; emission applies it once.
    """
    heat = (use.equipment_heat_fraction_schedule or
            use.equipment_fraction.constant(use.equipment_heat_fraction)).hourly(calendar_year)
    config = use.gain_partitions or GainPartitionSpec(policy="epsm_legacy_v1")
    if config.policy == "explicit":
        radiant = [config.equipment_fraction_radiant] * len(heat)
        latent = [config.equipment_fraction_latent] * len(heat)
    else:
        radiant = [min(.3, value) for value in heat]
        latent = [0.0] * len(heat)
    return {
        "radiant": radiant,
        "latent": latent,
        "convective": [max(0.0, h - r - latent_share) for h, r, latent_share in zip(heat, radiant, latent)],
        "lost": [1 - h for h in heat],
    }


def gain_partition_report(use: UseSpec, calendar_year: int) -> dict[str, object]:
    """Describe effective fractions and supplied, policy and engine-derived treatment.

    Equipment channel ranges describe the complete annual schedule; the source
    input retains its hourly values. People autocalculation has no invented
    numeric sensible or latent result.
    """
    config = use.gain_partitions or GainPartitionSpec(policy="epsm_legacy_v1")
    explicit = config.policy == "explicit"
    channels = equipment_partition_fractions(use, calendar_year)
    people_radiant = config.people_fraction_radiant if explicit else .3
    sensible = config.people_sensible_heat_fraction if explicit else None
    radiant = config.lighting_fraction_radiant if explicit else .3
    visible = config.lighting_fraction_visible if explicit else 0.0
    return_air = config.lighting_return_air_fraction if explicit else 0.0
    return {
        "policy": config.policy,
        "selection": "legacy_default" if use.gain_partitions is None else
                     "explicit" if explicit else "policy",
        "supplied_configuration": use.gain_partitions.model_dump(mode="json")
                                  if use.gain_partitions is not None else None,
        "people": {
            "fraction_radiant": people_radiant,
            "radiant_reference_basis": "sensible_heat",
            "sensible_heat_fraction": sensible,
            "sensible_heat_fraction_source": "engine_autocalculate" if sensible is None else "supplied",
            "latent_fraction": None if sensible is None else 1 - sensible,
            "latent_fraction_source": "engine_autocalculate" if sensible is None else "balance",
        },
        "equipment": {
            **{f"fraction_{name}": {"minimum": min(values), "maximum": max(values)}
               for name, values in channels.items()},
            "reference_basis": "electrical_input",
            "heat_fraction_source": use.equipment_heat_fraction_schedule.source
                                    if use.equipment_heat_fraction_schedule is not None else "scalar_input",
            "convective_treatment": "available_heat_minus_radiant_and_latent",
            "lost_treatment": "one_minus_available_heat",
        },
        "lighting": {
            "fraction_radiant": radiant,
            "fraction_visible": visible,
            "return_air_fraction": return_air,
            "fraction_convective": max(0.0, 1 - radiant - visible - return_air),
            "reference_basis": "lighting_input",
        },
    }
