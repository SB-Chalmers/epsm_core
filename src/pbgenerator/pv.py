"""Rooftop PV modelling via PVWatts V8 (PySAM).

A :class:`PVSystem` is an *installed asset* on a building — distinct from the
:class:`~pbgenerator.building_params.BuildingParams` simulation levers.  It
stores the nameplate design (DC capacity, tilt, azimuth, losses) and, once
evaluated, the production results (annual energy plus optional hourly/monthly
series with explicit units).

Evaluation uses NREL's PVWatts V8 model through the PySAM ``Pvwattsv8`` module.
PySAM is imported lazily so the rest of the package works without it installed;
calling :func:`evaluate_pv` without PySAM raises a clear error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .units import KWH, KW, WH, Quantity, TimeSeries


# PVWatts V8 module/array-type enumerations (see SAM docs).
ARRAY_FIXED_OPEN_RACK = 0
ARRAY_FIXED_ROOF_MOUNT = 1
ARRAY_1AXIS = 2
ARRAY_1AXIS_BACKTRACK = 3
ARRAY_2AXIS = 4

MODULE_STANDARD = 0
MODULE_PREMIUM = 1
MODULE_THIN_FILM = 2


@dataclass(frozen=True)
class PVResults:
    """Production results from a PVWatts V8 evaluation, with explicit units."""

    annual_energy: Quantity                 # kWh/yr
    capacity_factor: Quantity               # fraction (-)
    monthly_energy: TimeSeries | None = None  # 12 values, kWh
    hourly_ac: TimeSeries | None = None       # 8760 values, Wh (AC output)

    @property
    def annual_kwh(self) -> float:
        return self.annual_energy.value


@dataclass
class PVSystem:
    """A rooftop PV installation described in PVWatts V8 terms.

    Parameters
    ----------
    dc_capacity_kw:
        System nameplate DC capacity (``system_capacity``), kW.
    tilt_deg:
        Array tilt from horizontal, degrees.
    azimuth_deg:
        Array azimuth (180 = south in the northern hemisphere), degrees.
    array_type:
        PVWatts array type enum (see ``ARRAY_*`` constants).
    module_type:
        PVWatts module type enum (see ``MODULE_*`` constants).
    dc_ac_ratio:
        Inverter DC-to-AC sizing ratio.
    inv_efficiency_pct:
        Inverter efficiency, percent.
    system_losses_pct:
        Aggregate DC system losses, percent (PVWatts default ≈ 14.08).
    ground_coverage_ratio:
        GCR for tracking arrays.
    results:
        Populated by :func:`evaluate_pv`; ``None`` until evaluated.
    """

    dc_capacity_kw: float
    tilt_deg: float = 30.0
    azimuth_deg: float = 180.0
    array_type: int = ARRAY_FIXED_ROOF_MOUNT
    module_type: int = MODULE_STANDARD
    dc_ac_ratio: float = 1.15
    inv_efficiency_pct: float = 96.0
    system_losses_pct: float = 14.08
    ground_coverage_ratio: float = 0.4
    results: PVResults | None = None

    @property
    def capacity(self) -> Quantity:
        return Quantity(self.dc_capacity_kw, KW)


def evaluate_pv(
    pv: PVSystem,
    epw_path: str | Path,
    *,
    keep_hourly: bool = True,
) -> PVResults:
    """Run PVWatts V8 for ``pv`` against the EPW file and return PVResults.

    Parameters
    ----------
    pv:
        The :class:`PVSystem` to evaluate.
    epw_path:
        Path to the EnergyPlus/TMY weather file (PySAM reads EPW directly).
    keep_hourly:
        When ``True`` (default) the 8760-length AC output series is retained.

    Raises
    ------
    ImportError:
        If PySAM is not installed.
    """
    try:
        import PySAM.Pvwattsv8 as pvwatts  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover - depends on env
        raise ImportError(
            "PySAM is required for PV evaluation. Install with `pip install nrel-pysam`."
        ) from exc

    model = pvwatts.new()
    model.SolarResource.solar_resource_file = str(Path(epw_path).resolve())
    sd = model.SystemDesign
    sd.system_capacity = float(pv.dc_capacity_kw)
    sd.tilt = float(pv.tilt_deg)
    sd.azimuth = float(pv.azimuth_deg)
    sd.array_type = int(pv.array_type)
    sd.module_type = int(pv.module_type)
    sd.dc_ac_ratio = float(pv.dc_ac_ratio)
    sd.inv_eff = float(pv.inv_efficiency_pct)
    sd.losses = float(pv.system_losses_pct)
    sd.gcr = float(pv.ground_coverage_ratio)

    model.execute(0)

    out = model.Outputs
    annual = Quantity(float(out.annual_energy), KWH)
    cap_factor = Quantity(float(out.capacity_factor) / 100.0, "-")

    monthly = None
    monthly_vals = getattr(out, "monthly_energy", None)
    if monthly_vals is not None:
        monthly = TimeSeries(
            monthly_vals, KWH, "monthly", name="PV AC Energy", key="pv"
        )

    hourly = None
    if keep_hourly:
        ac = getattr(out, "ac", None)
        if ac is not None:
            hourly = TimeSeries(ac, WH, "hourly", name="PV AC Power", key="pv")

    results = PVResults(
        annual_energy=annual,
        capacity_factor=cap_factor,
        monthly_energy=monthly,
        hourly_ac=hourly,
    )
    pv.results = results
    return results


__all__ = [
    "PVSystem",
    "PVResults",
    "evaluate_pv",
    "ARRAY_FIXED_OPEN_RACK",
    "ARRAY_FIXED_ROOF_MOUNT",
    "ARRAY_1AXIS",
    "ARRAY_1AXIS_BACKTRACK",
    "ARRAY_2AXIS",
    "MODULE_STANDARD",
    "MODULE_PREMIUM",
    "MODULE_THIN_FILM",
]
