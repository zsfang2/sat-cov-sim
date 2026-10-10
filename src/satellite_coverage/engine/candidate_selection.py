"""Equal-cost candidate selection with separate development and holdout inputs."""

from dataclasses import dataclass
import json
import math

from ..config.pilot import canonical_bytes, exact_keys, identity, text_field
from ..orbit.visibility import utc

TIME_TOLERANCE_S = 1e-6
RULE = 'minimize_known_unavailable_plus_unknown_seconds; ties_within_1e-6_s_then_lexical_id'
COMPONENTS = ('sufficient_s', 'insufficient_s', 'invisible_s', 'unknown_s')


def _number(value,name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    return float(value)


@dataclass(frozen=True)
class _Snapshot:
    serialized: bytes

    def __post_init__(self):
        if not isinstance(self.serialized,bytes):
            raise ValueError('snapshot requires canonical JSON bytes')
        data=json.loads(self.serialized)
        self._validate(data)
        object.__setattr__(self,'serialized',canonical_bytes(data))

    @classmethod
    def from_mapping(cls,data):
        return cls(canonical_bytes(data))

    def to_mapping(self):
        return json.loads(self.serialized)

    @property
    def checksum(self):
        return identity(self.to_mapping())


@dataclass(frozen=True)
class CandidateSet(_Snapshot):
    def _validate(self,data):
        exact_keys(data,{'coordinate_basis','items'},'candidate set')
        text_field(data['coordinate_basis'],'coordinate_basis')
        items=data['items']
        if not isinstance(items,list) or not 1<=len(items)<=256:
            raise ValueError('require 1..256 candidates')
        ids=set(); heights=set(); costs=set()
        for item in items:
            exact_keys(item,{'candidate_id','east_m','north_m','height_agl_m','cost','feasible','reason'},'candidate')
            text_field(item['candidate_id'],'candidate_id'); text_field(item['reason'],'reason')
            if item['candidate_id'] in ids:raise ValueError('duplicate candidate ID')
            ids.add(item['candidate_id'])
            for key in ('east_m','north_m','height_agl_m','cost'):_number(item[key],key)
            if item['height_agl_m']<0 or item['cost']<=0 or type(item['feasible']) is not bool:
                raise ValueError('candidate requires nonnegative AGL, positive cost and explicit feasibility')
            heights.add(item['height_agl_m']); costs.add(item['cost'])
        if len(heights)!=1 or len(costs)!=1:
            raise ValueError('candidates must have identical AGL height and equal cost')
        items.sort(key=lambda item:item['candidate_id'])


@dataclass(frozen=True)
class PassRegistry(_Snapshot):
    def _validate(self,data):
        exact_keys(data,{'passes'},'pass registry')
        passes=data['passes']
        if not isinstance(passes,list) or not 2<=len(passes)<=1000:
            raise ValueError('require 2..1000 complete pass observations')
        seen=set()
        for p in passes:
            exact_keys(p,{'pass_id','split','start_utc','end_utc','basis'},'pass')
            text_field(p['pass_id'],'pass_id'); text_field(p['basis'],'pass basis')
            if p['pass_id'] in seen or p['split'] not in ('development','holdout'):
                raise ValueError('duplicate pass or invalid split')
            seen.add(p['pass_id'])
            a,b=utc(p['start_utc']),utc(p['end_utc'])
            if not 0<(b-a).total_seconds()<=7*86400:raise ValueError('invalid observation duration')
            p.update(start_utc=a.isoformat(),end_utc=b.isoformat())
        passes.sort(key=lambda p:p['start_utc'])
        if {p['split'] for p in passes}!={'development','holdout'}:
            raise ValueError('require both development and holdout passes')
        if any(utc(a['end_utc'])>=utc(b['start_utc']) for a,b in zip(passes,passes[1:])):
            raise ValueError('overlapping pass observations are not independent')
        if max(utc(p['end_utc']) for p in passes if p['split']=='development')>=min(utc(p['start_utc']) for p in passes if p['split']=='holdout'):
            raise ValueError('holdout must follow development without interleaving')


@dataclass(frozen=True)
class _Scores(_Snapshot):
    split = None

    def _validate(self,data):
        exact_keys(data,{'split','candidate_set','pass_registry','model_id','information_role','provenance','rows'},'scores')
        if self.split is None or data['split']!=self.split:
            raise ValueError('score split/type mismatch')
        for field in ('model_id','information_role','provenance'):text_field(data[field],field)
        candidates=CandidateSet.from_mapping(data['candidate_set'])
        registry=PassRegistry.from_mapping(data['pass_registry'])
        data['candidate_set'],data['pass_registry']=candidates.to_mapping(),registry.to_mapping()
        items=data['candidate_set']['items']
        passes={p['pass_id']:p for p in data['pass_registry']['passes'] if p['split']==self.split}
        expected={(c['candidate_id'],p) for c in items for p in passes}
        if not isinstance(data['rows'],list) or len(data['rows'])>100000:
            raise ValueError('score table requires a bounded list of rows')
        actual=set()
        for row in data['rows']:
            exact_keys(row,{'candidate_id','pass_id','source_id','longest_unavailable_s',*COMPONENTS},'score row')
            key=(row['candidate_id'],row['pass_id'])
            if key not in expected or key in actual:
                raise ValueError('duplicate, foreign or wrong-split score row')
            actual.add(key); text_field(row['source_id'],'source_id')
            for metric in (*COMPONENTS,'longest_unavailable_s'):
                if _number(row[metric],metric)<0:raise ValueError('durations cannot be negative')
            p=passes[row['pass_id']]
            duration=(utc(p['end_utc'])-utc(p['start_utc'])).total_seconds()
            if abs(math.fsum(row[k] for k in COMPONENTS)-duration)>TIME_TOLERANCE_S:
                raise ValueError('score durations must preserve the full observation denominator')
            if row['longest_unavailable_s']>row['insufficient_s']+row['invisible_s']+TIME_TOLERANCE_S:
                raise ValueError('longest unavailable exceeds cumulative known unavailable')
        if actual!=expected:raise ValueError('missing candidate/pass rows; unknown time cannot be dropped')
        data['rows'].sort(key=lambda r:(r['candidate_id'],r['pass_id']))


@dataclass(frozen=True)
class DevelopmentScores(_Scores):
    split='development'


@dataclass(frozen=True)
class HoldoutScores(_Scores):
    split='holdout'


def _aggregate(scores):
    data=scores.to_mapping()
    metrics=[]
    for candidate in data['candidate_set']['items']:
        rows=[r for r in data['rows'] if r['candidate_id']==candidate['candidate_id']]
        components={key:math.fsum(row[key] for row in rows) for key in COMPONENTS}
        metrics.append(dict(candidate_id=candidate['candidate_id'],feasible=candidate['feasible'],cost=candidate['cost'],
                            **components,observed_seconds=math.fsum(components.values()),
                            objective_s=math.fsum(components[k] for k in ('insufficient_s','invisible_s','unknown_s')),
                            longest_unavailable_s=max(row['longest_unavailable_s'] for row in rows)))
    return metrics


def _decision(development):
    data=development.to_mapping()
    metrics=_aggregate(development)
    feasible=[m for m in metrics if m['feasible']]
    minimum=min((m['objective_s'] for m in feasible),default=None)
    ties=sorted(m['candidate_id'] for m in feasible if m['objective_s']<=minimum+TIME_TOLERANCE_S) if feasible else []
    return dict(rule=RULE,status='selected' if ties else 'no_feasible_candidate',candidate_id=ties[0] if ties else None,
                tie_ids=ties,development_minimum_s=minimum,
                ranking=sorted(feasible,key=lambda m:(m['objective_s'],m['candidate_id'])),all_candidate_metrics=metrics,
                development_checksum=development.checksum,candidate_set_checksum=CandidateSet.from_mapping(data['candidate_set']).checksum,
                pass_registry_checksum=PassRegistry.from_mapping(data['pass_registry']).checksum,
                information_role=data['information_role'],model_id=data['model_id'],
                scope='upper conditional opportunity shortfall includes unknown time; not measured service outage')


@dataclass(frozen=True)
class SelectionReceipt(_Snapshot):
    def _validate(self,data):
        exact_keys(data,{'development','decision'},'selection receipt')
        development=DevelopmentScores.from_mapping(data['development'])
        if data['decision']!=_decision(development):
            raise ValueError('selection receipt does not match development-only decision')
        data['development']=development.to_mapping()


def select_candidate(development):
    if type(development) is not DevelopmentScores:
        raise ValueError('selector accepts DevelopmentScores only; holdout is evaluation-only')
    return SelectionReceipt.from_mapping(dict(development=development.to_mapping(),decision=_decision(development)))


def regret_seconds(chosen,minimum):
    difference=_number(chosen,'chosen objective')-_number(minimum,'oracle objective')
    if min(chosen,minimum)<0:raise ValueError('objectives cannot be negative')
    if difference < -TIME_TOLERANCE_S:raise ValueError('negative regret beyond rounding tolerance')
    return max(0.0,difference)


def evaluate_selection(receipt,holdout):
    if type(receipt) is not SelectionReceipt or type(holdout) is not HoldoutScores:
        raise ValueError('evaluation requires sealed selection receipt and HoldoutScores')
    selection=receipt.to_mapping()['decision']; data=holdout.to_mapping()
    for field,cls in [('candidate_set',CandidateSet),('pass_registry',PassRegistry)]:
        if cls.from_mapping(data[field]).checksum!=selection[field+'_checksum']:
            raise ValueError('selection/evaluation candidate or pass identity mismatch')
    metrics=_aggregate(holdout)
    feasible=sorted((m for m in metrics if m['feasible']),key=lambda m:(m['objective_s'],m['candidate_id']))
    chosen=next((m for m in feasible if m['candidate_id']==selection['candidate_id']),None)
    oracle=feasible[0] if feasible else None
    result=dict(status='evaluated' if chosen is not None else 'no_feasible_candidate',selection_checksum=receipt.checksum,
                holdout_checksum=holdout.checksum,candidate_set_checksum=selection['candidate_set_checksum'],
                pass_registry_checksum=selection['pass_registry_checksum'],rule=RULE,selected=chosen,oracle=oracle,
                regret_s=regret_seconds(chosen['objective_s'],oracle['objective_s']) if chosen is not None else None,
                ranking=feasible,all_candidate_metrics=metrics,
                observed_seconds=metrics[0]['observed_seconds'],holdout_rows=data['rows'],
                longest_meaning='maximum known unavailable interval within one observed pass; not joined across gaps',
                service_eligibility='unknown',minimum_useful_gain='undetermined',
                scope='holdout oracle is retrospective only; conservative conditional objective, not business certification')
    return result


def compare_evaluations(evaluations,baseline):
    if baseline not in evaluations:raise ValueError('baseline evaluation is required')
    base=evaluations[baseline]
    for result in evaluations.values():
        if any(result[k]!=base[k] for k in ('holdout_checksum','candidate_set_checksum','pass_registry_checksum','rule')):
            raise ValueError('all methods require the same holdout reference and candidates')
    return {method:dict(regret_s=result['regret_s'],
                        gain_s=None if base['selected'] is None or result['selected'] is None else base['selected']['objective_s']-result['selected']['objective_s'],
                        selected_candidate_id=None if result['selected'] is None else result['selected']['candidate_id'])
            for method,result in evaluations.items()}


def score_row_from_events(events,site_id,pass_id,registry):
    """Convert a site's multi-satellite opportunities without dropping empty time."""
    if type(registry) is not PassRegistry:raise ValueError('event row requires a pass registry')
    p=next((p for p in registry.to_mapping()['passes'] if p['pass_id']==pass_id),None)
    if p is None or any(utc(events['observation'][k])!=utc(p[k]) for k in ('start_utc','end_utc')):
        raise ValueError('event observation does not match the registered complete pass')
    values={key:[] for key in COMPONENTS}
    for index,segment in enumerate(events['opportunity']['segments']):
        if segment['state']=='available':key='sufficient_s'
        elif segment['state']=='unknown':key='unknown_s'
        elif segment['state']=='unavailable':
            states=[events['candidates'][c]['quality']['segments'][index]['state'] for c in events['candidate_ids']]
            key='insufficient_s' if 'insufficient' in states else 'invisible_s'
        else:raise ValueError('invalid opportunity state')
        values[key].append(segment['duration_s'])
    return dict(candidate_id=site_id,pass_id=pass_id,source_id=identity(events),
                **{k:math.fsum(v) for k,v in values.items()},
                longest_unavailable_s=events['opportunity']['longest_seconds']['unavailable'])
