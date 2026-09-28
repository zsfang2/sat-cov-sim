"""Analytic regressions for receiver-relative terrain visibility."""

from __future__ import annotations

import numpy as np
import pytest

from satellite_coverage.propagation import (
    directional_occlusion,
    knife_edge_loss_db,
)


@pytest.mark.parametrize("datum_m", [0.0, 500.0, -100.0])
@pytest.mark.parametrize("azimuth_deg", [0.0, 90.0, 180.0, 270.0])
def test_flat_nonzero_elevation_should_not_create_terrain_loss(datum_m, azimuth_deg):
    """CF-01 regression: every upward ray clears a constant-elevation plane."""
    heights_m = np.full((5, 5), datum_m, dtype=np.float64)

    blocked, excess_height_m, obstacle_distance_m = directional_occlusion(
        heights_m,
        azimuth_deg=azimuth_deg,
        elevation_deg=25.0,
        resolution_m=100.0,
    )
    loss_db = knife_edge_loss_db(
        excess_height_m,
        obstacle_distance_m,
        np.full_like(excess_height_m, 550_000.0),
        14.5e9,
    )

    assert not blocked.any()
    assert not loss_db.any()


def test_ridge_boundary_and_receiver_height_are_relative_to_ground():
    # North ridge is 102 m above the ground. At 100 m range and 2 m AGL,
    # the horizon is exactly arctan(100/100) = 45 degrees.
    terrain = np.array([[602.0], [500.0]])
    below = directional_occlusion(terrain, 0.0, 30.0, 100.0, receiver_height_agl_m=2.0)
    tangent = directional_occlusion(terrain, 0.0, 45.0, 100.0, receiver_height_agl_m=2.0)
    above = directional_occlusion(terrain, 0.0, 60.0, 100.0, receiver_height_agl_m=2.0)
    assert below[0][1, 0]
    assert below[1][1, 0] == pytest.approx(100.0 - 100.0 / np.sqrt(3), abs=1e-9)
    assert below[2][1, 0] == pytest.approx(100.0)
    assert not tangent[0].any() and not above[0].any()
    assert directional_occlusion(terrain, 0, 45, 100)[0][1, 0]
    assert not directional_occlusion(terrain, 0, 30, 100, receiver_height_agl_m=60)[0].any()


@pytest.mark.parametrize("azimuth", [0.0, 37.0, 90.0, 215.0])
def test_terrain_translation_preserves_blockage_excess_and_distance(azimuth):
    terrain = np.array([[0., 20., 0.], [0., 0., 0.], [0., 0., 10.]])
    original = directional_occlusion(terrain, azimuth, 25, 10, receiver_height_agl_m=2)
    shifted = directional_occlusion(terrain + 500, azimuth, 25, 10, receiver_height_agl_m=2)
    for a, b in zip(original, shifted):
        np.testing.assert_allclose(a, b, rtol=0, atol=1e-10)


def test_building_receivers_keep_explicit_ground_level_semantics():
    from satellite_coverage.propagation import urban_losses
    buildings = np.array([[50.], [0.], [0.], [0.]])
    loss, reflection, blocked = urban_losses(buildings, 0, 45, 10)
    np.testing.assert_array_equal(blocked[:, 0], [False, True, True, True])
    np.testing.assert_array_equal(loss[:, 0], [18, 18, 18, 18])
    np.testing.assert_array_equal(reflection[:, 0], [0, 3, 3, 3])


def test_unknown_terrain_is_not_silently_treated_as_clear():
    with pytest.raises(ValueError, match="nodata"):
        directional_occlusion(np.array([[np.nan]]), 0, 45, 10)
    with pytest.raises(ValueError):
        directional_occlusion(np.zeros((2, 2)), 0, 45, 0)
