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

from .specs import GainPartitionSpec, UseSpec


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
