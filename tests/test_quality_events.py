from copy import deepcopy, copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from satellite_coverage.engine.quality_events import (
    DirectLinkEvaluator, classify, direct_events, summarize_events,
)
from satellite_coverage.engine.links import calculate_links
from satellite_coverage.orbit.visibility import parse_catalog, TS

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2025,1,1,tzinfo=timezone.utc)
TLE = b'1 44714U 19074B   25001.18947582  .00035730  00000-0  24039-2 0  9991\n2 44714  53.0572 328.1885 0001289 107.3927 252.7203 15.06423914283568\n'


def stamp(t):
    return (START+timedelta(seconds=t)).isoformat()


def record(margin=1, elevation=20, status='computed'):
    return dict(status=status,geometry=dict(elevation_deg=elevation),
                budget=dict(margin=dict(value=margin,status='known' if margin is not None else 'unknown',unit='dB',reason='artificial')))


def run(curve, **kwargs):
    return direct_events({'a':lambda time:curve((time-START).total_seconds())},
                         start=stamp(0),end=stamp(10),step_s=10,max_probe_step_s=.25,
                         event_tolerance_s=.025,candidate_identities={'a':{'fixture':'analytic'}},**kwargs)


def windows(result,state='sufficient',candidate='a',channel='quality'):
    return [w for w in result['candidates'][candidate][channel]['windows'] if w['state']==state]


def offset(stamp):
    return (datetime.fromisoformat(stamp)-START).total_seconds()


def test_direct_crossings_root_bounds_and_duration_accounting():
    calls = []
    def curve(t):
        calls.append(t)
        return record(min(t-2.13,7.29-t))
    result=run(curve)
    window,=windows(result)
    assert abs(offset(window['start_utc'])-2.13)<.1
    assert abs(offset(window['end_utc'])-7.29)<.1
    for side,root in [('start',2.13),('end',7.29)]:
        left,right=map(offset,window[side+'_bracket_utc'])
        assert left<=root<=right and right-left<=.025
    assert not window['censored']
    quality=result['candidates']['a']['quality']
    assert sum(quality['seconds'].values())==pytest.approx(10)
    assert quality['seconds']['unknown']<=.05
    assert len(calls)==len(set(calls))==result['direct_time_count']
    assert all(offset(frame['timestamp_utc']) in calls for frame in result['samples'])
    assert result['service_eligibility']=='unknown'


def test_short_window_hidden_from_coarse_endpoints_is_directly_found():
    result=run(lambda t:record(.19-abs(t-4.41)))
    window,=windows(result)
    assert abs(window['duration_s']-.38)<.05
    assert 0<result['candidates']['a']['quality']['seconds']['sufficient']<1
    assert 'may be missed' in result['detection_limit']


def test_tangent_contact_has_no_positive_duration_window_and_plateau_is_known():
    tangent=run(lambda t:record(-(t-5)**2))
    assert windows(tangent)==[]
    assert tangent['candidates']['a']['threshold_contacts_utc']==[stamp(5)]
    plateau=run(lambda t:record(0))
    window,=windows(plateau)
    assert window['duration_s']==10 and window['start_clipped'] and window['end_clipped']
    assert window['censored']


def test_unknown_and_solver_failure_split_windows_preserve_every_candidate():
    def curve(t):
        if 3<t<4:
            raise RuntimeError('solver unavailable')
        return record(None if 6<t<7 else 1)
    result=run(curve)
    assert len(windows(result))==3
    assert result['candidates']['a']['geometry']['seconds']['unknown']>0
    assert result['candidates']['a']['quality']['seconds']['unknown']>1.9
    assert any(f['records']['a']['status']=='failed' for f in result['samples'])
    assert any('unknown_interval' in reason for w in windows(result) for reason in w['censor_reasons'])
    assert result['opportunity']['seconds']['available']<8.1


def test_irregular_sampling_is_duration_weighted_and_large_gap_is_unknown():
    samples=[dict(timestamp_utc=stamp(t),records={'a':record(m)}) for t,m in [(0,1),(1,1),(2,-1),(10,-1)]]
    result=summarize_events(samples,start=stamp(0),end=stamp(10),candidate_ids=['a'],max_gap_s=8)
    assert result['candidates']['a']['quality']['seconds']==dict(sufficient=1,insufficient=8,invisible=0,unknown=1)
    assert result['candidates']['a']['quality']['longest_seconds']['insufficient']==8
    gap=summarize_events(samples,start=stamp(0),end=stamp(10),candidate_ids=['a'],max_gap_s=2)
    assert gap['opportunity']['seconds']==dict(available=1,unavailable=0,unknown=9)


def test_missing_samples_no_candidates_and_handoff_cannot_fake_continuity():
    samples=[dict(timestamp_utc=stamp(t),records={'a':record(m),'b':record(-m)}) for t,m in [(0,1),(10,-1)]]
    result=summarize_events(samples,start=stamp(0),end=stamp(10),candidate_ids=['a','b'],max_gap_s=10)
    assert result['opportunity']['seconds']['unknown']==10
    assert set(result['candidates'])=={'a','b'}
    assert result['candidates']['a']['quality']['windows'][0]['event_id'] != result['candidates']['b']['quality']['windows'][0]['event_id']
    samples[1]['records'].pop('a')
    missing=summarize_events(samples,start=stamp(0),end=stamp(10),candidate_ids=['a','b'],max_gap_s=10)
    assert missing['samples'][-1]['records']['a']['reason']=='missing_candidate_sample'
    empty=direct_events({},start=stamp(0),end=stamp(10),step_s=10,max_probe_step_s=10,
                        event_tolerance_s=.1,candidate_identities={})
    assert empty['opportunity']['seconds']['unavailable']==10
    assert empty['opportunity']['segments'][0]['reason']=='no_candidates'


def test_any_candidate_semantics_and_geometry_quality_are_separate():
    result=direct_events({'a':lambda time:record(1),'b':lambda time:record(None)},
                         start=stamp(0),end=stamp(10),step_s=10,max_probe_step_s=1,event_tolerance_s=.1,
                         candidate_identities={'a':'constant','b':'missing'})
    assert result['opportunity']['seconds']['available']==10
    assert result['candidates']['b']['quality']['seconds']['unknown']==10
    assert classify(record(100,elevation=-5))['quality']=='invisible'
    assert classify(record(None))['geometry']=='visible'
    assert classify(record(1,status='failed'))['quality']=='unknown'
    assert classify(record(1,elevation=0))['geometry']=='invisible'
    assert classify(record(1,elevation=5),minimum_elevation_deg=10)['geometry']=='invisible'


def test_finite_terrain_contract_survives_direct_event_adapter():
    import numpy as np
    from satellite_coverage.geometry.terrain import TerrainGrid
    from satellite_coverage.engine.terrain_context import TerrainContext
    cfg=yaml.safe_load((ROOT/'configs/m1_fixed.yaml').read_text())
    cfg['receiver']['antenna_ellipsoid_height_m']=2
    cfg['source']['position_ecef_m']=[6378139+550000,550000,0]
    grid=TerrainGrid(np.zeros((41,41)),-205,205,10,'WGS84_ellipsoid','test',surface_type='synthetic')
    terrain=TerrainContext(grid,0,0,150,5,sampling_method='cell_intervals')
    evaluator=DirectLinkEvaluator(cfg,terrain=terrain)
    actual=evaluator(datetime.fromisoformat(cfg['start'].replace('Z','+00:00')))
    regular=calculate_links(cfg,terrain=terrain)['records'][0]
    a,b=deepcopy(actual['terrain_contract']),deepcopy(regular['terrain_contract'])
    assert a['audit_binding']['sample_id']==actual['sample_id']
    assert a['audit_binding']['query_id']!=b['audit_binding']['query_id']
    for contract in (a,b):
        for key in ('sample_id','query_id'):
            contract['audit_binding'].pop(key)
    assert a==b
    assert actual['budget']==regular['budget']
    assert actual['service_eligibility']=='unknown'


def test_direct_geometry_and_quality_windows_have_different_roots():
    result=run(lambda t:record(t-4,elevation=t-2))
    assert abs(offset(windows(result,'visible',channel='geometry')[0]['start_utc'])-2)<.1
    assert abs(offset(windows(result)[0]['start_utc'])-4)<.1
    assert result['candidates']['a']['quality']['seconds']['invisible']>1.9


def test_budget_and_invalid_inputs_fail_without_partial_success():
    calls=[]
    with pytest.raises(ValueError,match='budget'):
        direct_events({'a':lambda t:calls.append(t)},start=stamp(0),end=stamp(10),step_s=10,max_probe_step_s=.01,
                      event_tolerance_s=.001,candidate_identities={'a':'fixture'},max_samples=10)
    assert not calls
    with pytest.raises(ValueError,match='budget exhausted'):
        direct_events({'a':lambda t:record((t-START).total_seconds()-4.123)},start=stamp(0),end=stamp(10),step_s=10,max_probe_step_s=10,
                      event_tolerance_s=.001,candidate_identities={'a':'fixture'},max_samples=3)
    with pytest.raises(ValueError,match='mismatched'):
        run(lambda t:{**record(), 'candidate_id':'wrong'})
    with pytest.raises(ValueError,match='timezone|时区'):
        summarize_events([],start='2025-01-01',end=stamp(10),candidate_ids=[],max_gap_s=1)
    with pytest.raises(ValueError,match='finite'):
        classify(record(float('nan')))
    with pytest.raises(ValueError,match='unique'):
        summarize_events([],start=stamp(0),end=stamp(10),candidate_ids=['a','a'],max_gap_s=1)


def test_arbitrary_time_m1_matches_regular_grid_and_rejects_sequence_interpolation():
    cfg=yaml.safe_load((ROOT/'configs/m1_fixed.yaml').read_text())
    original=calculate_links(cfg)
    times=[r['timestamp_utc'] for r in original['records']]
    direct=calculate_links(cfg,evaluation_times=times)
    assert direct['selection']==original['selection']
    for a,b in zip(original['records'],direct['records']):
        assert a['geometry']==b['geometry'] and a['budget']==b['budget']
    evaluator=DirectLinkEvaluator(cfg)
    assert evaluator(datetime.fromisoformat(times[0]))==direct['records'][0]
    sequence=yaml.safe_load((ROOT/'configs/m1_sequence.yaml').read_text())
    with pytest.raises(ValueError,match='sampled'):
        calculate_links(sequence,evaluation_times=times)
    with pytest.raises(ValueError,match='interpolate'):
        DirectLinkEvaluator(sequence)
    for wrong in [[],[times[-1],times[0]],[times[0],times[0]],['1999-01-01T00:00:00Z']]:
        with pytest.raises(ValueError):
            calculate_links(cfg,evaluation_times=wrong)


def test_refinement_keeps_original_tle_selection_and_interval_age_policy():
    cfg=yaml.safe_load((ROOT/'configs/m1_tle.yaml').read_text())
    cfg.update(start='2025-01-01T05:00:00Z',end='2025-01-01T05:00:10Z',step_s=10)
    catalog=parse_catalog(TLE)
    old=catalog.records['44714'][0]
    newer=copy(old)
    newer.epoch=TS.utc(2025,1,1,5,0,5)
    newer.record_sha256='newer-record'
    catalog.records['44714'].append(newer)
    point=calculate_links(cfg,catalog,evaluation_times=['2025-01-01T05:00:09Z'])
    assert point['selection']['record_sha256']==old.record_sha256
    assert point['selection']['fixed_over_interval']
    shifted=deepcopy(cfg)
    shifted.update(start='2025-01-01T05:00:09Z',end='2025-01-01T05:00:10Z')
    assert calculate_links(shifted,catalog)['selection']['record_sha256']=='newer-record'
    catalog.records['44714']=[old]
    cfg.update(end='2025-01-02T05:00:00Z',step_s=3600)
    cfg['source']['max_age_days']=.1
    unavailable=calculate_links(cfg,catalog,evaluation_times=[cfg['start']])
    assert unavailable['records'][0]['reason']=='tle_epoch_exceeds_max_age_days'
