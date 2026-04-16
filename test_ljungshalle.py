"""Test: simulate LJUNGS-HÄLLE 1:284 (Uddevalla, 1965) and compare to EPC."""
import logging
from pathlib import Path

from src.pbgenerator.epc_io import (
    load_footprints, load_epc_metadata, detect_ventilation_system,
)
from src.pbgenerator.archetypes import cmf_1960
from src.pbgenerator.runner import run
from src.pbgenerator.weather import nearest_epw
from src.pbgenerator.reporting import log_epc_comparison

logging.basicConfig(level=logging.INFO, format="%(message)s")

EPC_FORMULAR_ID = 1026468  # LJUNGS-HÄLLE 1:284, Uddevalla

# ---- 1. Load footprint geometry and EPC data ----
fp = load_footprints(fastighetsbeteckning="LJUNGS-HÄLLE 1:284", husnummer=2)[0]
epc = load_epc_metadata(EPC_FORMULAR_ID)
vent_sys = detect_ventilation_system(EPC_FORMULAR_ID)

floors = epc["num_floors"]
sim_atemp = fp.footprint_area * floors

# ---- 2. Run simulation ----
params = cmf_1960(
    num_floors=floors,
    ventilation_system=vent_sys,
)

weather_file = nearest_epw(fp.centroid_lat, fp.centroid_lon)

results = run(
    name="ljungshalle",
    footprint_pts=fp.footprint_pts,
    params=params,
    weather_file=weather_file,
    idf_dir=Path("idf"),
    output_dir=Path("results"),
)

# ---- 3. Compare ----
log_epc_comparison(
    results,
    sim_atemp=sim_atemp,
    epc_atemp=epc["atemp"],
    energi_prestanda=epc["energi_prestanda"],
    fastighet_kwh=epc["fastighet_kwh"] or 0,
)
