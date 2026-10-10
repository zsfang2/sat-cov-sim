"""Small isolated-selection and post-selection holdout verification archive."""

import argparse
import json
from pathlib import Path

from satellite_coverage.engine.candidate_selection import (DevelopmentScores,HoldoutScores,SelectionReceipt,
    select_candidate,evaluate_selection,compare_evaluations)
from satellite_coverage.io.run_record import RunRecord,archive_sources,environment_record


def run(output):
    archive=RunRecord(output)
    root=Path(__file__).resolve().parents[1]
    try:
        archive.write('environment.json',environment_record(root))
        archive_sources(root,archive.path/'sources.zip')
        candidates=dict(coordinate_basis='synthetic local ENU metres',items=[dict(candidate_id=c,east_m=i*10,north_m=0,height_agl_m=2,
                            cost=1,feasible=True,reason='synthetic feasible') for i,c in enumerate('ABC')])
        registry=dict(passes=[dict(pass_id='development-pass',split='development',start_utc='2025-01-01T00:00:00Z',end_utc='2025-01-01T00:00:10Z',basis='synthetic complete observation'),
                             dict(pass_id='holdout-pass',split='holdout',start_utc='2025-01-01T01:00:00Z',end_utc='2025-01-01T01:00:10Z',basis='disjoint synthetic complete observation')])
        archive.write('config.json',dict(candidate_set=candidates,pass_registry=registry,scope='software cost tables, not information-layer value experiment'))
        def table(split,costs,model):
            return dict(split=split,candidate_set=candidates,pass_registry=registry,model_id=model,information_role='synthetic duration costs',
                        provenance='analytic fixture',rows=[dict(candidate_id=c,pass_id=split+'-pass',source_id=model+'-'+c,
                             sufficient_s=10-value,insufficient_s=value,invisible_s=0,unknown_s=0,longest_unavailable_s=value) for c,value in zip('ABC',costs)])
        receipts={}
        # Create and persist all selection receipts before constructing holdout inputs.
        for method,costs in [('baseline',(0,2,4)),('richer',(3,1,4)),('tie',(1,1,1))]:
            dev=DevelopmentScores.from_mapping(table('development',costs,method))
            archive.write(method+'-development.json',dev.to_mapping())
            receipt=select_candidate(dev)
            archive.write(method+'-selection.json',receipt.to_mapping())
            receipts[method]=receipt
        assert receipts['richer'].to_mapping()['decision']['candidate_id']=='B'
        outcomes={}
        for scenario,values in [('reversal',(1,8,4)),('no-benefit',(1,1,1))]:
            holdout=HoldoutScores.from_mapping(table('holdout',values,'common-reference-'+scenario))
            archive.write(scenario+'-holdout.json',holdout.to_mapping())
            results={method:evaluate_selection(receipt,holdout) for method,receipt in receipts.items()}
            archive.write(scenario+'-evaluations.json',results)
            outcomes[scenario]=compare_evaluations(results,'baseline')
        assert outcomes['reversal']['richer']['regret_s']==7
        assert outcomes['reversal']['richer']['gain_s']==-7
        assert outcomes['no-benefit']['richer']['gain_s']==0
        wrong=receipts['richer'].to_mapping(); wrong['decision']['candidate_id']='A'
        try:SelectionReceipt.from_mapping(wrong)
        except ValueError:tamper_rejected=True
        else:raise AssertionError('tampered selection accepted')
        try:select_candidate(holdout)
        except ValueError:leak_rejected=True
        else:raise AssertionError('holdout accepted by selector')
        summary=dict(outcomes=outcomes,tampered_receipt_rejected=tamper_rejected,holdout_selection_rejected=leak_rejected,
                     scope='artificial optimality and isolation; real information-layer evaluation remains separate')
        archive.write('summary.json',summary)
        archive.finish('passed')
        print(json.dumps(summary))
    except Exception as exc:
        archive.finish('failed',error=str(exc)); raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    run(parser.parse_args().output)
