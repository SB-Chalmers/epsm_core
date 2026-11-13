"""Self-draught exchange from a measured total air change.

A tracer-gas survey measures everything that enters a self-draught building, while
``natural_exchange_ach`` adds to envelope infiltration. The natural part of a measured
total is therefore what remains after this building's infiltration, which only Core can
state in conditioned-volume terms.
"""

from __future__ import annotations

from .specs.physics import AirflowSpec

MINIMUM_NATURAL_EXCHANGE_ACH = 0.05


def natural_exchange_for_total(total_ach, airflow, *, volume_m3, reference_area_m2=None):
    """Return the natural exchange that gives ``total_ach`` with this airflow's infiltration.

    Parameters
    ----------
    total_ach : float
        Measured total air change including envelope infiltration, in 1/h.
    airflow : AirflowSpec
        Airflow carrying the envelope infiltration.
    volume_m3 : float
        Conditioned volume the total refers to.
    reference_area_m2 : float, optional
        Load-reference area; required for area-based infiltration.

    Returns
    -------
    float
        Natural exchange in 1/h, at least ``MINIMUM_NATURAL_EXCHANGE_ACH``: a self-draught
        building keeps some stack flow however leaky its envelope assumption is.

    Raises
    ------
    ValueError
        If the total or volume is not positive, or area-based infiltration has no area.
    """
    if not isinstance(airflow, AirflowSpec):
        raise TypeError("airflow must be an AirflowSpec")
    if total_ach <= 0 or volume_m3 <= 0:
        raise ValueError("total_ach and volume_m3 must be positive")
    if airflow.envelope_infiltration_l_s_m2 is not None and reference_area_m2 is None:
        raise ValueError("Area-based infiltration requires reference_area_m2")
    infiltration = airflow.infiltration_design_flow_m3_s(
        reference_area_m2=reference_area_m2, volume_m3=volume_m3) * 3600 / volume_m3
    return max(total_ach - infiltration, MINIMUM_NATURAL_EXCHANGE_ACH)


def with_self_draught_total(spec, total_ach):
    """Return ``spec`` with its natural exchange set from a measured total air change.

    A building with any other topology has no natural exchange and returns unchanged, so
    a caller can apply a measured-use total without testing the installed system.
    """
    if spec.airflow.topology != "S":
        return spec
    natural = natural_exchange_for_total(
        total_ach, spec.airflow, volume_m3=spec.geometry.conditioned_volume_m3,
        reference_area_m2=spec.load_reference_area_m2)
    return spec.updated(airflow=spec.airflow.updated(natural_exchange_ach=natural))
