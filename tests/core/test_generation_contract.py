"""Generation and serialization invariants independent of EnergyPlus results."""

import copy
from dataclasses import replace

import numpy as np
import pytest

from epsm_core import CompilerSettings, EnergyPlusCompiler, HourlyOutputRequest
from epsm_core.context import mirror_suppression_eligibility, resolve_context, synthetic_context
from epsm_core.pipeline import resolve_geometry
from epsm_core.surface_checks import properties, validate_surfaces, vertices
from epsm_core.vertex_order import upper_left_vertices


@pytest.mark.parametrize("angle", [0, 37, 90])
def test_shared_vertex_identity_and_serialization(building, energyplus, angle):
    building = building.updated(geometry=building.geometry.updated(orientation_deg=angle))
    scene = resolve_geometry(building, panelize=True)
    identities = {}
    for surface in scene.graph.surfaces:
        for point in surface.vertices:
            assert identities.setdefault(tuple(point), point) is point
    model, report = EnergyPlusCompiler(energyplus).compile(building)
    for face in scene.graph.surfaces:
        output = vertices(model["BuildingSurface:Detailed"][face.name])
        assert any(
            np.array_equal(output, np.roll(face.vertices, i, axis=0))
            for i in range(len(face.vertices))
        )
    original = copy.deepcopy(model)
    validate_surfaces(model, report.data["zones"])
    assert model == original
    for category in (
        "BuildingSurface:Detailed",
        "FenestrationSurface:Detailed",
        "Shading:Building:Detailed",
    ):
        for obj in model.get(category, {}).values():
            assert np.array_equal(vertices(obj), upper_left_vertices(vertices(obj)))
    assert model == original


@pytest.mark.parametrize("seed", [0, 17, 41])
def test_context_radius_is_nested_boundary_distance(building, seed):
    geometry = building.geometry
    previous = {}
    target = geometry.parts[0].footprint.polygon
    for radius in (80, 120, 160, 240):
        context = synthetic_context(
            geometry, "urban_highrise_dense", seed=seed, radius_m=radius, max_buildings=1024
        )
        current = {b.identifier: b for b in context.buildings}
        assert all(current[name] == old for name, old in previous.items())
        assert all(target.distance(b.footprints[0].polygon) <= radius for b in context.buildings)
        assert context.generation["generator_version"] == "nested_grid_v2"
        previous = current


def test_mirror_proof_refuses_open_shell_and_standalone(building):
    context = synthetic_context(building.geometry, "rural", radius_m=80)
    resolved = resolve_context(building.geometry, context)
    assert mirror_suppression_eligibility(resolved)["mirror_suppression_eligible"]
    opened = replace(resolved, surfaces=tuple(s for s in resolved.surfaces if s.kind != "Floor"))
    assert not mirror_suppression_eligibility(opened)["mirror_suppression_eligible"]
    proof = mirror_suppression_eligibility(resolved, [object()])
    assert not proof["mirror_suppression_eligible"]
    assert proof["unqualified_surface_count"] == 1


def test_output_normalization_and_lean_contract(building, energyplus):
    a = HourlyOutputRequest(name=" Zone Mean Air Temperature ", key="zone")
    b = HourlyOutputRequest(name="zone mean air temperature", key="ZONE")
    assert CompilerSettings(hourly_outputs=(a, b)).hourly_outputs == (a,)
    compiler = EnergyPlusCompiler(energyplus)
    model, report = compiler.compile(building)
    assert model["Output:SQLite"]["sql"]["option_type"] == "Simple"
    assert "Output:Table:SummaryReports" not in model
    assert "Output:VariableDictionary" not in model
    assert all(
        not o["variable_name"].startswith("Surface ") for o in model["Output:Variable"].values()
    )
    assert report.data["serialized_geometry_sha256"]
    assert model["Timestep"]["timestep"]["number_of_timesteps_per_hour"] == 6


@pytest.mark.parametrize(
    "name,value",
    [
        ("shadow_max_figures", 1000000),
        ("reporting_profile", "surrogate"),
        ("diagnostic_policy", "strict"),
        ("shadow_geometry_recovery", "none"),
    ],
)
def test_removed_settings_rejected(name, value):
    with pytest.raises(ValueError):
        CompilerSettings(**{name: value})


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0, 0), (1e-8, 0, 0), (1, 1, 0)],
        [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0)],
        [(0, 0, 0), (1, 0, 0), (1, 1, 0.1), (0, 1, 0)],
    ],
)
def test_degenerate_faces_fail_read_only(points):
    original = copy.deepcopy(points)
    with pytest.raises(ValueError):
        properties(np.asarray(points, dtype=float))
    assert points == original


def test_location_mismatch_rejected(building, energyplus):
    with pytest.raises(ValueError, match="Site:Location differs"):
        EnergyPlusCompiler(energyplus).compile(
            building.updated(
                climate=building.climate.updated(latitude_deg=building.climate.latitude_deg + 1)
            )
        )


def test_shadow_capacity_fails_once_and_preserves_model(
    building, energyplus, tmp_path, monkeypatch
):
    import hashlib
    import json
    import subprocess

    from epsm_core.runner import EnergyPlusRunner, SimulationError

    runner = EnergyPlusRunner(energyplus)
    attempts = []

    def execute(command, **kwargs):
        path = kwargs["cwd"]
        attempts.append(hashlib.sha256((path / "model.epJSON").read_bytes()).hexdigest())
        assert kwargs["env"]["OMP_NUM_THREADS"] == "1"
        (path / "eplusout.err").write_text(
            " ** Warning ** Too many figures [>=15000] in a shadow overlap\n"
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("epsm_core.runner.subprocess.run", execute)
    target = tmp_path / "run"
    with pytest.raises(SimulationError) as error:
        runner.run(building, target)
    assert error.value.code == "SHADOW_COMPLEXITY_LIMIT"
    assert attempts == [hashlib.sha256((target / "model.epJSON").read_bytes()).hexdigest()]
    assert not (target / "preview").exists()
    assert not (target / "result.json").exists()
    diagnostics = json.loads((target / "diagnostics.json").read_text())
    assert diagnostics["failure_code"] == "SHADOW_COMPLEXITY_LIMIT"
    assert (
        diagnostics["shadow_complexity"]["maximum_figures_in_shadow_overlap_calculations"]
        == 1_000_000
    )


def test_weather_missing_required_field_fails_without_substitution(building, tmp_path):
    from pathlib import Path

    from epsm_core.weather import validate_epw_calendar

    lines = Path(building.climate.epw_path).read_text().splitlines()
    row = lines[8].split(",")
    row[6] = "99.9"
    lines[8] = ",".join(row)
    path = tmp_path / "missing-weather.epw"
    path.write_text("\n".join(lines) + "\n")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="dry bulb"):
        validate_epw_calendar(path, building.climate.calendar_year)
    assert path.read_bytes() == original
