from copy import deepcopy

import pytest

from satellite_coverage.experiments.terrain_sensitivity import compare_profiles


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
