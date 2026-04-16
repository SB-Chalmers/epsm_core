"""Test: simulate Building 1 of Fjällvägen 28 (ÄGIR 17) and compare to EPC."""
import logging
from pathlib import Path

from src.pbgenerator.epc_io import (
    load_footprints, load_epc_metadata, detect_ventilation_system,
    load_epc_energy, load_context_footprints,
)
from src.pbgenerator.archetypes import cmf_1960
from src.pbgenerator.runner import run
from src.pbgenerator.weather import nearest_epw
from src.pbgenerator.reporting import log_epc_comparison
from src.pbgenerator.idf_builder import context_shades_from_footprints

logging.basicConfig(level=logging.INFO, format="%(message)s")

EPC_FORMULAR_ID = 1033661  # Fjällvägen 28A, ÄGIR 17

# ---- 1. Load footprint geometry and EPC data ----
fp = load_footprints(fastighetsbeteckning="ÄGIR 17", husnummer=1)[0]
epc = load_epc_metadata(EPC_FORMULAR_ID)
vent_sys = detect_ventilation_system(EPC_FORMULAR_ID)
epc_energy = load_epc_energy(EPC_FORMULAR_ID)

floors = epc["num_floors"]
basement_floors = epc["num_basement_floors"]
sim_atemp = fp.footprint_area * (floors + basement_floors)

# ---- 2. Run simulation ----
params = cmf_1960(
    num_floors=floors,
    ventilation_system=vent_sys,
    num_basement_floors=basement_floors,
    cold_attic=True,
)

weather_file = nearest_epw(fp.centroid_lat, fp.centroid_lon)

# ---- Context shading from neighbouring buildings ----
ctx_fps = load_context_footprints(fp, radius_m=100)
origin_x = min(p[0] for p in fp.footprint_pts)
origin_y = min(p[1] for p in fp.footprint_pts)
ctx_shades = context_shades_from_footprints(ctx_fps, origin_x, origin_y)

results = run(
    name="fjallvagen28",
    footprint_pts=fp.footprint_pts,
    params=params,
    weather_file=weather_file,
    idf_dir=Path("idf"),
    output_dir=Path("results"),
    context_shades=ctx_shades,
)

# ---- 3. Compare ----
log_epc_comparison(
    results,
    sim_atemp=sim_atemp,
    epc_atemp=epc["atemp"],
    energi_prestanda=epc["energi_prestanda"],
    epc_energy=epc_energy,
    ventilation_system=vent_sys,
)
