"""Notebook scenes retain the same geometry contract as the standalone viewer."""
import json
import subprocess
import sys

import pytest

from epsm_core import Footprint, GeometrySpec
from epsm_core.inspection import geometry_scene
from epsm_core.viewer import viewer_data, widget_epjson

pytest.importorskip("anywidget")


def test_widget_scene_and_independent_state():
    from epsm_core.notebook import GeometryWidget

    geometry = GeometrySpec.from_footprint(Footprint.rectangle(12, 8), storeys=2, storey_height_m=3)
    first, second = geometry.widget(), geometry.widget(height=400)
    try:
        assert isinstance(first, GeometryWidget)
        model, report = geometry_scene(geometry)
        assert first.scene == viewer_data(model, report)
        assert first.model_id != second.model_id
        first.selected_surface = first.scene["objects"][0]["name"]
        assert second.selected_surface == ""
        assert first._repr_mimebundle_()[0]["application/vnd.jupyter.widget-view+json"]["model_id"]
        assert second.height == 400
    finally:
        first.close()
        second.close()


def test_compiled_widget_reads_reports(tmp_path):
    geometry = GeometrySpec.from_footprint(Footprint.rectangle(12, 8), storeys=1, storey_height_m=3)
    model, report = geometry_scene(geometry)
    path = tmp_path / "model.epJSON"
    path.write_text(json.dumps(model))
    (tmp_path / "compilation.json").write_text(json.dumps({"report_json": json.dumps(report)}))
    (tmp_path / "diagnostics.json").write_text(json.dumps({"accepted": False}))
    widget = widget_epjson(path)
    try:
        assert widget.scene["diagnostics"]["accepted"] is False
        assert widget.scene["report"] == json.loads(json.dumps(report))
    finally:
        widget.close()


def test_core_import_does_not_load_notebook_dependencies():
    subprocess.run([sys.executable, "-c", "import sys; import epsm_core; assert 'anywidget' not in sys.modules; assert 'ipywidgets' not in sys.modules"], check=True)


def test_widget_dependency_error_is_actionable(monkeypatch):
    from epsm_core import notebook
    import builtins

    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "anywidget":
            raise ImportError("missing")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(ImportError, match=r"epsm_core\[notebook\]"):
        notebook._widget_type()
