"""Whole-pass event comparisons and explicitly guarded range-cache diagnostics."""

from copy import deepcopy
import math

from ..config.pilot import identity
from ..engine.direction_table import CacheMismatch, TerrainLocalSolver
from ..orbit.visibility import utc


def compact_record(record):
    result=deepcopy(record)
    profile=result.get('terrain',{}).pop('profile',None)
    if profile is not None:
        result['terrain']['profile_checksum']=identity(profile)
        result['terrain']['profile_recovery']='recompute from archived terrain/config and this direct geometry'
    return result


def threshold_record(record, threshold_dbm):
    """Explicit derived event record, linked to its unchanged propagation source."""
    if isinstance(threshold_dbm,bool) or not isinstance(threshold_dbm,(int,float)) or not math.isfinite(threshold_dbm):
        raise ValueError('threshold must be finite dBm')
    source=identity(record)
    result={k:deepcopy(record[k]) for k in ('timestamp_utc','candidate_id','status','geometry')}
    for key in ('reason','terrain_contract'):
        if key in record:
            result[key]=deepcopy(record[key])
    result.update(source_record_checksum=source,threshold_dbm=threshold_dbm,
                  config_checksum=identity(dict(propagation_record=source,threshold_dbm=threshold_dbm)),
                  derivation='declared threshold subtracted from unchanged direct scalar power',service_eligibility='unknown')
    budget=record.get('budget')
    if budget is None:
        result['budget']=None
    else:
        power=deepcopy(budget['received_power'])
        result['budget']=dict(received_power=power,margin=dict(
            value=power['value']-threshold_dbm if power['status']=='known' else None,
            status=power['status'],unit='dB',reason='hypothetical threshold on archived direct propagation'))
    return result


def guard_record(record, table, context, receiver, frequency_hz, tolerance_db):
    """Sidecar only: direct M1 already ran; no claim to skip propagation work."""
    geometry=record.get('geometry')
    if geometry is None or geometry['azimuth_deg'] is None:
        return dict(status='geometry_unavailable',uses_direct=True)
    solver=TerrainLocalSolver(context,receiver,frequency_hz=frequency_hz,slant_range_m=geometry['slant_range_m'])
    try:
        response=table.query(geometry['azimuth_deg'],geometry['elevation_deg'],expected_descriptor=solver.descriptor(),
                             error_tolerance_db=tolerance_db)
    except CacheMismatch:
        return dict(status='identity_mismatch_range',uses_direct=True,actual_range_m=geometry['slant_range_m'])
    # Do not replace direct record or fabricate missing profile metadata on a hit.
    return dict(status=response['method'],uses_direct=True,actual_range_m=geometry['slant_range_m'],
                cache_query=response,meaning='compatibility diagnostic; returned propagation remains direct M1')


def _windows(result,candidate,channel,state):
    return [w for w in result['candidates'][candidate][channel]['windows'] if w['state']==state]


def match_windows(predicted,reference):
    pairs=[]
    for i,a in enumerate(predicted):
        for j,b in enumerate(reference):
            overlap=(min(utc(a['end_utc']),utc(b['end_utc']))-max(utc(a['start_utc']),utc(b['start_utc']))).total_seconds()
            if overlap>0:
                pairs.append((-overlap,i,j))
    used_a,used_b=set(),set()
    matched=[]
    for _,i,j in sorted(pairs):
        if i in used_a or j in used_b:
            continue
        used_a.add(i); used_b.add(j)
        a,b=predicted[i],reference[j]
        matched.append(dict(predicted_index=i,reference_index=j,
                            start_error_s=(utc(a['start_utc'])-utc(b['start_utc'])).total_seconds(),
                            end_error_s=(utc(a['end_utc'])-utc(b['end_utc'])).total_seconds()))
    return dict(predicted_count=len(predicted),reference_count=len(reference),matched=matched,
                false_windows=len(predicted)-len(matched),missed_windows=len(reference)-len(matched),
                max_boundary_error_s=max((abs(row[k]) for row in matched for k in ('start_error_s','end_error_s')),default=None))


def disagreement(predicted,reference):
    a,b=predicted['opportunity']['segments'],reference['opportunity']['segments']
    i=j=0
    counts=dict(both_available_s=0.0,both_unavailable_s=0.0,optimistic_s=0.0,pessimistic_s=0.0,unknown_pair_s=0.0)
    while i<len(a) and j<len(b):
        left=max(utc(a[i]['start_utc']),utc(b[j]['start_utc']))
        right=min(utc(a[i]['end_utc']),utc(b[j]['end_utc']))
        duration=max(0,(right-left).total_seconds())
        x,y=a[i]['state'],b[j]['state']
        key=('unknown_pair_s' if 'unknown' in (x,y) else
             'both_available_s' if x==y=='available' else 'both_unavailable_s' if x==y else
             'optimistic_s' if x=='available' else 'pessimistic_s')
        counts[key]+=duration
        ea,eb=utc(a[i]['end_utc']),utc(b[j]['end_utc'])
        if ea<=eb:i+=1
        if eb<=ea:j+=1
    counts['known_pair_s']=sum(v for k,v in counts.items() if k!='unknown_pair_s')
    return counts


def compare_events(predicted,reference):
    if predicted['observation']!=reference['observation'] or predicted['candidate_ids']!=reference['candidate_ids']:
        raise ValueError('event comparison requires identical observation and candidate set')
    rows=[]
    for candidate in predicted['candidate_ids']:
        for channel,state in [('geometry','visible'),('quality','sufficient')]:
            p,r=predicted['candidates'][candidate][channel],reference['candidates'][candidate][channel]
            row=dict(candidate_id=candidate,channel=channel,**match_windows(_windows(predicted,candidate,channel,state),_windows(reference,candidate,channel,state)))
            row['seconds_delta']={s:p['seconds'][s]-r['seconds'][s] for s in p['seconds']}
            row['longest_delta']={s:p['longest_seconds'][s]-r['longest_seconds'][s] for s in p['seconds']}
            row['all_known_event_counts_match']=all(sum(w['state']==s for w in p['windows'])==sum(w['state']==s for w in r['windows']) for s in p['seconds'] if s!='unknown')
            rows.append(row)
    return dict(channels=rows,disagreement_seconds=disagreement(predicted,reference))


def convergence_pair(predicted,reference,boundary_s,duration_s):
    comparison=compare_events(predicted,reference)
    missing=any(segment['state']=='unknown' and segment['reason']!='transition_bracket'
                for result in (predicted,reference) for candidate in result['candidate_ids']
                for channel in ('geometry','quality') for segment in result['candidates'][candidate][channel]['segments'])
    failed=any(frame['records'][candidate]['status']!='computed' for result in (predicted,reference)
               for frame in result['samples'] for candidate in result['candidate_ids'])
    okay=not missing and not failed and all(row['false_windows']==row['missed_windows']==0 and row['all_known_event_counts_match']
        and (row['max_boundary_error_s'] is None or row['max_boundary_error_s']<=boundary_s)
        and max(map(abs,row['seconds_delta'].values()))<=duration_s
        and max(map(abs,row['longest_delta'].values()))<=duration_s for row in comparison['channels'])
    return dict(passed=okay,missing_reference=missing,failed_reference=failed,comparison=comparison)


def validate_split(passes):
    ids=[p['pass_id'] for p in passes]
    if len(ids)!=len(set(ids)) or {p['split'] for p in passes}!={'development','holdout'}:
        raise ValueError('whole-pass split requires unique IDs and separate development/holdout groups')
    ordered=sorted(passes,key=lambda p:utc(p['observation_start']))
    for p in ordered:
        if not utc(p['observation_start'])<utc(p['geometry_start'])<utc(p['geometry_end'])<utc(p['observation_end']):
            raise ValueError('complete pass must lie inside its padded observation')
    if any(utc(a['observation_end'])>=utc(b['observation_start']) for a,b in zip(ordered,ordered[1:])):
        raise ValueError('overlapping complete-pass observations cannot cross split')
    development=[p for p in ordered if p['split']=='development']
    holdout=[p for p in ordered if p['split']=='holdout']
    if utc(development[-1]['observation_end'])>=utc(holdout[0]['observation_start']):
        raise ValueError('holdout must follow development; no interleaving')
    return identity(passes)
