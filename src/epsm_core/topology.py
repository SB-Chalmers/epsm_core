# File: topology.py
# Purpose: Shared cell-to-surface topology for physical parts and generated thermal zones.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-06
# Changelog:
#   2026-09-06 - Document topology interfaces, examples, constraints and processing rationale.

"""Shared cell-to-surface topology for physical parts and generated thermal zones.

Notes
-----
Private planar cells retain physical part and storey ownership while generating thermal
zones. Shared vertex registries and contact intersections produce reciprocal faces.
Physical same-zone slabs become internal mass; orientation is applied after unrotated
overlay.

Examples
--------
Supply a validated BuildingSpec as ``building``.

Example::

    from epsm_core.specs.geometry import Footprint
    from epsm_core.specs.geometry import GeometrySpec
    from epsm_core.topology import building_cells
    from epsm_core.geometry import local_polygons

    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
    )
    polygons, origin = local_polygons(geometry)
    cells = building_cells(building, polygons)
"""

from copy import copy
from dataclasses import dataclass, field
from math import cos, radians, sin

from shapely import STRtree, unary_union
from shapely.geometry import LineString, Point, Polygon

from .geometry import facade_edges, horizontal_patches, horizontal_vertices, wall_vertices
from .zoning import GRID, exposed_facades, perimeter_core_partitions, polygon_components

MAX_THERMAL_CELLS = 4096


@dataclass
class Cell:
    """Mutable private extrusion cell used to build thermal topology.

    Attributes
    ----------
    part : object
        Physical ownership part associated with the current footprint.  Required at
        construction.
    polygon : object
        Metric planar region; ownership and zoning meaning come from the enclosing record.
        Required at construction.
    bottom : float
        Vertical elevation in metres in the current scene datum.  Required at construction.
    top : float
        Nominal assembly for the named envelope or partition role; optional roles must be
        supplied when the selected topology requires them.  Required at construction.
    conditioned : bool
        Whether the physical part or cell belongs to conditioned thermal volume.  Required
        at construction.
    kind : str
        Supported measure discriminator or geometric classification, according to the
        record.  Required at construction.
    storey : int
        Zero-based above-grade storey; None selects a facade-wide value.  Required at
        construction.
    zone : str
        Resolved thermal-zone identity.  Default: ``''``.
    identifier : str
        Stable identifier within the owning collection.  Default: ``''``.
    zone_kind : str
        Generated dwelling/common/stairwell/perimeter/core classification where applicable.
        Default: ``''``.
    apartment_type : str
        Dwelling type label; empty for common, stairwell or nonresidential regions.
        Default: ``''``.
    perimeter_facade_id : str
        Original exposed facade responsible for a perimeter region.  Default: ``''``.

    Notes
    -----
    Physical part and storey ownership survive generated zoning cuts. bottom/top are metric
    elevations; zone identity and polygon coordinates can be updated during graph
    construction.

    Examples
    --------
    Example::

        from epsm_core.topology import Cell
        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        part = geometry.parts[0]
        polygon = geometry.footprints[0].polygon
        cell = Cell(part, polygon, 0, 3, True, "main", 0)
    """

    part: object
    polygon: object
    bottom: float
    top: float
    conditioned: bool
    kind: str
    storey: int
    zone: str = ""
    identifier: str = ""
    zone_kind: str = ""
    apartment_type: str = ""
    perimeter_facade_id: str = ""


@dataclass
class Surface:
    """Mutable oriented thermal face with ownership and boundary metadata.

    Attributes
    ----------
    name : str
        Identifier or field name interpreted by the current operation.  Required at
        construction.
    zone : str
        Resolved thermal-zone identity.  Required at construction.
    vertices : list
        Ordered three-dimensional metric surface vertices; winding controls the normal.
        Required at construction.
    kind : str
        Supported measure discriminator or geometric classification, according to the
        record.  Required at construction.
    construction : str
        Construction role or emitted construction name, including reverse suffix where
        needed.  Required at construction.
    boundary : str
        EnergyPlus outside boundary condition such as Outdoors, Ground or Surface.  Required
        at construction.
    adjacent : str
        Reciprocal surface name for a Surface boundary; empty otherwise.  Default: ``''``.
    part_id : str
        Owning physical part or neighbouring-building identifier.  Default: ``''``.
    facade_id : str
        Stable physical facade identifier from GeometrySpec.facades().  Default: ``''``.
    storey : int
        Zero-based above-grade storey; None selects a facade-wide value.  Default: ``0``.
    area : float
        Geometric pane or surface area in square metres.  Default: ``0``.
    annotations : list
        Inspectable assumption labels inherited from physical ownership evidence.  Default:
        a fresh list per instance.
    cell_kind : str
        Physical vertical region classification: main, basement or attic.  Default: ``''``.

    Notes
    -----
    Vertices use the local metric scene. Surface boundaries use reciprocal adjacent names;
    Outdoors, Ground and Adiabatic have their respective physical interpretations.
    Construction role may include a reverse suffix.

    Examples
    --------
    Example::

        from epsm_core.topology import Surface

        surface = Surface(
            "wall_0",
            "zone",
            [(0, 0, 0), (2, 0, 0), (2, 0, 3), (0, 0, 3)],
            "Wall",
            "wall",
            "Outdoors",
            area=6,
        )
    """

    name: str
    zone: str
    vertices: list
    kind: str
    construction: str
    boundary: str
    adjacent: str = ""
    part_id: str = ""
    facade_id: str = ""
    storey: int = 0
    area: float = 0
    annotations: list = field(default_factory=list)
    cell_kind: str = ""


@dataclass
class SurfaceGraph:
    """Resolved mutable thermal topology and its assumption reports.

    Attributes
    ----------
    surfaces : list
        Mutable thermal face list, or immutable shading tuple in ContextResolution.
        Required at construction.
    zones : dict
        Zone metadata keyed by name, including expected volume_m3.  Required at
        construction.
    internal_mass : list
        Physical same-zone intermediate slab records, counted once in quantities.  Required
        at construction.
    valid_facades : set
        Set of source facade IDs accepted by the shared graph.  Required at construction.
    approximations : list
        Explicit modelling assumptions such as approximate nonconvex interior view factors.
        Required at construction.
    layout_report : dict
        Procedural outcome, achieved zoning and any explicitly requested fallback evidence.
        Default: a fresh dict per instance.
    zoning_report : dict
        Procedural outcome, achieved zoning and any explicitly requested fallback evidence.
        Default: a fresh dict per instance.

    Notes
    -----
    surfaces, zones and internal_mass are shared across geometry consumers. Internal slab
    quantities are physical records counted once, even when compiled into two exposed
    InternalMass halves.

    Examples
    --------
    Example::

        from epsm_core.topology import SurfaceGraph

        graph = SurfaceGraph([], {}, [], set(), [])
    """

    surfaces: list
    zones: dict
    internal_mass: list
    valid_facades: set
    approximations: list
    layout_report: dict = field(default_factory=dict)
    zoning_report: dict = field(default_factory=dict)


def with_geometry(spec, geometry):
    """Replace geometry on a validated building or geometry-only preview input.

    Parameters
    ----------
    spec : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    geometry : GeometrySpec
        Physical parts, metric coordinate frame, orientation and zoning controls.

    Returns
    -------
    object
        Replacement input with the supplied geometry.

    Notes
    -----
    BuildingSpec.updated revalidates the complete building. Preview namespaces are shallow-
    copied, so their other referenced objects remain shared.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``.

    Example::

        from epsm_core.topology import with_geometry

        replacement = with_geometry(building, building.geometry)
    """
    # 1. Replace geometry on a validated building or geometry-only preview input.
    if hasattr(spec, "updated"):
        return spec.updated(geometry=geometry)
    replacement = copy(spec)
    replacement.geometry = geometry
    return replacement


def _segments(a, b, points):
    """Yield an edge split at nearby interior points in directed order.

    Parameters
    ----------
    a : tuple of float
        Directed edge start in metric plan coordinates.
    b : tuple of float
        Directed edge end in metric plan coordinates.
    points : sequence
        Coordinates or Shapely points in the frame expected by the geometric helper.

    Yields
    ------
    tuple
        Start and end coordinates for each noncollapsed segment.

    Notes
    -----
    Uses a 1e-7 m proximity and endpoint tolerance. The caller supplies spatially filtered
    Shapely points to bound work.

    Examples
    --------
    Example::

        from epsm_core.topology import _segments

        from shapely.geometry import Point

        assert len(list(_segments((0, 0), (2, 0), [Point(1, 0)]))) == 2
    """

    # 1. Yield an edge split at nearby interior points in directed order.
    edge = LineString([a, b])
    nodes = {0.0: tuple(a), edge.length: tuple(b)}
    for point in points:
        if edge.distance(point) < 1e-7:
            distance = edge.project(point)
            if 1e-7 < distance < edge.length - 1e-7:
                nodes[distance] = tuple(point.coords[0])
    distances = sorted(nodes)
    for start, stop in zip(distances, distances[1:]):
        if stop - start > 1e-7:
            yield nodes[start], nodes[stop]


def building_cells(spec, polygons, partitions=None):
    """Extrude physical storeys and optional thermal partitions into private cells.

    Parameters
    ----------
    spec : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    polygons : sequence of Polygon
        Local metric footprints in the same order as geometry.parts.
    partitions : dict or sequence
        Generated planar subdivisions; cell building uses (part ID, storey) keys, coverage
        validation uses polygons. Default: ``None``.

    Returns
    -------
    list of Cell
        Cells retaining physical part and storey ownership.

    Notes
    -----
    Basements and attics keep unsplit floorplates. Stairwell regions share a zone across
    storeys. MAX_THERMAL_CELLS bounds memory and surface-generation complexity.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``.

    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.topology import building_cells
        from epsm_core.geometry import local_polygons

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        polygons, origin = local_polygons(geometry)
        cells = building_cells(building, polygons)
    """
    # 1. Extrude physical storeys and optional thermal partitions into private cells.
    geometry = spec.geometry
    cells = []

    def add_cell(cell):
        """Append one private cell while enforcing the global cell limit.

        Parameters
        ----------
        cell : Cell
            Private extrusion cell carrying physical part and storey ownership.

        Returns
        -------
        None
            Mutates the enclosing cells list.

        Raises
        ------
        ValueError
            If the input or generated result violates the constraints described in Notes.

        Notes
        -----
        The limit is checked before insertion; exceeding it raises ValueError instead of
        producing a partial accepted mesh.

        Examples
        --------
        Within the enclosing operation, after its captured state has been initialized::

            add_cell(Cell(part, polygon, 0, 3, True, "main", 0))
        """

        if len(cells) >= MAX_THERMAL_CELLS:
            raise ValueError(f"Geometry exceeds {MAX_THERMAL_CELLS} thermal cells")
        cells.append(cell)

    # 2. Retain physical part/storey ownership while creating private thermal cells.
    for part, polygon in zip(geometry.parts, polygons):
        if geometry.basement_depth_m:
            add_cell(
                Cell(
                    part,
                    polygon,
                    -geometry.basement_depth_m,
                    0,
                    geometry.basement_conditioned,
                    "basement",
                    -1,
                )
            )
        for i, (bottom, top) in enumerate(
            zip(part.storey_elevations_m, part.storey_elevations_m[1:])
        ):
            plan = (partitions or {}).get((part.identifier, i))
            if plan is None:
                add_cell(Cell(part, polygon, bottom, top, part.conditioned, "main", i))
            else:
                for j, region in enumerate(plan):
                    kind = region.kind
                    identifier = f"{part.identifier}_main_{i}_{kind}_{j}"
                    zone = f"{part.identifier}_stairwell_{j}" if kind == "stairwell" else identifier
                    add_cell(
                        Cell(
                            part,
                            region.polygon,
                            bottom,
                            top,
                            part.conditioned,
                            "main",
                            i,
                            zone=zone,
                            identifier=identifier,
                            zone_kind=kind,
                            apartment_type=getattr(region, "apartment_type", ""),
                            perimeter_facade_id=getattr(region, "facade_id", ""),
                        )
                    )
        roof = geometry.roof_for(part)
        if roof.topology == "cold_attic":
            top = part.storey_elevations_m[-1]
            add_cell(
                Cell(part, polygon, top, top + roof.attic_height_m, False, "attic", part.floors)
            )
    return cells


def _node_cell_vertices(cells, polygons):
    """Coalesce near-coincident cut vertices using one shared registry.

    Parameters
    ----------
    cells : list of Cell
        Mutable private extrusion cells used for shared topology construction.
    polygons : sequence of Polygon
        Local metric footprints in the same order as geometry.parts.

    Returns
    -------
    None
        Replaces each cell polygon in place.

    Raises
    ------
    ValueError
        Rejected conditions: Generated thermal cell collapsed during shared vertex noding.

    Notes
    -----
    Clusters points within 1e-7 m, preferring original footprint corners. Shared choices
    avoid mismatched reciprocal faces. Collapsed or invalid reconstructed cells are
    rejected.

    Examples
    --------
    Supply matching private Cell records as ``cells`` from building_cells.

    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.topology import _node_cell_vertices
        from epsm_core.geometry import local_polygons

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        polygons, origin = local_polygons(geometry)
        _node_cell_vertices(cells, polygons)
    """
    # 1. Coalesce near-coincident cut vertices using one shared registry.
    originals = {
        tuple(p)
        for polygon in polygons
        for ring in (polygon.exterior, *polygon.interiors)
        for p in ring.coords[:-1]
    }
    # 2. Cluster one shared coordinate registry to keep reciprocal meshes identical.
    coordinates = sorted(
        originals
        | {
            tuple(p)
            for cell in cells
            for ring in (cell.polygon.exterior, *cell.polygon.interiors)
            for p in ring.coords[:-1]
        }
    )
    points = [Point(p) for p in coordinates]
    tree = STRtree(points)
    parents = list(range(len(points)))

    def root(i):
        """Find a vertex-cluster representative with union-find path compression.

        Parameters
        ----------
        i : int
            Zero-based index in the enclosing registry or generated face sequence.

        Returns
        -------
        int
            Root index in the enclosing parents array.

        Notes
        -----
        Mutates parent links for faster repeated lookup; the index must already belong to the
        registry.

        Examples
        --------
        Within the enclosing operation, after its captured state has been initialized::

            root(0)
        """

        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for i, point in enumerate(points):
        for j in tree.query(point, predicate="dwithin", distance=1e-7):
            parents[root(int(j))] = root(i)
    groups = {}
    for i, coordinate in enumerate(coordinates):
        groups.setdefault(root(i), []).append(coordinate)
    replacements = {}
    for group in groups.values():
        chosen = min((p for p in group if p in originals), default=min(group))
        replacements.update((p, chosen) for p in group)

    def ring_coordinates(ring):
        """Map a ring through the shared vertex registry and remove consecutive duplicates.

        Parameters
        ----------
        ring : LinearRing
            Shapely ring whose repeated closing point is handled by the helper.

        Returns
        -------
        list of tuple
            Unclosed representative coordinates.

        Notes
        -----
        Uses replacements built for the entire mesh. Rings reduced below three points need
        caller-level handling before polygon reconstruction.

        Examples
        --------
        Within the enclosing operation, after its captured state has been initialized::

            ring_coordinates(cells[0].polygon.exterior)
        """

        # 1. Map a ring through the shared vertex registry and remove consecutive duplicates.
        result = []
        for p in ring.coords[:-1]:
            point = replacements[tuple(p)]
            if not result or point != result[-1]:
                result.append(point)
        if len(result) > 1 and result[0] == result[-1]:
            result.pop()
        return result

    # 3. Rebuild cell rings from common representatives and reject numerical collapse.
    for cell in cells:
        shell = ring_coordinates(cell.polygon.exterior)
        holes = [ring_coordinates(ring) for ring in cell.polygon.interiors]
        polygon = Polygon(shell, [h for h in holes if len(h) >= 3])
        if not polygon.is_valid or polygon.area < 1e-7:
            raise ValueError("Generated thermal cell collapsed during shared vertex noding")
        cell.polygon = polygon


def build_surface_graph(spec, polygons):
    """Resolve thermal zoning and apply only explicitly requested fallback.

    Parameters
    ----------
    spec : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    polygons : sequence of Polygon
        Local metric footprints in the same order as geometry.parts.

    Returns
    -------
    SurfaceGraph
        Resolved surfaces, zones, internal slabs and zoning provenance.

    Notes
    -----
    Overlay occurs in the unrotated frame and the complete graph is rotated once. Procedural
    ValueError can trigger per_storey fallback only when requested, replacing zoning for the
    entire building and recording the reason.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``.

    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.topology import build_surface_graph
        from epsm_core.geometry import local_polygons

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        polygons, origin = local_polygons(geometry)
        graph = build_surface_graph(building, polygons)
    """
    # 1. Resolve thermal zoning and apply only explicitly requested fallback.
    geometry = spec.geometry
    if geometry.orientation_deg:
        # Overlay in the source building frame. Rotate the complete shared mesh
        # once afterwards, so scene orientation cannot introduce independent cut
        # rounding or change which experimental floorplan succeeds.
        working = with_geometry(spec, geometry.updated(orientation_deg=0))
        from .geometry import local_polygons

        unrotated, _ = local_polygons(working.geometry)
        graph = build_surface_graph(working, unrotated)
        angle = radians(-geometry.orientation_deg)
        c, s = cos(angle), sin(angle)

        def transform(vertices):
            """Rotate complete 3-D vertices clockwise around the shared scene origin.

            Parameters
            ----------
            vertices : array_like
                Ordered three-dimensional metric surface vertices; winding controls the normal.

            Returns
            -------
            list of tuple
                Rotated x/y coordinates with unchanged z.

            Notes
            -----
            Captures sine and cosine from the requested scene orientation. Apply after overlay so
            orientation cannot change topology decisions.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                transform([(0, 0, 3), (1, 0, 3)])
            """

            return [(x * c - y * s, x * s + y * c, z) for x, y, z in vertices]

        for surface in graph.surfaces:
            surface.vertices = transform(surface.vertices)
        for mass in graph.internal_mass:
            mass["vertices"] = [transform(patch) for patch in mass["vertices"]]
        return graph
    # 2. Resolve the requested procedural mode in an orientation-independent frame.
    mode = geometry.zoning.mode
    # Preserve physical source vertices. Rounding a symmetric roof footprint can
    # move a reflex corner off its ridge and create artificial sliver facets.
    try:
        if mode == "apartments":
            from .apartments import build_apartment_graph

            graph = build_apartment_graph(spec, polygons)
        else:
            partitions = None
            if mode == "perimeter_core":
                cache, partitions = {}, {}
                part_tops = {
                    p.identifier: p.storey_elevations_m[-1]
                    + (
                        geometry.roof_for(p).attic_height_m
                        if geometry.roof_for(p).topology == "cold_attic"
                        else 0
                    )
                    for p in geometry.parts
                }
                for part, polygon in zip(geometry.parts, polygons):
                    if not part.conditioned:
                        continue
                    for i, (bottom, top) in enumerate(
                        zip(part.storey_elevations_m, part.storey_elevations_m[1:])
                    ):
                        edges = exposed_facades(
                            part,
                            polygon,
                            geometry.parts,
                            polygons,
                            bottom,
                            top,
                            {w.facade_id for w in geometry.party_walls},
                            part_tops,
                        )
                        key = (part.identifier, tuple(edges), geometry.zoning.depth_m)
                        if key not in cache:
                            cache[key] = perimeter_core_partitions(
                                polygon, edges, geometry.zoning.depth_m
                            )
                        partitions[(part.identifier, i)] = cache[key]
            graph = graph_from_cells(spec, polygons, building_cells(spec, polygons, partitions))
        graph.zoning_report = dict(
            requested_mode=mode,
            effective_mode=mode,
            on_failure=geometry.zoning.on_failure,
            substituted=False,
        )
        return graph
    except ValueError as exc:
        if (
            mode not in ("perimeter_core", "apartments")
            or geometry.zoning.on_failure != "per_storey"
        ):
            raise
        # 3. Substitute the complete building only under the explicit per_storey failure policy.
        baseline = with_geometry(
            spec,
            geometry.updated(
                zoning=geometry.zoning.updated(mode="per_storey", on_failure="error", depth_m=4.5)
            ),
        )
        graph = build_surface_graph(baseline, polygons)
        graph.zoning_report = dict(
            requested_mode=mode,
            effective_mode="per_storey",
            on_failure="per_storey",
            substituted=True,
            reason=str(exc),
            affected_parts=[p.identifier for p in geometry.parts],
        )
        if mode == "apartments":
            graph.layout_report = dict(
                status="fallback_per_storey",
                parts=[
                    dict(
                        part_id=p.identifier,
                        status="fallback_per_storey",
                        reason=str(exc),
                        unit_counts={},
                    )
                    for p in geometry.parts
                ],
            )
        return graph


def graph_from_cells(spec, polygons, cells):
    """Build paired thermal boundaries and physical slab records from private cells.

    Parameters
    ----------
    spec : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    polygons : sequence of Polygon
        Local metric footprints in the same order as geometry.parts.
    cells : list of Cell
        Mutable private extrusion cells used for shared topology construction.

    Returns
    -------
    SurfaceGraph
        Surface topology with zone metrics and approximation reports.

    Raises
    ------
    ValueError
        Rejected conditions: Party wall references unknown facade; Ambiguous shared-edge
        ownership; Generated internal partition could not be paired.

    Notes
    -----
    Mutates cell polygons, IDs and zone assignments. Horizontal overlaps are constructed
    once for reciprocal meshes; wall cuts share vertices and elevation bands. Same-zone
    slabs become internal mass, while artificial same-zone walls disappear.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``.

    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.topology import building_cells
        from epsm_core.topology import graph_from_cells
        from epsm_core.geometry import local_polygons

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        polygons, origin = local_polygons(geometry)
        graph = graph_from_cells(building, polygons, building_cells(building, polygons))
    """
    # 1. Build paired thermal boundaries and physical slab records from private cells.
    geometry = spec.geometry
    _node_cell_vertices(cells, polygons)
    parent = list(range(len(cells)))

    def root(i):
        """Find a connected-volume representative with path compression.

        Parameters
        ----------
        i : int
            Zero-based index in the enclosing registry or generated face sequence.

        Returns
        -------
        int
            Root index in the enclosing cell parent array.

        Notes
        -----
        Used for whole-building zone grouping. Connectivity requires compatible conditioning and
        actual horizontal or vertical contact.

        Examples
        --------
        Within the enclosing operation, after its captured state has been initialized::

            root(0)
        """

        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    tree = STRtree([c.polygon for c in cells])
    if geometry.zoning.mode == "whole_building":
        for i, cell in enumerate(cells):
            for j in tree.query(cell.polygon, predicate="intersects"):
                other = cells[j]
                if i >= j or cell.conditioned != other.conditioned:
                    continue
                if not cell.conditioned and ((cell.kind == "attic") != (other.kind == "attic")):
                    continue
                overlap = cell.polygon.intersection(other.polygon)
                vertical = min(cell.top, other.top) - max(cell.bottom, other.bottom)
                horizontal_contact = overlap.area > 1e-7 and (
                    abs(cell.top - other.bottom) < GRID or abs(other.top - cell.bottom) < GRID
                )
                if horizontal_contact or (overlap.length > 1e-7 and vertical > GRID):
                    parent[root(j)] = root(i)
    # 2. Aggregate connected cell areas and volumes into their resolved thermal zones.
    zones = {}
    for i, cell in enumerate(cells):
        cell.identifier = cell.identifier or f"{cell.part.identifier}_{cell.kind}_{cell.storey}"
        cell.zone = (
            f"volume_{root(i)}"
            if geometry.zoning.mode == "whole_building"
            else cell.zone or cell.identifier
        )
        data = zones.setdefault(
            cell.zone,
            dict(
                floor_area_m2=0,
                volume_m3=0,
                conditioned=cell.conditioned,
                part_ids=[],
                elevations_m=[],
            ),
        )
        if cell.zone_kind != "stairwell" or cell.storey == 0:
            data["floor_area_m2"] += cell.polygon.area
        data["volume_m3"] += cell.polygon.area * (cell.top - cell.bottom)
        data["part_ids"] = sorted(set(data["part_ids"] + [cell.part.identifier]))
        data["elevations_m"] = sorted(set(data["elevations_m"] + [cell.bottom, cell.top]))
        if cell.zone_kind:
            data["zone_kind"] = cell.zone_kind
        if cell.apartment_type:
            data["apartment_type"] = cell.apartment_type
        if cell.perimeter_facade_id:
            data["perimeter_facade_id"] = cell.perimeter_facade_id
    surfaces, masses = [], []
    total = unary_union(polygons)
    original_edges = {
        part.identifier: [
            (fid, LineString([a, b])) for fid, a, b in facade_edges(p, part.identifier)
        ]
        for part, p in zip(geometry.parts, polygons)
    }
    valid_facades = {fid for edges in original_edges.values() for fid, _ in edges}
    party = {w.facade_id: w for w in geometry.party_walls}
    for wall in party.values():
        if not wall.contact_confirmed or wall.neighbor_conditioning != "heated":
            raise ValueError(
                f"Party wall {wall.facade_id} requires reviewed heated-neighbor contact"
            )
    if set(party) - valid_facades:
        raise ValueError("Party wall references unknown facade")
    for edges in original_edges.values():
        for fid, line in edges:
            if fid in party and line.difference(total.boundary).length > 1e-7:
                raise ValueError(f"Party facade {fid} is internal to the building")
    coordinates = {
        tuple(p)
        for cell in cells
        for ring in (cell.polygon.exterior, *cell.polygon.interiors)
        for p in ring.coords[:-1]
    }
    coordinates.update(
        tuple(p)
        for poly in polygons
        for ring in (poly.exterior, *poly.interiors)
        for p in ring.coords[:-1]
    )
    points = [Point(p) for p in sorted(coordinates)]
    point_tree = STRtree(points)

    def add(cell, vertices, kind, role, boundary, suffix, **kwargs):
        """Create a surface carrying physical ownership and assumption annotations.

        Parameters
        ----------
        cell : Cell
            Private extrusion cell carrying physical part and storey ownership.
        vertices : array_like
            Ordered three-dimensional metric surface vertices; winding controls the normal.
        kind : str
            Surface, object or region classification consumed by the enclosing builder.
        role : str
            Construction role or emitted construction name, including reverse suffix where
            needed.
        boundary : str
            EnergyPlus outside boundary condition such as Outdoors, Ground or Surface.
        suffix : str
            Deterministic local suffix appended to the owning cell identifier.
        **kwargs : dict
            Additional Surface metadata forwarded to the dataclass constructor.

        Returns
        -------
        Surface
            Newly appended graph face.

        Notes
        -----
        Rounds x/y to eight decimals and preserves z. Additional metadata is forwarded to
        Surface; adjacency is linked later from coincident faces.

        Examples
        --------
        Within the enclosing operation, after its captured state has been initialized::

            face = add(
                cell,
                wall_vertices((0, 0), (2, 0), 0, 3),
                "Wall",
                "wall",
                "Outdoors",
                "wall_0",
                area=6,
            )
        """

        # 1. Create a surface carrying physical ownership and assumption annotations.
        annotations = []
        if cell.part.height_status != "measured":
            annotations.append(f"{cell.part.height_status} height")
        if cell.part.outline_kind != "facade":
            annotations.append(cell.part.outline_kind)
        surface = Surface(
            f"{cell.identifier}_{suffix}",
            cell.zone,
            [(round(x, 8), round(y, 8), z) for x, y, z in vertices],
            kind,
            role,
            boundary,
            part_id=cell.part.identifier,
            storey=cell.storey,
            annotations=annotations,
            cell_kind=cell.kind,
            **kwargs,
        )
        surfaces.append(surface)
        return surface

    # 3. Track each horizontal contact once so reciprocal slab geometry cannot diverge.
    covered = {(i, up): [] for i in range(len(cells)) for up in (False, True)}
    # Build each slab intersection once to guarantee identical reciprocal meshes.
    for i, first in enumerate(cells):
        for j in tree.query(first.polygon, predicate="intersects"):
            if i >= j:
                continue
            second = cells[j]
            if abs(first.top - second.bottom) < GRID:
                lower, upper, li, ui = first, second, i, j
            elif abs(second.top - first.bottom) < GRID:
                lower, upper, li, ui = second, first, j, i
            else:
                continue
            contact = lower.polygon.intersection(upper.polygon)
            if contact.area < 1e-7:
                continue
            covered[(li, True)].append(contact)
            covered[(ui, False)].append(contact)
            patches = [
                patch for p in polygon_components(contact) for patch in horizontal_patches(p)
            ]
            if lower.zone == upper.zone:
                if upper.kind == "main" and lower.zone_kind != "stairwell":
                    masses.append(
                        dict(
                            name=f"{lower.identifier}_{upper.identifier}_slab",
                            zone=lower.zone,
                            area_m2=contact.area,
                            part_id=lower.part.identifier,
                            elevation_m=lower.top,
                            storey=lower.storey,
                            vertices=[horizontal_vertices(p, lower.top) for p in patches],
                        )
                    )
                continue
            role = "top" if "attic" in (lower.kind, upper.kind) else "intermediate_floor"
            if "basement" in (lower.kind, upper.kind) and lower.conditioned != upper.conditioned:
                role = "basement_ceiling"
            for pi, patch in enumerate(patches):
                for cell, up in ((lower, True), (upper, False)):
                    reverse = (not up) if role == "top" else up
                    suffix = f"{'ceiling' if up else 'floor'}_contact_{li}_{ui}_{pi}"
                    add(
                        cell,
                        horizontal_vertices(patch, lower.top, up),
                        "Ceiling" if up else "Floor",
                        role + ("_reverse" if reverse else ""),
                        "Surface",
                        suffix,
                        area=patch.area,
                    )
    # 4. Resolve exposed horizontal remnants and wall bands at all neighbour cuts.
    for i, cell in enumerate(cells):
        for up, height in ((False, cell.bottom), (True, cell.top)):
            remainder = cell.polygon.difference(unary_union(covered[(i, up)]))
            patches = [
                patch for p in polygon_components(remainder) for patch in horizontal_patches(p)
            ]
            for pi, patch in enumerate(patches):
                boundary = "Outdoors" if up else "Ground"
                role = ("weather_shell" if cell.kind == "attic" else "top") if up else "ground"
                if not cell.conditioned and role in ("top", "ground"):
                    role = "unconditioned_" + role
                add(
                    cell,
                    horizontal_vertices(patch, height, up),
                    "Roof" if up else "Floor",
                    role,
                    boundary,
                    f"{'ceiling' if up else 'floor'}_{pi}",
                    area=patch.area,
                )
        neighbors = [cells[j] for j in tree.query(cell.polygon, predicate="intersects") if j != i]
        levels = sorted(
            {
                cell.bottom,
                cell.top,
                *(z for c in cells for z in (c.bottom, c.top) if cell.bottom < z < cell.top),
            }
        )
        for ei, (_, a, b) in enumerate(facade_edges(cell.polygon, cell.part.identifier)):
            line = LineString([a, b])
            near = [points[j] for j in point_tree.query(line.buffer(1e-7))]
            fid = next(
                (
                    fid
                    for fid, original in original_edges[cell.part.identifier]
                    if line.difference(original.buffer(1e-7)).length < 1e-7
                ),
                "",
            )
            for si, (start, end) in enumerate(_segments(a, b, near)):
                edge = LineString([start, end])
                midpoint = edge.interpolate(0.5, normalized=True)
                for zi, (bottom, top) in enumerate(zip(levels, levels[1:])):
                    adjacent = [
                        c
                        for c in neighbors
                        if c.bottom <= bottom + GRID
                        and c.top >= top - GRID
                        and c.polygon.boundary.distance(midpoint) < 1e-7
                    ]
                    if len(adjacent) > 1:
                        raise ValueError("Ambiguous shared-edge ownership")
                    other = adjacent[0] if adjacent else None
                    if other and other.zone == cell.zone:
                        continue
                    role = "weather_shell" if cell.kind == "attic" else "wall"
                    boundary = "Outdoors"
                    if other:
                        boundary = "Surface"
                        if cell.conditioned == other.conditioned:
                            kinds = {cell.zone_kind, other.zone_kind}
                            role = (
                                "dwelling_partition"
                                if kinds == {"dwelling"}
                                else "common_partition"
                                if kinds & {"dwelling", "common", "stairwell"}
                                else "partition"
                            )
                        else:
                            role = "wall" if cell.conditioned else "wall_reverse"
                    elif fid in party:
                        boundary = "Adiabatic"
                    elif cell.kind == "basement":
                        boundary, role = "Ground", "basement_wall"
                    if not cell.conditioned and not other and role in ("wall", "basement_wall"):
                        role = "unconditioned_" + role
                    surface = add(
                        cell,
                        wall_vertices(start, end, bottom, top),
                        "Wall",
                        role,
                        boundary,
                        f"wall_{ei}_s{si}_z{zi}",
                        facade_id=fid,
                        area=edge.length * (top - bottom),
                    )
                    if boundary == "Adiabatic":
                        surface.annotations.append(
                            "assumed adiabatic party wall: " + party[fid].neighbor_id
                        )
                    if boundary == "Outdoors" and not fid:
                        raise ValueError("Generated internal partition could not be paired")
    # 5. Pair reciprocal faces by common coordinates, requiring exactly two owners.
    coincident = {}
    for surface in surfaces:
        if surface.boundary == "Surface":
            key = tuple(sorted(tuple(round(x / GRID) for x in v) for v in surface.vertices))
            coincident.setdefault(key, []).append(surface)
    for pair in coincident.values():
        if len(pair) != 2:
            raise ValueError(
                "Shared surface lacks exactly one reciprocal face: "
                + ", ".join(s.name for s in pair)
            )
        pair[0].adjacent, pair[1].adjacent = pair[1].name, pair[0].name
        if pair[0].construction in ("dwelling_partition", "common_partition"):
            pair[1].construction += "_reverse"
    # 6. Record enclosure assumptions before replacing provisional pitched attic shells.
    approximations = []
    complex_enclosure = any(
        p.interiors or abs(p.convex_hull.area - p.area) > 1e-6 for p in polygons
    )
    for zone in zones:
        zone_cells = [c for c in cells if c.zone == zone]
        shape = unary_union([c.polygon for c in zone_cells])
        if shape.geom_type == "Polygon" and (
            shape.interiors or abs(shape.convex_hull.area - shape.area) > 1e-6
        ):
            complex_enclosure = True
        if len({c.part.storey_elevations_m[-1] for c in zone_cells}) > 1:
            complex_enclosure = True
    if complex_enclosure:
        approximations.append(
            "EnergyPlus approximate interior view factors in a nonconvex or unequal-height enclosure"
        )
    graph = SurfaceGraph(surfaces, zones, masses, valid_facades, approximations)
    from .roofs import apply_roofs

    graph = apply_roofs(spec, polygons, graph)
    for surface in graph.surfaces:
        surface.vertices = [(round(x, 8), round(y, 8), z) for x, y, z in surface.vertices]
    return graph
