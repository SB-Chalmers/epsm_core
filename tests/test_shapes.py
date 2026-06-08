"""Unit tests for parametric footprint shapes (:mod:`pbgenerator.shapes`).

No EnergyPlus required — these cover the generator geometry, validation, the
dict round-trip through :class:`Building`, and the flat shape columns.

Run with::

    PYTHONPATH=src python -m unittest discover -s tests
"""
from __future__ import annotations

import unittest

from pbgenerator import Building, FootprintShape, Location, WeatherSite, cmf_1960
from pbgenerator.serialize import flatten_run


def _signed_area(pts: list[list[float]]) -> float:
    n = len(pts)
    a = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


class TestFootprintShape(unittest.TestCase):
    def test_rectangle(self):
        s = FootprintShape.rectangle(20, 12)
        pts = s.footprint_pts()
        self.assertEqual(len(pts), 4)
        self.assertGreater(_signed_area(pts), 0.0)            # CCW winding
        self.assertAlmostEqual(abs(_signed_area(pts)), 240.0)

    def test_l_shape(self):
        s = FootprintShape.l_shape(30, 20, 12, 8)
        pts = s.footprint_pts()
        self.assertEqual(len(pts), 6)
        self.assertGreater(_signed_area(pts), 0.0)
        self.assertAlmostEqual(abs(_signed_area(pts)), 30 * 20 - 12 * 8)

    def test_u_shape(self):
        s = FootprintShape.u_shape(30, 20, 10, 8)
        pts = s.footprint_pts()
        self.assertEqual(len(pts), 8)
        self.assertGreater(_signed_area(pts), 0.0)
        self.assertAlmostEqual(abs(_signed_area(pts)), 30 * 20 - 10 * 8)

    def test_o_shape_reserved(self):
        s = FootprintShape.o_shape(30, 20, 10, 8)
        self.assertEqual(s.shape_type, "O")
        with self.assertRaises(NotImplementedError):
            s.footprint_pts()

    def test_validation(self):
        with self.assertRaises(ValueError):
            FootprintShape.l_shape(20, 12, 25, 8)        # cut_length >= length
        with self.assertRaises(ValueError):
            FootprintShape.u_shape(20, 12, 10, 15)       # cut_width >= width
        with self.assertRaises(ValueError):
            FootprintShape("rectangle", 20, 12, cut_length=5)  # rectangle takes no cut
        with self.assertRaises(ValueError):
            FootprintShape("hexagon", 20, 12)            # unknown type

    def test_round_trip_and_flat_columns(self):
        s = FootprintShape.l_shape(30, 18, 12, 8)
        loc = Location.hypothetical_site(
            city="X", centroid_lat=57.7, centroid_lon=11.9,
            weather=WeatherSite(epw_path="w.epw", station_name="t", wmo="0"),
        )
        b = Building(name="l", params=cmf_1960(4, "FTX"),
                     footprint_pts=s.footprint_pts(), location=loc, shape=s)
        # shape survives the dict round-trip
        b2 = Building.from_dict(b.to_dict(include_results=False))
        self.assertEqual(b2.shape, s)
        # and is surfaced as flat columns
        row = flatten_run(b)
        self.assertEqual(row["shape_type"], "L")
        self.assertAlmostEqual(row["shape_length_m"], 30.0)
        self.assertAlmostEqual(row["shape_width_m"], 18.0)
        self.assertAlmostEqual(row["shape_cut_length_m"], 12.0)
        self.assertAlmostEqual(row["shape_cut_width_m"], 8.0)


if __name__ == "__main__":
    unittest.main()
