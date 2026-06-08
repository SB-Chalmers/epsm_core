"""Unit tests for serialisation (:mod:`pbgenerator.serialize`) and the
campaign store (:mod:`pbgenerator.store`).

These tests do **not** require EnergyPlus: a :class:`BuildingResults` is fed
synthetic hourly series so the dict/JSON round-trip and the DuckDB + Parquet
persistence are covered without a simulation.

Run with::

    PYTHONPATH=src python -m unittest discover -s tests
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pbgenerator import (
    Building,
    BuildingResults,
    Location,
    PVSystem,
    Quantity,
    SimStore,
    TimeSeries,
    WeatherSite,
    cmf_1960,
    compute_run_id,
)
from pbgenerator.results import _ZONE_TEMP_VAR
from pbgenerator.units import DEG_C, J, KWH

_SQUARE = [[0, 0], [20, 0], [20, 12], [0, 12]]
_HEAT_VAR = "Zone Ideal Loads Zone Total Heating Energy"


def _building(pv: bool = False) -> Building:
    weather = WeatherSite(epw_path="weather.epw", station_name="test", wmo="99999")
    loc = Location.hypothetical_site(
        city="Testville", centroid_lat=57.7, centroid_lon=11.9, weather=weather
    )
    system = PVSystem(dc_capacity_kw=12.0, tilt_deg=20.0) if pv else None
    return Building(name="demo", params=cmf_1960(4, "FTX"),
                    footprint_pts=_SQUARE, location=loc, pv=system)


def _with_results(b: Building) -> Building:
    res = BuildingResults(engine="energyplus")
    res.heating = Quantity(96000.0, KWH)
    res.cooling = Quantity(0.0, KWH)
    res.dhw = Quantity(12000.0, KWH)
    res.site_energy = Quantity(108000.0, KWH)
    res.hourly[f"{_ZONE_TEMP_VAR}::ZONE1"] = TimeSeries(
        [21.5] * 8760, DEG_C, name=_ZONE_TEMP_VAR, key="ZONE1"
    )
    res.hourly[f"{_HEAT_VAR}::ZONE1"] = TimeSeries(
        [10.0] * 8760, J, name=_HEAT_VAR, key="ZONE1"
    )
    res.compute_eui(960.0)
    res.build_monthly()
    b.results = res
    return b


class TestSerializationRoundTrip(unittest.TestCase):
    def test_building_inputs_round_trip(self):
        b = _building(pv=True)
        b2 = Building.from_dict(b.to_dict(include_results=False))
        self.assertEqual(b2.name, b.name)
        self.assertEqual(b2.params, b.params)
        self.assertEqual(b2.footprint_pts, b.footprint_pts)
        self.assertEqual(b2.location.city, "Testville")
        self.assertEqual(b2.location.weather.wmo, "99999")
        self.assertIsNotNone(b2.pv)
        self.assertEqual(b2.pv.dc_capacity_kw, 12.0)

    def test_json_round_trip_with_results(self):
        b = _with_results(_building())
        b2 = Building.from_json(b.to_json(include_timeseries=True))
        self.assertAlmostEqual(b2.results.heating.value, 96000.0)
        self.assertAlmostEqual(b2.results.heating_eui.value, 100.0)
        self.assertEqual(len(b2.results.hourly), 2)
        self.assertEqual(len(b2.results.hourly[f"{_ZONE_TEMP_VAR}::ZONE1"]), 8760)

    def test_run_id_is_input_only_and_stable(self):
        b = _building()
        rid_before = compute_run_id(b)
        _with_results(b)  # attaching results must not change the id
        self.assertEqual(compute_run_id(b), rid_before)
        # A changed input *does* change the id.
        b.params = cmf_1960(5, "FTX")
        self.assertNotEqual(compute_run_id(b), rid_before)


class TestSimStore(unittest.TestCase):
    def test_write_read_runs_and_timeseries(self):
        b = _with_results(_building())
        with tempfile.TemporaryDirectory() as tmp:
            store = SimStore(tmp)
            rid = store.write(b)
            self.assertTrue(store.has_run(rid))
            self.assertEqual(store.n_runs(), 1)

            runs = store.read_runs()
            self.assertEqual(len(runs), 1)
            row = runs.iloc[0]
            self.assertEqual(row["run_id"], rid)
            self.assertEqual(row["ventilation_system"], "FTX")
            self.assertEqual(int(row["num_floors"]), 4)
            self.assertAlmostEqual(float(row["heating_kwh"]), 96000.0)
            self.assertAlmostEqual(float(row["footprint_area_m2"]), 240.0)

            # Hourly series reconstruct exactly (float32 tolerance).
            ts = store.read_timeseries(rid)
            self.assertEqual(len(ts), 2)
            temp = ts[f"{_ZONE_TEMP_VAR}::ZONE1"]
            self.assertEqual(len(temp), 8760)
            self.assertAlmostEqual(temp.values[0], 21.5, places=4)

            # Full results reconstruct (hourly + monthly + scalar metrics).
            res = store.read_results(rid)
            self.assertEqual(len(res.hourly), 2)
            self.assertEqual(len(res.monthly), 2)
            self.assertAlmostEqual(res.heating.value, 96000.0)
            self.assertAlmostEqual(res.heating_eui.value, 100.0)
            store.close()

    def test_idempotent_rewrite(self):
        b = _with_results(_building())
        with tempfile.TemporaryDirectory() as tmp:
            store = SimStore(tmp)
            store.write(b)
            store.write(b)
            self.assertEqual(store.n_runs(), 1)
            store.close()

    def test_stage_is_db_free_and_picklable(self):
        import pickle

        b = _with_results(_building())
        with tempfile.TemporaryDirectory() as tmp:
            store = SimStore(tmp)
            # stage() writes the parquet partition and returns the flat row
            # without ever opening the DuckDB connection (worker-safe).
            row = store.stage(b)
            self.assertIn("run_id", row)
            self.assertIsNone(store._con)
            self.assertTrue(store.timeseries_path(row["run_id"]).exists())
            # The store pickles cleanly (no live connection crosses processes).
            store2 = pickle.loads(pickle.dumps(store))
            self.assertIsNone(store2._con)
            # Main process persists the staged row.
            store.upsert_run(row)
            self.assertEqual(store.n_runs(), 1)
            store.close()

    def test_has_run_on_empty_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SimStore(tmp)
            self.assertFalse(store.has_run("deadbeefdeadbeef"))
            self.assertEqual(store.n_runs(), 0)
            self.assertTrue(store.read_runs().empty)
            store.close()


class TestFeatureColumns(unittest.TestCase):
    def test_geometry_constructions_flags_weather(self):
        from pbgenerator.serialize import flatten_run

        row = flatten_run(_building())
        # derived geometry (square 20 x 12)
        self.assertAlmostEqual(row["bbox_length_m"], 20.0)
        self.assertAlmostEqual(row["bbox_breadth_m"], 12.0)
        self.assertAlmostEqual(row["bbox_aspect_ratio"], 20.0 / 12.0)
        self.assertAlmostEqual(row["perimeter_m"], 64.0)
        self.assertGreater(row["volume_m3"], 0.0)
        self.assertGreater(row["envelope_area_m2"], 0.0)
        self.assertGreater(row["compactness_av"], 0.0)
        for o in ("north", "east", "south", "west"):
            self.assertIn(f"wall_area_{o}_m2", row)
            self.assertIn(f"window_area_{o}_m2", row)
        # derived flags
        self.assertIn(row["has_basement"], (True, False))
        self.assertEqual(row["heated_attic"], True)
        self.assertEqual(row["window_openable"], False)
        # weather degrades to None for the fake EPW path
        self.assertIsNone(row["hdd_17c"])
        self.assertIsNone(row["cdd_22c"])
        # per-element U-values resolve from the real construction set
        self.assertIsInstance(row["u_ext_wall"], float)
        self.assertGreater(row["u_ext_wall"], 0.0)
        self.assertIsInstance(row["u_window"], float)
        # raw footprint always retained
        self.assertIn("footprint_json", row)

    def test_shape_columns_none_for_raw_footprint(self):
        from pbgenerator.serialize import flatten_run

        row = flatten_run(_building())
        self.assertIsNone(row["shape_type"])
        self.assertIsNone(row["shape_length_m"])
        self.assertIsNone(row["shape_cut_width_m"])


if __name__ == "__main__":
    unittest.main()
