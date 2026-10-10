"""Finite-radius information layers and conservative fixed-decision evidence."""

from copy import deepcopy
import time

from ..config.pilot import identity
from ..engine.model_comparison import ROLES, common_budget, compare_models
from ..engine.quality_events import summarize_events
from ..engine.terrain_context import TerrainContext
from .model_comparison import classify_refinements

METHODS = ('no_terrain', 'sky_proxy', 'm3_single_edge', 'm4_multi_edge_reference')


def layer_record(propagation, method, eirp_dbm, threshold_dbm):
    """Power-only scenario changes derive from fixed propagation, never from holdout."""
    if method not in METHODS:
        raise ValueError('unknown information method')
    source = propagation['layers'][method]
    result = dict(timestamp_utc=propagation['timestamp_utc'], candidate_id=propagation['satellite_id'],
                  status=source['status'], geometry=deepcopy(propagation['geometry']),
                  reason=source['reason'], budget=None,
                  source_record_checksum=propagation['checksum'], information_role=method,
                  scenario=dict(eirp_dbm=eirp_dbm, threshold_dbm=threshold_dbm),
                  scope='finite-radius conditional research; not physical truth or service')
    if method == 'sky_proxy':
        result['geometric_proxy'] = dict(visibility=source['visibility'], scope='finite_radius_sky_outline_only')
    else:
        power = None if source['power_dbm'] is None else source['power_dbm']+eirp_dbm-propagation['base_eirp_dbm']
        result['budget'] = dict(received_power=dict(value=power, unit='dBm', status='known' if power is not None else 'unknown'),
            margin=dict(value=None if power is None else power-threshold_dbm, unit='dB',
                        status='known' if power is not None else 'unknown', reason=source['reason']))
    result['config_checksum'] = identity(dict(source=propagation['checksum'], method=method,
                                               eirp_dbm=eirp_dbm, threshold_dbm=threshold_dbm))
    return result


class PropagationLedger:
    """Share exact propagation across scenario analysis; this is not a speed benchmark."""

    def __init__(self, base, grid, receiver, cfg, site_id, pass_id, provenance, stream, *, native_spacing_m):
        self.base, self.receiver, self.cfg = base, receiver, cfg
        self.site_id, self.pass_id, self.provenance, self.stream = site_id, pass_id, provenance, stream
        self.native_spacing_m = native_spacing_m
        self.contexts = [TerrainContext(grid, receiver['lon_deg'], receiver['lat_deg'], cfg['radius_m'], step,
                            effective_radius_m=cfg['effective_radius_m'], loss_cap_db=cfg['loss_cap_db'],
                            sampling_method='cell_intervals') for step in cfg['spatial_steps_m']]
        self.memo = {}
        self.costs = dict(requests=0, direct_queries=0, analysis_reuses=0, base_geometry_budget_s=0.0,
                          shared_profile_s=0.0, roles_s={r:0.0 for r in ROLES}, comparison_total_s=0.0,
                          io_s=0.0, reference_eligible=0, reference_unverified=0, below_horizon=0)

    def __call__(self, instant):
        self.costs['requests'] += 1
        stamp = instant.isoformat()
        if stamp in self.memo:
            self.costs['analysis_reuses'] += 1
            return self.memo[stamp]
        import json
        started = time.perf_counter()
        baseline = self.base(instant)
        self.costs['base_geometry_budget_s'] += time.perf_counter()-started
        geometry = baseline['geometry']
        if geometry is None:
            raise ValueError('direct baseline geometry unavailable')
        power = baseline['budget']['received_power']
        layers = dict(no_terrain=dict(status=baseline['status'], power_dbm=power['value'] if power['status']=='known' else None,
                                      reason='declared FSPL and constant atmosphere only'))
        evidence, eligibility = [], None
        if geometry['elevation_deg'] <= 0:
            self.costs['below_horizon'] += 1
            layers['sky_proxy'] = dict(status='computed', visibility='not_applicable', reason='below_horizon')
            for method in METHODS[2:]:
                layers[method] = dict(status='computed', power_dbm=None, reason='below_horizon')
        else:
            rows_by_step = []
            g = dict(geometry, frequency_hz=self.cfg['frequency_hz'])
            budget = common_budget(frequency_hz=self.cfg['frequency_hz'], slant_range_m=g['slant_range_m'],
                eirp_dbm=self.cfg['eirps_dbm'][0], receiver_gain_dbi=0,
                nonlocal_losses_db=dict(gas=self.cfg['atmosphere_loss_db'],rain=0,clutter=0,other=0), threshold_offsets_db=[0])
            metadata = dict(sample_id=f'{self.site_id}:{self.pass_id}:{stamp}', candidate_id=self.site_id,
                timestamp_utc=stamp, pass_id=self.pass_id, satellite_id=self.cfg['norad_id'], scene_id='qinling_mountain',
                config_hash=identity(self.cfg), native_spacing_m=self.native_spacing_m)
            for context in self.contexts:
                begin = time.perf_counter()
                rows, profile = compare_models(context,g,self.receiver,budget,metadata=metadata,provenance=self.provenance,
                    reference_limits={k:self.cfg[k] for k in ('maximum_points','maximum_depth','maximum_nodes')})
                self.costs['comparison_total_s'] += time.perf_counter()-begin
                self.costs['shared_profile_s'] += rows[0]['resources']['shared_preparation_time_s']
                for row in rows:
                    self.costs['roles_s'][row['model']['role_id']] += row['resources']['wall_time_s']
                rows_by_step.append(rows)
            refs = [rows[2] for rows in rows_by_step]
            eligibility = classify_refinements(refs,self.cfg['spatial_raw_tolerance_db'])[0]
            eligible = eligibility['eligibility']=='eligible_within_tested_discretization'
            self.costs['reference_eligible' if eligible else 'reference_unverified'] += 1
            sky, current, reference = rows_by_step[0][0], rows_by_step[0][1], refs[-1]
            layers['sky_proxy'] = dict(status='computed' if sky['result']['status']=='known' else 'unknown',
                visibility=sky['result']['visibility'],reason='sky_has_no_quality_model')
            for method,row,allowed in [('m3_single_edge',current,True),('m4_multi_edge_reference',reference,eligible)]:
                q=row['result']['received_power']
                known=allowed and q['status']=='known'
                layers[method]=dict(status='computed' if known else 'unknown', power_dbm=q['value'] if known else None,
                    reason='finite_radius_conditional' if known else 'spatial_reference_unverified_or_unavailable')
            # Archive all three roles and steps, with profile recovery from frozen grids and exact geometry.
            for rows in rows_by_step:
                evidence.extend(dict(identity=row['identity'], role=row['model']['role_id'],step_m=row['terrain']['step_m'],
                    profile_sha256=row['terrain']['profile_sha256'],candidate_sha256=row['terrain']['candidate_sha256'],
                    reference_eligibility=row['model']['reference_eligibility'],result=row['result']) for row in rows)
        item = dict(timestamp_utc=stamp, satellite_id=self.cfg['norad_id'], site_id=self.site_id, pass_id=self.pass_id,
                    base_eirp_dbm=self.cfg['eirps_dbm'][0], geometry=geometry, layers=layers,
                    reference_eligibility=eligibility, paired_evidence=evidence,
                    recovery='frozen centered grid, config, receiver and exact geometry reproduce omitted profiles')
        item['checksum'] = identity(item)
        begin = time.perf_counter()
        self.stream.write(json.dumps(item,allow_nan=False,separators=(',',':'))+'\n')
        self.costs['io_s'] += time.perf_counter()-begin
        # Large pairing evidence stays on disk; derived records bind the full line checksum.
        self.memo[stamp] = {k:v for k,v in item.items() if k != 'paired_evidence'}
        self.costs['direct_queries'] += 1
        return self.memo[stamp]


def unavailable_reference(events, reason):
    """Keep observed geometry and denominator when temporal reference fails eligibility."""
    frames = []
    for frame in events['samples']:
        records = {}
        for candidate, record in frame['records'].items():
            records[candidate] = dict(timestamp_utc=frame['timestamp_utc'],candidate_id=candidate,
                status='unknown', geometry=deepcopy(record['geometry']), budget=None, reason=reason,
                source_record_checksum=identity(record))
        frames.append(dict(timestamp_utc=frame['timestamp_utc'],records=records))
    result = summarize_events(frames,start=events['observation']['start_utc'],end=events['observation']['end_utc'],
        candidate_ids=events['candidate_ids'],max_gap_s=events['max_gap_s'])
    result['reference_eligibility'] = dict(eligible=False, reason=reason, diagnostic_event_checksum=identity(events))
    return result


def uncertainty_intervals(evaluation):
    """Known unavailability is a lower bound; unknown-inclusive objective an upper bound."""
    metrics = evaluation['all_candidate_metrics']
    selected = evaluation['selected']
    if selected is None:
        return None
    lower = lambda m:m['insufficient_s']+m['invisible_s']
    feasible = [m for m in metrics if m['feasible']]
    return dict(selected_lower_s=lower(selected), selected_upper_s=selected['objective_s'],
        regret_lower_s=max(0,lower(selected)-min(m['objective_s'] for m in feasible)),
        regret_upper_s=max(0,selected['objective_s']-min(lower(m) for m in feasible)),
        meaning='partial-identification interval under unknown time, not a measured physical error bound')
