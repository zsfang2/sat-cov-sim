from copy import deepcopy
from datetime import datetime,timedelta,timezone

import pytest

from satellite_coverage.engine.quality_events import summarize_events
from satellite_coverage.experiments.pass_events import (threshold_record,compare_events,convergence_pair,validate_split)

ORIGIN=datetime(2025,1,1,tzinfo=timezone.utc)


def stamp(s):return (ORIGIN+timedelta(seconds=s)).isoformat()


def sample(margin):
    return dict(status='computed',geometry=dict(elevation_deg=20),budget=dict(margin=dict(value=margin,unit='dB',status='known' if margin is not None else 'unknown')))


def curve(values):
    return summarize_events([dict(timestamp_utc=stamp(t),records={'a':sample(v)}) for t,v in values],
                            start=stamp(0),end=stamp(10),candidate_ids=['a'],max_gap_s=10)


def test_event_disagreement_is_time_weighted_not_frame_based():
    reference=curve([(0,-1),(1,-1),(2,1),(10,1)])
    prediction=curve([(0,-1),(7,-1),(8,1),(10,1)])
    result=compare_events(prediction,reference)
    seconds=result['disagreement_seconds']
    assert seconds['pessimistic_s']==5 and seconds['optimistic_s']==0
    assert seconds['unknown_pair_s']==2 and seconds['known_pair_s']==8
    assert result['channels'][1]['max_boundary_error_s']==6
    assert not convergence_pair(prediction,reference,.1,.5)['passed']
    assert convergence_pair(reference,reference,.1,.5)['passed']


def test_missing_reference_and_event_misses_cannot_pass_convergence():
    reference=curve([(0,-1),(2,-1),(3,1),(4,1),(5,-1),(10,-1)])
    missing=curve([(0,None),(10,None)])
    absent=curve([(0,-1),(10,-1)])
    report=compare_events(absent,reference)
    assert report['channels'][1]['missed_windows']==1
    assert report['channels'][1]['max_boundary_error_s'] is None
    assert not convergence_pair(missing,missing,.1,.5)['passed']
    assert convergence_pair(missing,missing,.1,.5)['missing_reference']
    changed=deepcopy(reference); changed['observation']['end_utc']=stamp(11)
    with pytest.raises(ValueError,match='identical'):
        compare_events(reference,changed)


def test_threshold_derivation_has_separate_identity_and_keeps_source_unchanged():
    source=dict(timestamp_utc=stamp(0),candidate_id='a',status='computed',geometry=dict(elevation_deg=20),
                budget=dict(received_power=dict(value=-150,unit='dBm',status='known'),margin=None))
    original=deepcopy(source)
    a,b=threshold_record(source,-160),threshold_record(source,-140)
    assert source==original
    assert a['budget']['margin']['value']==10 and b['budget']['margin']['value']==-10
    assert a['source_record_checksum']==b['source_record_checksum']
    assert a['config_checksum']!=b['config_checksum']
    with pytest.raises(ValueError,match='finite'):
        threshold_record(source,float('nan'))


def test_whole_pass_split_rejects_duplicates_overlap_and_interleaving():
    passes=[dict(pass_id='a',split='development',observation_start=stamp(0),geometry_start=stamp(1),geometry_end=stamp(9),observation_end=stamp(10)),
            dict(pass_id='b',split='holdout',observation_start=stamp(20),geometry_start=stamp(21),geometry_end=stamp(29),observation_end=stamp(30))]
    assert validate_split(passes).startswith('sha256:')
    for change in (lambda p:p[1].update(pass_id='a'),lambda p:p[1].update(observation_start=stamp(5)),
                   lambda p:(p[0].update(split='holdout'),p[1].update(split='development'))):
        wrong=deepcopy(passes); change(wrong)
        with pytest.raises(ValueError):validate_split(wrong)
