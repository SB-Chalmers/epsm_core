"""Optional notebook display, using the same offline scene as the browser viewer."""

from pathlib import Path


def _widget_type():
    try:
        import anywidget
        import traitlets
    except ImportError as error:
        raise ImportError("Install epsm_core[notebook] to display embedded 3D widgets") from error

    class GeometryWidget(anywidget.AnyWidget):
        """Independent WebGL scene; selected_surface is synchronized back to Python.

        ``close()`` releases the widget view and its renderer. Assets and scene data
        travel through the kernel, so the browser need not reach a loopback server.
        """

        _esm = Path(__file__).with_name("viewer_assets") / "widget.js"
        scene = traitlets.Dict().tag(sync=True)
        height = traitlets.Int(600, min=200, max=4000).tag(sync=True)
        selected_surface = traitlets.Unicode("").tag(sync=True)

    return GeometryWidget


def __getattr__(name):
    if name == "GeometryWidget":
        cls = _widget_type()
        globals()[name] = cls
        return cls
    raise AttributeError(name)


def scene_widget(scene, *, height=600):
    """Wrap a viewer_data payload without writing files or starting a server."""
    cls = globals().get("GeometryWidget") or __getattr__("GeometryWidget")
    return cls(scene=scene, height=height)


def geometry_widget(geometry, *, facade=None, context=None, height=600):
    """Resolve a metric GeometrySpec into a geometry-only notebook scene."""
    from .inspection import geometry_scene
    from .viewer import viewer_data

    model, report = geometry_scene(geometry, facade=facade, context=context)
    return scene_widget(viewer_data(model, report), height=height)
