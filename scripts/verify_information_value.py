"""Execute frozen four-layer E4 with all development receipts sealed before holdout."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import shutil
import time

import numpy as np
import yaml

from satellite_coverage.config.pilot import identity
from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.engine.candidate_selection import (CandidateSet, PassRegistry, DevelopmentScores,
    HoldoutScores, select_candidate, evaluate_selection, compare_evaluations, score_row_from_events)
from satellite_coverage.engine.quality_events import DirectLinkEvaluator, direct_events
from satellite_coverage.experiments.information_value import (METHODS, PropagationLedger, layer_record,
    unavailable_reference, uncertainty_intervals)
from satellite_coverage.experiments.pass_events import convergence_pair
from satellite_coverage.geometry.geodetic import antenna_position
from satellite_coverage.geometry.terrain import TerrainGrid
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record
from satellite_coverage.orbit.visibility import parse_catalog
from verify_model_comparison import write_csv
from verify_pass_events import link_config, event_archive


def plot_results(path, reports, scenarios, observed_seconds):
    """Keep unknown-time intervals and the full denominator visible, not rounding noise."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12,4))
    for index,method in enumerate(METHODS):
        rows=[r for r in reports if r['method']==method]
        x=np.arange(len(rows))+(index-1.5)*.05
        y=np.array([r['gain_s'] for r in rows])
        lower=np.array([r['gain_lower_s'] for r in rows]); upper=np.array([r['gain_upper_s'] for r in rows])
        if method=='no_terrain':lower=y.copy(); upper=y.copy()  # a choice compared with itself
        axes[0].errorbar(x,y,yerr=np.array([y-lower,upper-y]),marker='o',capsize=3,label=method)
        axes[1].plot(range(len(rows)),[100*r['unknown_s']/observed_seconds for r in rows],marker='o',label=method)
    for ax in axes:
        ax.set_xticks(range(len(scenarios)),[s[0] for s in scenarios],rotation=35,ha='right'); ax.grid(alpha=.3)
    axes[0].set_ylabel('Conditional gain and unknown-time bounds (s)')
    axes[0].axhline(0,color='gray',linewidth=.5)
    axes[1].set_ylabel('Selected holdout unknown time (%)'); axes[1].set_ylim(0,100)
    axes[0].legend(fontsize=7); fig.tight_layout(); fig.savefig(path,dpi=140); plt.close(fig)


def run(inputs, output, config_path=None):
    root=Path(__file__).resolve().parents[1]
    inputs=Path(inputs)
    config_path=Path(config_path) if config_path is not None else root/'configs/m6_e4.yaml'
    cfg=yaml.safe_load(config_path.read_text())
    freeze=json.loads((inputs/'freeze.json').read_text())
    if freeze['config_sha256']!=checksum_sha256(config_path) or freeze['config_checksum']!=identity(cfg):
        raise ValueError('pre-quality frozen configuration changed')
    for name,digest in json.loads((inputs/'artifacts.json').read_text())['files'].items():
        if checksum_sha256(inputs/name)!=digest:
            raise ValueError('prepared input artifact changed: '+name)
    candidates=CandidateSet.from_mapping(json.loads((inputs/'candidates.json').read_text()))
    registry=PassRegistry.from_mapping(json.loads((inputs/'registry.json').read_text()))
    if candidates.checksum!=freeze['candidate_set_checksum'] or registry.checksum!=freeze['pass_registry_checksum']:
        raise ValueError('frozen candidate/pass identity changed')
    run=RunRecord(output)
    try:
        env=environment_record(root)
        provenance={k:env[k] for k in ('code_commit','source_fingerprint')}
        run.write('environment.json',env)
        run.write('config.json',cfg)
        run.write('freeze.json',freeze)
        run.write('candidates.json',candidates.to_mapping())
        run.write('registry.json',registry.to_mapping())
        run.write('preparation-artifacts.json',json.loads((inputs/'artifacts.json').read_text()))
        run.write('preparation-resources.json',json.loads((inputs/'resources.json').read_text()))
        archive_sources(root,run.path/'sources.zip')
        shutil.copyfile(inputs/'input.tle',run.path/'input.tle')
        catalog=parse_catalog((inputs/'input.tle').read_bytes())
        grids={}; metadata={}
        for site in freeze['sites']:
            for name in (site['grid'],site['metadata'],site['candidate_id']+'-read.json'):
                shutil.copyfile(inputs/name,run.path/name)
            data=np.load(inputs/site['grid'])
            meta=json.loads((inputs/site['metadata']).read_text())
            metadata[site['candidate_id']]=meta
            half=data.shape[0]*meta['resolution_m']/2
            grids[site['candidate_id']]=TerrainGrid(data,-half,half,meta['resolution_m'],'WGS84_ellipsoid',identity(meta),surface_type='DSM')
        scenarios=[(f'p{power}-t{threshold}',power,threshold) for power in cfg['eirps_dbm'] for threshold in cfg['thresholds_dbm']]
        dev=defaultdict(lambda:defaultdict(list)); hold=defaultdict(list)
        receipts={}; diagnostics=[]; costs=[]; sequence=[]
        selection_s=0.0
        for split in ('development','holdout'):
            if split=='holdout':
                # Every method/scenario decision is persisted before any held-out propagation.
                for scenario,_,_ in scenarios:
                    receipts[scenario]={}
                    for method in METHODS:
                        table=DevelopmentScores.from_mapping(dict(split='development',candidate_set=candidates.to_mapping(),
                            pass_registry=registry.to_mapping(),model_id=method,information_role=method,
                            provenance=identity(dict(freeze=freeze,scenario=scenario,source=env['source_fingerprint'])),rows=dev[scenario][method]))
                        begin=time.perf_counter()
                        receipt=select_candidate(table)
                        selection_s+=time.perf_counter()-begin
                        name=f'{scenario}-{method}-receipt.json'
                        run.write(name,receipt.to_mapping())
                        receipts[scenario][method]=receipt
                        sequence.append(dict(action='sealed_development_receipt',scenario=scenario,method=method,
                                             file=name,checksum=receipt.checksum))
                run.write('receipt-barrier.json',dict(receipts=sequence,holdout_started=False))
                run.log('all_development_receipts_persisted_before_holdout')
            for p in registry.to_mapping()['passes']:
                if p['split']!=split:continue
                for site in freeze['sites']:
                    site_id=site['candidate_id']
                    sequence.append(dict(action='begin_propagation',split=split,pass_id=p['pass_id'],site=site_id))
                    request_cfg=dict(cfg,receiver=site['receiver'],eirp_dbm=cfg['eirps_dbm'][0])
                    request=link_config(request_cfg,dict(observation_start=p['start_utc'],observation_end=p['end_utc']))
                    base=DirectLinkEvaluator(request,catalog)
                    if base.catalog.checksum!=cfg['tle_sha256'].removeprefix('sha256:'):
                        raise ValueError('TLE identity mismatch')
                    run.write(f"{site_id}-{p['pass_id']}-request.json",request)
                    begin=time.perf_counter(); event_s=0.0; derive_s=0.0
                    with (run.path/f"{site_id}-{p['pass_id']}-propagation.jsonl").open('w') as stream:
                        ledger=PropagationLedger(base,grids[site_id],antenna_position(site['receiver']),cfg,
                                                 site_id,p['pass_id'],provenance,stream,
                                                 native_spacing_m=metadata[site_id]['estimated_native_spacing_max_m'])
                        for scenario,power,threshold in scenarios:
                            for method in (METHODS if split=='development' else (METHODS[-1],)):
                                previous=None; pairs=[]; final=None
                                indices=range(3) if method==METHODS[-1] else [cfg['nonreference_time_level']]
                                for index in indices:
                                    level=cfg['reference_levels'][index]
                                    def evaluate(t):
                                        nonlocal derive_s
                                        propagation=ledger(t)
                                        started=time.perf_counter()
                                        result=layer_record(propagation,method,power,threshold)
                                        derive_s+=time.perf_counter()-started
                                        return result
                                    started=time.perf_counter()
                                    events=direct_events({cfg['norad_id']:evaluate},start=p['start_utc'],end=p['end_utc'],
                                        step_s=cfg['initial_step_s'],max_probe_step_s=level['probe_s'],
                                        event_tolerance_s=level['tolerance_s'],max_samples=cfg['max_samples'],
                                        candidate_identities={cfg['norad_id']:dict(base=base.identity,site=site_id,method=method,
                                            power=power,threshold=threshold,freeze=identity(freeze),provenance=provenance)})
                                    event_s+=time.perf_counter()-started
                                    name=f"{site_id}-{p['pass_id']}-{scenario}-{method}-level{index}.json"
                                    artifact=event_archive(events)
                                    artifact['recovery']='layer_record from same site/pass propagation ledger, scenario and method; sample_times_utc'
                                    run.write(name,artifact)
                                    if previous is not None:
                                        pairs.append(convergence_pair(previous,events,cfg['boundary_change_tolerance_s'],cfg['duration_change_tolerance_s']))
                                    previous=events; final=events
                                raw_score=score_row_from_events(final,site_id,p['pass_id'],registry)
                                eligible=method!=METHODS[-1] or (len(pairs)==2 and all(pair['passed'] for pair in pairs))
                                geometry_windows=[w for w in final['candidates'][cfg['norad_id']]['geometry']['windows'] if w['state']=='visible']
                                complete=len(geometry_windows)==1 and not geometry_windows[0]['censored']
                                if method==METHODS[-1]:
                                    eligible=eligible and complete
                                    if not eligible:
                                        final=unavailable_reference(final,'spatial_or_temporal_reference_not_verified')
                                final_name=f"{site_id}-{p['pass_id']}-{scenario}-{method}-final.json"
                                final_archive=event_archive(final)
                                final_archive['recovery']='last level event; if eligibility false apply unavailable_reference to last level'
                                run.write(final_name,final_archive)
                                score=score_row_from_events(final,site_id,p['pass_id'],registry)
                                if split=='development':dev[scenario][method].append(score)
                                else:hold[scenario].append(score)
                                diagnostics.append(dict(scenario=scenario,site=site_id,pass_id=p['pass_id'],split=split,method=method,
                                    eligible=eligible,complete_geometric_pass=complete,temporal_pairs=pairs,score=score,
                                    raw_diagnostic_score=raw_score,final_file=final_name,
                                    longest_insufficient_s=final['candidates'][cfg['norad_id']]['quality']['longest_seconds']['insufficient']))
                                print(split,site_id,p['pass_id'],scenario,method,'eligible',eligible,
                                      'sufficient',round(score['sufficient_s'],3),'unknown',round(score['unknown_s'],3),flush=True)
                        costs.append(dict(site=site_id,pass_id=p['pass_id'],split=split,**ledger.costs,
                            total_wall_s=time.perf_counter()-begin,event_inclusive_s=event_s,derivation_s=derive_s,
                            attribution='event time includes propagation and derivation; role costs share preparation; memo reuse is analysis only'))
        run.write('sequence.json',sequence)
        run.write('diagnostics.json',diagnostics)
        run.write('costs.json',dict(propagation=costs,selection_s=selection_s))
        reports=[]; evaluations={}
        started=time.perf_counter()
        for scenario,power,threshold in scenarios:
            table=HoldoutScores.from_mapping(dict(split='holdout',candidate_set=candidates.to_mapping(),
                pass_registry=registry.to_mapping(),model_id=METHODS[-1],information_role='common_eligible_reference',
                provenance=identity(dict(freeze=freeze,scenario=scenario,source=env['source_fingerprint'])),rows=hold[scenario]))
            run.write(scenario+'-holdout.json',table.to_mapping())
            results={method:evaluate_selection(receipt,table) for method,receipt in receipts[scenario].items()}
            comparison=compare_evaluations(results,'no_terrain')
            for method,result in results.items():
                result['uncertainty']=uncertainty_intervals(result)
                selected=result['selected']
                base=results['no_terrain']['selected']
                low=lambda m:m['insufficient_s']+m['invisible_s']
                reports.append(dict(scenario=scenario,eirp_dbm=power,threshold_dbm=threshold,method=method,
                    **comparison[method],oracle_candidate_id=result['oracle']['candidate_id'],
                    sufficient_s=selected['sufficient_s'],insufficient_s=selected['insufficient_s'],
                    invisible_s=selected['invisible_s'],unknown_s=selected['unknown_s'],
                    longest_unavailable_s=selected['longest_unavailable_s'],objective_s=selected['objective_s'],
                    gain_lower_s=low(base)-selected['objective_s'],gain_upper_s=base['objective_s']-low(selected),
                    regret_lower_s=result['uncertainty']['regret_lower_s'],regret_upper_s=result['uncertainty']['regret_upper_s']))
            evaluations[scenario]=results
        run.write('evaluations.json',evaluations)
        write_csv(run.path/'results.csv',reports)
        write_csv(run.path/'costs.csv',[{k:v for k,v in row.items() if k!='roles_s'} for row in costs])
        plot_results(run.path/'e4.png',reports,scenarios,next(iter(results.values()))['observed_seconds'])
        refs=[d for d in diagnostics if d['method']==METHODS[-1]]
        summary=dict(scope='finite-radius numerical information-value experiment; not physical truth or service',
            config_sha256=freeze['config_sha256'],candidate_set_checksum=candidates.checksum,pass_registry_checksum=registry.checksum,
            source_fingerprint=env['source_fingerprint'],receipts=len(scenarios)*len(METHODS),
            cases=reports,reference_cases=len(refs),reference_eligible=sum(d['eligible'] for d in refs),
            holdout_reference_cases=sum(d['split']=='holdout' for d in refs),
            holdout_reference_eligible=sum(d['eligible'] and d['split']=='holdout' for d in refs),
            judgment='inconclusive_due_reference_unknowns' if any(not d['eligible'] for d in refs) else
                     'adjust_no_robust_positive_gain' if not any(r['method']!='no_terrain' and r['gain_lower_s']>0 for r in reports) else 'continue_conditional_research',
            business={k:cfg[k] for k in ('minimum_useful_gain','max_compute_budget','allowed_event_error')},
            evaluation_and_reporting_s=time.perf_counter()-started)
        run.write('summary.json',summary)
        run.finish('passed',meaning='execution and artifact checks; numerical eligibility reported separately')
    except Exception as exc:
        run.finish('failed',error=str(exc))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    run(args.inputs,args.output,args.config)
