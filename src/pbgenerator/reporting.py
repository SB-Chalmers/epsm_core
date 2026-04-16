"""EPC-comparable result reporting.

Compares simulation *delivered energy* against the EPC energiprestanda,
which per BEN (BFS 2016:12) equals:

    EP = (uppvärmning + tappvarmvatten + fastighetsel + komfortkyla) / Atemp

All values are normalårskorrigerade and expressed as delivered energy
(purchased DH + purchased electricity), **not** heating demand.

When EPC energy breakdown columns are available (FjvVV, Fastighet, etc.)
they are used directly instead of Sveby assumptions.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Typical COP for exhaust-air heat pumps (frånluftvärmepump) in Swedish MFH.
# Range 2.5–3.5; 3.0 is a conservative central estimate (BETSI, VVS-forum).
FVP_COP = 3.0


def _epc_heating_kwh(epc_energy: dict[str, int | None]) -> int:
    """Sum all EPC heating energy carriers (kWh, raw measured)."""
    keys = [
        "Fjv", "FjvUPPV", "Olja", "Gas",
        "ElVatten", "ElDirekt",
        "PumpMark", "PumpMarkUPPV",
        "PumpFranluft", "PumpFranluftUPPV",
        "PumpLuftLuft", "PumpLuftLuftUPPV",
        "PumpLuftVatten", "PumpLuftVattenUPPV",
    ]
    return sum(epc_energy.get(k) or 0 for k in keys)


def _epc_fvp_electricity(epc_energy: dict[str, int | None]) -> int:
    """Electricity consumed by exhaust-air heat pump (kWh)."""
    return epc_energy.get("PumpFranluftUPPV") or 0


def _normal_year_factor(
    epc_energy: dict[str, int | float | None],
    epc_atemp: float,
    energi_prestanda: int,
) -> float | None:
    """Derive the normal-year correction factor for heating.

    Uses the stored EgiNormKorrGD if available, otherwise back-calculates
    from the EPC energiprestanda:

        f = (EP × Atemp − FjvVV − VVBered − Fastighet) / Heating_raw

    Returns None if data is insufficient.
    """
    # 1) Use stored factor if available
    stored = epc_energy.get("NormKorrGD")
    if stored is not None and stored > 0:
        return float(stored)

    # 2) Back-calculate
    if not energi_prestanda or not epc_atemp:
        return None
    ep_total = energi_prestanda * epc_atemp
    dhw = (epc_energy.get("FjvVV") or 0) + (epc_energy.get("VVBered") or 0)
    fastig = epc_energy.get("Fastighet") or 0
    komfort = epc_energy.get("Komfort") or 0
    htg_raw = _epc_heating_kwh(epc_energy)
    if htg_raw <= 0:
        return None
    htg_corrected = ep_total - dhw - fastig - komfort
    if htg_corrected <= 0:
        return None
    return htg_corrected / htg_raw


def log_epc_comparison(
    results: dict[str, float],
    *,
    sim_atemp: float,
    epc_atemp: float,
    energi_prestanda: int,
    epc_energy: dict[str, int | None] | None = None,
    ventilation_system: str = "F",
    fgeo: float = 1.0,
    # Legacy fallbacks — used only when epc_energy is not provided
    fastighet_kwh: int = 0,
    dhw_vvc_kwh_m2: float = 0.0,
) -> dict[str, float]:
    """Compare simulation results to EPC delivered energy.

    The EPC energiprestanda is *delivered* energy (per Boverket BEN):
    purchased DH + purchased HP electricity + fastighetsel, per Atemp,
    normalårskorrigerad.

    The simulation gives heating *demand* (IdealLoads).  To make an
    apples-to-apples comparison:

    1. For FVP buildings the demand is converted to delivered energy
       by subtracting the free heat extracted from exhaust air.
    2. DHW is taken from the EPC measured DH-for-hot-water (FjvVV)
       instead of the simulated value, because VVC pipe losses are
       already included in the measured value.
    3. Fastighetsel comes from EPC metered data.
    4. Sveby airing add-on (4.0 × fgeo kWh/m²) is added because the
       simulation does not model vädring (window opening).

    Parameters
    ----------
    results : simulation results dict from runner.run().
    sim_atemp : simulated building Atemp (m²).
    epc_atemp : total Atemp from the EPC (m²).
    energi_prestanda : EPC energy performance (kWh/m²/yr).
    epc_energy : EPC energy breakdown from load_epc_energy().
        When provided, FjvVV and Fastighet are used directly.
    ventilation_system : "S", "F", "FT", "FTX", or "FVP".
    fgeo : Sveby geographic factor for airing add-on (default 1.0).
    """
    sim_heating = results["heating_kwh"]
    sim_cooling = results["cooling_kwh"]
    sim_dhw = results["dhw_kwh"]
    sim_site = results["site_kwh"]

    # ── EPC-measured values (preferred) vs Sveby fallbacks ──────────
    if epc_energy is not None:
        # DHW: use EPC measured DH for hot water (includes VVC losses).
        epc_dhw = (epc_energy.get("FjvVV") or 0) + (epc_energy.get("VVBered") or 0)
        # Scale to sim geometry: EPC DHW covers the whole property.
        dhw_used = epc_dhw * (sim_atemp / epc_atemp) if epc_atemp else 0.0
        dhw_source = "EPC FjvVV"

        # Fastighetsel
        epc_fastig = epc_energy.get("Fastighet") or 0
        bldg_svc = epc_fastig * (sim_atemp / epc_atemp) if epc_atemp else 0.0

        # FVP delivered-energy correction
        fvp_el = _epc_fvp_electricity(epc_energy)
    else:
        # Legacy path: simulated DHW + Sveby VVC add-on
        dhw_used = sim_dhw + dhw_vvc_kwh_m2 * sim_atemp
        dhw_source = "Sim+VVC"
        bldg_svc = fastighet_kwh * (sim_atemp / epc_atemp) if epc_atemp else 0.0
        fvp_el = 0

    # ── Heating: convert demand → delivered ─────────────────────────
    # FVP (frånluftvärmepump) is a *heating system*, not a ventilation type.
    # A building can have självdrag ventilation with a supplementary FVP.
    # Check for FVP presence via epc_energy, not ventilation_system.
    #   Heat output = COP × electricity
    #   Free heat   = (COP - 1) × electricity
    # The simulation gives the full demand (no FVP).  Delivered energy
    # = demand − free_heat.  The EPC counts HP_el as delivered,
    # so: delivered_heating = demand − (COP−1)×el.
    fvp_free_heat = 0.0
    if fvp_el > 0:
        fvp_free_heat = (FVP_COP - 1) * fvp_el
        # Scale to sim geometry
        fvp_free_heat *= (sim_atemp / epc_atemp) if epc_atemp else 1.0

    sim_delivered_heating = max(0.0, sim_heating - fvp_free_heat)

    sveby_airing = 4.0 * fgeo * sim_atemp

    # Include FVP electricity as delivered energy (it's purchased).
    fvp_el_scaled = fvp_el * (sim_atemp / epc_atemp) if epc_atemp and fvp_el else 0.0

    # ── Totals ──────────────────────────────────────────────────────
    # EPC-comparable = delivered heating + airing + DHW + fastighetsel + FVP_el
    # Cooling excluded — existing residential buildings have no active cooling.
    epc_total = (sim_delivered_heating + sveby_airing + dhw_used
                 + bldg_svc + fvp_el_scaled)
    ratio = (epc_total / sim_atemp / energi_prestanda) if energi_prestanda else 0.0

    # ── EPC side breakdown (for comparison) ─────────────────────────
    epc_htg_delivered = 0
    if epc_energy is not None:
        epc_htg_delivered = _epc_heating_kwh(epc_energy)

    # ── Logging ─────────────────────────────────────────────────────
    log.info("=== Simulation (delivered energy) ===")
    log.info("  Heating demand:    %7.0f kWh  (%5.1f kWh/m2)",
             sim_heating, sim_heating / sim_atemp)
    if fvp_free_heat > 0:
        log.info("  FVP free heat:    -%7.0f kWh  (-%4.1f kWh/m2)  [COP=%.1f]",
                 fvp_free_heat, fvp_free_heat / sim_atemp, FVP_COP)
        log.info("  FVP electricity:   %7.0f kWh  (%5.1f kWh/m2)",
                 fvp_el_scaled, fvp_el_scaled / sim_atemp)
    log.info("  Delivered heating: %7.0f kWh  (%5.1f kWh/m2)",
             sim_delivered_heating + fvp_el_scaled,
             (sim_delivered_heating + fvp_el_scaled) / sim_atemp)
    log.info("  Sveby airing:      %7.0f kWh  (%5.1f kWh/m2)",
             sveby_airing, sveby_airing / sim_atemp)
    log.info("  DHW (%s):     %7.0f kWh  (%5.1f kWh/m2)",
             dhw_source, dhw_used, dhw_used / sim_atemp)
    log.info("  Fastighetsel:      %7.0f kWh  (%5.1f kWh/m2)",
             bldg_svc, bldg_svc / sim_atemp)
    log.info("  ---")
    log.info("  Sim delivered:     %7.0f kWh  (%5.1f kWh/m2)",
             epc_total, epc_total / sim_atemp)

    if epc_energy is not None:
        log.info("")
        log.info("=== EPC measured (raw, not normalårskorrigerad) ===")
        log.info("  Heating delivered: %7d kWh  (%5.1f kWh/m2)",
                 epc_htg_delivered, epc_htg_delivered / epc_atemp)
        epc_dhw_val = (epc_energy.get("FjvVV") or 0) + (epc_energy.get("VVBered") or 0)
        log.info("  DHW (FjvVV):       %7d kWh  (%5.1f kWh/m2)",
                 epc_dhw_val, epc_dhw_val / epc_atemp)
        epc_fastig_val = epc_energy.get("Fastighet") or 0
        log.info("  Fastighetsel:      %7d kWh  (%5.1f kWh/m2)",
                 epc_fastig_val, epc_fastig_val / epc_atemp)
        summa2 = epc_energy.get("Summa2") or 0
        if summa2:
            log.info("  Total measured:    %7d kWh  (%5.1f kWh/m2)",
                     summa2, summa2 / epc_atemp)

        # Normal-year correction
        f_ny = _normal_year_factor(epc_energy, epc_atemp, energi_prestanda)
        if f_ny is not None:
            epc_htg_corrected = epc_htg_delivered * f_ny
            src = "EgiNormKorrGD" if epc_energy.get("NormKorrGD") else "back-calc"
            log.info("")
            log.info("=== Normal-year correction (%s) ===", src)
            log.info("  Factor:            %.3f  (measurement year was %.0f%% warmer)",
                     f_ny, (1 - 1 / f_ny) * 100)
            period_s = epc_energy.get("PeriodStart")
            period_e = epc_energy.get("PeriodEnd")
            if period_s and period_e:
                log.info("  Measurement period: %s – %s  (YYMM)", period_s, period_e)
            log.info("  Heating corrected: %7.0f kWh  (%5.1f kWh/m2)",
                     epc_htg_corrected, epc_htg_corrected / epc_atemp)
            epc_total_corr = epc_htg_corrected + epc_dhw_val + epc_fastig_val
            log.info("  EPC total (norm.): %7.0f kWh  (%5.1f kWh/m2)",
                     epc_total_corr, epc_total_corr / epc_atemp)
    else:
        f_ny = None

    log.info("")
    log.info("=== Comparison ===")
    log.info("  Sim delivered:     %5.1f kWh/m2  (Atemp=%.0f m2)",
             epc_total / sim_atemp, sim_atemp)
    log.info("  EPC energiprest:   %5d kWh/m2  (Atemp=%.0f m2, normalårskorr.)",
             energi_prestanda, epc_atemp)
    log.info("  Ratio (sim/EPC):   %.2f", ratio)
    if f_ny is not None and epc_atemp:
        summa2_val = epc_energy.get("Summa2") or 0 if epc_energy else 0
        if summa2_val:
            raw_ep = summa2_val / epc_atemp
            ratio_raw = (epc_total / sim_atemp) / raw_ep if raw_ep else 0
            log.info("  Ratio (sim/raw):   %.2f  (vs %.1f kWh/m2 un-corrected)",
                     ratio_raw, raw_ep)

    return {
        "sim_heating_demand_kwh": sim_heating,
        "sim_delivered_heating_kwh": sim_delivered_heating,
        "fvp_free_heat_kwh": fvp_free_heat,
        "fvp_el_kwh": fvp_el_scaled,
        "sveby_airing_kwh": sveby_airing,
        "dhw_kwh": dhw_used,
        "bldg_services_kwh": bldg_svc,
        "sim_cooling_kwh": sim_cooling,
        "epc_total_kwh": epc_total,
        "sim_site_kwh": sim_site,
        "epc_ratio": ratio,
        "normal_year_factor": f_ny,
    }
