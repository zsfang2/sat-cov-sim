"""Rebuild E4 event inputs and score identities from archived direct propagation."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from satellite_coverage.config.pilot import identity
from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.engine.candidate_selection import PassRegistry, SelectionReceipt, score_row_from_events
from satellite_coverage.engine.quality_events import summarize_events
from satellite_coverage.experiments.information_value import layer_record, unavailable_reference
from satellite_coverage.io.run_record import write_json


def audit(path):
    path=Path(path)
    read=lambda name:json.loads((path/name).read_text())
    manifest=read('artifacts.json')['files']
    for name,digest in manifest.items():
        if checksum_sha256(path/name)!=digest:raise ValueError('artifact mismatch: '+name)
    cfg=read('config.json'); registry=PassRegistry.from_mapping(read('registry.json'))
    sequence=read('sequence.json')
    holdout=min(i for i,event in enumerate(sequence) if event['action']=='begin_propagation' and event['split']=='holdout')
    sealed=[(i,event) for i,event in enumerate(sequence) if event['action']=='sealed_development_receipt']
    if len(sealed)!=len(cfg['methods'])*len(cfg['eirps_dbm'])*len(cfg['thresholds_dbm']) or any(i>=holdout for i,_ in sealed):
        raise ValueError('receipt barrier violated')
    for _,event in sealed:
        receipt=SelectionReceipt.from_mapping(read(event['file']))
        if receipt.checksum!=event['checksum']:raise ValueError('receipt identity changed')
    groups=defaultdict(list)
    for diagnostic in read('diagnostics.json'):groups[(diagnostic['site'],diagnostic['pass_id'])].append(diagnostic)
    count=0; checks=[]; spatial=[]
    for (site,pass_id),items in groups.items():
        ledger={}; eligibility=Counter(); deltas=[]; cap_count=0
        with (path/f'{site}-{pass_id}-propagation.jsonl').open() as stream:
            for line in stream:
                row=json.loads(line); checksum=row.pop('checksum')
                if identity(row)!=checksum:raise ValueError('propagation row identity mismatch')
                row['checksum']=checksum
                reference=row['reference_eligibility']
                if reference is not None:
                    eligibility[reference['eligibility']]+=1
                    deltas.extend(d for d in reference['adjacent_raw_deltas_db'] if d is not None)
                else:eligibility['below_horizon']+=1
                cap_count+=sum(r['role']=='reference_multi_edge_deygout_v1' and r['result']['cap_triggered'] for r in row['paired_evidence'])
                row.pop('paired_evidence')
                if row['timestamp_utc'] in ledger:raise ValueError('duplicate direct timestamp')
                ledger[row['timestamp_utc']]=row; count+=1
        spatial.append(dict(site=site,pass_id=pass_id,query_counts=dict(eligibility),
            maximum_adjacent_raw_delta_db=max(deltas,default=None),capped_reference_level_queries=cap_count,
            denominator='unique direct query times; not duration weighted; below-horizon separate'))
        for d in items:
            prefix=d['final_file'].removesuffix('-final.json')
            power=float(d['scenario'].split('-t')[0][1:]); threshold=float(d['scenario'].split('-t')[1])
            # Preserve original scalar JSON types: int and float have distinct identities.
            power=next(p for p in cfg['eirps_dbm'] if p==power)
            threshold=next(t for t in cfg['thresholds_dbm'] if t==threshold)
            levels=range(3) if d['method']=='m4_multi_edge_reference' else [cfg['nonreference_time_level']]
            for level in levels:
                name=prefix+f'-level{level}.json'
                saved=read(name)
                samples=[dict(timestamp_utc=t,records={cfg['norad_id']:layer_record(ledger[t],d['method'],power,threshold)})
                         for t in saved['sample_times_utc']]
                if identity(samples)!=saved['input_checksum']:raise ValueError('event input mismatch: '+name)
                rebuilt=summarize_events(samples,start=saved['observation']['start_utc'],end=saved['observation']['end_utc'],
                    candidate_ids=saved['candidate_ids'],max_gap_s=saved['max_gap_s'],minimum_elevation_deg=saved['minimum_elevation_deg'])
                if any(rebuilt[k]!=saved[k] for k in ('candidates','opportunity','input_checksum')):
                    raise ValueError('event integration mismatch: '+name)
                original={k:v for k,v in saved.items() if k not in ('sample_times_utc','record_status_counts','recovery')}
                original['samples']=rebuilt['samples']
                checks.append(dict(file=name,input_checksum=saved['input_checksum'],times=len(samples)))
            final=original if d['eligible'] else unavailable_reference(original,'spatial_or_temporal_reference_not_verified')
            if score_row_from_events(final,site,pass_id,registry)!=d['score']:
                raise ValueError('final score/source identity mismatch: '+d['final_file'])
            saved_final=read(d['final_file'])
            if any(final[k]!=saved_final[k] for k in ('candidates','opportunity','input_checksum')):
                raise ValueError('final event mismatch')
        print('audited',site,pass_id,len(ledger),'direct rows',flush=True)
    return dict(status='passed',artifact_count=len(manifest),artifact_manifest_sha256=checksum_sha256(path/'artifacts.json'),
        receipts_before_holdout=len(sealed),direct_rows=count,event_inputs=len(checks),checks=checks,
        final_scores=sum(map(len,groups.values())),spatial_reference=spatial)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    write_json(args.output,audit(args.run))
