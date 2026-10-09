import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from satellite_coverage.config.pilot import identity
from satellite_coverage.engine import links
from satellite_coverage.engine.links import calculate_links
from satellite_coverage.data_sources.terrain_tiles import TerrainResourceError
from satellite_coverage.experiments.orbit_link import execute
from test_terrain_integration import config, context, raster, ROOT


def test_scope_at_every_extraction_level_and_unchanged_identity():
    terrain = context()
    data = config()
    result = calculate_links(data,terrain=terrain)
    expected = identity(dict(config_checksum=result['config_checksum'],terrain=terrain.descriptor(),
                             selection=result['selection']))
    assert result['physical_input_checksum'] == expected
    assert 'terrain_contract' not in terrain.descriptor()
    assert result['terrain_contract']['scope'] == 'finite_radius_conditional'
    query_ids = []
    for row in result['records']:
        contract = row['terrain_contract']
        power = row['budget']['received_power']
        assert contract['failure_kind'] is None
        assert power['status'] == 'known'
        assert power['terrain_contract']['full_path_status'] == 'not_verified'
        assert contract['radius_audit_status'] == 'not_attached'
        assert contract['audit_binding']['physical_input_checksum'] == expected
        assert contract['audit_binding']['terrain_grid_sha256'] == terrain.descriptor()['grid_sha256']
        assert contract['audit_binding']['receiver_ellipsoid_height_m'] == 2
        assert row['terrain']['terrain_contract']['radius_m'] == 150
        query_ids.append(contract['audit_binding']['query_id'])
    assert len(set(query_ids)) == len(query_ids)
    clear = calculate_links(data)
    assert 'terrain_contract' not in clear
    assert result['records'][0]['budget']['received_power']['value'] == pytest.approx(
        clear['records'][0]['budget']['received_power']['value']-result['records'][0]['terrain']['used_loss_db'])


@pytest.mark.parametrize('kind,expected', [('nodata','data_gap'),('receiver','data_gap'),
    ('zenith','unsupported_geometry'),('near','unsupported_geometry'),('below','not_applicable'),
    ('sampling','sampling_not_verified'),('component','component_unavailable')])
def test_failure_categories_preserve_formal_unavailability(kind, expected):
    data = config()
    heights = np.zeros((41,41))
    options = {}
    if kind == 'nodata': heights[10,20] = np.nan
    if kind == 'receiver': heights[20,20] = np.nan
    if kind in ('zenith','below','near'):
        for direction in data['source']['directions']:
            if kind == 'near': direction['slant_range_m'] = 10
            else: direction['elevation_deg'] = 90 if kind == 'zenith' else -10
    if kind == 'sampling':
        heights[10,:] = 102
        options['horizon_tolerance_deg'] = .1
    if kind == 'component':
        data['budget']['losses']['atmosphere'] = dict(enabled=True,status='unknown',value=None,reason='not available')
    result = calculate_links(data,terrain=context(heights,**options))
    row = result['records'][0]
    assert row['terrain_contract']['failure_kind'] == expected
    assert row['budget']['received_power']['status'] != 'known'
    assert row['terrain_contract']['full_path_status'] == 'not_verified'


def test_unavailable_or_failed_geometry_keeps_binding(monkeypatch):
    data = yaml.safe_load((ROOT/'configs/m1_tle.yaml').read_text())
    data['receiver'] = config()['receiver']
    monkeypatch.setattr(links,'select_tle',lambda *args: (None,{'policy':'past_only'},'no_tle_at_or_before_start'))
    result = calculate_links(data,terrain=context())
    assert result['records'][0]['terrain_contract']['failure_kind'] == 'upstream_unavailable'
    assert result['records'][0]['terrain_contract']['audit_binding']['azimuth_deg'] is None
    def broken(*args):
        raise ValueError('controlled solver failure')
    monkeypatch.setattr(links,'input_geometry',broken)
    row = calculate_links(config(),terrain=context())['records'][0]
    assert row['terrain_contract']['failure_kind'] == 'solver_failure'


def test_far_ridge_never_upgrades_full_path():
    heights = np.zeros((41,41))
    heights[3,:] = 200
    short = calculate_links(config(),terrain=context(heights))['records'][0]
    assert short['terrain']['los_status'] == 'clear_within_radius'
    assert short['terrain_contract']['full_path_status'] == 'not_verified'
    assert short['terrain_contract']['radius_audit_status'] == 'not_attached'


def make_run_inputs(tmp_path, **extra):
    path, declaration = raster(tmp_path)
    cfg = tmp_path/'link.yaml'
    cfg.write_text(yaml.safe_dump(config()))
    terrain = tmp_path/'terrain.yaml'
    terrain.write_text(yaml.safe_dump(dict(dem_path=path.name,declaration=declaration,geoid=None,
        radius_m=150,resolution_m=10,step_m=10,effective_radius_m=None,loss_cap_db=60,**extra)))
    return cfg,terrain


def test_cli_archives_contract_and_execution_diagnostics(tmp_path):
    cfg,terrain = make_run_inputs(tmp_path)
    out = tmp_path/'run'
    result = execute(cfg,None,out,ROOT,terrain)
    archived = json.loads((out/'links.json').read_text())
    assert archived == json.loads(json.dumps(result))
    assert archived['records'][0]['budget']['received_power']['terrain_contract']['scope'] == 'finite_radius_conditional'
    metadata = json.loads((out/'terrain.json').read_text())
    assert 'budget' not in metadata
    assert json.loads((out/'terrain_read.json').read_text())['budget']['tile_size'] == 128


@pytest.mark.parametrize('budget,exception,kind', [({'target_cells':1},TerrainResourceError,'resource_budget_exceeded'),
                                                ({'target_cells':0},ValueError,'invalid_input')])
def test_cli_resource_and_input_refusals_are_distinct(tmp_path,budget,exception,kind):
    cfg,terrain = make_run_inputs(tmp_path,read_budget=budget)
    out = tmp_path/'run'
    with pytest.raises(exception) as error:
        execute(cfg,None,out,ROOT,terrain)
    assert isinstance(error.value,ValueError)
    status = json.loads((out/'validation.json').read_text())
    assert status['failure_kind'] == kind and status['status'] == 'failed'
    assert not (out/'links.json').exists()
    assert 'validation.json' in json.loads((out/'artifacts.json').read_text())['files']


@pytest.mark.parametrize('changed', ['frequency','height','direction','grid'])
def test_query_binding_changes_with_physical_inputs(changed):
    data = config()
    original = calculate_links(data,terrain=context())['records'][0]['terrain_contract']['audit_binding']
    terrain = context()
    if changed == 'frequency': data['budget']['frequency_hz'] *= 2
    if changed == 'height': data['receiver']['antenna_ellipsoid_height_m'] += 1
    if changed == 'direction':
        for direction in data['source']['directions']: direction['azimuth_deg'] = 45
    if changed == 'grid': terrain = context(np.ones((41,41)))
    actual = calculate_links(data,terrain=terrain)['records'][0]['terrain_contract']['audit_binding']
    assert actual['query_id'] != original['query_id']
    assert actual['physical_input_checksum'] != original['physical_input_checksum']
