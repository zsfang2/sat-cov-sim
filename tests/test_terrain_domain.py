"""Analytical domain counterexamples; no physical ground-truth claims."""

import json
import math

import numpy as np
import pytest

from satellite_coverage.geometry.terrain import TerrainGrid, terrain_profile
from satellite_coverage.geometry.cell_profile import cell_profile
from satellite_coverage.engine.terrain_context import TerrainContext
from satellite_coverage.engine.terrain_link import evaluate_profile


def grid(values=None):
    return TerrainGrid(np.zeros((41, 41)) if values is None else values,
                       -205, 205, 10, "WGS84_ellipsoid", "domain-flat", surface_type="synthetic")


def profile(dem=None, **options):
    args = dict(receiver_east_m=0, receiver_north_m=0, antenna_agl_m=2,
                azimuth_deg=0, radius_m=150, step_m=10)
    args.update(options)
    return cell_profile(dem or grid(), **args)


@pytest.mark.parametrize("elevation", [0, 1e-12, 30, 89, 89.9])
def test_flat_supported_elevations_are_finite(elevation):
    result = evaluate_profile(profile(), elevation_deg=elevation,
                              slant_range_m=550000, frequency_hz=14.5e9)
    assert result["loss_status"] == "known"
    assert result["los_status"] == "clear_within_radius"
    json.dumps(result, allow_nan=False)
    if elevation == 89.9:
        assert result["excluded_behind_receiver_points"] > 0
        assert result["dominant_edge"] is None
        assert result["raw_loss_db"] == 0


@pytest.mark.parametrize("range_m,elevation", [(100, 30), (150, 0), (550000, 89.999)])
def test_transmitter_within_horizontal_profile_is_explicitly_unsupported(range_m, elevation):
    result = evaluate_profile(profile(), elevation_deg=elevation,
                              slant_range_m=range_m, frequency_hz=14.5e9)
    assert result["loss_status"] == "not_computed"
    assert "satellite_within_profile_radius; shorten_profile" in result["incomplete_reasons"]
    json.dumps(result, allow_nan=False)


def test_zenith_has_explicit_domain_reason():
    context = TerrainContext(grid(), 0, 0, 150, 10, sampling_method="cell_intervals")
    result = context.evaluate(dict(geometrically_above_local_horizontal=True, azimuth_deg=None),
                              dict(antenna_ellipsoid_height_m=2))
    assert result["reason"] == "zenith_profile_not_supported"
    assert result["loss_status"] == "not_computed"


@pytest.mark.parametrize("frequency", [1e-320, 1e-300])
def test_finite_but_unrepresentable_fresnel_values_rejected(frequency):
    with pytest.raises(ValueError, match="finite numerical range"):
        evaluate_profile(profile(), elevation_deg=0, slant_range_m=550000, frequency_hz=frequency)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_query_and_sample_rejected(value):
    with pytest.raises(ValueError):
        evaluate_profile(profile(), elevation_deg=value, slant_range_m=550000, frequency_hz=14.5e9)
    with pytest.raises(ValueError):
        grid().sample(value, 0)


def test_finite_height_overflow_is_not_missing_terrain():
    values = np.full((41, 41), -1e308)
    values[10, :] = 1e308
    with pytest.raises(ValueError, match="finite numerical range"):
        profile(grid(values))


def test_empty_forward_domain_has_reason():
    p = profile()
    p["samples"] = [{"distance_m": 0, "relative_height_m": 0}]
    p["intervals"] = []
    result = evaluate_profile(p, elevation_deg=0, slant_range_m=550000, frequency_hz=14.5e9)
    assert result["loss_status"] == "not_computed"
    assert result["incomplete_reasons"] == ["no_forward_knife_edge_candidates"]


def test_projection_vertex_is_retained_between_behind_endpoints():
    # d=x*cos(el)-x²*sin(el)/(2R)-AGL*sin(el) has a positive
    # interior maximum while both interval endpoints project behind receiver.
    radius, elevation, agl = 1e6, 89.9, .1
    end = 5000.
    p = dict(sampling_method="cell_intervals", effective_radius_m=radius,
             receiver_ground_m=0, antenna_agl_m=agl, radius_m=end,
             incomplete_reasons=[], samples=[dict(distance_m=x, relative_height_m=-agl-x*x/(2*radius))
                                             for x in (0, end)],
             intervals=[dict(start_m=0, end_m=end, elevation_m=0)])
    result = evaluate_profile(p, elevation_deg=elevation, slant_range_m=1e8, frequency_hz=1.)
    assert result["loss_status"] == "known"
    assert any(s["candidate_kind"] == "projection_vertex" for s in result["samples"])
    assert result["raw_loss_db"] > 0


def test_cell_boundary_half_open_and_gaps():
    dem = grid()
    assert dem.sample(-205, 205) == (0., "known")
    assert dem.sample(205, 0) == (None, "outside_dem")
    assert dem.sample(0, -205) == (None, "outside_dem")
    values = np.zeros((41, 41)); values[10, 20] = np.nan
    result = evaluate_profile(profile(grid(values)), elevation_deg=30,
                              slant_range_m=550000, frequency_hz=14.5e9)
    assert "nodata" in result["incomplete_reasons"] and result["raw_loss_db"] is None
    json.dumps(result, allow_nan=False)
