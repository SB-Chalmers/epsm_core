import json
import sqlite3
import subprocess
from pathlib import Path

import numpy as np
import pytest

from epsm_core import EnergyPlusCompiler
from epsm_core.surface_checks import properties, vertices
from epsm_core.vertex_order import upper_left_vertices


@pytest.mark.parametrize('angle', [0, 37, 181])
@pytest.mark.parametrize('translation', [(0, 0, 0), (125000, -83000, 19)])
def test_export_start_is_cyclic_invariant_and_preserves_geometry(angle, translation):
    theta = np.radians(angle)
    rotation = np.array([[np.cos(theta), -np.sin(theta), 0],
                         [np.sin(theta), np.cos(theta), 0], [0, 0, 1]])
    parent = np.array([[0., 0, 0], [10, 0, 0], [10, 0, 3], [0, 0, 3]]) @ rotation.T + translation
    child = np.array([[2., 0, 1], [8, 0, 1], [8, 0, 2], [2, 0, 2]]) @ rotation.T + translation
    for points in (parent, child):
        expected = upper_left_vertices(points)
        assert expected[0, 2] == points[:, 2].max()
        for start in range(4):
            actual = upper_left_vertices(np.roll(points, start, axis=0))
            np.testing.assert_array_equal(actual, expected)
            assert {tuple(p) for p in actual} == {tuple(p) for p in points}
            assert properties(actual)[0] == pytest.approx(properties(points)[0])
            np.testing.assert_allclose(properties(actual)[1], properties(points)[1], atol=1e-8)
    assert properties(upper_left_vertices(parent))[1] @ properties(upper_left_vertices(child))[1] > 1-1e-8


@pytest.mark.parametrize('normal_sign', [1, -1])
def test_horizontal_export_start_is_stable(normal_sign):
    points = np.array([[0., 0, 3], [10, 0, 3], [10, 5, 3], [0, 5, 3]])[::normal_sign]
    expected = upper_left_vertices(points)
    np.testing.assert_array_equal(expected[0], [0 if normal_sign == 1 else 10, 5, 3])
    for start in range(4):
        np.testing.assert_array_equal(upper_left_vertices(np.roll(points,start,axis=0)), expected)


@pytest.mark.energyplus
def test_partial_parent_shadow_fully_shades_contained_window(building, energyplus, tmp_path):
    weather = Path(building.climate.epw_path)
    if weather.stat().st_size < 10000:
        pytest.skip('Full weather fixture unavailable')
    model, _ = EnergyPlusCompiler(energyplus).compile(building)
    windows = model['FenestrationSurface:Detailed']
    name, window = next((k,v) for k,v in windows.items()
                        if properties(vertices(v))[1][1] < -0.99 and vertices(v)[:,2].max()<3)
    v=vertices(window)
    # A close opaque panel covers only the central window, leaving most of its
    # parent wall sunlit. This catches mismatched parent/child local origins.
    shade=np.array([[v[:,0].min()-1,-.01,v[:,2].max()+1],
                    [v[:,0].min()-1,-.01,0],
                    [v[:,0].max()+1,-.01,0],
                    [v[:,0].max()+1,-.01,v[:,2].max()+1]])
    model['Shading:Building:Detailed']={'test_panel':dict(number_of_vertices=4,vertices=[
        {f'vertex_{a}_coordinate':float(n) for a,n in zip('xyz',p)} for p in shade])}
    model['ShadowCalculation']={'test':dict(shading_calculation_method='PolygonClipping',
        shading_calculation_update_frequency_method='Timestep')}
    period=next(iter(model['RunPeriod'].values()))
    period.update(begin_month=1,begin_day_of_month=20,end_month=1,end_day_of_month=20)
    model['Output:Variable']={'sunlit':dict(key_value='*',variable_name='Surface Outside Face Sunlit Fraction',reporting_frequency='Timestep')}
    path=tmp_path/'model.epJSON';path.write_text(json.dumps(model))
    with (tmp_path/'engine.log').open('w') as log:
        result=subprocess.run([str(energyplus),'-w',str(weather),'-d',str(tmp_path),str(path)],
                              stdout=log,stderr=subprocess.STDOUT,timeout=120)
    assert result.returncode == 0
    with sqlite3.connect(tmp_path/'eplusout.sql') as db:
        rows=dict(db.execute('''SELECT d.KeyValue,r.Value FROM ReportData r
          JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
          JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
          WHERE e.EnvironmentType=3 AND COALESCE(t.WarmupFlag,0)=0 AND t.Hour=12 AND t.Minute=0
          AND d.Name='Surface Outside Face Sunlit Fraction' ''').fetchall())
    assert rows[name.upper()] < .001
    assert rows[window['building_surface_name'].upper()] > .1
