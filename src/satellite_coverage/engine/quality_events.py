"""Conditional, sample-supported events with explicit unresolved time intervals."""

from copy import deepcopy
from datetime import timedelta
import math

from ..config.link import LinkConfig
from ..config.pilot import identity
from ..orbit.visibility import utc
from .links import calculate_links


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be finite and positive')
    return float(value)


def _interval(start, end):
    start, end = utc(start), utc(end)
    if not 0 < (end-start).total_seconds() <= 7*86400:
        raise ValueError('observation interval must be positive and at most seven days')
    return start, end


def classify(record, minimum_elevation_deg=0):
    """Keep geometry independently usable when a power component is unavailable."""
    if not isinstance(record, dict) or record.get('status') not in ('computed', 'failed', 'not_computed', 'unknown'):
        raise ValueError('invalid candidate record status')
    geometry = record.get('geometry')
    state = dict(geometry='unknown', quality='unknown', margin_db=None,
                 reason=record.get('reason', 'unavailable_geometry'), source_status=record['status'])
    if geometry is None:
        return state
    elevation = geometry.get('elevation_deg')
    if isinstance(elevation, bool) or not isinstance(elevation, (int, float)) or not math.isfinite(elevation) or not -90 <= elevation <= 90:
        raise ValueError('geometry requires finite elevation in [-90,90]')
    visible = elevation > 0 and elevation >= minimum_elevation_deg
    state['geometry'] = 'visible' if visible else 'invisible'
    if not visible:
        state.update(quality='invisible', reason='geometrically_invisible')
        return state
    if record['status'] != 'computed':
        return state
    margin = (record.get('budget') or {}).get('margin')
    if margin is None:
        state['reason'] = 'margin_unavailable'
        return state
    if margin.get('unit') != 'dB' or margin.get('status') not in ('known', 'unknown', 'not_applicable', 'not_computed', 'failed'):
        raise ValueError('margin must have a supported quantity status and dB unit')
    value = margin.get('value')
    if margin['status'] != 'known':
        if value is not None:
            raise ValueError('unavailable margin cannot contain a numerical value')
        state['reason'] = margin.get('reason', margin['status'])
        return state
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('known margin must be finite')
    state.update(quality='sufficient' if value >= 0 else 'insufficient', margin_db=value,
                 reason='declared_threshold_comparison')
    return state


def _segment(a, b, left, right, max_gap_s):
    if (b-a).total_seconds() > max_gap_s:
        state, reason = 'unknown', 'sampling_gap'
    elif left == 'unknown' or right == 'unknown':
        state, reason = 'unknown', 'unavailable_endpoint'
    elif left != right:
        state, reason = 'unknown', 'transition_bracket'
    else:
        state, reason = left, 'matching_sample_endpoints'
    return dict(start_utc=a.isoformat(), end_utc=b.isoformat(), duration_s=(b-a).total_seconds(),
                state=state, reason=reason, left_state=left, right_state=right)


def _summarize(segments, states, namespace):
    seconds = {state: math.fsum(s['duration_s'] for s in segments if s['state'] == state) for state in states}
    windows = []
    for index, segment in enumerate(segments):
        state = segment['state']
        if windows and windows[-1]['state'] == state:
            windows[-1]['end_utc'] = segment['end_utc']
            windows[-1]['duration_s'] += segment['duration_s']
            windows[-1]['last_segment'] = index
        else:
            windows.append(dict(start_utc=segment['start_utc'], end_utc=segment['end_utc'], state=state,
                                duration_s=segment['duration_s'], first_segment=index, last_segment=index))
    for window in windows:
        first, last = window.pop('first_segment'), window.pop('last_segment')
        window['start_clipped'] = first == 0
        window['end_clipped'] = last == len(segments)-1
        reasons = []
        for side, neighbor in (('start', first-1), ('end', last+1)):
            if not 0 <= neighbor < len(segments):
                reasons.append(side+'_observation_boundary')
            elif segments[neighbor]['state'] == 'unknown':
                previous = segments[neighbor]
                if previous['reason'] == 'transition_bracket':
                    window[side+'_bracket_utc'] = [previous['start_utc'], previous['end_utc']]
                else:
                    reasons.append(side+'_unknown_interval')
        window['censored'] = bool(reasons)
        window['censor_reasons'] = reasons
        window['event_type'] = namespace['channel']+'_'+window['state']
        window['event_id'] = identity(dict(namespace=namespace,start=window['start_utc'],end=window['end_utc'],state=window['state']))
        window['unknown_duration_s'] = window['duration_s'] if window['state'] == 'unknown' else 0.0
    return dict(seconds=seconds, total_seconds=math.fsum(seconds.values()), windows=windows,
                longest_seconds={state: max((w['duration_s'] for w in windows if w['state'] == state), default=0)
                                 for state in states}, segments=segments)


def summarize_events(samples, *, start, end, candidate_ids, max_gap_s, minimum_elevation_deg=0):
    """Integrate interval lengths, retaining all records and unknown gaps.

    Matching endpoints support a constant-state interval estimate. Differing
    endpoints never create an interpolated event or a claim of direct precision.
    """
    begin, finish = _interval(start, end)
    max_gap_s = _positive(max_gap_s, 'max_gap_s')
    if isinstance(minimum_elevation_deg, bool) or not isinstance(minimum_elevation_deg, (int, float)) or not 0 <= minimum_elevation_deg < 90:
        raise ValueError('minimum_elevation_deg must be in [0,90)')
    if not isinstance(candidate_ids, list) or any(not isinstance(c, str) or not c for c in candidate_ids) or len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError('candidate IDs must be unique nonempty strings')
    if not isinstance(samples, list) or not 2 <= len(samples) <= 100001:
        raise ValueError('require 2..100001 time samples')
    times = [utc(s['timestamp_utc']) for s in samples]
    if times[0] != begin or times[-1] != finish or any(a >= b for a,b in zip(times, times[1:])):
        raise ValueError('samples must strictly increase and include both observation endpoints')
    frames, candidates = [], {}
    for time, sample in zip(times, samples):
        records = sample['records']
        if not isinstance(records, dict) or set(records)-set(candidate_ids):
            raise ValueError('sample contains undeclared candidates')
        frame = dict(timestamp_utc=time.isoformat(), records={}, states={})
        for candidate in candidate_ids:
            record = deepcopy(records.get(candidate, dict(status='unknown', reason='missing_candidate_sample', geometry=None, budget=None)))
            if record.get('candidate_id', candidate) != candidate or utc(record.get('timestamp_utc', time.isoformat())) != time:
                raise ValueError('candidate/time binding mismatch')
            frame['records'][candidate] = record
            frame['states'][candidate] = classify(record, minimum_elevation_deg)
        frames.append(frame)
    for candidate in candidate_ids:
        entry = {}
        for channel, states in (('geometry', ('visible','invisible','unknown')),
                                ('quality', ('sufficient','insufficient','invisible','unknown'))):
            segments = [_segment(a,b,frames[i]['states'][candidate][channel],frames[i+1]['states'][candidate][channel],max_gap_s)
                        for i,(a,b) in enumerate(zip(times,times[1:]))]
            entry[channel] = _summarize(segments, states, dict(candidate_id=candidate,channel=channel))
        entry['threshold_contacts_utc'] = [f['timestamp_utc'] for f in frames if f['states'][candidate]['margin_db'] == 0]
        candidates[candidate] = entry
    opportunities = []
    for i, (a,b) in enumerate(zip(times,times[1:])):
        parts = [candidates[c]['quality']['segments'][i] for c in candidate_ids]
        states = [p['state'] for p in parts]
        state = 'available' if 'sufficient' in states else ('unknown' if 'unknown' in states else 'unavailable')
        reason = 'no_candidates' if not parts else 'candidate_interval_union'
        if state == 'unknown':
            reason = 'transition_bracket' if all(p['state'] != 'unknown' or p['reason'] == 'transition_bracket' for p in parts) else 'unavailable_candidate_interval'
        opportunities.append(dict(start_utc=a.isoformat(), end_utc=b.isoformat(), duration_s=(b-a).total_seconds(), state=state, reason=reason))
    return dict(schema_version=1, observation=dict(start_utc=begin.isoformat(),end_utc=finish.isoformat()),
                candidate_ids=list(candidate_ids), candidates=candidates, samples=frames,
                opportunity=_summarize(opportunities, ('available','unavailable','unknown'), dict(candidate_ids=list(candidate_ids),channel='opportunity')),
                integration='interval-duration weighting; matching endpoints assumed constant; unresolved transitions remain unknown',
                max_gap_s=max_gap_s, minimum_elevation_deg=minimum_elevation_deg,
                input_checksum=identity(samples), service_eligibility='unknown',
                scope='conditional candidate propagation opportunity; no service selection or continuity guarantee')


def direct_events(evaluators, *, start, end, step_s, max_probe_step_s, event_tolerance_s,
                  candidate_identities, minimum_elevation_deg=0, max_samples=100001):
    """Evaluate all candidates at every added timestamp; never interpolate power."""
    begin, finish = _interval(start,end)
    step_s = _positive(step_s,'step_s')
    probe = _positive(max_probe_step_s,'max_probe_step_s')
    tolerance = _positive(event_tolerance_s,'event_tolerance_s')
    if min(step_s,probe,tolerance) < 1e-6 or tolerance > probe:
        raise ValueError('time controls require microsecond resolution and tolerance <= probe step')
    if type(max_samples) is not int or not 2 <= max_samples <= 100001:
        raise ValueError('max_samples must be in 2..100001')
    if set(evaluators) != set(candidate_identities) or any(not isinstance(c,str) or not c or not callable(e) for c,e in evaluators.items()):
        raise ValueError('each candidate requires an evaluator and identity')
    if any(not candidate_identities[c] for c in evaluators):
        raise ValueError('candidate identities cannot be empty')
    # Validate scalar controls before any expensive callback or side effect.
    if isinstance(minimum_elevation_deg,bool) or not isinstance(minimum_elevation_deg,(int,float)) or not 0 <= minimum_elevation_deg < 90:
        raise ValueError('minimum elevation outside [0,90)')
    duration = round((finish-begin).total_seconds()*1e6)
    step_us = max(1,round(step_s*1e6))
    probe_us, tolerance_us = max(1,round(probe*1e6)),max(1,round(tolerance*1e6))
    if (duration+min(step_us,probe_us)-1)//min(step_us,probe_us)+1 > max_samples:
        raise ValueError('event sample budget exceeded before evaluation')
    candidates = sorted(evaluators)
    frames, states = {}, {}
    def evaluate(tick):
        if tick in frames:
            return
        if len(frames) >= max_samples:
            raise ValueError('event sample budget exhausted; no completed event result')
        time = begin+timedelta(microseconds=tick)
        records = {}
        for candidate in candidates:
            try:
                record = evaluators[candidate](time)
            except (ValueError,RuntimeError,ArithmeticError) as exc:
                record = dict(status='failed',reason=f'direct_evaluation: {exc}',geometry=None,budget=None)
            if not isinstance(record,dict) or record.get('candidate_id',candidate) != candidate or utc(record.get('timestamp_utc',time.isoformat())) != time:
                raise ValueError('direct evaluator returned a mismatched record')
            records[candidate] = deepcopy(record)
        frames[tick] = dict(timestamp_utc=time.isoformat(),records=records)
        states[tick] = {c: classify(records[c],minimum_elevation_deg) for c in candidates}
    ticks = list(range(0,duration,step_us))+[duration]
    for tick in ticks:
        evaluate(tick)
    stack = list(zip(ticks,ticks[1:]))
    while stack:
        left,right = stack.pop()
        different = any(states[left][c][channel] != states[right][c][channel] for c in candidates for channel in ('geometry','quality'))
        if right-left > probe_us or (different and right-left > tolerance_us):
            middle = (left+right)//2
            evaluate(middle)
            stack.extend(((left,middle),(middle,right)))
    result = summarize_events([frames[t] for t in sorted(frames)],start=start,end=end,candidate_ids=candidates,
                              max_gap_s=probe_us/1e6+1e-12,minimum_elevation_deg=minimum_elevation_deg)
    settings = dict(step_s=step_us/1e6,max_probe_step_s=probe_us/1e6,event_tolerance_s=tolerance_us/1e6,
                    max_samples=max_samples,candidate_identities=deepcopy(candidate_identities))
    result.update(evaluation='direct_at_every_recorded_time', direct_time_count=len(frames),
                  candidate_evaluation_count=len(frames)*len(candidates), settings=settings,
                  run_checksum=identity(dict(settings=settings,input_checksum=result['input_checksum'],observation=result['observation'])),
                  detection_limit='features narrower than probe spacing may be missed; no continuous or business accuracy certification')
    return result


class DirectLinkEvaluator:
    """Direct M1 adapter; original interval fixes TLE selection and age checks."""

    def __init__(self, config, catalog=None, *, terrain=None):
        self.config = config if isinstance(config,LinkConfig) else LinkConfig.from_mapping(config)
        data = self.config.to_mapping()
        if data['source']['mode'] not in ('tle','fixed_ecef'):
            raise ValueError('direct time evaluation cannot interpolate a sampled sequence')
        self.catalog, self.terrain = catalog,terrain
        self.candidate_id = data['source']['candidate_id']
        self.identity = dict(config_checksum=self.config.checksum,catalog_sha256=None if catalog is None else catalog.checksum,
                             terrain=None if terrain is None else terrain.descriptor())

    def __call__(self,time):
        return calculate_links(self.config,self.catalog,terrain=self.terrain,evaluation_times=[time.isoformat()])['records'][0]
