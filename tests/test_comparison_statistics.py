from copy import deepcopy

import pytest

from satellite_coverage.engine.model_comparison import ROLES
from satellite_coverage.experiments.model_comparison import classify_refinements, summarize
from test_model_comparison import request


def test_reference_requires_both_refinements_and_stable_state():
    rows = [r for step in (10, 5, 2.5) for r in request(step=step)[0]]
    reference = [r for r in rows if r['model']['role_id'] == ROLES[2]]
    # Explicit adversarial convergence data: one small last change is insufficient.
    for row, value in zip(reference, (20., 10., 10.01)):
        row['result']['raw_loss_db'] = value
    classify_refinements(rows)
    assert all(r['model']['reference_eligibility'] == 'unverified' for r in reference)
    assert all(r['model']['evidence_level'] != 'V1' for r in reference)
    for row, value in zip(reference, (10.02, 10.01, 10.0)):
        row['result']['raw_loss_db'] = value
    classify_refinements(rows)
    assert all(r['model']['reference_eligibility'] == 'eligible_within_tested_discretization' for r in reference)
    reference[-1]['result']['cap_triggered'] = True
    classify_refinements(rows)
    assert all(r['model']['reference_eligibility'] == 'unverified' for r in reference)


def test_incomplete_refinement_cannot_qualify_and_duplicate_is_rejected():
    rows = request()[0]
    classify_refinements(rows)
    assert rows[2]['model']['reference_eligibility'] == 'unverified'
    with pytest.raises(ValueError):
        classify_refinements(rows+deepcopy(rows))


def test_statistics_preserve_unavailable_denominators_and_sky_exclusion():
    rows = request()[0]+request(missing=True)[0]
    classify_refinements(rows)
    summary = summarize(rows)
    assert summary['row_count'] == 6
    assert summary['pair_count'] == 2
    assert sum(t['unknown'] for t in summary['thresholds']) == 3
    assert len(summary['failures']) == 3
    assert sum(g['converged_reference_difference']['count'] for g in summary['groups']) == 0
    assert all(r['rows'] == 2 for r in summary['roles'])
    assert sum(v['count'] for v in summary['visibility']) == 6


def test_refinement_rejects_changed_solver_source():
    rows = request(step=10)[0]+request(step=5)[0]+request(step=2.5)[0]
    rows[-1]['model']['source_fingerprint'] = 'different'
    with pytest.raises(ValueError, match='solver identity'):
        classify_refinements(rows)


def test_unverified_reference_cannot_be_promoted_by_label():
    rows = request()[0]
    rows[2]['model'].update(evidence_level='V1', reference_eligibility='eligible_within_tested_discretization')
    with pytest.raises(ValueError, match='refinement evidence'):
        summarize(rows)
