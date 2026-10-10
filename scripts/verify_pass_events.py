"""Frozen whole-pass direct-time convergence and guarded-cache diagnostics."""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np
import yaml

from satellite_coverage.config.link import sample_times
from satellite_coverage.config.pilot import identity
from satellite_coverage.engine.direction_table import DirectionTable, TerrainLocalSolver
from satellite_coverage.engine.quality_events import DirectLinkEvaluator, direct_events, summarize_events
from satellite_coverage.engine.terrain_context import TerrainContext
from satellite_coverage.experiments.direction_cache import timings, break_even
from satellite_coverage.experiments.pass_events import (compact_record, threshold_record, guard_record,
    compare_events, convergence_pair, validate_split)
from satellite_coverage.geometry.geodetic import antenna_position
from satellite_coverage.geometry.terrain import TerrainGrid
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record
from satellite_coverage.orbit.visibility import parse_catalog, select_record, utc
from verify_model_comparison import write_csv


def digest(path):
    return 'sha256:'+hashlib.sha256(Path(path).read_bytes()).hexdigest()


def link_config(cfg,pass_spec):
    return dict(schema_version=1,experiment_id='whole-pass-conditional',start=pass_spec['observation_start'],
                end=pass_spec['observation_end'],step_s=cfg['initial_step_s'],receiver=deepcopy(cfg['receiver']),
                source=dict(mode='tle',candidate_id=cfg['norad_id'],norad_id=cfg['norad_id'],tle_policy=cfg['tle_policy'],max_age_days=cfg['max_age_days']),
                budget=dict(frequency_hz=cfg['frequency_hz'],power=dict(mode='eirp',eirp_dbm=cfg['eirp_dbm']),
                    receiver_antenna=dict(model='isotropic',gain_dbi=0,basis='declared ideal isotropic'),
                    losses=dict(atmosphere=dict(enabled=True,value=cfg['atmosphere_loss_db'],status='known',reason='constant scenario'),
                                local=dict(enabled=False,reason='terrain supplies local'),misc=dict(enabled=False,reason='declared zero')),
                    threshold=None,assumption_basis='conditional scalar mean; hypothetical system, no service claim'))


def event_run(callback,cfg,p,threshold,level,provider_identity):
    return direct_events({cfg['norad_id']:lambda t:threshold_record(callback(t),threshold)},
                         start=p['observation_start'],end=p['observation_end'],step_s=cfg['initial_step_s'],
                         max_probe_step_s=level['probe_s'],event_tolerance_s=level['tolerance_s'],max_samples=cfg['max_samples'],
                         candidate_identities={cfg['norad_id']:dict(propagation=provider_identity,threshold_dbm=threshold)})


def event_archive(result):
    output={k:v for k,v in result.items() if k!='samples'}
    output['sample_times_utc']=[r['timestamp_utc'] for r in result['samples']]
    output['record_status_counts']=dict(Counter(r['status'] for frame in result['samples'] for r in frame['records'].values()))
    output['recovery']='derive threshold-specific records from the pass direct-ledger JSONL at sample_times_utc'
    return output


def metric_passes(comparison,cfg):
    return all(r['false_windows']==r['missed_windows']==0 and r['all_known_event_counts_match']
               and (r['max_boundary_error_s'] is None or r['max_boundary_error_s']<=cfg['boundary_change_tolerance_s'])
               and max(map(abs,r['seconds_delta'].values()))<=cfg['duration_change_tolerance_s']
               and max(map(abs,r['longest_delta'].values()))<=cfg['duration_change_tolerance_s'] for r in comparison['channels'])


def run(output):
    root=Path(__file__).resolve().parents[1]
    cfg=yaml.safe_load((root/'configs/m5_e3.yaml').read_text())
    freeze=json.loads((root/'reports/m5/e3-design-sources.json').read_text())
    if digest(root/'configs/m5_e3.yaml')!=freeze['config_sha256']:
        raise ValueError('frozen configuration changed')
    split_hash=validate_split(freeze['passes'])
    archive=RunRecord(output)
    try:
        archive.write('config.json',cfg)
        archive.write('split.json',dict(passes=freeze['passes'],checksum=split_hash))
        archive.write('environment.json',environment_record(root))
        archive_sources(root,archive.path/'sources.zip')
        prepare_start=time.perf_counter()
        source=root/cfg['terrain_run']
        for name,key in ((cfg['terrain_grid'],'grid_sha256'),(cfg['terrain_metadata'],'metadata_sha256')):
            if digest(source/name)!=cfg[key]:raise ValueError('terrain input hash mismatch')
            shutil.copyfile(source/name,archive.path/name)
        if digest(root/cfg['tle_path'])!=cfg['tle_sha256']:raise ValueError('TLE input hash mismatch')
        shutil.copyfile(root/cfg['tle_path'],archive.path/'input.tle')
        catalog=parse_catalog((archive.path/'input.tle').read_bytes())
        for p in freeze['passes']:
            selected_tle=select_record(catalog.records[cfg['norad_id']],utc(p['observation_start']),cfg['tle_policy'])
            if selected_tle is None or selected_tle.record_sha256!=freeze['selected_tle_record_sha256']:
                raise ValueError('frozen TLE selection changed')
        data=np.load(archive.path/cfg['terrain_grid'])
        meta=json.loads((archive.path/cfg['terrain_metadata']).read_text())
        half=data.shape[0]*meta['resolution_m']/2
        grid=TerrainGrid(data,-half,half,meta['resolution_m'],'WGS84_ellipsoid',identity(meta),surface_type='DSM')
        context=TerrainContext(grid,cfg['receiver']['lon_deg'],cfg['receiver']['lat_deg'],cfg['radius_m'],cfg['step_m'],
                               effective_radius_m=cfg['effective_radius_m'],loss_cap_db=cfg['loss_cap_db'],sampling_method='cell_intervals')
        receiver=antenna_position(cfg['receiver'])
        first=freeze['passes'][0]
        base=DirectLinkEvaluator(link_config(cfg,first),catalog,terrain=context)
        anchor_time=utc(first['observation_start'])+(utc(first['observation_end'])-utc(first['observation_start']))/2
        anchor=base(anchor_time)
        anchor_solver=TerrainLocalSolver(context,receiver,frequency_hz=cfg['frequency_hz'],slant_range_m=anchor['geometry']['slant_range_m'])
        preparation_s=time.perf_counter()-prepare_start
        begin=time.perf_counter()
        table=DirectionTable.build(anchor_solver,azimuth_step_deg=cfg['cache_azimuth_step_deg'],elevations_deg=cfg['cache_elevations_deg'])
        build_s=time.perf_counter()-begin
        begin=time.perf_counter(); cache_path=table.save(archive.path); save_s=time.perf_counter()-begin
        begin=time.perf_counter(); table=DirectionTable.load(cache_path,expected_descriptor=anchor_solver.descriptor()); reload_s=time.perf_counter()-begin
        archive.write('cache.json',dict(preparation_s=preparation_s,build_s=build_s,save_s=save_s,reload_s=reload_s,bytes=cache_path.stat().st_size,
                                        anchor_time=anchor_time.isoformat(),anchor_range_m=anchor['geometry']['slant_range_m'],cache_key=table.cache_key))
        comparisons,convergence,reference_index,analysis_costs=[],[],[],[]
        for p in freeze['passes']:
            request=link_config(cfg,p)
            evaluator=DirectLinkEvaluator(request,catalog,terrain=context)
            archive.write(p['pass_id']+'-request.json',request)
            memo={}
            calls=0
            start=time.perf_counter()
            with (archive.path/(p['pass_id']+'-direct-ledger.jsonl')).open('w') as stream:
                def saved(t):
                    nonlocal calls
                    calls+=1
                    key=t.isoformat()
                    if key not in memo:
                        row=compact_record(evaluator(t))
                        memo[key]=row
                        stream.write(json.dumps(dict(record_checksum=identity(row),record=row),allow_nan=False)+'\n')
                    return memo[key]
                for threshold in cfg['thresholds_dbm']:
                    levels=[]; consecutive=0; pairs=[]
                    for index,level in enumerate(cfg['reference_levels']):
                        result=event_run(saved,cfg,p,threshold,level,evaluator.identity)
                        levels.append(result)
                        name=f"{p['pass_id']}-t{threshold}-level{index}.json"
                        archive.write(name,event_archive(result))
                        if index:
                            pair=convergence_pair(levels[-2],result,cfg['boundary_change_tolerance_s'],cfg['duration_change_tolerance_s'])
                            pairs.append(pair)
                            consecutive=consecutive+1 if pair['passed'] else 0
                        print(p['pass_id'],threshold,'level',index,'times',result['direct_time_count'],'consecutive',consecutive,flush=True)
                        if index+1>=cfg['minimum_reference_levels'] and consecutive>=cfg['required_adjacent_passes']:
                            break
                    geom_windows=[w for w in levels[-1]['candidates'][cfg['norad_id']]['geometry']['windows'] if w['state']=='visible']
                    complete_pass=len(geom_windows)==1 and not geom_windows[0]['censored']
                    verified=consecutive>=cfg['required_adjacent_passes'] and complete_pass
                    reference=levels[-1]
                    convergence.append(dict(pass_id=p['pass_id'],split=p['split'],threshold_dbm=threshold,verified=verified,complete_pass=complete_pass,level=len(levels)-1,pairs=pairs))
                    reference_index.append(dict(pass_id=p['pass_id'],threshold_dbm=threshold,verified=verified,level=len(levels)-1,file=name))
                    for i,result in enumerate(levels):
                        comparison=compare_events(result,reference)
                        comparisons.append(dict(pass_id=p['pass_id'],split=p['split'],threshold_dbm=threshold,method=f'direct_level_{i}',
                                                reference_verified=verified,meets_diagnostic=verified and metric_passes(comparison,cfg),comparison=comparison))
                    for step in cfg['coarse_steps_s']:
                        samples=[dict(timestamp_utc=t.isoformat(),records={cfg['norad_id']:threshold_record(saved(t),threshold)})
                                 for t in sample_times(dict(start=request['start'],end=request['end'],step_s=step))]
                        coarse=summarize_events(samples,start=request['start'],end=request['end'],candidate_ids=[cfg['norad_id']],max_gap_s=step)
                        archive.write(f"{p['pass_id']}-t{threshold}-coarse{step}.json",event_archive(coarse))
                        comparison=compare_events(coarse,reference)
                        comparisons.append(dict(pass_id=p['pass_id'],split=p['split'],threshold_dbm=threshold,method=f'coarse_{step}',
                                                reference_verified=verified,meets_diagnostic=verified and metric_passes(comparison,cfg),comparison=comparison))
            analysis_costs.append(dict(pass_id=p['pass_id'],wall_s=time.perf_counter()-start,requests=calls,
                                       actual_propagation_evaluations=len(memo),reused=calls-len(memo),meaning='analysis only; not cold timing'))
        archive.write('convergence.json',convergence)
        archive.write('reference-index.json',reference_index)
        # Select from predeclared base levels using development cases only.
        selected=None
        for index in range(cfg['minimum_reference_levels']):
            dev=[r for r in comparisons if r['split']=='development' and r['method']==f'direct_level_{index}']
            if len(dev)==cfg['development_pass_count']*len(cfg['thresholds_dbm']) and all(r['meets_diagnostic'] for r in dev):
                selected=index; break
        archive.write('selection.json',dict(selected_level=selected,used_split='development',holdout_not_used=True,
                                            fallback_if_none='reference settings per case as unselected diagnostic'))
        costs=[]
        for p in freeze['passes']:
            evaluator=DirectLinkEvaluator(link_config(cfg,p),catalog,terrain=context)
            def guarded(t):
                raw=evaluator(t)
                note=guard_record(raw,table,context,receiver,cfg['frequency_hz'],cfg['cache_exact_tolerance_db'])
                guard_notes[note['status']]+=1
                return compact_record(raw)
            def direct(t):return compact_record(evaluator(t))
            guard_notes=Counter()
            start,end=utc(p['observation_start']),utc(p['observation_end'])
            fixed_times=[start+(end-start)*i/(cfg['hot_times_per_pass']-1) for i in range(cfg['hot_times_per_pass'])]
            direct_timing=timings(lambda:[direct(t) for t in fixed_times],cfg['hot_repeats'])
            guard_timing=timings(lambda:[guarded(t) for t in fixed_times],cfg['hot_repeats'])
            hot_guard_counts=dict(guard_notes)
            for threshold in cfg['thresholds_dbm']:
                ref=next(r for r in reference_index if r['pass_id']==p['pass_id'] and r['threshold_dbm']==threshold)
                reference=json.loads((archive.path/ref['file']).read_text())
                level=cfg['reference_levels'][selected if selected is not None else ref['level']]
                begin=time.perf_counter(); direct_result=event_run(direct,cfg,p,threshold,level,evaluator.identity); direct_wall=time.perf_counter()-begin
                guard_notes.clear()
                begin=time.perf_counter(); guard_result=event_run(guarded,cfg,p,threshold,level,dict(evaluator=evaluator.identity,cache_key=table.cache_key)); guard_wall=time.perf_counter()-begin
                paired=compare_events(guard_result,direct_result)
                if not metric_passes(paired,dict(cfg,boundary_change_tolerance_s=0,duration_change_tolerance_s=0)):
                    raise AssertionError('sidecar changed direct event results')
                comparison=compare_events(guard_result,reference)
                comparisons.append(dict(pass_id=p['pass_id'],split=p['split'],threshold_dbm=threshold,method='guarded_selected' if selected is not None else 'guarded_reference_diagnostic',
                                        reference_verified=ref['verified'],meets_diagnostic=ref['verified'] and metric_passes(comparison,cfg),comparison=comparison))
                archive.write(f"{p['pass_id']}-t{threshold}-guarded.json",event_archive(guard_result))
                archive.write(f"{p['pass_id']}-t{threshold}-cold-direct.json",event_archive(direct_result))
                d=direct_timing['median_s']/len(fixed_times); q=guard_timing['median_s']/len(fixed_times)
                costs.append(dict(pass_id=p['pass_id'],split=p['split'],threshold_dbm=threshold,selected_level=selected,
                                  reference_verified=ref['verified'],precision_matched_to_direct=True,meets_reference_diagnostic=ref['verified'] and metric_passes(comparison,cfg),
                                  direct_hot=direct_timing,guarded_hot=guard_timing,hot_guard_counts=hot_guard_counts,
                                  cold_direct_s=direct_wall,cold_guarded_s=guard_wall,cold_direct_times=direct_result['direct_time_count'],
                                  cold_guarded_times=guard_result['direct_time_count'],guard_counts=dict(guard_notes),
                                  build_break_even=break_even(preparation_s+build_s+save_s,d,q),reload_break_even=break_even(preparation_s+reload_s,d,q)))
                print(p['pass_id'],threshold,'cold direct/guard',round(direct_wall,3),round(guard_wall,3),dict(guard_notes),flush=True)
        archive.write('comparisons.json',comparisons)
        archive.write('costs.json',costs)
        archive.write('analysis-reuse.json',analysis_costs)
        rows=[]
        for r in comparisons:
            for c in r['comparison']['channels']:
                rows.append(dict(pass_id=r['pass_id'],split=r['split'],threshold_dbm=r['threshold_dbm'],method=r['method'],channel=c['channel'],
                                 reference_verified=r['reference_verified'],meets_diagnostic=r['meets_diagnostic'],
                                 predicted_count=c['predicted_count'],reference_count=c['reference_count'],false_windows=c['false_windows'],missed_windows=c['missed_windows'],
                                 boundary_error_s=c['max_boundary_error_s'],max_duration_delta_s=max(map(abs,c['seconds_delta'].values())),
                                 max_longest_delta_s=max(map(abs,c['longest_delta'].values())),**r['comparison']['disagreement_seconds']))
        write_csv(archive.path/'comparisons.csv',rows)
        write_csv(archive.path/'costs.csv',[dict(pass_id=r['pass_id'],split=r['split'],threshold_dbm=r['threshold_dbm'],
                  cold_direct_s=r['cold_direct_s'],cold_guarded_s=r['cold_guarded_s'],hot_ratio=r['guarded_hot']['median_s']/r['direct_hot']['median_s'],
                  qbuild=r['build_break_even']['queries'],qreload=r['reload_break_even']['queries'],break_even_status=r['build_break_even']['status']) for r in costs])
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,axes=plt.subplots(1,2,figsize=(12,4))
        for p in freeze['passes']:
            sub=[r for r in rows if r['pass_id']==p['pass_id'] and r['channel']=='quality' and r['threshold_dbm']==-150 and r['method'].startswith('direct_level_')]
            axes[0].plot([int(r['method'].split('_')[-1]) for r in sub],[r['max_duration_delta_s'] for r in sub],marker='o',label=p['pass_id']+' '+p['split'])
        axes[0].set(xlabel='Direct refinement level',ylabel='Max state duration difference (s)',title='Threshold -150 dBm; all passes')
        axes[0].legend(fontsize=7)
        axes[1].bar([r['pass_id'] for r in costs[::len(cfg['thresholds_dbm'])]],
                    [r['guarded_hot']['median_s']/r['direct_hot']['median_s'] for r in costs[::len(cfg['thresholds_dbm'])]])
        axes[1].axhline(1,color='black',linewidth=1)
        axes[1].set(ylabel='Guarded / direct median time',title='Five repeats; no analysis memoization')
        fig.tight_layout(); fig.savefig(archive.path/'event-error-cost.png',dpi=140); plt.close(fig)
        summary=dict(pass_count=len(freeze['passes']),threshold_count=len(cfg['thresholds_dbm']),reference_verified=sum(r['verified'] for r in convergence),
                     reference_cases=len(convergence),selected_development_level=selected,
                     all_guarded_events_equal_direct=True,break_even_statuses=dict(Counter(r['build_break_even']['status'] for r in costs)),
                     cache_key=table.cache_key,analysis_actual_evaluations=sum(r['actual_propagation_evaluations'] for r in analysis_costs),
                     analysis_reused_evaluations=sum(r['reused'] for r in analysis_costs),
                     scope='same finite-radius model time convergence; guarded range mismatch sidecar is not a cache accelerator; business event error undetermined')
        archive.write('summary.json',summary)
        archive.finish('passed',reference_unresolved=summary['reference_cases']-summary['reference_verified'])
        print(json.dumps(summary),flush=True)
    except Exception as exc:
        archive.finish('failed',error=str(exc))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    run(parser.parse_args().output)
