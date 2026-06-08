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

    b = Building(name="agir17", params=cmf_1960(4, "FTX"),
                 footprint_pts=[[0, 0], [20, 0], [20, 12], [0, 12]],
                 location=loc)
    b.build_model()        # populate honeybee_model + geometry
    b.simulate(...)        # run E+ and store results on the object
    b.simulate_pv()        # optional PVWatts V8 production
    print(b.results.site_eui)

Geometry (``footprint_pts``) lives on the building itself, independent of
``location`` (weather/site/provenance).  The same building can therefore be
re-simulated under different weather by swapping its location, e.g.::

    b.location = Location.hypothetical_site(city="Kiruna", weather=kiruna_epw)
    b.simulate(...)        # same geometry, different climate
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
    from .shapes import FootprintShape
    from epsm_data import ConstructionSet


@dataclass
class Building:
    """A complete, simulatable building and its retained results."""

    name: str
    params: BuildingParams
    footprint_pts: list[list[float]]
    location: Location
    pv: PVSystem | None = None

    # Optional authoring provenance: how the footprint was parameterised
    # (rectangle / L / U / O).  ``footprint_pts`` stays the source of truth.
    shape: "FootprintShape | None" = None

    # Generated artifacts (populated by build_model / simulate).
    honeybee_model: "Model | None" = field(default=None, repr=False)
    rooms: "BuildingRooms | None" = field(default=None, repr=False)
    results: BuildingResults | None = None

    def __post_init__(self) -> None:
        # Normalise footprint vertices to plain [[x, y], ...] floats.
        self.footprint_pts = [[float(c) for c in pt] for pt in self.footprint_pts]

    # -- geometry / area ---------------------------------------------------

    @property
    def footprint_area_m2(self) -> float:
        """Footprint area in m² (shoelace formula)."""
        pts = self.footprint_pts
        n = len(pts)
        a = 0.0
        for i in range(n):
            j = (i + 1) % n
            a += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1]
        return abs(a) / 2.0

    @property
    def heated_floor_area_m2(self) -> float | None:
        """Heated (Atemp-proxy) floor area in m², from perimeter rooms.

        Requires :meth:`build_model` to have run.  Returns ``None`` otherwise.
        """
        if self.rooms is None:
            return None
        return self.rooms.perimeter_floor_area

    # -- constructions / envelope -----------------------------------------

    @property
    def construction(self) -> "ConstructionSet":
        """The building's envelope as the epsm_data :class:`ConstructionSet`.

        Pure epsm_data domain objects — no honeybee leaks through.  Resolved
        live from ``params.construction_set`` (the building stores only the
        set *name*).  ``.elements`` maps each ``BuildingElement`` role to an
        ``Element`` / ``WindowElement`` exposing ``.u_value`` (W/m²K, incl.
        boundary air films), ``.r_total`` and ``.components`` →
        ``Component.layers`` → ``Layer.materials``::

            from epsm_data import BuildingElement
            cs = b.construction
            cs.elements[BuildingElement.EXT_WALL].u_value
            cs.elements[BuildingElement.EXT_WALL].components[0].thickness
            for slot in cs.elements[BuildingElement.EXT_WALL].components[0].layers:
                slot.layer.materials  # material composition of each layer

        Raises ``ValueError`` if the building's construction set has no
        epsm_data archetype behind it.
        """
        from .constructions import get_epsm_construction_set

        return get_epsm_construction_set(self.params.construction_set)

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
        include_pv: bool = True,
    ) -> BuildingResults:
        """Run the simulation and store :class:`BuildingResults` on this object.

        Parameters mirror :func:`pbgenerator.runner.run` but results are
        retained on ``self.results`` (and returned for convenience).

        If a PV system is attached (``self.pv`` is set) and ``include_pv`` is
        ``True`` (the default), rooftop PV is evaluated automatically and its
        results are folded into ``self.results.pv``.
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

        if include_pv and self.pv is not None:
            self.simulate_pv(keep_hourly=keep_hourly)

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

    # -- serialisation -----------------------------------------------------

    def to_dict(self, *, include_results: bool = True,
                include_timeseries: bool = False) -> dict:
        """Plain, JSON-ready dict of this building (no honeybee objects).

        ``include_results=False`` yields only the inputs that define the run
        (identity, params, footprint, location, PV design).  See
        :mod:`pbgenerator.serialize`.
        """
        from .serialize import building_to_dict

        return building_to_dict(
            self, include_results=include_results,
            include_timeseries=include_timeseries,
        )

    def to_json(self, *, include_results: bool = True,
                include_timeseries: bool = False, indent: int | None = None) -> str:
        """This building as a JSON string."""
        from .serialize import to_json

        return to_json(
            self.to_dict(include_results=include_results,
                         include_timeseries=include_timeseries),
            indent=indent,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "Building":
        """Rebuild a :class:`Building` from :meth:`to_dict` output."""
        from .serialize import building_from_dict

        return building_from_dict(data)

    @classmethod
    def from_json(cls, text: str) -> "Building":
        """Rebuild a :class:`Building` from :meth:`to_json` output."""
        from .serialize import from_json

        return cls.from_dict(from_json(text))


__all__ = ["Building"]
