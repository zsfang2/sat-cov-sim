from copy import deepcopy
import json
import math

import numpy as np
import pytest

from satellite_coverage.config.pilot import identity
from satellite_coverage.domain.link_record import Quantity, QuantityStatus
from satellite_coverage.engine.direction_table import CacheMismatch, DirectionTable, TerrainLocalSolver
from satellite_coverage.engine.terrain_context import TerrainContext
from satellite_coverage.engine.terrain_contract import terrain_scope
from satellite_coverage.geometry.terrain import TerrainGrid


class AnalyticSolver:
    def __init__(self, mode='smooth'):
        self.mode = mode
        self.calls = 0
        self.inputs = dict(environment=dict(radius_m=150, step_m=5, sampling_method='cell_intervals', loss_cap_db=60,
                                           grid_sha256='artificial', vertical_datum='WGS84_ellipsoid'),
                           receiver=dict(lon_deg=0, lat_deg=0, height_m=2), frequency_hz=1e9,
                           model=dict(id='analytic:'+mode, version=1), system=dict(slant_range_m=550000, mean='scalar'))

    def descriptor(self):
        return deepcopy(self.inputs)

    def evaluate(self, azimuth, elevation):
        self.calls += 1
        if self.mode == 'failure':
            raise RuntimeError('deliberate failure')
        raw = (azimuth or 0)/100 + elevation/10
        status = 'known'
        visibility = 'clear_within_radius'
        if self.mode == 'unknown' and azimuth == 90:
            status, raw, visibility = 'unknown', None, 'unknown'
        if self.mode == 'boundary' and azimuth == 90:
            visibility = 'blocked'
        if self.mode == 'cap' and azimuth == 90:
            raw = 70
        cap = self.inputs['environment']['loss_cap_db']
        return dict(local_loss=Quantity(min(raw, cap) if raw is not None else None, 'dB', QuantityStatus(status), 'analytic_fixture').to_mapping(),
                    raw_loss_db=raw, loss_cap_db=cap, cap_triggered=raw is not None and raw > cap,
                    visibility=visibility, terrain_contract=terrain_scope(self.inputs['environment']), included_effects=['local'], reasons=[])


def table(solver=None, **kwargs):
    solver = solver or AnalyticSolver()
    return DirectionTable.build(solver, azimuth_step_deg=90, elevations_deg=[0, 10, 20], **kwargs), solver


def test_original_samples_exact_and_defensive_copy():
    t, s = table()
    for sample in t.samples:
        q = t.query(sample['azimuth_deg'], sample['elevation_deg'], expected_descriptor=s.descriptor())
        assert q['response'] == sample['response']
        assert q['error_bound_db'] == 0
    samples = t.samples
    samples[0]['response']['raw_loss_db'] = 999
    assert t.samples[0]['response']['raw_loss_db'] == 0
    assert s.calls == 12


def test_bilinear_affine_interior_and_nearest():
    t, s = table()
    q = t.query(30, 4, expected_descriptor=s.descriptor())
    assert q['response']['local_loss']['value'] == pytest.approx(.7, abs=1e-12)
    assert sum(n['weight'] for n in q['neighbors']) == pytest.approx(1)
    assert q['accuracy'] == 'not_verified'
    assert t.query(30, 4, method='nearest', expected_descriptor=s.descriptor())['response']['raw_loss_db'] == 0
    assert t.query(80, 9, method='nearest', expected_descriptor=s.descriptor())['response']['raw_loss_db'] == pytest.approx(1.9)


def test_periodic_wrap_and_seam_weights():
    t, s = table()
    for az in (0, 360, 720, -360):
        assert t.query(az, 10, expected_descriptor=s.descriptor())['response'] == t.query(0, 10, expected_descriptor=s.descriptor())['response']
    seam = t.query(315, 10, expected_descriptor=s.descriptor())
    assert seam['response']['raw_loss_db'] == pytest.approx((3.7+1)/2)
    assert {n['azimuth_index'] for n in seam['neighbors']} == {0, 3}


@pytest.mark.parametrize('mode', ['unknown', 'boundary', 'cap'])
@pytest.mark.parametrize('method', ['nearest', 'bilinear'])
def test_incompatible_states_force_fallback(mode, method):
    t, s = table(AnalyticSolver(mode))
    result = t.query(45, 5, method=method, expected_descriptor=s.descriptor())
    assert result['method'] == 'fallback_required'
    assert result['response']['local_loss']['value'] is None
    assert any(row['boundary'] for row in t.samples)
    direct = t.query(45, 5, method=method, expected_descriptor=s.descriptor(), fallback_solver=s)
    assert direct['method'] == 'direct_fallback'
    assert direct['response'] == s.evaluate(45, 5)


@pytest.mark.parametrize('az,el,reason', [(0, -1, 'outside_elevation_domain'), (0, 30, 'outside_elevation_domain'),
                                        (None, 90, 'zenith_azimuth_degeneracy'), (10, 89.95, 'zenith_azimuth_degeneracy')])
def test_domain_and_zenith_never_extrapolate(az, el, reason):
    t, s = table()
    result = t.query(az, el, expected_descriptor=s.descriptor())
    assert result['fallback_reason'] == reason
    assert result['response']['local_loss']['status'] == 'not_computed'


def test_requested_accuracy_requires_direct_evaluation_except_samples():
    t, s = table()
    result = t.query(30, 4, expected_descriptor=s.descriptor(), error_tolerance_db=.1, fallback_solver=s)
    assert result['method'] == 'direct_fallback'
    assert result['fallback_reason'] == 'interpolation_error_not_certified'
    assert t.query(0, 10, expected_descriptor=s.descriptor(), error_tolerance_db=0)['method'] == 'sample'


@pytest.mark.parametrize('section,field,value', [('environment', 'grid_sha256', 'other'), ('environment', 'vertical_datum', 'other'),
                                              ('receiver', 'height_m', 10), ('model', 'version', 2),
                                              ('system', 'slant_range_m', 600000), ('system', 'mean', 'coherent')])
def test_identity_changes_reject_hits_and_disk_load(tmp_path, section, field, value):
    t, s = table()
    path = t.save(tmp_path)
    wrong = s.descriptor()
    wrong[section][field] = value
    with pytest.raises(CacheMismatch):
        t.query(0, 10, expected_descriptor=wrong)
    with pytest.raises(CacheMismatch):
        DirectionTable.load(path, expected_descriptor=wrong)


def test_frequency_and_fallback_solver_identity():
    t, s = table()
    wrong = s.descriptor()
    wrong['frequency_hz'] *= 2
    with pytest.raises(CacheMismatch):
        t.query(0, 10, expected_descriptor=wrong)
    other = AnalyticSolver()
    other.inputs['frequency_hz'] *= 2
    with pytest.raises(CacheMismatch):
        t.query(0, 30, expected_descriptor=s.descriptor(), fallback_solver=other)


def test_disk_roundtrip_checksum_exclusive_write_and_budgets(tmp_path):
    t, s = table()
    path = t.save(tmp_path)
    loaded = DirectionTable.load(path, expected_descriptor=s.descriptor())
    assert loaded.samples == t.samples
    assert loaded.cache_key == t.cache_key
    with pytest.raises(FileExistsError):
        t.save(tmp_path)
    with pytest.raises(ValueError, match='read budget'):
        DirectionTable.load(path, expected_descriptor=s.descriptor(), maximum_bytes=1)
    with pytest.raises(ValueError, match='sample budget'):
        DirectionTable.load(path, expected_descriptor=s.descriptor(), maximum_samples=1)
    payload = json.loads(path.read_text())
    payload['payload']['samples'][0]['response']['raw_loss_db'] = 999
    path.write_text(json.dumps(payload))
    with pytest.raises(CacheMismatch):
        DirectionTable.load(path, expected_descriptor=s.descriptor())
    payload['content_sha256'] = identity(payload['payload'])
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='raw/used/cap'):
        DirectionTable.load(path, expected_descriptor=s.descriptor())


def test_build_budget_preflight_and_batch_order():
    s = AnalyticSolver()
    with pytest.raises(ValueError, match='budget'):
        table(s, maximum_samples=5)
    assert s.calls == 0
    a, _ = table(s, chunk_size=1)
    b, _ = table(AnalyticSolver(), chunk_size=7)
    assert a.samples == b.samples and a.cache_key == b.cache_key
    directions = [(0, 10), (30, 4), (315, 5), (None, 90)]
    batch = list(a.query_batch(directions, chunk_size=3, expected_descriptor=s.descriptor()))
    assert list(map(len, batch)) == [3, 1]
    assert [q for chunk in batch for q in chunk] == [a.query(*d, expected_descriptor=s.descriptor()) for d in directions]


def test_solver_failures_are_retained():
    t, s = table(AnalyticSolver('failure'))
    assert len(t.samples) == 12
    assert all(r['response']['local_loss']['status'] == 'failed' for r in t.samples)
    query = t.query(45, 5, expected_descriptor=s.descriptor(), fallback_solver=s)
    assert query['method'] == 'direct_fallback'
    assert query['response']['local_loss']['status'] == 'failed'


@pytest.mark.parametrize('az,el', [(math.nan, 10), (0, math.inf), (None, 5), (0, 91), (True, 10)])
def test_invalid_directions(az, el):
    t, s = table()
    with pytest.raises(ValueError):
        t.query(az, el, expected_descriptor=s.descriptor())


def test_real_provider_preserves_direct_loss_scope_and_key_dependencies():
    raster = np.zeros((41, 41))
    raster[10] = 42
    context = TerrainContext(TerrainGrid(raster, -205, 205, 10, 'WGS84_ellipsoid', 'ridge', surface_type='synthetic'),
                             0, 0, 150, 5, sampling_method='cell_intervals')
    receiver = dict(lon_deg=0, lat_deg=0, antenna_ellipsoid_height_m=2)
    solver = TerrainLocalSolver(context, receiver, frequency_hz=1e9, slant_range_m=550000)
    t = DirectionTable.build(solver, azimuth_step_deg=90, elevations_deg=[5, 10, 15])
    direct = context.evaluate(dict(azimuth_deg=0, elevation_deg=5, frequency_hz=1e9, slant_range_m=550000,
                                   geometrically_above_local_horizontal=True), receiver)
    query = t.query(0, 5, expected_descriptor=solver.descriptor())
    assert query['response']['raw_loss_db'] == direct['raw_loss_db']
    assert query['response']['local_loss']['value'] == direct['used_loss_db']
    assert query['response']['terrain_contract']['full_path_status'] == 'not_verified'
    for frequency, distance, height in [(2e9, 550000, 2), (1e9, 600000, 2), (1e9, 550000, 10)]:
        other = TerrainLocalSolver(context, dict(receiver, antenna_ellipsoid_height_m=height), frequency_hz=frequency, slant_range_m=distance)
        with pytest.raises(CacheMismatch):
            t.query(0, 5, expected_descriptor=other.descriptor())
    assert solver.evaluate(None, 90)['local_loss']['status'] == 'not_computed'
    assert solver.evaluate(0, -1)['local_loss']['status'] == 'not_applicable'
