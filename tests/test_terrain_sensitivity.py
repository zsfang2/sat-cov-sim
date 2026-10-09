from copy import deepcopy

import pytest

from satellite_coverage.experiments.terrain_sensitivity import compare_profiles, assess_radius_stability
from satellite_coverage.experiments.terrain_sensitivity import assess_query_radius_stability


def rows():
    return [{"height_above_surface_m":2,"azimuth_deg":0,"coverage_complete":True,"horizon_deg":3,
             "queries":{"5":{"loss_status":"known","raw_loss_db":0,"los_status":"clear_within_radius"}}}]


def test_stability_requires_height_loss_and_classification_agreement():
    base = rows()
    assert compare_profiles(base,base)["stable_under_diagnostic_thresholds"]
    changed = deepcopy(base)
    changed[0]["horizon_deg"] += .2
    assert not compare_profiles(changed,base)["stable_under_diagnostic_thresholds"]
    changed = deepcopy(base)
    changed[0]["queries"]["5"]["raw_loss_db"] = 2
    assert not compare_profiles(changed,base)["stable_under_diagnostic_thresholds"]
    changed[0]["queries"]["5"]["raw_loss_db"] = 0
    changed[0]["queries"]["5"]["los_status"] = "blocked"
    assert compare_profiles(changed,base)["los_classification_changes"] == 1


def test_missing_coverage_or_loss_never_counts_as_stable():
    a, b = rows(), rows()
    a[0]["coverage_complete"] = False
    result = compare_profiles(a,b)
    assert not result["stable_under_diagnostic_thresholds"] and result["horizon_error_deg"]["max"] is None
    a = rows()
    a[0]["queries"]["5"].update(loss_status="not_computed",raw_loss_db=None)
    assert not compare_profiles(a,b)["stable_under_diagnostic_thresholds"]


def test_comparison_rejects_unpaired_experiments():
    with pytest.raises(ValueError): compare_profiles(rows(),[])
    with pytest.raises(ValueError): compare_profiles(rows()*2,rows())
    different = rows()
    different[0]["azimuth_deg"] = 5
    with pytest.raises(ValueError): compare_profiles(rows(),different)


def radius_rows(horizons=(3,3,3,3)):
    result = []
    for radius, horizon in zip((3000,6000,12000,24000),horizons):
        row = rows()[0]
        row.update(radius_m=radius,horizon_deg=horizon)
        result.append(row)
    return result


def test_radius_stability_requires_multiple_extensions_and_is_not_global():
    result = assess_radius_stability(radius_rows())
    assert result["smallest_stable_tested_radius_m"] == 3000
    assert result["global_radius_sufficiency"] == "not_verified"
    assert [r["status"] for r in result["entries"]] == [
        "stable_within_tested_extent", "stable_within_tested_extent",
        "insufficient_larger_radius_evidence", "insufficient_larger_radius_evidence"]


def test_later_ridge_cannot_be_hidden_by_early_plateau():
    result = assess_radius_stability(radius_rows((3,3,3,8)))
    assert result["smallest_stable_tested_radius_m"] is None
    assert all(e["status"] == "changed_with_expansion" for e in result["entries"][:-1])


def test_cumulative_drift_checks_all_larger_radii():
    result = assess_radius_stability(radius_rows((3,3.06,3.12,3.18)))
    assert result["entries"][0]["status"] == "changed_with_expansion"
    assert result["entries"][1]["status"] == "changed_with_expansion"


def test_missing_outer_coverage_blocks_radius_stability():
    data = radius_rows()
    data[-1]["coverage_complete"] = False
    result = assess_radius_stability(data)
    assert all(e["status"] == "unknown_missing_or_unsupported_queries" for e in result["entries"])


@pytest.mark.parametrize("value", [-1,float("nan"),float("inf")])
def test_invalid_diagnostic_tolerance_rejected(value):
    with pytest.raises(ValueError):
        assess_radius_stability(radius_rows(),horizon_tolerance_deg=value)


def test_radius_audit_rejects_mixed_steps_duplicate_directions_and_single_radius():
    with pytest.raises(ValueError): assess_radius_stability(radius_rows()[:1])
    with pytest.raises(ValueError): assess_radius_stability(radius_rows()*2)
    with pytest.raises(ValueError): assess_radius_stability(radius_rows(),minimum_extensions=0)


def test_per_query_audit_retains_failed_elevations_without_hiding_neighbours():
    data = radius_rows()
    for row in data:
        row['queries']['10'] = dict(row['queries']['5'])
    data[-1]['queries']['10'].update(loss_status='not_computed', raw_loss_db=None)
    result = assess_query_radius_stability(data)
    assert len(result) == 2
    assert result[0]['entries'][0]['status'] == 'stable_within_tested_extent'
    assert result[1]['entries'][0]['status'] == 'unknown_missing_or_unsupported_queries'
    assert result[1]['samples'][-1]['raw_loss_db'] is None
    assert all(r['global_radius_sufficiency'] == 'not_verified' for r in result)


def test_per_query_audit_keeps_loss_change_even_with_fixed_horizon():
    data = radius_rows()
    data[-1]['queries']['5']['raw_loss_db'] = 12
    result = assess_query_radius_stability(data)[0]
    assert result['entries'][0]['status'] == 'changed_with_expansion'
    assert result['entries'][0]['comparisons'][-1]['raw_loss_error_db']['max'] == 12
    assert result['entries'][-1]['status'] == 'insufficient_larger_radius_evidence'


def test_per_query_missing_elevation_rejected_even_with_incomplete_profile():
    data = radius_rows()
    data[-1]['coverage_complete'] = False
    data[-1]['queries'] = {}
    with pytest.raises(ValueError, match='elevations'):
        assess_query_radius_stability(data)
