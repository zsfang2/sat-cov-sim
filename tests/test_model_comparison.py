from copy import deepcopy
import math

import numpy as np
import pytest

from satellite_coverage.config.pilot import identity
from satellite_coverage.engine.model_comparison import ROLES, binding, common_budget, compare_models, validate_pair
from satellite_coverage.engine.terrain_context import TerrainContext
from satellite_coverage.geometry.terrain import TerrainGrid


def request(*, step=5, elevation=5, missing=False, limits=None):
    raster = np.zeros((41, 41))
    raster[10] = math.nan if missing else 42
    context = TerrainContext(TerrainGrid(raster, -205, 205, 10, 'WGS84_ellipsoid', 'synthetic-ridge',
                                         surface_type='synthetic'), 0, 0, 150, step,
                             effective_radius_m=6371000, sampling_method='cell_intervals')
    geometry = dict(azimuth_deg=None if elevation == 90 else 0, elevation_deg=elevation,
                    slant_range_m=550000, frequency_hz=14.5e9, geometrically_above_local_horizontal=elevation > 0)
    receiver = dict(lon_deg=0, lat_deg=0, antenna_ellipsoid_height_m=2)
    budget = common_budget(frequency_hz=14.5e9, slant_range_m=550000, eirp_dbm=40, receiver_gain_dbi=0,
                           nonlocal_losses_db=dict(gas=0, rain=0, clutter=0, other=0), threshold_offsets_db=[-10, 0, 10])
    metadata = dict(sample_id='direction-0-5', candidate_id='origin', timestamp_utc=None, pass_id=None,
                    satellite_id=None, scene_id='single_ridge', config_hash='frozen', native_spacing_m=10)
    rows, evidence = compare_models(context, geometry, receiver, budget, metadata=metadata,
                                    provenance=dict(code_commit='test', source_fingerprint='test-source'), reference_limits=limits)
    return rows, evidence, context.evaluate(geometry, receiver)


def test_three_roles_m3_exact_equivalence_and_sky_no_db():
    rows, evidence, direct = request()
    assert [r['model']['role_id'] for r in rows] == list(ROLES)
    assert rows[1]['solver_detail'] == direct
    for key in ('raw_loss_db', 'used_loss_db', 'cap_triggered'):
        assert rows[1]['result'][key] == direct[key]
    assert rows[0]['result']['visibility'] == 'blocked'
    assert rows[0]['result']['local_loss']['value'] is None
    assert rows[0]['result']['received_power']['status'] == 'not_applicable'
    assert rows[0]['terrain']['profile_sha256'] == identity(evidence['profile'])
    assert validate_pair(rows)


@pytest.mark.parametrize('mutation', ['two_roles', 'duplicate', 'geometry', 'frequency', 'height', 'unit',
                                     'sky_loss', 'effect', 'source', 'zero_unknown', 'power', 'scope'])
def test_negative_pair_mutations(mutation):
    rows, _, _ = request(missing=mutation == 'zero_unknown')
    if mutation == 'two_roles':
        rows.pop()
    elif mutation == 'duplicate':
        rows[2] = deepcopy(rows[1])
    elif mutation == 'geometry':
        rows[1]['geometry']['elevation_deg'] += 1
    elif mutation == 'frequency':
        rows[1]['budget']['frequency_hz'] *= 2
    elif mutation == 'height':
        rows[1]['geometry']['receiver_ellipsoid_height_m'] += 1
    elif mutation == 'unit':
        rows[1]['result']['received_power']['unit'] = 'dBW'
    elif mutation == 'sky_loss':
        rows[0]['result']['local_loss'].update(status='known', value=60)
    elif mutation == 'effect':
        rows[1]['model']['included_effects'].append('free_space')
    elif mutation == 'source':
        rows[1]['model']['source_fingerprint'] = 'different'
    elif mutation == 'zero_unknown':
        rows[1]['result']['used_loss_db'] = 0
    elif mutation == 'power':
        rows[1]['result']['received_power']['value'] += 1
    elif mutation == 'scope':
        rows[1]['result']['terrain_contract']['full_path_status'] = 'verified'
    with pytest.raises(ValueError):
        validate_pair(rows)


def test_step_has_shared_query_but_different_pair_identity():
    coarse, _, _ = request(step=10)
    fine, _, _ = request(step=5)
    assert coarse[0]['identity']['query_id'] == fine[0]['identity']['query_id']
    assert coarse[0]['identity']['pair_id'] != fine[0]['identity']['pair_id']
    assert binding(coarse[0], refinement=True) == binding(fine[0], refinement=True)


@pytest.mark.parametrize('elevation,status', [(0, 'not_applicable'), (-1, 'not_applicable'), (90, 'not_computed')])
def test_geometric_unavailability_is_retained(elevation, status):
    rows, _, _ = request(elevation=elevation)
    assert len(rows) == 3
    assert all(r['result']['status'] == status for r in rows)
    assert all(r['result']['received_power']['value'] is None for r in rows)


def test_nodata_and_resource_failure_are_not_dropped():
    rows, _, _ = request(missing=True)
    assert all(r['result']['failure_kind'] == 'data_gap' for r in rows)
    assert all(r['result']['received_power']['value'] is None for r in rows)
    rows, _, _ = request(limits=dict(maximum_points=1, maximum_depth=256, maximum_nodes=16383))
    assert rows[2]['result']['status'] == 'failed'
    assert rows[2]['result']['failure_kind'] == 'resource_limit'
    assert rows[1]['result']['status'] == 'known'
    assert rows[2]['result']['raw_loss_db'] is None


def test_duplicate_effect_cannot_be_disguised_as_common_input():
    rows, _, _ = request()
    for row in rows:
        row['budget']['nonlocal_components'][1]['effects'] = ['free_space']
        row['identity']['pair_id'] = row['identity']['input_checksum'] = identity(binding(row))
        row['identity']['query_id'] = identity(binding(row, refinement=True))
        row['identity']['result_id'] = identity(dict(pair_id=row['identity']['pair_id'], model=row['model']))
    with pytest.raises(ValueError):
        validate_pair(rows)
