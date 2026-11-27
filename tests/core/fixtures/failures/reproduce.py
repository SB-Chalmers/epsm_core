"""Reproduce one anonymised EPSM stock-run failure (see issues #91-#95).

    python tests/core/fixtures/failures/reproduce.py <case.json.gz> <weather .epw> [run-dir]

Cases are anonymised BuildingSpecs: identifiers replaced, provenance removed, model frame
relative to the footprint centroid (no map coordinates). Geometry and shadow cases fail on
public OneBuilding TMYx weather (e.g. SWE_VG_Gothenburg-Landvetter.AP.025260_TMYx.2009-2023);
psychrometric cases need the actual-year weather named in their issue.

The case keeps its schedule year. The public EPW is re-dated to that year (29 Feb copied
from 28 Feb in a leap year) and bound to the spec before the run. Prints the failure code.
"""
import calendar
import gzip
import os
import shutil
import sys
from pathlib import Path

from epsm_core import EnergyPlusRunner
from epsm_core.specs import BuildingSpec
from epsm_core.weather import climate_from_epw

case, tmy = Path(sys.argv[1]), Path(sys.argv[2])
run = Path(sys.argv[3] if len(sys.argv) > 3 else "repro-run").resolve()
text = gzip.decompress(case.read_bytes()).decode() if case.suffix == ".gz" else case.read_text()
spec = BuildingSpec.model_validate_json(text)
year = spec.climate.calendar_year
lines = tmy.read_text().splitlines()
head, data = lines[:8], lines[8:]
out, feb28 = [], []
for row in data:
    f = row.split(",")
    f[0] = str(year)
    out.append(",".join(f))
    if calendar.isleap(year) and f[1] == "2" and f[2] == "28":
        feb28.append(f)
        if f[3] == "24":  # after the last hour of 28 Feb, add 29 Feb as a copy
            out += [",".join(g[:2] + ["29"] + g[3:]) for g in feb28]
first_day = calendar.day_name[calendar.weekday(year, 1, 1)]
head = [h if not h.startswith("DATA PERIODS") else f"DATA PERIODS,1,1,Data,{first_day},1/1,12/31" for h in head]
if calendar.isleap(year):
    head = [",".join(["HOLIDAYS/DAYLIGHT SAVINGS", "Yes"] + h.split(",")[2:]) if h.startswith("HOLIDAYS") else h for h in head]
run.parent.mkdir(parents=True, exist_ok=True)
weather = run.parent / f"{run.name}-weather-{year}.epw"
weather.write_text("\n".join(head + out) + "\n")
spec = spec.updated(climate=climate_from_epw(weather, calendar_year=year))
shutil.rmtree(run, ignore_errors=True)
try:
    r = EnergyPlusRunner(os.environ.get("ENERGYPLUS_EXE")).run(
        spec, run, timeout_seconds=int(os.environ.get("TIMEOUT", "3000"))
    )
    print("ACCEPTED", r.scalars.get("space_heating_demand_kwh"))
except Exception as e:
    print("FAILED", getattr(e, "code", type(e).__name__), str(e)[:400])
