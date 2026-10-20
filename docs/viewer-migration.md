# Display scene data with epsm_viewer

Core produces geometry and scientific metadata. The separate TypeScript-first
`epsm_viewer` repository owns browser rendering and an optional lightweight Python
display package. Studio owns adapters for its application. The viewer consumes
portable `epsm.scene/1` dictionaries and does not import Core.

## Install optional display tools

Install Core in the environment used by the example. Build the viewer's Python
wheel using that repository's instructions, then install the actual artifact:

```sh
python -m pip install '/path/to/epsm_viewer-<version>-py3-none-any.whl'
# For live notebook display, install the wheel with its optional notebook extra:
python -m pip install '/path/to/epsm_viewer-<version>-py3-none-any.whl[notebook]'
```

These are explicit local wheel paths, not package-index release promises. Core
does not load the viewer automatically, and no example adds a neighbouring
checkout to Python's import path. The demo notebook environment also needs
Core's documented notebook dependencies.

## Preview an authored geometry

```python
from epsm_core import Footprint, GeometrySpec
from epsm_viewer import scene_widget, view_scene, write_scene

geometry = GeometrySpec.from_footprint(
    Footprint.rectangle(12, 8), storeys=2, storey_height_m=3,
)
scene = geometry.scene()
assert scene["schema"] == "epsm.scene/1"

# Browser: writes a viewer bundle and serves it while the handle is open.
with view_scene(scene, directory="output/preview", launch_browser=False) as preview:
    print(preview.url)
    # Keep this context open while inspecting that URL.

# Notebook: display(widget) in a live notebook; close it when finished.
widget = scene_widget(scene, height=600)
# display(widget)
widget.close()

# Explicit static bundle for a caller-owned web server.
directory = write_scene(scene, directory="output/preview-bundle")
```

Use `geometry.scene(facade=..., context=...)` for supplied facade and neighbour
inputs. A missing facade explicitly previews zero glazing. `BuildingSpec.scene()`
and physical `Building.scene()` use their retained geometry, facade and context.
Draft preview does not require weather, EnergyPlus or complete energy readiness.

## Inspect a compiled model

Read the caller-selected files explicitly. `CompilationReport.data` can be passed
directly when it is already loaded; a stored compilation report may wrap that
mapping in `report_json`.

```python
import json
from pathlib import Path
from epsm_core import scene_data
from epsm_viewer import view_scene

run = Path("output/run")  # Existing caller-owned compilation artifacts.
model = json.loads((run / "model.epJSON").read_text())
report = json.loads((run / "compilation.json").read_text())
if "report_json" in report:
    report = json.loads(report["report_json"])
scene = scene_data(model, report)
with view_scene(scene, directory=run / "preview", launch_browser=False) as preview:
    print(preview.url)
```

Supply loaded diagnostics and geometry-preparation mappings to `scene_data` when
available. Displaying geometry does not run a simulation or establish acceptance.

## Removed Core display APIs

| Earlier Core operation | Replacement |
| --- | --- |
| `GeometrySpec.view`, `BuildingSpec.view`, `preview_geometry` | `view_scene(value.scene(), directory=...)` |
| `GeometrySpec.widget`, `BuildingSpec.widget` | `scene_widget(value.scene())` |
| `viewer_data(model, report, ...)` | `scene_data(model, report, ...)` |
| `widget_epjson`, `view_epjson`, `write_viewer` | Explicitly read artifacts, call `scene_data`, then use Viewer display helpers |
| `epsm-core view` | A Python call to `view_scene(scene_data(model, report), ...)` |

Core no longer bundles JavaScript, notebook widgets, browser launch or a loopback
server. Historical screenshots and dated validation records describe the version
that produced them; they are not evidence that the extracted viewer was tested.
