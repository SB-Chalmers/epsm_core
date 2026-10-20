import numpy as np
import pytest

from epsm_core.compiler import EnergyPlusCompiler
from epsm_core.diagnostics import WarningRule, error_diagnostics
from epsm_core.scene import scene_data
from epsm_core.surface_checks import properties, vertices
from epsm_core.weather import hourly_axis


def test_diagnostics_recurring_and_rules(tmp_path):
    p = tmp_path / "test.err"
    p.write_text(
        " ** Warning ** Known notice\n ** Warning ** Known notice\n ** ~~~ ** This error occurred 17 total times;\n"
    )
    d = error_diagnostics(p)
    assert d["warning_count"] == 17 and not d["accepted"]
    rule = WarningRule(
        "fixture", "1", "24.2", "Known notice", "Verified fixture conditions", ("fixture",), 17
    )
    assert error_diagnostics(p, rules=(rule,), conditions=("fixture",))["accepted"]
    assert not error_diagnostics(p, rules=(rule,), conditions=())["accepted"]
    assert not error_diagnostics(p, rules=(rule,), conditions=("fixture",), engine_version="24.1")[
        "accepted"
    ]
    p.write_text(" ** Warning ** FixViewFactors: View factors not complete\n")
    broad = WarningRule(
        "fixture", "1", "24.2", ".*", "test always-fail categories", ("fixture",), 100
    )
    assert not error_diagnostics(p, rules=(broad,), conditions=("fixture",))["accepted"]
    assert not error_diagnostics(tmp_path / "missing.err")["accepted"]


@pytest.mark.parametrize("year,hours", [(2023, 8760), (2024, 8784), (2100, 8760), (2000, 8784)])
def test_calendar(year, hours, building):
    climate = building.climate.updated(calendar_year=year)
    axis = hourly_axis(year)
    assert len(axis) == climate.hours_in_year == hours
    assert np.all(np.diff(axis) == np.timedelta64(1, "h"))


def test_scene_opening_polygon_areas(building, energyplus):
    compiler = EnergyPlusCompiler(energyplus)
    model, report = compiler.compile(building)
    data = scene_data(model, report.data)
    for obj in data["objects"]:
        parent = model.get("BuildingSurface:Detailed", {}).get(obj["name"])
        if not parent:
            continue
        gross = properties(vertices(parent))[0]
        openings = sum(
            properties(vertices(o))[0]
            for o in model.get("FenestrationSurface:Detailed", {}).values()
            if o["building_surface_name"] == obj["name"]
        )
        assert obj["area_m2"] == pytest.approx(gross)
        assert obj["net_area_m2"] == pytest.approx(gross - openings)
        assert len(obj["holes"]) == sum(
            o["building_surface_name"] == obj["name"]
            for o in model.get("FenestrationSurface:Detailed", {}).values()
        )


@pytest.mark.parametrize("bad_column,bad_value", [("Hour", 1), ("Minute", 15), ("Interval", 30)])
def test_sql_calendar_rejects_invalid_intervals(building, tmp_path, bad_column, bad_value):
    import sqlite3
    from datetime import datetime, timedelta

    from epsm_core.results import read_results

    path = tmp_path / "calendar.sql"
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TABLE ReportDataDictionary (ReportDataDictionaryIndex INTEGER,Name TEXT,KeyValue TEXT,Units TEXT,ReportingFrequency TEXT,IsMeter INTEGER);
            CREATE TABLE EnvironmentPeriods (EnvironmentPeriodIndex INTEGER,EnvironmentType INTEGER);
            CREATE TABLE Time (TimeIndex INTEGER,Month INTEGER,Day INTEGER,Hour INTEGER,Minute INTEGER,Interval INTEGER,WarmupFlag INTEGER,EnvironmentPeriodIndex INTEGER);
            CREATE TABLE ReportData (ReportDataDictionaryIndex INTEGER,Value REAL,TimeIndex INTEGER);
            INSERT INTO ReportDataDictionary VALUES (1,'Fixture signal','Zone','J','Hourly',0);
            INSERT INTO EnvironmentPeriods VALUES (1,3);""")
        start = datetime(building.climate.calendar_year, 1, 1)
        rows = []
        for i in range(building.climate.hours_in_year):
            t = start + timedelta(hours=i)
            rows.append((i, t.month, t.day, t.hour + 1, 0, 60, 0, 1))
        db.executemany("INSERT INTO Time VALUES (?,?,?,?,?,?,?,?)", rows)
        db.executemany("INSERT INTO ReportData VALUES (1,0,?)", [(i,) for i in range(len(rows))])
        # Test fixture column is chosen only from the hard-coded parameterization above.
        db.execute(f"UPDATE Time SET {bad_column}=? WHERE TimeIndex=2", (bad_value,))
    with pytest.raises(ValueError, match="calendar hours"):
        read_results(path, building, None, {})


@pytest.mark.parametrize("message", [
    "DeterminePolygonOverlap: Too many figures [>10000000] detected in an overlap calculation.",
    "Too many vertices [>=15] in a shadow overlap",
])
def test_shadow_limits_cannot_be_waived(tmp_path,message):
    path=tmp_path/"shadow.err"
    path.write_text(" ** Warning ** "+message+"\n")
    rule=WarningRule("broad","1","24.2",".*","test",("test",),100)
    report=error_diagnostics(path,rules=(rule,),conditions=("test",))
    assert not report["accepted"]
    assert report["messages"][0]["category"]=="shadow_overlap_limit"
