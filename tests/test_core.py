from satellite_coverage.coordinates import LocalGrid
from satellite_coverage.propagation import directional_occlusion, fspl_db, knife_edge_loss_db

import numpy as np


def test_grid_is_north_up_and_centered():
    grid = LocalGrid(34.0, 108.0, size=4, extent_m=400.0)
    lat, lon = grid.latlon_mesh()
    assert lat[0, 0] > lat[-1, 0]
    assert lon[0, 0] < lon[0, -1]


def test_fspl_increases_with_distance():
    assert fspl_db(2_000.0, 2e9) > fspl_db(1_000.0, 2e9)


def test_directional_obstacle_casts_shadow():
    heights = np.zeros((5, 5), dtype=float)
    heights[1, 2] = 50.0
    blocked, excess, distance = directional_occlusion(heights, azimuth_deg=0.0, elevation_deg=20.0, resolution_m=10.0)
    assert blocked[2:, 2].any()
    assert np.any(excess > 0)
    assert np.all(knife_edge_loss_db(excess, distance, np.full_like(excess, 550_000.0), 2e9) >= 0)
