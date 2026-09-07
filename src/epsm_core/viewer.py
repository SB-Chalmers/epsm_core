# File: viewer.py
# Purpose: Offline epJSON viewer, serving an explicit artifact allowlist on loopback only.
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
#   2026-09-06 - Document viewer interfaces, examples, constraints and processing rationale.

"""Offline epJSON viewer, serving an explicit artifact allowlist on loopback only.

Notes
-----
The viewer triangulates explicit World-coordinate artifacts and retains original
identity, construction and diagnostic metadata. It serves only a token-prefixed, in-
memory allowlist on loopback. Generated artifacts persist after the ViewerHandle closes.

Examples
--------
Replace example paths with existing local inputs; output paths must be writable.

Example::

    from epsm_core.viewer import view_epjson

    with view_epjson("output/run/model.epJSON", launch_browser=False) as handle:
        print(handle.url)
"""

import json
import mimetypes
import secrets
import shutil
import tempfile
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

import numpy as np
from shapely import constrained_delaunay_triangles, unary_union
from shapely.geometry import Polygon

from .surface_checks import properties, vertices

ASSETS = Path(__file__).with_name("viewer_assets")


def viewer_data(model, report=None, diagnostics=None, preparation=None):
    """Triangulate world-coordinate epJSON surfaces into an offline viewer payload.

    Parameters
    ----------
    model : dict
        EnergyPlus epJSON object mapping keyed by object type and name.
    report : dict or None
        Decoded CompilationReport.data mapping; None supplies no compilation metadata.
        Default: ``None``.
    diagnostics : dict
        Structured acceptance decisions and original diagnostic evidence. Default: ``None``.
    preparation : dict or None
        Serialized geometry-preparation artifact used for source/cleaned overlays. Default:
        ``None``.

    Returns
    -------
    dict
        Render objects, reports, diagnostics, preparation and internal mass.

    Raises
    ------
    ValueError
        Rejected conditions: Viewer currently requires World epJSON coordinates; convert
        relative coordinates first.

    Notes
    -----
    Subtracts windows from parent surfaces before triangulation. Requires World coordinates;
    relative-coordinate conversion is not inferred. InternalMass visual slabs are explicitly
    marked as visualization rather than thermal boundaries.

    Examples
    --------
    Example::

        from epsm_core.viewer import viewer_data

        assert viewer_data({})["objects"] == []
    """

    # 1. Triangulate world-coordinate epJSON surfaces into an offline viewer payload.
    report = report or {}
    objects = []
    rules = next(iter(model.get("GlobalGeometryRules", {}).values()), {})
    if rules.get("coordinate_system", "World") != "World":
        raise ValueError(
            "Viewer currently requires World epJSON coordinates; convert relative coordinates first"
        )
    openings = {}
    for name, obj in model.get("FenestrationSurface:Detailed", {}).items():
        openings.setdefault(obj["building_surface_name"], []).append((name, obj))

    # 2. Subtract openings in a local surface plane before world-space triangulation.
    def render_object(name, obj, kind, holes=(), parent=None):
        """Append one renderable surface with opening cutouts and audit metadata.

        Parameters
        ----------
        name : str
            Identifier or field name interpreted by the current operation.
        obj : dict
            One epJSON surface or opening object with coordinate fields.
        kind : str
            Surface, object or region classification consumed by the enclosing builder.
        holes : sequence of tuple
            Named opening objects to subtract from the parent polygon. Default: ``()``.
        parent : str
            Related surface identity; reciprocal neighbour or thermal parent according to the
            operation. Default: ``None``.

        Returns
        -------
        None
            Adds a record to the enclosing objects list.

        Raises
        ------
        ValueError
            If the input or generated result violates the constraints described in Notes.

        Notes
        -----
        Projects into an orthonormal local plane to preserve area; triangle vertices are then
        lifted to world coordinates. Reads construction and zone details from the enclosing
        report.

        Examples
        --------
        Within the enclosing operation, after its captured state has been initialized::

            render_object("wall", model["BuildingSurface:Detailed"]["wall"], "surface")
        """

        # 1. Append one renderable surface with opening cutouts and audit metadata.
        v = vertices(obj).astype(float)
        area, normal, _ = properties(v)
        u = v[1] - v[0]
        u /= np.linalg.norm(u)
        w = np.cross(normal, u)

        def project(points):
            """Project world points into the current surface's orthonormal plane.

            Parameters
            ----------
            points : sequence
                Coordinates or Shapely points in the frame expected by the geometric helper.

            Returns
            -------
            list of tuple
                Local two-dimensional coordinates in metres.

            Notes
            -----
            The enclosing surface supplies origin and two in-plane unit vectors. Inputs must already
            be coplanar for a faithful representation.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                project(vertices(obj))
            """

            return [(float((p - v[0]) @ u), float((p - v[0]) @ w)) for p in points]

        shape = Polygon(project(v)).difference(
            unary_union([Polygon(project(vertices(h))) for _, h in holes])
        )
        if not shape.is_valid:
            raise ValueError(f"Invalid opening coverage for epJSON object {name}")
        triangles = []
        for triangle in constrained_delaunay_triangles(shape).geoms:
            for x, y in list(triangle.exterior.coords)[:3]:
                triangles.extend((v[0] + x * u + y * w).tolist())
        metadata = dict(report.get("surfaces", {}).get(parent or name, {}))
        metadata.update(report.get("openings", {}).get(name, {}))
        metadata.update(report.get("shading", {}).get(name, {}))
        zone = metadata.get("zone", obj.get("zone_name"))
        metadata.update(
            {
                k: v
                for k, v in report.get("zones", {}).get(zone, {}).items()
                if k in ("zone_kind", "apartment_type")
            }
        )
        role = obj.get("construction_name", "")
        construction = report.get("constructions", {}).get(role.removesuffix("_reverse"), {})
        raw_construction = model.get("Construction", {}).get(role, {})
        layers = [
            dict(
                name=n,
                **model.get("Material", {}).get(
                    n, model.get("WindowMaterial:SimpleGlazingSystem", {}).get(n, {})
                ),
            )
            for n in raw_construction.values()
        ]
        objects.append(
            dict(
                name=name,
                kind=kind,
                parent=parent,
                vertices=v.tolist(),
                triangles=triangles,
                normal=normal.tolist(),
                area_m2=area,
                net_area_m2=shape.area,
                metadata=metadata,
                boundary=obj.get("outside_boundary_condition"),
                zone=zone,
                construction_name=role,
                layers=layers,
                construction_report=construction,
                epjson=obj,
            )
        )

    # 3. Preserve object identity across opaque faces, panes and shading geometry.
    for name, obj in model.get("BuildingSurface:Detailed", {}).items():
        render_object(name, obj, "surface", openings.get(name, []))
    for name, obj in model.get("FenestrationSurface:Detailed", {}).items():
        render_object(name, obj, "opening", parent=obj["building_surface_name"])
    for name, obj in model.get("Shading:Building:Detailed", {}).items():
        render_object(name, obj, report.get("shading", {}).get(name, {}).get("kind", "context"))
    # 4. Mark physical slab visuals explicitly so they cannot be mistaken for thermal faces.
    for mass in report.get("internal_mass", []):
        for i, v in enumerate(mass.get("vertices", [])):
            name = mass["name"] + f"_visual_{i}"
            obj = dict(
                vertices=[
                    dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z)
                    for x, y, z in v
                ],
                construction_name="internal_slab_face_a",
                zone_name=mass["zone"],
                surface_type="Floor",
            )
            render_object(name, obj, "slab_visual")
            objects[-1]["metadata"].update(
                representation="visualization of InternalMass; not a thermal boundary",
                storey=mass.get("storey", 0) + 1,
                part_id=mass["part_id"],
            )
    return dict(
        objects=objects,
        report=report,
        diagnostics=diagnostics or {},
        preparation=preparation,
        internal_mass=model.get("InternalMass", {}),
    )


def write_viewer(epjson_path, directory):
    """Write a self-contained viewer bundle beside explicit simulation artifacts.

    Parameters
    ----------
    epjson_path : str or Path
        Existing epJSON file whose geometry is to be inspected.
    directory : str or Path or None
        Local artifact directory; consult Notes for creation, overwrite and default-path
        behavior.

    Returns
    -------
    Path
        Output directory containing assets and model.json.

    Notes
    -----
    Reads adjacent compilation, diagnostics and preparation JSON when available. Copies
    bundled assets and overwrites model.json; it does not start a server.

    Examples
    --------
    Replace example paths with existing local inputs; output paths must be writable.

    Example::

        from epsm_core.viewer import write_viewer

        directory = write_viewer("output/run/model.epJSON", "output/run/preview")
    """

    # 1. Write a self-contained viewer bundle beside explicit simulation artifacts.
    epjson_path, directory = Path(epjson_path), Path(directory)
    model = json.loads(epjson_path.read_text())

    def adjacent(name):
        """Read an optional JSON artifact beside the enclosing epJSON input.

        Parameters
        ----------
        name : str
            Identifier or field name interpreted by the current operation.

        Returns
        -------
        dict
            Parsed artifact, or an empty mapping when absent.

        Notes
        -----
        Malformed JSON still raises; only missing files receive an empty fallback.

        Examples
        --------
        Within the enclosing operation, after its captured state has been initialized::

            adjacent("diagnostics.json")
        """

        p = epjson_path.parent / name
        return json.loads(p.read_text()) if p.exists() else {}

    report = adjacent("compilation.json")
    if "report_json" in report:
        report = json.loads(report["report_json"])
    payload = viewer_data(
        model, report, adjacent("diagnostics.json"), adjacent("geometry-preparation.json")
    )
    # 2. Copy local bundled assets and emit a finite JSON payload for offline rendering.
    directory.mkdir(parents=True, exist_ok=True)
    for path in ASSETS.iterdir():
        if path.is_file():
            shutil.copyfile(path, directory / path.name)
    (directory / "model.json").write_text(json.dumps(payload, allow_nan=False))
    return directory


@dataclass
class ViewerHandle:
    """Own a local preview URL, generated directory, server and worker thread.

    Attributes
    ----------
    url : str
        Tokenized loopback URL while the viewer server is running.  Required at
        construction.
    directory : Path
        Local artifact directory; consult Notes for creation, overwrite and default-path
        behavior.  Required at construction.
    _server : object
        Owned HTTP server or serving thread, released by ViewerHandle.close.  Required at
        construction.
    _thread : object
        Owned HTTP server or serving thread, released by ViewerHandle.close.  Required at
        construction.

    Notes
    -----
    Use a with block or close to release server resources. Closing retains generated
    artifacts. The tokenized URL is valid only while the server is running.

    Examples
    --------
    Replace example paths with existing local inputs; output paths must be writable.

    Example::

        from epsm_core.viewer import view_epjson

        with view_epjson("output/run/model.epJSON", launch_browser=False) as handle:
            print(handle.url)
    """

    url: str
    directory: Path
    _server: object
    _thread: object

    def close(self):
        """Stop the preview server, release its socket and join its worker thread.

        Returns
        -------
        None
            Shuts down resources owned by this handle.

        Notes
        -----
        Waits up to five seconds for the thread. Generated files are retained for inspection;
        call from the client thread, not the serving thread.

        Examples
        --------
        Supply a live ViewerHandle as ``handle`` from view_epjson.

        Example::

            handle.close()
        """

        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def __enter__(self):
        """Return this handle for deterministic context-managed cleanup.

        Returns
        -------
        ViewerHandle
            This same live handle.

        Notes
        -----
        Entering does not create a second server. __exit__ closes the existing one.

        Examples
        --------
        Supply a live ViewerHandle as ``handle`` from view_epjson.

        Example::

            with handle as active:
                print(active.url)
        """

        return self

    def __exit__(self, *args):
        """Close the viewer when leaving a with block.

        Parameters
        ----------
        *args : tuple
            Exception type, value and traceback supplied by the context manager protocol.

        Returns
        -------
        None
            Exceptions from the with block are not suppressed.

        Notes
        -----
        Cleanup runs for both successful and exceptional exits.

        Examples
        --------
        Supply a live ViewerHandle as ``handle`` from view_epjson.

        Example::

            with handle:
                print(handle.url)
        """

        self.close()

    def __str__(self):
        """Represent the handle as its tokenized loopback URL.

        Returns
        -------
        str
            URL that can be opened in a browser.

        Notes
        -----
        The URL remains useful only while the associated server is running.

        Examples
        --------
        Supply a live ViewerHandle as ``handle`` from view_epjson.

        Example::

            assert str(handle) == handle.url
        """

        return self.url


def view_epjson(path, *, directory=None, launch_browser=True):
    """Write and serve an allowlisted snapshot through a tokenized loopback URL.

    Parameters
    ----------
    path : str or Path
        Local input file path; the operation never downloads missing input.
    directory : str or Path or None
        Local artifact directory; consult Notes for creation, overwrite and default-path
        behavior. Default: ``None``.
    launch_browser : bool
        Open the default browser when true; the returned server still needs cleanup.
        Default: ``True``.

    Returns
    -------
    ViewerHandle
        Live preview handle that must be closed.

    Notes
    -----
    Binds 127.0.0.1 on an ephemeral port and starts a daemon thread. Only allowlisted
    regular nonsymlink artifacts are snapshotted; source siblings are excluded. Browser
    launch is optional, and generated files persist after shutdown.

    Examples
    --------
    Replace example paths with existing local inputs; output paths must be writable.

    Example::

        from epsm_core.viewer import view_epjson

        with view_epjson("output/run/model.epJSON", launch_browser=False) as handle:
            print(handle.url)
    """

    # 1. Write and serve an allowlisted snapshot through a tokenized loopback URL.
    directory = write_viewer(path, directory or tempfile.mkdtemp(prefix="epsm-preview-"))
    # Snapshot only generated artifacts. Never expose source siblings or symlinks.
    # 2. Snapshot only allowlisted regular files; never serve source siblings or symlinks.
    allowed = {
        p.name: p.read_bytes()
        for p in directory.iterdir()
        if p.name in {a.name for a in ASSETS.iterdir()} | {"model.json"}
        and p.is_file()
        and not p.is_symlink()
    }
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        """Serve only the enclosing viewer's token-prefixed in-memory artifact snapshot.

        Notes
        -----
        Instantiated by ThreadingHTTPServer per connection. It does not expose arbitrary
        filesystem paths or log requests to stderr; unknown paths return 404.

        Examples
        --------
        Within the enclosing operation, after its captured state has been initialized::

            # ThreadingHTTPServer creates Handler when a browser requests handle.url.
        """

        def do_GET(self):
            """Serve an allowlisted snapshot file under the enclosing random URL prefix.

            Returns
            -------
            None
                Writes an HTTP response to the request stream.

            Notes
            -----
            Unknown paths return 404. Responses disable MIME sniffing and caching; query strings do
            not participate in file selection.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                # A browser GET to handle.url serves index.html through this method.
            """

            # 1. Serve an allowlisted snapshot file under the enclosing random URL prefix.
            path = urlsplit(self.path).path
            prefix = "/" + token + "/"
            filename = path[len(prefix) :] or "index.html" if path.startswith(prefix) else None
            if filename not in allowed:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header(
                "Content-Type", mimetypes.guess_type(filename)[0] or "application/octet-stream"
            )
            self.send_header("Content-Length", str(len(allowed[filename])))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(allowed[filename])

        def log_message(self, *args):
            """Suppress default request logging for the local preview server.

            Parameters
            ----------
            *args : tuple
                HTTP server log format and arguments, deliberately ignored.

            Returns
            -------
            None
                Intentionally emits no request log.

            Notes
            -----
            The HTTP handler supplies formatting arguments; application diagnostics remain in the
            generated artifacts.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                # BaseHTTPRequestHandler calls log_message during a handled request.
            """

            pass

    # 3. Bind an ephemeral loopback port and return an explicitly closeable handle.
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    handle = ViewerHandle(
        f"http://127.0.0.1:{server.server_port}/{token}/", directory, server, thread
    )
    if launch_browser:
        webbrowser.open(handle.url)
    return handle


def widget_epjson(path, *, height=600):
    """Display compiled World-coordinate epJSON inline; requires epsm_core[notebook].

    Reads adjacent reports and diagnostics, as the standalone viewer does. Does not
    start an HTTP server, launch a browser or run EnergyPlus.
    """
    from .notebook import scene_widget

    path = Path(path)

    def adjacent(name):
        file = path.parent / name
        return json.loads(file.read_text()) if file.exists() else {}

    report = adjacent("compilation.json")
    if "report_json" in report:
        report = json.loads(report["report_json"])
    return scene_widget(
        viewer_data(
            json.loads(path.read_text()), report,
            adjacent("diagnostics.json"), adjacent("geometry-preparation.json"),
        ),
        height=height,
    )
