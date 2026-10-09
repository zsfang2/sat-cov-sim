import math

import numpy as np
import pytest

from satellite_coverage.engine.terrain_link import evaluate_profile


def interval(left, right, delta, radius=None):
    def sample(x):
        return {"distance_m": x, "relative_height_m": delta-(0 if radius is None else x*x/(2*radius))}
    return {"sampling_method": "cell_intervals", "effective_radius_m": radius,
            "receiver_ground_m": 0, "antenna_agl_m": 0, "radius_m": right,
            "incomplete_reasons": [], "samples": [sample(left), sample(right)],
            "intervals": [{"start_m": left, "end_m": right, "elevation_m": delta}]}


def dense_reference(left, right, delta, radius, elevation, length, frequency):
    # Independent vectorized evaluation, no production polynomial/root helper.
    x = np.linspace(left, right, 200001)
    y = delta-(0 if radius is None else x*x/(2*radius))
    theta = np.deg2rad(elevation)
    d = x*np.cos(theta)+y*np.sin(theta)
    h = y*np.cos(theta)-x*np.sin(theta)
    keep = (d > 0) & (d < length)
    v = h[keep]*np.sqrt(2*length/((299792458/frequency)*d[keep]*(length-d[keep])))
    raw = np.where(v <= -.78, 0, np.maximum(0, 6.9+20*np.log10(np.sqrt((v-.1)**2+1)+v-.1)))
    return float(raw.max())


def test_interior_loss_maximum_is_not_horizon_extremum():
    # Low-angle clear ray: v is closest to zero inside the cell even though
    # neither boundary gives the dominant loss. Endpoints alone give zero.
    profile = interval(1, 1000, -.01)
    result = evaluate_profile(profile, elevation_deg=.01, slant_range_m=550000, frequency_hz=1e9)
    reference = dense_reference(1, 1000, -.01, None, .01, 550000, 1e9)
    assert result["dominant_edge"]["candidate_kind"] == "stationary_fresnel_v"
    assert result["raw_loss_db"] == pytest.approx(reference, abs=1e-7)
    assert result["raw_loss_db"] > 0


@pytest.mark.parametrize("radius", [None, 1e6, 6371000])
@pytest.mark.parametrize("delta,elevation", [(-.01,.01), (-2,0), (10,5), (100,30)])
def test_stationary_candidates_against_dense_direct_evaluation(radius, delta, elevation):
    result = evaluate_profile(interval(10, 1000, delta, radius), elevation_deg=elevation,
                              slant_range_m=550000, frequency_hz=1e9)
    expected = dense_reference(10, 1000, delta, radius, elevation, 550000, 1e9)
    assert result["loss_status"] == "known"
    assert result["raw_loss_db"] == pytest.approx(expected, abs=2e-6)


def test_below_ray_projection_behind_receiver_is_not_a_data_gap():
    result = evaluate_profile(interval(1, 100, -10), elevation_deg=30,
                              slant_range_m=550000, frequency_hz=14.5e9)
    assert result["excluded_behind_receiver_points"] == 1
    assert result["loss_status"] == "known"
    assert result["los_status"] == "clear_within_radius"
    assert result["raw_loss_db"] == 0


def test_projection_beyond_transmitter_remains_unsupported():
    result = evaluate_profile(interval(1, 100, 1e6), elevation_deg=30,
                              slant_range_m=1000, frequency_hz=14.5e9)
    assert result["loss_status"] == "not_computed"
    assert "obstacle_projection_outside_link" in result["incomplete_reasons"]
