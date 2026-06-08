"""Footprint-based building generator with Honeybee Energy."""

from .archetypes import apply_levers, cmf_1960, sample_wwr
from .batch import deploy
from .building import Building
from .building_params import BuildingParams, FacadeWWR
from .cohort import Cohort, gothenburg_1960s, uddevalla_1960s
from .constructions import (
    BETSI_TEMPLATES,
    LEVER_BOUNDS,
    ConstructionSetDef,
    get_construction_set,
    make_construction_set,
)
from .location import EPCSource, Location, WeatherSite
from .pv import PVResults, PVSystem, evaluate_pv
from .reporting import compare_building_to_epc
from .results import BuildingResults
from .series import FloorResults, Signal, ZoneCollection, ZoneResults
from .units import Quantity, TimeSeries

__all__ = [
    # config / runtime entry points
    "cli",
    "config",
    "geometry",
    "idf_builder",
    "runner",
    # high-level aggregate
    "Building",
    "BuildingResults",
    "Location",
    "WeatherSite",
    "EPCSource",
    "PVSystem",
    "PVResults",
    "evaluate_pv",
    "compare_building_to_epc",
    "Signal",
    "ZoneResults",
    "ZoneCollection",
    "FloorResults",
    "Quantity",
    "TimeSeries",
    # parameter model
    "BuildingParams",
    "FacadeWWR",
    # archetypes / levers
    "cmf_1960",
    "sample_wwr",
    "apply_levers",
    # construction sets
    "ConstructionSetDef",
    "get_construction_set",
    "make_construction_set",
    "BETSI_TEMPLATES",
    "LEVER_BOUNDS",
    # cohort builders
    "Cohort",
    "gothenburg_1960s",
    "uddevalla_1960s",
    # batch deployment
    "deploy",
]
