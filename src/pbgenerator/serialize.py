"""Pure dict / JSON serialisation for the domain objects.

Every :class:`~pbgenerator.building.Building` and its parts round-trips through
plain Python ``dict`` (and therefore JSON) with no honeybee or EnergyPlus
objects involved.  This is the foundation for :mod:`pbgenerator.store`, which
persists large simulation campaigns, and for any caching / reproducibility
workflow.

Two flavours of output are provided:

* **structured** (``*_to_dict`` / ``*_from_dict``) — a faithful, nested,
  fully reversible representation.  Use for archiving a single building and
  rebuilding it later (``Building.from_dict(b.to_dict())``).
* **flat** (``flatten_run``) — a single one-level ``dict`` of scalars suitable
  for one row of a columnar table (the ``runs`` table consumed by ML).  Time
  series are *not* included here; they are stored separately as Parquet.

Schema version is stamped on every structured payload so future format changes
stay detectable.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .building_params import BuildingParams, FacadeWWR
from .location import EPCSource, Location, WeatherSite
from .pv import PVResults, PVSystem
from .results import BuildingResults
from .shapes import FootprintShape
from .units import Quantity, TimeSeries

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .building import Building

SCHEMA_VERSION = 1

# Degree-day base temperatures (°C) for the weather features.
HDD_BASE_C = 17.0
CDD_BASE_C = 22.0


# ---------------------------------------------------------------------------
# Quantity / TimeSeries
# ---------------------------------------------------------------------------

def quantity_to_dict(q: Quantity | None) -> dict | None:
    if q is None:
        return None
    return {"value": q.value, "unit": q.unit}


def quantity_from_dict(d: dict | None) -> Quantity | None:
    if d is None:
        return None
    return Quantity(d["value"], d["unit"])


def timeseries_to_dict(ts: TimeSeries | None) -> dict | None:
    if ts is None:
        return None
    return {
        "values": list(ts.values),
        "unit": ts.unit,
        "timestep": ts.timestep,
        "name": ts.name,
        "key": ts.key,
    }


def timeseries_from_dict(d: dict | None) -> TimeSeries | None:
    if d is None:
        return None
    return TimeSeries(
        d["values"],
        d["unit"],
        d.get("timestep", "hourly"),
        d.get("name", ""),
        d.get("key", ""),
    )


# ---------------------------------------------------------------------------
# BuildingParams
# ---------------------------------------------------------------------------

def params_to_dict(p: BuildingParams) -> dict:
    """Fully reversible dict for :class:`BuildingParams` (nested ``wwr``)."""
    return asdict(p)


def params_from_dict(d: dict) -> BuildingParams:
    d = dict(d)
    wwr = d.pop("wwr")
    if isinstance(wwr, dict):
        wwr = FacadeWWR(**wwr)
    return BuildingParams(wwr=wwr, **d)


# ---------------------------------------------------------------------------
# Location / WeatherSite / EPCSource
# ---------------------------------------------------------------------------

def weather_to_dict(w: WeatherSite | None) -> dict | None:
    if w is None:
        return None
    return {
        "epw_path": str(w.epw_path),
        "station_name": w.station_name,
        "wmo": w.wmo,
        "station_lat": w.station_lat,
        "station_lon": w.station_lon,
        "period": w.period,
        "distance_km": w.distance_km,
    }


def weather_from_dict(d: dict | None) -> WeatherSite | None:
    if d is None:
        return None
    return WeatherSite(
        epw_path=Path(d["epw_path"]),
        station_name=d.get("station_name", ""),
        wmo=d.get("wmo", ""),
        station_lat=d.get("station_lat"),
        station_lon=d.get("station_lon"),
        period=d.get("period", ""),
        distance_km=d.get("distance_km"),
    )


def epc_to_dict(e: EPCSource | None) -> dict | None:
    if e is None:
        return None
    return asdict(e)


def epc_from_dict(d: dict | None) -> EPCSource | None:
    if d is None:
        return None
    return EPCSource(**d)


def location_to_dict(loc: Location) -> dict:
    return {
        "centroid_lat": loc.centroid_lat,
        "centroid_lon": loc.centroid_lon,
        "city": loc.city,
        "hypothetical": loc.hypothetical,
        "weather": weather_to_dict(loc.weather),
        "epc": epc_to_dict(loc.epc),
    }


def location_from_dict(d: dict) -> Location:
    return Location(
        centroid_lat=d.get("centroid_lat"),
        centroid_lon=d.get("centroid_lon"),
        city=d.get("city", ""),
        hypothetical=d.get("hypothetical", False),
        weather=weather_from_dict(d.get("weather")),
        epc=epc_from_dict(d.get("epc")),
    )


# ---------------------------------------------------------------------------
# FootprintShape (authoring provenance)
# ---------------------------------------------------------------------------

def shape_to_dict(s: FootprintShape | None) -> dict | None:
    if s is None:
        return None
    return {
        "shape_type": s.shape_type,
        "length": s.length,
        "width": s.width,
        "cut_length": s.cut_length,
        "cut_width": s.cut_width,
    }


def shape_from_dict(d: dict | None) -> FootprintShape | None:
    if d is None:
        return None
    return FootprintShape(
        shape_type=d["shape_type"],
        length=d["length"],
        width=d["width"],
        cut_length=d.get("cut_length", 0.0),
        cut_width=d.get("cut_width", 0.0),
    )


# ---------------------------------------------------------------------------
# PV
# ---------------------------------------------------------------------------

def pvresults_to_dict(r: PVResults | None, *, include_timeseries: bool = True) -> dict | None:
    if r is None:
        return None
    out = {
        "annual_energy": quantity_to_dict(r.annual_energy),
        "capacity_factor": quantity_to_dict(r.capacity_factor),
        "monthly_energy": timeseries_to_dict(r.monthly_energy),
    }
    if include_timeseries:
        out["hourly_ac"] = timeseries_to_dict(r.hourly_ac)
    return out


def pvresults_from_dict(d: dict | None) -> PVResults | None:
    if d is None:
        return None
    return PVResults(
        annual_energy=quantity_from_dict(d["annual_energy"]),
        capacity_factor=quantity_from_dict(d["capacity_factor"]),
        monthly_energy=timeseries_from_dict(d.get("monthly_energy")),
        hourly_ac=timeseries_from_dict(d.get("hourly_ac")),
    )


def pvsystem_to_dict(pv: PVSystem | None, *, include_results: bool = True,
                     include_timeseries: bool = True) -> dict | None:
    if pv is None:
        return None
    out = {
        "dc_capacity_kw": pv.dc_capacity_kw,
        "tilt_deg": pv.tilt_deg,
        "azimuth_deg": pv.azimuth_deg,
        "array_type": pv.array_type,
        "module_type": pv.module_type,
        "dc_ac_ratio": pv.dc_ac_ratio,
        "inv_efficiency_pct": pv.inv_efficiency_pct,
        "system_losses_pct": pv.system_losses_pct,
        "ground_coverage_ratio": pv.ground_coverage_ratio,
    }
    if include_results:
        out["results"] = pvresults_to_dict(pv.results, include_timeseries=include_timeseries)
    return out


def pvsystem_from_dict(d: dict | None) -> PVSystem | None:
    if d is None:
        return None
    d = dict(d)
    results = pvresults_from_dict(d.pop("results", None))
    pv = PVSystem(**d)
    pv.results = results
    return pv


# ---------------------------------------------------------------------------
# BuildingResults
# ---------------------------------------------------------------------------

def results_to_dict(res: BuildingResults | None, *, include_timeseries: bool = False) -> dict | None:
    """Serialise results.

    By default only the scalar metrics (+ monthly aggregates) are emitted; the
    full hourly store is large and lives in Parquet, so pass
    ``include_timeseries=True`` only for small/standalone archives.
    """
    if res is None:
        return None
    out: dict[str, Any] = {
        "engine": res.engine,
        "heating": quantity_to_dict(res.heating),
        "cooling": quantity_to_dict(res.cooling),
        "dhw": quantity_to_dict(res.dhw),
        "site_energy": quantity_to_dict(res.site_energy),
        "heating_eui": quantity_to_dict(res.heating_eui),
        "cooling_eui": quantity_to_dict(res.cooling_eui),
        "site_eui": quantity_to_dict(res.site_eui),
        "atemp_m2": res.atemp_m2,
        "epc_comparison": res.epc_comparison,
        "pv": pvresults_to_dict(res.pv, include_timeseries=include_timeseries)
        if isinstance(res.pv, PVResults) else None,
        "artifacts": dict(res.artifacts),
        "monthly": {k: timeseries_to_dict(ts) for k, ts in res.monthly.items()},
    }
    if include_timeseries:
        out["hourly"] = {k: timeseries_to_dict(ts) for k, ts in res.hourly.items()}
    return out


def results_from_dict(d: dict | None) -> BuildingResults | None:
    if d is None:
        return None
    res = BuildingResults(engine=d.get("engine", "energyplus"))
    res.heating = quantity_from_dict(d.get("heating")) or res.heating
    res.cooling = quantity_from_dict(d.get("cooling")) or res.cooling
    res.dhw = quantity_from_dict(d.get("dhw")) or res.dhw
    res.site_energy = quantity_from_dict(d.get("site_energy")) or res.site_energy
    res.heating_eui = quantity_from_dict(d.get("heating_eui"))
    res.cooling_eui = quantity_from_dict(d.get("cooling_eui"))
    res.site_eui = quantity_from_dict(d.get("site_eui"))
    res.atemp_m2 = d.get("atemp_m2")
    res.epc_comparison = d.get("epc_comparison")
    res.pv = pvresults_from_dict(d.get("pv"))
    res.artifacts = dict(d.get("artifacts", {}))
    res.monthly = {
        k: timeseries_from_dict(v) for k, v in (d.get("monthly") or {}).items()
    }
    res.hourly = {
        k: timeseries_from_dict(v) for k, v in (d.get("hourly") or {}).items()
    }
    return res


# ---------------------------------------------------------------------------
# Building (top-level aggregate)
# ---------------------------------------------------------------------------

def building_to_dict(
    b: "Building",
    *,
    include_results: bool = True,
    include_timeseries: bool = False,
) -> dict:
    """Fully reversible dict for a :class:`Building`.

    ``include_results=False`` yields the pure *input* description (identity +
    params + footprint + location + PV design) — this is what defines a run and
    is hashed to form a stable ``run_id``.
    """
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "name": b.name,
        "params": params_to_dict(b.params),
        "footprint_pts": [[float(x), float(y)] for x, y in b.footprint_pts],
        "location": location_to_dict(b.location),
        "shape": shape_to_dict(b.shape),
        "pv": pvsystem_to_dict(
            b.pv, include_results=include_results, include_timeseries=include_timeseries
        ),
    }
    if include_results:
        out["results"] = results_to_dict(b.results, include_timeseries=include_timeseries)
    return out


def building_from_dict(d: dict) -> "Building":
    from .building import Building

    b = Building(
        name=d["name"],
        params=params_from_dict(d["params"]),
        footprint_pts=[list(pt) for pt in d["footprint_pts"]],
        location=location_from_dict(d["location"]),
        pv=pvsystem_from_dict(d.get("pv")),
        shape=shape_from_dict(d.get("shape")),
    )
    b.results = results_from_dict(d.get("results"))
    return b


# ---------------------------------------------------------------------------
# JSON convenience
# ---------------------------------------------------------------------------

def to_json(d: dict, *, indent: int | None = None) -> str:
    return json.dumps(d, default=str, indent=indent)


def from_json(text: str) -> dict:
    return json.loads(text)


# ---------------------------------------------------------------------------
# Flat run row (one columnar record per simulation)
# ---------------------------------------------------------------------------

def _q(q: Quantity | None) -> float | None:
    return q.value if q is not None else None


@lru_cache(maxsize=None)
def _degree_days(epw_path: str | None,
                 hdd_base: float = HDD_BASE_C,
                 cdd_base: float = CDD_BASE_C) -> tuple[float | None, float | None]:
    """Annual heating/cooling degree-days from an EPW (``None`` if unreadable).

    Cached per EPW path so a campaign reusing a handful of weather files only
    parses each one once per process.
    """
    if not epw_path:
        return (None, None)
    try:
        from ladybug.epw import EPW

        temps = EPW(epw_path).dry_bulb_temperature.values
    except Exception:
        return (None, None)
    hdd = sum(max(hdd_base - t, 0.0) for t in temps) / 24.0
    cdd = sum(max(t - cdd_base, 0.0) for t in temps) / 24.0
    return (round(hdd, 1), round(cdd, 1))


def flatten_params(p: BuildingParams) -> dict:
    """Flatten params to scalar columns (``wwr`` expanded to four columns)."""
    d = asdict(p)
    wwr = d.pop("wwr")
    for side, v in wwr.items():
        d[f"wwr_{side}"] = v
    return d


def flatten_location(loc: Location) -> dict:
    w, e = loc.weather, loc.epc
    hdd, cdd = _degree_days(str(w.epw_path)) if w else (None, None)
    out = {
        "loc_city": loc.city,
        "loc_lat": loc.centroid_lat,
        "loc_lon": loc.centroid_lon,
        "loc_hypothetical": loc.hypothetical,
        "weather_epw": str(w.epw_path) if w else None,
        "weather_station": w.station_name if w else None,
        "weather_wmo": w.wmo if w else None,
        "weather_period": w.period if w else None,
        "hdd_17c": hdd,
        "cdd_22c": cdd,
    }
    if e is not None:
        out.update({
            "epc_objektidentitet": e.objektidentitet,
            "epc_formular_id": e.formular_id,
            "epc_kommun": e.kommun,
            "epc_construction_year": e.construction_year,
            "epc_atemp_m2": e.atemp_epc_m2,
            "epc_energi_prestanda": e.energi_prestanda,
            "epc_fastighet_kwh": e.fastighet_kwh,
        })
    return out


def flatten_pv(pv: PVSystem | None) -> dict:
    if pv is None:
        return {"pv_installed": False}
    out = {
        "pv_installed": True,
        "pv_dc_capacity_kw": pv.dc_capacity_kw,
        "pv_tilt_deg": pv.tilt_deg,
        "pv_azimuth_deg": pv.azimuth_deg,
        "pv_array_type": pv.array_type,
        "pv_module_type": pv.module_type,
    }
    if isinstance(pv.results, PVResults):
        out["pv_annual_kwh"] = _q(pv.results.annual_energy)
        out["pv_capacity_factor"] = _q(pv.results.capacity_factor)
    return out


def flatten_results(res: BuildingResults | None) -> dict:
    if res is None:
        return {}
    out = {
        "engine": res.engine,
        "heating_kwh": _q(res.heating),
        "cooling_kwh": _q(res.cooling),
        "dhw_kwh": _q(res.dhw),
        "site_kwh": _q(res.site_energy),
        "heating_eui": _q(res.heating_eui),
        "cooling_eui": _q(res.cooling_eui),
        "site_eui": _q(res.site_eui),
        "atemp_m2": res.atemp_m2,
        "n_signals": len(res.hourly),
    }
    if isinstance(res.pv, PVResults):
        out["pv_annual_kwh"] = _q(res.pv.annual_energy)
        out["pv_capacity_factor"] = _q(res.pv.capacity_factor)
    return out


# Per-element U-value columns (raw epsm_data catalog values, W/m²K) and the
# epsm_data role each maps to.  Roles absent from a construction set -> None.
_U_VALUE_ROLES = {
    "u_ext_wall": "EXT_WALL",
    "u_ext_wall_low": "EXT_WALL_LOW",
    "u_ext_wall_medium": "EXT_WALL_MEDIUM",
    "u_ext_wall_high": "EXT_WALL_HIGH",
    "u_roof": "ROOF",
    "u_top_floor": "TOP_FLOOR",
    "u_intermediate_floor": "INTERMEDIATE_FLOOR",
    "u_ground_floor": "GROUND_FLOOR",
    "u_basement_floor": "BASEMENT_FLOOR",
    "u_basement_wall": "BASEMENT_WALL",
    "u_int_wall_loadbearing": "INT_WALL_LOADBEARING",
    "u_int_wall_nonloadbearing": "INT_WALL_NONLOADBEARING",
}
_CONSTRUCTION_COLUMNS = (
    *_U_VALUE_ROLES.keys(), "u_window", "window_shgc", "window_vt",
)


def flatten_constructions(b: "Building") -> dict:
    """Resolved per-element U-values (raw catalog, W/m²K) for the run row.

    Reads the building's epsm_data :class:`ConstructionSet`.  Missing roles and
    any resolution failure degrade gracefully to ``None`` columns.
    """
    cols: dict[str, Any] = {k: None for k in _CONSTRUCTION_COLUMNS}
    try:
        from epsm_data import BuildingElement

        elements = b.construction.elements
    except Exception:
        return cols

    def _u(role_name: str) -> float | None:
        role = getattr(BuildingElement, role_name, None)
        el = elements.get(role) if role is not None else None
        if el is None:
            return None
        try:
            return float(el.u_value)
        except Exception:
            return None

    for col, role_name in _U_VALUE_ROLES.items():
        cols[col] = _u(role_name)

    win = elements.get(getattr(BuildingElement, "WINDOW", None))
    if win is not None:
        cols["u_window"] = getattr(win, "u_value", None)
        cols["window_shgc"] = getattr(win, "shgc", None)
        cols["window_vt"] = getattr(win, "vt", None)
    else:
        # Glazing isn't part of the epsm_data element set; pull the raw glazing
        # spec from the honeybee construction set instead.
        try:
            from .constructions import get_construction_set

            glaz = get_construction_set(b.params.construction_set).window.materials[0]
            cols["u_window"] = getattr(glaz, "u_factor", None)
            cols["window_shgc"] = getattr(glaz, "shgc", None)
            cols["window_vt"] = getattr(glaz, "visible_transmittance", None)
        except Exception:
            pass
    return cols


def flatten_geometry(b: "Building") -> dict:
    """Derived geometry descriptors (analytic; no honeybee model build needed)."""
    from .runner import _polygon_area_perimeter, _wall_areas_by_orientation

    pts = b.footprint_pts
    area, perimeter = _polygon_area_perimeter(pts)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bbox_x = max(xs) - min(xs)
    bbox_y = max(ys) - min(ys)
    length = max(bbox_x, bbox_y)
    breadth = min(bbox_x, bbox_y)
    aspect = length / breadth if breadth > 0 else None

    p = b.params
    total_height = p.num_floors * p.floor_height
    volume = area * total_height
    # Above-grade envelope: vertical walls + roof + ground floor.
    envelope = perimeter * total_height + 2.0 * area
    compactness = envelope / volume if volume > 0 else None

    wall_net, window = _wall_areas_by_orientation(pts, total_height, p.wwr)
    out: dict[str, Any] = {
        "perimeter_m": perimeter,
        "bbox_length_m": length,
        "bbox_breadth_m": breadth,
        "bbox_aspect_ratio": aspect,
        "volume_m3": volume,
        "envelope_area_m2": envelope,
        "compactness_av": compactness,
        "wall_area_total_m2": sum(wall_net.values()),
        "window_area_total_m2": sum(window.values()),
    }
    for o in ("north", "east", "south", "west"):
        out[f"wall_area_{o}_m2"] = wall_net[o]
        out[f"window_area_{o}_m2"] = window[o]
    return out


def flatten_flags(b: "Building") -> dict:
    """Derived boolean inputs."""
    p = b.params
    return {
        "has_basement": p.num_basement_floors > 0,
        "heated_attic": not p.cold_attic,
        "is_zoned": p.apartment_depth > 0,
        "window_openable": False,  # not modelled yet; placeholder for forward-compat
    }


def flatten_shape(s: FootprintShape | None) -> dict:
    """Footprint-shape authoring columns (``None`` for raw footprints)."""
    if s is None:
        return {
            "shape_type": None,
            "shape_length_m": None,
            "shape_width_m": None,
            "shape_cut_length_m": None,
            "shape_cut_width_m": None,
        }
    return {
        "shape_type": s.shape_type,
        "shape_length_m": s.length,
        "shape_width_m": s.width,
        "shape_cut_length_m": s.cut_length,
        "shape_cut_width_m": s.cut_width,
    }


def flatten_run(b: "Building") -> dict:
    """One flat scalar row describing a building's inputs *and* results.

    This is exactly one record of the campaign ``runs`` table.  Time series are
    excluded (stored separately as Parquet).
    """
    row: dict[str, Any] = {
        "name": b.name,
        "footprint_area_m2": b.footprint_area_m2,
    }
    row.update(flatten_params(b.params))
    row.update(flatten_location(b.location))
    row.update(flatten_pv(b.pv))
    row.update(flatten_results(b.results))
    row.update(flatten_geometry(b))
    row.update(flatten_constructions(b))
    row.update(flatten_flags(b))
    row.update(flatten_shape(b.shape))
    # Footprint kept as JSON so the geometry is recoverable from the row alone.
    row["footprint_json"] = json.dumps([[float(x), float(y)] for x, y in b.footprint_pts])
    return row


__all__ = [
    "SCHEMA_VERSION",
    "quantity_to_dict", "quantity_from_dict",
    "timeseries_to_dict", "timeseries_from_dict",
    "params_to_dict", "params_from_dict",
    "weather_to_dict", "weather_from_dict",
    "epc_to_dict", "epc_from_dict",
    "location_to_dict", "location_from_dict",
    "shape_to_dict", "shape_from_dict",
    "pvresults_to_dict", "pvresults_from_dict",
    "pvsystem_to_dict", "pvsystem_from_dict",
    "results_to_dict", "results_from_dict",
    "building_to_dict", "building_from_dict",
    "to_json", "from_json",
    "flatten_params", "flatten_location", "flatten_pv", "flatten_results",
    "flatten_geometry", "flatten_constructions", "flatten_flags", "flatten_shape",
    "flatten_run",
]
