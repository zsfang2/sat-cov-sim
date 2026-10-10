from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from satellite_coverage.engine.candidate_selection import (CandidateSet,PassRegistry,DevelopmentScores,HoldoutScores,
    SelectionReceipt,select_candidate,evaluate_selection,compare_evaluations,regret_seconds,score_row_from_events)


def candidates():
    return dict(coordinate_basis='declared local ENU metres',items=[dict(candidate_id=c,east_m=i*10,north_m=0,
                height_agl_m=2,cost=1,feasible=True,reason='synthetic feasible site') for i,c in enumerate('ABC')])


def registry():
    return dict(passes=[dict(pass_id='dev',split='development',start_utc='2025-01-01T00:00:00Z',end_utc='2025-01-01T00:00:10Z',basis='complete synthetic pass'),
                       dict(pass_id='test',split='holdout',start_utc='2025-01-01T00:01:00Z',end_utc='2025-01-01T00:01:10Z',basis='independent complete synthetic pass')])


def table(split='development',losses=(3,1,4)):
    return dict(split=split,candidate_set=candidates(),pass_registry=registry(),model_id='artificial',information_role='declared conditional score',
                provenance='known synthetic cost table',rows=[dict(candidate_id=c,pass_id='dev' if split=='development' else 'test',source_id='fixture-'+c,
                    sufficient_s=10-loss,insufficient_s=loss,invisible_s=0,unknown_s=0,longest_unavailable_s=loss) for c,loss in zip('ABC',losses)])


def test_development_optimum_and_holdout_reversal_do_not_leak():
    development=DevelopmentScores.from_mapping(table())
    receipt=select_candidate(development)
    assert receipt.to_mapping()['decision']['candidate_id']=='B'
    holdout=HoldoutScores.from_mapping(table('holdout',(1,8,4)))
    result=evaluate_selection(receipt,holdout)
    assert result['selected']['candidate_id']=='B' and result['oracle']['candidate_id']=='A'
    assert result['regret_s']==7 and result['observed_seconds']==10
    assert result['selected']['longest_unavailable_s']==8
    assert receipt==select_candidate(development)
    assert result['service_eligibility']=='unknown'
    with pytest.raises(ValueError,match='DevelopmentScores only'):select_candidate(holdout)
    with pytest.raises(ValueError,match='HoldoutScores'):evaluate_selection(receipt,development)
    relabeled=holdout.to_mapping(); relabeled['split']='development'
    with pytest.raises(ValueError,match='wrong-split'):DevelopmentScores.from_mapping(relabeled)


def test_ties_fixed_at_declared_rounding_and_input_order_does_not_change_choice():
    data=table(losses=(1.0000005,1,4))
    receipt=select_candidate(DevelopmentScores.from_mapping(data))
    assert receipt.to_mapping()['decision']['tie_ids']==['A','B']
    assert receipt.to_mapping()['decision']['candidate_id']=='A'
    reverse=deepcopy(data); reverse['rows'].reverse(); reverse['candidate_set']['items'].reverse()
    assert select_candidate(DevelopmentScores.from_mapping(reverse))==receipt
    with pytest.raises(FrozenInstanceError):receipt.serialized=b'{}'


def test_unknown_is_explicit_conservative_penalty_and_invisible_stays_in_denominator():
    data=table(losses=(0,2,4))
    data['rows'][0].update(sufficient_s=5,unknown_s=5)
    data['rows'][2].update(insufficient_s=0,invisible_s=4)
    receipt=select_candidate(DevelopmentScores.from_mapping(data))
    assert receipt.to_mapping()['decision']['candidate_id']=='B'
    all_rows=receipt.to_mapping()['decision']['all_candidate_metrics']
    assert all(r['observed_seconds']==10 for r in all_rows)
    assert all_rows[0]['objective_s']==5 and all_rows[0]['unknown_s']==5


def test_no_benefit_is_not_reported_as_success_or_removed():
    a=select_candidate(DevelopmentScores.from_mapping(table(losses=(0,2,4))))
    b=select_candidate(DevelopmentScores.from_mapping(table(losses=(2,0,4))))
    holdout=HoldoutScores.from_mapping(table('holdout',(1,1,1)))
    report=compare_evaluations({'base':evaluate_selection(a,holdout),'rich':evaluate_selection(b,holdout)},'base')
    assert report['rich']==dict(regret_s=0,gain_s=0,selected_candidate_id='B')
    worse=HoldoutScores.from_mapping(table('holdout',(0,3,4)))
    assert compare_evaluations({'base':evaluate_selection(a,worse),'rich':evaluate_selection(b,worse)},'base')['rich']['gain_s']==-3


def test_no_feasible_candidate_retains_observation_and_returns_no_oracle():
    dev,held=table(),table('holdout')
    for data in (dev,held):
        for item in data['candidate_set']['items']:item.update(feasible=False,reason='installation forbidden in fixture')
    result=evaluate_selection(select_candidate(DevelopmentScores.from_mapping(dev)),HoldoutScores.from_mapping(held))
    assert result['status']=='no_feasible_candidate' and result['regret_s'] is None
    assert result['selected'] is result['oracle'] is None and result['observed_seconds']==10
    assert len(result['all_candidate_metrics'])==3


@pytest.mark.parametrize('change',[
    lambda d:d['candidate_set']['items'][0].update(cost=2),
    lambda d:d['candidate_set']['items'][0].update(height_agl_m=3),
    lambda d:d['candidate_set']['items'][0].update(feasible='yes'),
    lambda d:d['rows'].pop(),
    lambda d:d['rows'].append(deepcopy(d['rows'][0])),
    lambda d:d['rows'][0].update(sufficient_s=0),
    lambda d:d['rows'][0].update(unknown_s=float('nan')),
    lambda d:d['rows'][0].update(longest_unavailable_s=11),
    lambda d:d['pass_registry']['passes'][1].update(start_utc='2025-01-01T00:00:05Z'),
])
def test_invalid_or_unfair_comparisons_rejected(change):
    data=table(); change(data)
    with pytest.raises(ValueError):DevelopmentScores.from_mapping(data)


def test_tampered_receipt_and_different_holdout_or_candidates_rejected():
    receipt=select_candidate(DevelopmentScores.from_mapping(table()))
    altered=receipt.to_mapping(); altered['decision']['candidate_id']='A'
    with pytest.raises(ValueError,match='does not match'):SelectionReceipt.from_mapping(altered)
    held=table('holdout'); held['candidate_set']['items'][0]['east_m']=11
    with pytest.raises(ValueError,match='identity mismatch'):evaluate_selection(receipt,HoldoutScores.from_mapping(held))
    one=evaluate_selection(receipt,HoldoutScores.from_mapping(table('holdout')))
    two=evaluate_selection(receipt,HoldoutScores.from_mapping(table('holdout',(4,4,4))))
    with pytest.raises(ValueError,match='same holdout'):compare_evaluations({'one':one,'two':two},'one')


def test_regret_roundoff_is_bounded_and_invalid_negatives_fail():
    assert regret_seconds(1,1.0000005)==0
    with pytest.raises(ValueError,match='negative regret'):regret_seconds(1,1.000002)
    with pytest.raises(ValueError,match='cannot be negative'):regret_seconds(-1,-2)


def test_defensive_copies_and_direct_serialization_cannot_bypass_validation():
    original=table()
    snap=DevelopmentScores.from_mapping(original)
    checksum=snap.checksum
    original['rows'][0]['insufficient_s']=999
    snap.to_mapping()['candidate_set']['items'][0]['cost']=999
    assert snap.checksum==checksum
    with pytest.raises(FrozenInstanceError):snap.split='holdout'
    with pytest.raises(ValueError):CandidateSet(b'{}')
    with pytest.raises(ValueError):PassRegistry.from_mapping(dict(passes=[]))


def test_event_adapter_keeps_no_satellite_time_and_binds_pass_interval():
    from satellite_coverage.engine.quality_events import summarize_events
    p=registry()['passes'][0]
    empty=summarize_events([dict(timestamp_utc=p['start_utc'],records={}),dict(timestamp_utc=p['end_utc'],records={})],
                           start=p['start_utc'],end=p['end_utc'],candidate_ids=[],max_gap_s=10)
    row=score_row_from_events(empty,'A','dev',PassRegistry.from_mapping(registry()))
    assert row['invisible_s']==10 and row['sufficient_s']==0 and row['longest_unavailable_s']==10
    with pytest.raises(ValueError,match='does not match'):
        score_row_from_events(empty,'A','test',PassRegistry.from_mapping(registry()))
