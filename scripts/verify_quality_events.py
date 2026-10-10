"""Archive offline analytic event cases and a real scalar-pipeline adapter check."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import yaml

from satellite_coverage.engine.quality_events import direct_events, summarize_events, DirectLinkEvaluator
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record


def run(output):
    archive = RunRecord(output)
    root = Path(__file__).resolve().parents[1]
    origin = datetime(2025,1,1,tzinfo=timezone.utc)
    def stamp(seconds):
        return (origin+timedelta(seconds=seconds)).isoformat()
    def sample(value,elevation=20):
        return dict(status='computed',geometry=dict(elevation_deg=elevation),
                    budget=dict(margin=dict(value=value,status='known' if value is not None else 'unknown',unit='dB',reason='analytic fixture')))
    try:
        archive.write('environment.json',environment_record(root))
        archive_sources(root,archive.path/'sources.zip')
        settings=dict(start=stamp(0),end=stamp(10),step_s=10,max_probe_step_s=.25,event_tolerance_s=.025)
        formulas=dict(crossing='min(t-2.13,7.29-t)',short='0.19-abs(t-4.41)',contact='-(t-5)**2',
                      missing='unknown for 3<t<4; solver failure for 6<t<7; otherwise margin=1',
                      geometry='margin=t-4; elevation=t-2')
        archive.write('config.json',dict(settings=settings,formulas=formulas,analytic_root_tolerance_s=.1,
                                        missing_assumption='unknown is never connected',scope='software examples, not E3 whole-pass validation'))
        def missing(t):
            if 6<t<7:
                raise RuntimeError('injected solver failure')
            return sample(None if 3<t<4 else 1)
        curves=dict(crossing=lambda t:sample(min(t-2.13,7.29-t)),short=lambda t:sample(.19-abs(t-4.41)),
                    contact=lambda t:sample(-(t-5)**2),missing=missing,geometry=lambda t:sample(t-4,t-2))
        results={}
        summary={}
        for name,curve in curves.items():
            result=direct_events({'candidate':lambda time,curve=curve:curve((time-origin).total_seconds())},
                                 **settings,candidate_identities={'candidate':dict(formula=formulas[name])})
            results[name]=result
            archive.write(name+'.json',result)
            quality=result['candidates']['candidate']['quality']
            assert abs(quality['total_seconds']-10)<1e-12
            summary[name]=dict(direct_times=result['direct_time_count'],seconds=quality['seconds'],
                               longest_seconds=quality['longest_seconds'],contacts=result['candidates']['candidate']['threshold_contacts_utc'])
        roots=[]
        for name,expected in [('crossing',(2.13,7.29)),('short',(4.22,4.6))]:
            window,=[w for w in results[name]['candidates']['candidate']['quality']['windows'] if w['state']=='sufficient']
            for side,truth in zip(('start','end'),expected):
                actual=(datetime.fromisoformat(window[side+'_utc'])-origin).total_seconds()
                error=abs(actual-truth)
                assert error<=.1
                roots.append(dict(case=name,side=side,analytic_s=truth,estimated_s=actual,abs_error_s=error))
        assert summary['contact']['seconds']['sufficient']==0
        assert summary['missing']['seconds']['unknown']>=2
        archive.write('roots.json',roots)
        irregular=summarize_events([dict(timestamp_utc=stamp(t),records={'candidate':sample(m)}) for t,m in [(0,1),(1,1),(2,-1),(10,-1)]],
                                   start=stamp(0),end=stamp(10),candidate_ids=['candidate'],max_gap_s=8)
        assert irregular['candidates']['candidate']['quality']['seconds']==dict(sufficient=1,insufficient=8,invisible=0,unknown=1)
        archive.write('irregular.json',irregular)
        cfg=yaml.safe_load((root/'configs/m1_fixed.yaml').read_text())
        cfg.update(start=stamp(0),end=stamp(10),step_s=10)
        evaluator=DirectLinkEvaluator(cfg)
        direct=direct_events({evaluator.candidate_id:evaluator},**settings,candidate_identities={evaluator.candidate_id:evaluator.identity})
        assert all(f['records'][evaluator.candidate_id]['status']=='computed' for f in direct['samples'])
        archive.write('m1-config.json',cfg)
        archive.write('m1-events.json',direct)
        summary.update(max_analytic_boundary_error_s=max(row['abs_error_s'] for row in roots),
                       m1_direct_times=direct['direct_time_count'],business_event_tolerance='undetermined',
                       scope='directly evaluated software fixtures; finite probe spacing does not prove all continuous events')
        archive.write('summary.json',summary)
        archive.finish('passed')
        print(json.dumps(summary))
    except Exception as exc:
        archive.finish('failed',error=str(exc))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    run(parser.parse_args().output)
