import math

import numpy as np
import pytest

from satellite_coverage.geometry.cell_profile import cell_profile
from satellite_coverage.geometry.cell_horizon import cell_horizon
from satellite_coverage.geometry.terrain import TerrainGrid
from satellite_coverage.engine.terrain_link import evaluate_profile


def profile(values, **changes):
    grid = TerrainGrid(values, -205, 205, 10, "WGS84_ellipsoid", "test")
    options = dict(receiver_east_m=0, receiver_north_m=0, antenna_agl_m=2,
                   azimuth_deg=0, radius_m=150, step_m=10)
    options.update(changes)
    return cell_profile(grid, **options)


def test_ridge_retains_both_heights_at_near_face():
    values = np.zeros((41, 41))
    values[10, :] = 102
    result = profile(values)
    assert result["horizon_deg"] == pytest.approx(math.degrees(math.atan2(100, 95)))
    assert result["limiting_distance_m"] == pytest.approx(95)
    face = [s for s in result["samples"] if s["distance_m"] == 95]
    assert {s["elevation_m"] for s in face} == {0, 102}
    assert {s["boundary_side"] for s in face} == {"left_limit", "right_limit"}


@pytest.mark.parametrize("azimuth", [0, 45, 89.999, 90, 135, 180, 225, 270, 315, 359.99])
def test_random_grid_matches_separate_horizon_extrema(azimuth):
    values = np.random.default_rng(718).uniform(-20, 100, (41, 41))
    grid = TerrainGrid(values, -205, 205, 10, "WGS84_ellipsoid", "test")
    options = dict(receiver_east_m=1.7, receiver_north_m=-2.3, antenna_agl_m=2,
                   azimuth_deg=azimuth, radius_m=150, effective_radius_m=6371000)
    oracle = cell_horizon(grid, **options)
    for step in (60, 10, 1.5):
        result = cell_profile(grid, step_m=step, **options)
        assert result["coverage_complete"]
        assert result["horizon_deg"] == pytest.approx(oracle["horizon_deg"], abs=1e-10)


def test_flat_curvature_interior_extremum_and_height_translation():
    options = dict(antenna_agl_m=.001, effective_radius_m=1e6, step_m=60)
    result = profile(np.zeros((41, 41)), **options)
    assert result["limiting_distance_m"] == pytest.approx(math.sqrt(2000))
    translated = profile(np.full((41, 41), 500.), **options)
    assert translated["horizon_deg"] == pytest.approx(result["horizon_deg"], abs=1e-10)


def test_missing_interval_is_not_skipped_by_large_step():
    values = np.zeros((41, 41))
    values[10, :] = np.nan
    result = profile(values, step_m=60)
    assert not result["coverage_complete"]
    assert "nodata" in result["incomplete_reasons"]
    result = profile(np.zeros((41, 41)), radius_m=300)
    assert "outside_dem" in result["incomplete_reasons"]


def test_receiver_endpoint_is_not_a_knife_edge():
    result = evaluate_profile(profile(np.zeros((41, 41))), elevation_deg=5,
                              slant_range_m=550000, frequency_hz=14.5e9)
    assert result["loss_status"] == "known"
    assert result["raw_loss_db"] == 0


def test_missing_receiver_height_remains_unknown():
    values = np.zeros((41, 41))
    values[20, 20] = np.nan
    result = profile(values)
    assert result["horizon_deg"] is None
    assert "receiver_nodata" in result["incomplete_reasons"]


def test_angular_boundary_brackets_converge_to_analytic_cell_corners():
    # The isolated obstacle spans east [15,25], north [95,105]. Its
    # angular support is bounded by the far-west and near-east corners,
    # independently of the implementation's cell traversal algorithm.
    values = np.zeros((41, 41))
    values[10, 22] = 102
    left = math.degrees(math.atan2(15, 105))
    right = math.degrees(math.atan2(25, 95))
    previous = (math.inf, math.inf)
    for spacing in (4., 2., 1., .5, .25):
        blocked = []
        for azimuth in np.arange(0, 24+spacing/2, spacing):
            p = profile(values, azimuth_deg=float(azimuth))
            result = evaluate_profile(p, elevation_deg=1, slant_range_m=550000, frequency_hz=14.5e9)
            assert result["loss_status"] == "known"
            expected = left < azimuth < right
            assert (result["los_status"] == "blocked") == expected
            if expected:
                blocked.append(float(azimuth))
        errors = (min(blocked)-left, right-max(blocked))
        assert all(0 <= error <= spacing for error in errors)
        assert all(new <= old+1e-12 for new, old in zip(errors, previous))
        previous = errors
