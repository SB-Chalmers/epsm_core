"""Unit tests for the redesigned Building aggregate and its domain layer.

These tests exercise the parts of the redesign that do **not** require a live
EnergyPlus run or a PySAM install:

* unit-aware containers (:mod:`pbgenerator.units`);
* aggregate construction and geometry (:class:`pbgenerator.building.Building`);
* typed result retrieval, including hourly zone temperatures and monthly
  aggregation (:class:`pbgenerator.results.BuildingResults`);
* rooftop PV evaluation with PVWatts V8 stubbed out;
* the dry-run CLI path (IDF generation only).

The full EnergyPlus simulation path is validated separately (it needs the
EnergyPlus binary); here we feed :class:`BuildingResults` synthetic series so
the typed-results contract is still covered without a simulation.

Run with::

    PYTHONPATH=src python -m unittest discover -s tests
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

from pbgenerator import (
    Building,
    BuildingResults,
    Location,
    PVSystem,
    Quantity,
    TimeSeries,
    WeatherSite,
    cmf_1960,
    evaluate_pv,
)
from pbgenerator.results import _ZONE_TEMP_VAR
from pbgenerator.units import DEG_C, J, KWH, KWH_PER_M2

_SQUARE = [[0, 0], [20, 0], [20, 12], [0, 12]]


class TestUnits(unittest.TestCase):
    def test_quantity_conversion_and_str(self):
        gj = Quantity(3.6, "GJ")
        kwh = gj.to(KWH, 277.7777777778)
        self.assertAlmostEqual(kwh.value, 1000.0, places=3)
        self.assertEqual(kwh.unit, KWH)
        self.assertEqual(str(Quantity(145.2, KWH_PER_M2)), "145.2 kWh/m2")

    def test_timeseries_stats(self):
        ts = TimeSeries([1.0, 2.0, 3.0, 4.0], DEG_C, name="t")
        self.assertEqual(len(ts), 4)
        self.assertEqual(ts.total, 10.0)
        self.assertEqual(ts.mean, 2.5)
        self.assertEqual(ts.minimum, 1.0)
        self.assertEqual(ts.maximum, 4.0)

    def test_monthly_sum_and_mean(self):
        energy = TimeSeries([1.0] * 8760, J, name="e")
        monthly = energy.to_monthly()
        self.assertEqual(len(monthly), 12)
        self.assertEqual(monthly.total, 8760.0)  # sums preserve total
        self.assertEqual(monthly.values[0], 744.0)  # January has 744 hours

        temps = TimeSeries([20.0] * 8760, DEG_C, name="t")
        monthly_mean = temps.to_monthly_mean()
        self.assertEqual(len(monthly_mean), 12)
        self.assertTrue(all(abs(v - 20.0) < 1e-9 for v in monthly_mean.values))

    def test_monthly_requires_hourly_8760(self):
        with self.assertRaises(ValueError):
            TimeSeries([1.0, 2.0], J).to_monthly()


class TestAggregateConstruction(unittest.TestCase):
    def _building(self) -> Building:
        weather = WeatherSite(epw_path="weather.epw", station_name="test")
        loc = Location.hypothetical_site(_SQUARE, city="Testville", weather=weather)
        return Building(name="demo", params=cmf_1960(4, "FTX"), location=loc)

    def test_retains_params_location_weather(self):
        b = self._building()
        self.assertEqual(b.name, "demo")
        self.assertEqual(b.params.ventilation_system, "FTX")
        self.assertEqual(b.params.num_floors, 4)
        self.assertTrue(b.location.hypothetical)
        self.assertEqual(b.location.city, "Testville")
        self.assertEqual(Path(b.location.epw_path).name, "weather.epw")
        self.assertEqual(b.footprint_pts, [[float(x), float(y)] for x, y in _SQUARE])

    def test_footprint_area_shoelace(self):
        b = self._building()
        self.assertAlmostEqual(b.location.footprint_area_m2, 240.0)

    def test_build_model_populates_geometry(self):
        b = self._building()
        model = b.build_model()
        self.assertIsNotNone(model)
        self.assertIsNotNone(b.honeybee_model)
        self.assertIsNotNone(b.rooms)
        # 20x12 footprint, 4 floors -> 960 m2 heated area.
        self.assertAlmostEqual(b.heated_floor_area_m2, 960.0, places=1)

    def test_heated_area_none_before_build(self):
        self.assertIsNone(self._building().heated_floor_area_m2)


class TestTypedResults(unittest.TestCase):
    def _results(self) -> BuildingResults:
        res = BuildingResults(engine="energyplus")
        res.heating = Quantity(96000.0, KWH)
        res.cooling = Quantity(0.0, KWH)
        res.site_energy = Quantity(108000.0, KWH)
        # Two synthetic hourly series: a zone temperature and a heating flux.
        res.hourly["%s::ZONE1" % _ZONE_TEMP_VAR] = TimeSeries(
            [21.5] * 8760, DEG_C, name=_ZONE_TEMP_VAR, key="ZONE1"
        )
        res.hourly["Zone Ideal Loads Zone Total Heating Energy::ZONE1"] = TimeSeries(
            [10.0] * 8760, J, name="Zone Ideal Loads Zone Total Heating Energy", key="ZONE1"
        )
        res.compute_eui(540.0)
        res.build_monthly()
        return res

    def test_eui_computed_with_units(self):
        res = self._results()
        self.assertEqual(res.atemp_m2, 540.0)
        self.assertEqual(res.site_eui.unit, KWH_PER_M2)
        self.assertAlmostEqual(res.site_eui.value, 200.0)

    def test_zone_temperatures_retrieved(self):
        res = self._results()
        zt = res.zone_temperatures()
        self.assertIn("ZONE1", zt)
        self.assertEqual(zt["ZONE1"].unit, DEG_C)
        self.assertEqual(len(zt["ZONE1"]), 8760)
        self.assertAlmostEqual(zt["ZONE1"].mean, 21.5)

    def test_variable_lookup(self):
        res = self._results()
        htg = res.variable("Zone Ideal Loads Zone Total Heating Energy")
        self.assertIsNotNone(htg)
        self.assertEqual(htg.unit, J)

    def test_monthly_aggregation(self):
        res = self._results()
        # Energy series are summed; temperature series are averaged.
        htg_key = "Zone Ideal Loads Zone Total Heating Energy::ZONE1"
        temp_key = "%s::ZONE1" % _ZONE_TEMP_VAR
        self.assertEqual(len(res.monthly[htg_key]), 12)
        self.assertEqual(res.monthly[htg_key].values[0], 744 * 10.0)  # Jan sum
        self.assertAlmostEqual(res.monthly[temp_key].values[0], 21.5)  # Jan mean

    def test_as_dict_backwards_compat(self):
        res = self._results()
        d = res.as_dict()
        self.assertEqual(
            set(d), {"heating_kwh", "cooling_kwh", "dhw_kwh", "site_kwh"}
        )
        self.assertAlmostEqual(d["heating_kwh"], 96000.0)


class TestFriendlyAccessors(unittest.TestCase):
    """Keyless, autocomplete-friendly access to time series."""

    def _results(self) -> BuildingResults:
        res = BuildingResults(engine="energyplus")
        # Two floors, one zone each.
        for floor in (1, 2):
            zone = "FLOOR%d_ROOM_ABC_DEMO" % floor
            res.hourly["%s::%s" % (_ZONE_TEMP_VAR, zone)] = TimeSeries(
                [20.0 + floor] * 8760, DEG_C, name=_ZONE_TEMP_VAR, key=zone
            )
            res.hourly["Zone Lights Total Heating Energy::%s" % zone] = TimeSeries(
                [5.0] * 8760, J, name="Zone Lights Total Heating Energy", key=zone
            )
        return res

    def test_building_level_signal(self):
        res = self._results()
        # Lighting is an energy flux -> summed across the two zones.
        self.assertEqual(res.lighting.hourly.values[0], 10.0)
        self.assertEqual(res.lighting.unit, J)
        self.assertEqual(len(res.lighting.monthly), 12)
        # Annual energy is reported in kWh.
        self.assertEqual(res.lighting.annual.unit, KWH)
        self.assertAlmostEqual(res.lighting.annual.value, 10.0 * 8760 / 3.6e6)

    def test_building_temperature_is_averaged(self):
        res = self._results()
        # Two zones at 21 and 22 -> building mean 21.5.
        self.assertAlmostEqual(res.air_temperature.hourly.values[0], 21.5)
        self.assertAlmostEqual(res.air_temperature.annual.value, 21.5)
        self.assertEqual(res.air_temperature.annual.unit, DEG_C)

    def test_missing_variable_returns_none(self):
        res = self._results()
        self.assertIsNone(res.cooling_load)  # not in the synthetic data

    def test_available_lists_present_signals(self):
        res = self._results()
        self.assertIn("lighting", res.available())
        self.assertIn("air_temperature", res.available())
        self.assertNotIn("cooling_load", res.available())

    def test_zone_access_by_index_and_name(self):
        res = self._results()
        self.assertEqual(len(res.zones), 2)
        z0 = res.zones[0]
        self.assertEqual(z0.floor, 1)
        self.assertAlmostEqual(z0.air_temperature.hourly.values[0], 21.0)
        by_name = res.zones["FLOOR2_ROOM_ABC_DEMO"]
        self.assertAlmostEqual(by_name.air_temperature.hourly.values[0], 22.0)

    def test_floor_navigation(self):
        res = self._results()
        self.assertEqual(len(res.floors), 2)
        floor1 = res.floors[0]
        self.assertEqual(floor1.number, 1)
        self.assertEqual(len(floor1.zones), 1)
        # Floor aggregate of a single zone equals that zone.
        self.assertAlmostEqual(
            floor1.zones[0].air_temperature.hourly.values[0], 21.0
        )
        self.assertAlmostEqual(floor1.air_temperature.hourly.values[0], 21.0)


class TestPVStubbed(unittest.TestCase):
    """Evaluate PV with a fake PySAM.Pvwattsv8 module injected into sys.modules."""

    def setUp(self):
        self._saved = sys.modules.get("PySAM.Pvwattsv8")
        fake = types.ModuleType("PySAM.Pvwattsv8")

        class _Group:
            pass

        class _Model:
            def __init__(self):
                self.SolarResource = _Group()
                self.SystemDesign = _Group()
                self.Outputs = _Group()

            def execute(self, _verbosity):
                self.Outputs.annual_energy = 12000.0
                self.Outputs.capacity_factor = 11.4  # percent
                self.Outputs.monthly_energy = [1000.0] * 12
                self.Outputs.ac = [1.0] * 8760

        fake.new = lambda: _Model()
        # Ensure the parent package exists for the "import PySAM.Pvwattsv8" path.
        sys.modules.setdefault("PySAM", types.ModuleType("PySAM"))
        sys.modules["PySAM.Pvwattsv8"] = fake

    def tearDown(self):
        if self._saved is not None:
            sys.modules["PySAM.Pvwattsv8"] = self._saved
        else:
            sys.modules.pop("PySAM.Pvwattsv8", None)

    def test_evaluate_pv_populates_results(self):
        pv = PVSystem(dc_capacity_kw=10.0, tilt_deg=30, azimuth_deg=180)
        res = evaluate_pv(pv, "weather.epw", keep_hourly=True)
        self.assertEqual(res.annual_kwh, 12000.0)
        self.assertEqual(res.annual_energy.unit, KWH)
        self.assertAlmostEqual(res.capacity_factor.value, 0.114)  # converted from %
        self.assertIsNotNone(res.monthly_energy)
        self.assertEqual(len(res.monthly_energy), 12)
        self.assertIsNotNone(res.hourly_ac)
        self.assertEqual(len(res.hourly_ac), 8760)
        # Result is retained on the system object.
        self.assertIs(pv.results, res)


class TestDryRunCLI(unittest.TestCase):
    def test_build_from_config_and_write_idf(self):
        import json
        import tempfile

        from pbgenerator.building_params import load_config
        from pbgenerator.cli import build_from_config

        tmp = Path(tempfile.mkdtemp())
        cfg_path = tmp / "config.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "footprint_pts": _SQUARE,
                    "building": {"num_floors": 2, "ventilation_system": "F"},
                    "weather_file": "weather.epw",
                    "idf_dir": str(tmp / "idf"),
                    "output_dir": str(tmp / "out"),
                }
            )
        )
        cfg = load_config(cfg_path)
        building = build_from_config(cfg, "demo")
        self.assertEqual(building.name, "demo")
        self.assertEqual(building.params.num_floors, 2)

        idf_path = tmp / "idf" / "in.idf"
        idf_path.parent.mkdir(parents=True, exist_ok=True)
        building.write_idf(idf_path)
        self.assertTrue(idf_path.exists())
        self.assertGreater(idf_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
