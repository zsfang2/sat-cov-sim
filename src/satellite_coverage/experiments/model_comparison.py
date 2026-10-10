"""Paired model statistics, kept distinct from same-model refinement evidence."""

from collections import Counter, defaultdict
from copy import deepcopy
import itertools

import numpy as np

from ..config.pilot import identity
from ..engine.model_comparison import ROLES, binding, validate_pair


def classify_refinements(rows, tolerance_db=.1):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['identity']['query_id'], row['model']['role_id'])].append(row)
    appendix = []
    for (query, role), group in sorted(groups.items()):
        group.sort(key=lambda row: -row['terrain']['step_m'])
        if any(binding(row, refinement=True) != binding(group[0], refinement=True) for row in group):
            raise ValueError('refinement changed inputs other than step')
        model_keys = ('role_id', 'version', 'model_family', 'solver_source', 'source_fingerprint', 'code_commit',
                      'included_effects', 'excluded_effects', 'independence_limits')
        if any(any(row['model'][k] != group[0]['model'][k] for k in model_keys) for row in group):
            raise ValueError('refinement changed solver identity')
        steps = [row['terrain']['step_m'] for row in group]
        if len(set(steps)) != len(steps):
            raise ValueError('duplicate refinement observation')
        complete = all(row['result']['status'] == 'known' for row in group)
        refinements = len(steps) == 3 and steps[0] == 2*steps[1] and steps[1] == 2*steps[2]
        losses = [row['result']['raw_loss_db'] for row in group]
        deltas = [abs(a-b) if a is not None and b is not None else None for a, b in zip(losses, losses[1:])]
        stable = len({(r['result']['visibility'], r['result']['cap_triggered']) for r in group}) == 1
        eligible = complete and refinements and stable and all(d is not None and d <= tolerance_db for d in deltas)
        status = 'eligible_within_tested_discretization' if eligible else 'unverified' if complete else 'unavailable'
        appendix.append(dict(query_id=query, role_id=role, steps_m=steps, raw_losses_db=losses,
                             adjacent_raw_deltas_db=deltas, complete=complete, stable_visibility_cap=stable,
                             eligibility=status if role != ROLES[0] else 'not_attenuation_reference',
                             tolerance_db=tolerance_db, scene_id=group[0]['identity']['scene_id']))
        if role == ROLES[2]:
            for row in group:
                row['model']['reference_eligibility'] = status
                row['model']['evidence_level'] = ('V1' if eligible else 'V0' if row['terrain']['surface_type'] == 'synthetic'
                                                   else 'numerical_model_unverified')
                row['identity']['result_id'] = identity(dict(pair_id=row['identity']['pair_id'], model=row['model']))
    return appendix


def error_stats(values):
    if not values:
        return dict(count=0, signed_mean_db=None, mae_db=None, p95_absolute_db=None, max_absolute_db=None)
    values = np.asarray(values)
    return dict(count=len(values), signed_mean_db=float(values.mean()), mae_db=float(np.abs(values).mean()),
                p95_absolute_db=float(np.percentile(np.abs(values), 95)), max_absolute_db=float(np.max(np.abs(values))))


def summarize(rows):
    expected = deepcopy(rows)
    classify_refinements(expected)
    for row, check in zip(rows, expected):
        if any(row['model'][key] != check['model'][key] for key in ('evidence_level', 'reference_eligibility')):
            raise ValueError('reference grade lacks matching refinement evidence')
    pairs = defaultdict(list)
    for row in rows:
        pairs[row['identity']['pair_id']].append(row)
    differences, threshold, visibility = [], [], []
    for pair, group in sorted(pairs.items()):
        validate_pair(group)
        by_role = {row['model']['role_id']: row for row in group}
        current, reference = [by_role[role] for role in ROLES[1:]]
        a, b = current['result'], reference['result']
        known = a['status'] == b['status'] == 'known'
        capped = a['cap_triggered'] or b['cap_triggered']
        eligible = reference['model']['reference_eligibility'] == 'eligible_within_tested_discretization'
        item = dict(pair_id=pair, query_id=current['identity']['query_id'], scene_id=current['identity']['scene_id'],
                    elevation_deg=current['geometry']['elevation_deg'], frequency_hz=current['budget']['frequency_hz'],
                    blockage=a['visibility'], step_m=current['terrain']['step_m'], paired_known=known,
                    capped=capped, reference_eligible=eligible,
                    current_raw_loss_db=a['raw_loss_db'], reference_raw_loss_db=b['raw_loss_db'],
                    current_used_loss_db=a['used_loss_db'], reference_used_loss_db=b['used_loss_db'],
                    raw_difference_db=b['raw_loss_db']-a['raw_loss_db'] if known else None,
                    used_difference_db=b['used_loss_db']-a['used_loss_db'] if known else None,
                    power_difference_db=b['received_power']['value']-a['received_power']['value'] if known else None)
        differences.append(item)
        for offset in current['budget']['threshold_offsets_db']:
            qa, qb = [r['margin_by_threshold'][str(offset)] for r in (a, b)]
            usable = qa['status'] == qb['status'] == 'known'
            threshold.append(dict(pair_id=pair, offset_db=offset, known=usable,
                                  current_pass=qa['value'] >= 0 if usable else None,
                                  reference_pass=qb['value'] >= 0 if usable else None,
                                  disagreement=(qa['value'] >= 0) != (qb['value'] >= 0) if usable else None,
                                  capped=capped, reference_eligible=eligible))
        for role_a, role_b in itertools.combinations(ROLES, 2):
            visibility.append(dict(role_a=role_a, role_b=role_b,
                                   visibility_a=by_role[role_a]['result']['visibility'],
                                   visibility_b=by_role[role_b]['result']['visibility']))
    groups = defaultdict(list)
    for item in differences:
        groups[(item['scene_id'], item['elevation_deg'], item['blockage'], item['frequency_hz'])].append(item)
    grouped = []
    for key, items in sorted(groups.items()):
        usable = [i for i in items if i['paired_known'] and not i['capped']]
        converged = [i for i in usable if i['reference_eligible']]
        grouped.append(dict(zip(('scene_id', 'elevation_deg', 'blockage', 'frequency_hz'), key),
                            total_pairs=len(items), paired_known=sum(i['paired_known'] for i in items),
                            capped_pairs=sum(i['capped'] for i in items), model_difference=error_stats([i['raw_difference_db'] for i in usable]),
                            used_loss_difference=error_stats([i['used_difference_db'] for i in usable]),
                            received_power_difference=error_stats([i['power_difference_db'] for i in usable]),
                            converged_reference_difference=error_stats([i['raw_difference_db'] for i in converged])))
    thresholds = []
    for offset in sorted({t['offset_db'] for t in threshold}):
        items = [t for t in threshold if t['offset_db'] == offset]
        known = [t for t in items if t['known']]
        thresholds.append(dict(offset_db=offset, total=len(items), known=len(known), unknown=len(items)-len(known),
                               disagreements=sum(t['disagreement'] for t in known), capped=sum(t['capped'] for t in known),
                               uncapped_disagreements=sum(t['disagreement'] for t in known if not t['capped']),
                               uncapped_known=sum(not t['capped'] for t in known)))
    counts = Counter(tuple(v[k] for k in ('role_a', 'role_b', 'visibility_a', 'visibility_b')) for v in visibility)
    visibility_counts = [dict(zip(('role_a', 'role_b', 'visibility_a', 'visibility_b'), key), count=count)
                         for key, count in sorted(counts.items())]
    role_stats = []
    for role in ROLES:
        selected = [r for r in rows if r['model']['role_id'] == role]
        role_stats.append(dict(role_id=role, rows=len(selected), statuses=dict(Counter(r['result']['status'] for r in selected)),
                               failure_kinds=dict(Counter(r['result']['failure_kind'] or 'none' for r in selected)),
                               cap_count=sum(r['result']['cap_triggered'] for r in selected),
                               solver_wall_s=sum(r['resources']['wall_time_s'] for r in selected),
                               peak_process_rss_kib=max((r['resources']['process_peak_rss_kib'] for r in selected), default=0),
                               memory_attribution='process_shared_not_per_solver',
                               reference_eligibility=dict(Counter(r['model']['reference_eligibility'] for r in selected))))
    return dict(pair_count=len(pairs), row_count=len(rows), roles=role_stats, groups=grouped,
                thresholds=thresholds, visibility=visibility_counts,
                differences=differences, threshold_details=threshold,
                capped_pairs=[i for i in differences if i['capped']],
                failures=[dict(pair_id=r['identity']['pair_id'], role_id=r['model']['role_id'], **r['result'])
                          for r in rows if r['result']['status'] not in ('known',)],
                scope='finite-radius numerical-model differences, not measurement error; sky has no dB comparison')
