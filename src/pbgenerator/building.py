"""The top-level :class:`Building` aggregate.

A ``Building`` is the single object that owns everything about one building:

* its identity (``name``);
* its simulation inputs (:class:`~pbgenerator.building_params.BuildingParams`);
* its location, city, coordinates, weather/EPW, and EPC provenance
  (:class:`~pbgenerator.location.Location`);
* any installed rooftop PV (:class:`~pbgenerator.pv.PVSystem`);
* the generated Honeybee :class:`~honeybee.model.Model` and room geometry
  (cached artifacts, rebuilt on demand);
* the simulation results (:class:`~pbgenerator.results.BuildingResults`),
  retained after a run with annual metrics, monthly aggregates, hourly time
  series, and units on every value.

Typical use::

    b = Building(name="agir17", params=cmf_1960(4, "FTX"), location=loc)
    b.build_model()        # populate honeybee_model + geometry
    b.simulate(...)        # run E+ and store results on the object
    b.simulate_pv()        # optional PVWatts V8 production
    print(b.results.site_eui)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .building_params import BuildingParams
from .location import Location
from .pv import PVSystem
from .results import BuildingResults

if TYPE_CHECKING:  # pragma: no cover - typing only
    from honeybee.model import Model
    from .geometry import BuildingRooms


@dataclass
class Building:
    """A complete, simulatable building and its retained results."""

    name: str
    params: BuildingParams
    location: Location
    pv: PVSystem | None = None

    # Generated artifacts (populated by build_model / simulate).
    honeybee_model: "Model | None" = field(default=None, repr=False)
    rooms: "BuildingRooms | None" = field(default=None, repr=False)
    results: BuildingResults | None = None

    # -- geometry / area ---------------------------------------------------

    @property
    def footprint_pts(self) -> list[list[float]]:
        return self.location.footprint_pts

    @property
    def heated_floor_area_m2(self) -> float | None:
        """Heated (Atemp-proxy) floor area in m², from perimeter rooms.

        Requires :meth:`build_model` to have run.  Returns ``None`` otherwise.
        """
        if self.rooms is None:
            return None
        return self.rooms.perimeter_floor_area

    # -- result navigation -------------------------------------------------

    @property
    def zones(self):
        """Per-zone result views (see :attr:`BuildingResults.zones`).

        Requires :meth:`simulate` to have run with hourly output retained.
        """
        if self.results is None:
            raise ValueError("No results yet; call building.simulate() first")
        return self.results.zones

    @property
    def floors(self):
        """Per-floor result views (see :attr:`BuildingResults.floors`)."""
        if self.results is None:
            raise ValueError("No results yet; call building.simulate() first")
        return self.results.floors

    # -- model construction ------------------------------------------------

    def build_model(self, context_shades=None) -> "Model":
        """Build (and cache) the Honeybee model and room geometry."""
        from .idf_builder import build_model_with_rooms

        model, rooms = build_model_with_rooms(
            self.name, self.footprint_pts, self.params, context_shades=context_shades
        )
        self.honeybee_model = model
        self.rooms = rooms
        return model

    def write_idf(self, path: str | Path, context_shades=None) -> Path:
        """Write the building's IDF to ``path`` and return it."""
        from .idf_builder import write_idf

        path = Path(path)
        write_idf(path, self.name, self.footprint_pts, self.params,
                  context_shades=context_shades)
        return path

    # -- simulation --------------------------------------------------------

    def simulate(
        self,
        idf_dir: str | Path | None = None,
        output_dir: str | Path | None = None,
        *,
        engine: str = "energyplus",
        context_shades=None,
        atemp_override: float | None = None,
        engine_options: dict | None = None,
        keep_hourly: bool = True,
    ) -> BuildingResults:
        """Run the simulation and store :class:`BuildingResults` on this object.

        Parameters mirror :func:`pbgenerator.runner.run` but results are
        retained on ``self.results`` (and returned for convenience).
        """
        from .runner import simulate_building

        results = simulate_building(
            self,
            idf_dir=idf_dir,
            output_dir=output_dir,
            engine=engine,
            context_shades=context_shades,
            atemp_override=atemp_override,
            engine_options=engine_options,
            keep_hourly=keep_hourly,
        )
        self.results = results
        return results

    # -- PV ----------------------------------------------------------------

    def simulate_pv(self, *, keep_hourly: bool = True):
        """Evaluate rooftop PV (PVWatts V8) and store results on the PV system.

        Requires :attr:`pv` to be set and an EPW to be available on the
        building's location.  Returns the :class:`~pbgenerator.pv.PVResults`.
        """
        from .pv import evaluate_pv

        if self.pv is None:
            raise ValueError("Building has no PV system to evaluate (self.pv is None)")
        epw = self.location.epw_path
        if epw is None:
            raise ValueError("Building location has no weather/EPW file for PV evaluation")

        pv_results = evaluate_pv(self.pv, epw, keep_hourly=keep_hourly)
        if self.results is not None:
            self.results.pv = pv_results
        return pv_results


__all__ = ["Building"]
