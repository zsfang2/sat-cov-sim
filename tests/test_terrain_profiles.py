import math

import numpy as np
import pytest

from satellite_coverage.geometry.terrain import TerrainGrid, terrain_profile, horizon_profile
from satellite_coverage.engine.terrain_link import evaluate_profile


def grid(values=None, datum=0):
    return TerrainGrid(np.full((41, 41), float(datum)) if values is None else values,
                       -205, 205, 10, "synthetic local height datum", "analytic-grid")


def profile(dem=None, **kwargs):
    options = dict(receiver_east_m=0, receiver_north_m=0, antenna_agl_m=2,
                   azimuth_deg=0, radius_m=150, step_m=10)
    options.update(kwargs)
    return terrain_profile(dem or grid(), **options)


def evaluate(p, **kwargs):
    options = dict(elevation_deg=30, slant_range_m=550000, frequency_hz=14.5e9)
    options.update(kwargs)
    return evaluate_profile(p, **options)


@pytest.mark.parametrize("azimuth", [0, 90, 180, 270])
def test_flat_horizon_and_los(azimuth):
    p = profile(azimuth_deg=azimuth)
    assert p["coverage_complete"]
    assert p["horizon_deg"] == pytest.approx(math.degrees(math.atan2(-2, 150)))
    assert p["limiting_distance_m"] == 150
    result = evaluate(p)
    assert result["los_status"] == "clear_within_radius"
    assert result["raw_loss_db"] == 0 and result["truncated_before_satellite"]


def test_ridge_height_datum_and_antenna_change():
    heights = np.zeros((41, 41))
    heights[10, :] = 102  # north 100 m, relative height 100 m
    p = profile(grid(heights))
    assert p["horizon_deg"] == pytest.approx(45)
    assert p["limiting_distance_m"] == 100
    assert evaluate(p, elevation_deg=40)["los_status"] == "blocked"
    tangent = evaluate(p, elevation_deg=45)
    assert tangent["los_status"] == "clear_within_radius"
    assert tangent["raw_loss_db"] == pytest.approx(6.9+20*math.log10(math.sqrt(1.01)-.1), abs=1e-9)
    assert profile(grid(heights), antenna_agl_m=52)["horizon_deg"] == pytest.approx(math.degrees(math.atan(.5)))
    moved = profile(grid(heights+500))
    assert moved["horizon_deg"] == p["horizon_deg"]
    assert evaluate(moved)["raw_loss_db"] == evaluate(p)["raw_loss_db"]


def test_curvature_once_and_effective_radius():
    flat = profile(antenna_agl_m=0)
    curved = profile(antenna_agl_m=0, effective_radius_m=6371000)
    effective = profile(antenna_agl_m=0, effective_radius_m=4/3*6371000)
    assert curved["horizon_deg"] < effective["horizon_deg"] < flat["horizon_deg"] == 0
    sample = curved["samples"][-1]
    assert sample["curvature_drop_m"] == pytest.approx(150**2/(2*6371000))
    with pytest.raises(ValueError, match="pre-applied"):
        profile(TerrainGrid(np.zeros((3, 3)), -15, 15, 10, "test", "fixture", True))


@pytest.mark.parametrize("gap", ["nodata", "outside", "coarse"])
def test_incomplete_profiles_cannot_claim_clear_or_zero_loss(gap):
    heights = np.zeros((41, 41))
    options = {}
    if gap == "nodata":
        heights[10, 20] = np.nan
    elif gap == "outside":
        options["radius_m"] = 300
    else:
        options["step_m"] = 20
    result = evaluate(profile(grid(heights), **options))
    assert result["los_status"] == "unknown"
    assert result["used_loss_db"] is None and not result["coverage_complete"]


def test_known_obstacle_still_blocks_when_other_samples_missing():
    heights = np.zeros((41, 41))
    heights[10, 20] = 102
    heights[15, 20] = np.nan
    result = evaluate(profile(grid(heights)))
    assert result["los_status"] == "blocked"
    assert result["loss_status"] == "not_computed"


def test_receiver_nodata_no_false_result():
    heights = np.zeros((41, 41))
    heights[20, 20] = np.nan
    p = profile(grid(heights))
    assert p["horizon_deg"] is None and "receiver_nodata" in p["incomplete_reasons"]
    assert evaluate(p)["los_status"] == "unknown"


def test_cap_retains_raw_loss_and_signed_fresnel_clearance():
    heights = np.zeros((41, 41))
    heights[10, 20] = 102
    result = evaluate(profile(grid(heights)), loss_cap_db=3)
    assert result["raw_loss_db"] > result["used_loss_db"] == 3
    assert result["cap_triggered"]
    assert result["dominant_edge"]["clearance_m"] < 0
    assert result["dominant_edge"]["first_fresnel_radius_m"] > 0


def test_sampling_convergence_and_native_resolution_retained():
    heights = np.zeros((41, 41))
    heights[8:13, :] = 10
    errors = []
    # North edge of the near cell is reached at 75 m in this nearest-cell model.
    reference = math.degrees(math.atan2(8, 75))
    for step in (10, 5, 2.5):
        p = profile(grid(heights), step_m=step)
        errors.append(abs(p["horizon_deg"]-reference))
        assert p["native_resolution_m"] == 10
    assert errors[-1] <= errors[1] <= errors[0]


def test_scope_limit_and_immutable_grid():
    dem = grid()
    with pytest.raises(ValueError):
        dem.elevations_m.setflags(write=True)
    result = evaluate(profile(), slant_range_m=100)
    assert not result["coverage_complete"] and result["loss_status"] == "not_computed"
    outlines = horizon_profile(dem, [0, 90, 180, 270], receiver_east_m=0, receiver_north_m=0,
                              antenna_agl_m=2, radius_m=150, step_m=10)
    assert len(outlines) == 4


@pytest.mark.parametrize("options", [{"step_m": 0}, {"radius_m": -1}, {"antenna_agl_m": -1},
                                     {"azimuth_deg": 360}, {"effective_radius_m": 0}])
def test_invalid_profile_options(options):
    with pytest.raises(ValueError):
        profile(**options)
