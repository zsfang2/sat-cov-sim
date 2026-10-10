from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
import yaml

from satellite_coverage.engine.direction_table import TerrainLocalSolver
from satellite_coverage.engine.terrain_context import TerrainContext
from satellite_coverage.experiments.direction_cache import break_even, recompose, full_pipeline, check_pipeline
from satellite_coverage.geometry.terrain import TerrainGrid


def setup():
    cfg = yaml.safe_load((Path(__file__).resolve().parents[1]/'configs/m2_e1.yaml').read_text())
    grid = TerrainGrid(np.zeros((41, 41)), -205, 205, 10, 'WGS84_ellipsoid', 'test', surface_type='synthetic')
    context = TerrainContext(grid, 0, 0, 150, 5, effective_radius_m=6371000, sampling_method='cell_intervals')
    receiver = dict(lon_deg=0, lat_deg=0, antenna_ellipsoid_height_m=2)
    solver = TerrainLocalSolver(context, receiver, frequency_hz=cfg['baseline']['frequency_hz'], slant_range_m=cfg['slant_range_m'])
    return cfg, context, receiver, solver


def test_actual_pipeline_recomposition_detects_component_error():
    cfg, context, receiver, solver = setup()
    params = cfg['baseline']
    response = solver.evaluate(params['azimuth_deg'], params['elevation_deg'])
    budget = recompose(response, params, cfg)
    record = full_pipeline(context, receiver, params, cfg)['records'][0]
    assert check_pipeline(record, response, budget, params, cfg)
    wrong = deepcopy(budget)
    wrong['components'][0]['quantity']['value'] += 1
    with pytest.raises(AssertionError, match='component'):
        check_pipeline(record, response, wrong, params, cfg)


def test_power_and_antenna_change_recompose_without_altering_local_loss():
    cfg, _, _, solver = setup()
    params = cfg['baseline']
    response = solver.evaluate(params['azimuth_deg'], params['elevation_deg'])
    original = deepcopy(response)
    a = recompose(response, params, cfg)
    b = recompose(response, dict(params, eirp_dbm=params['eirp_dbm']+10), cfg)
    c = recompose(response, dict(params, antenna='cosine'), cfg)
    assert b['received_power']['value']-a['received_power']['value'] == pytest.approx(10, abs=1e-6)
    assert c['received_power']['value']-a['received_power']['value'] == pytest.approx(c['receiver_gain_dbi']-a['receiver_gain_dbi'], abs=1e-6)
    assert response == original


def test_no_finite_break_even_is_explicit():
    assert break_even(10, .02, .01) == dict(status='finite', queries=1000)
    for query in (.02, .03):
        assert break_even(10, .02, query) == dict(status='no_finite_break_even', queries=None)
