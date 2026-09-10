from __future__ import annotations

import numpy as np
import pytest

from satellite_coverage.propagation import (
    directional_occlusion,
    knife_edge_loss_db,
)


@pytest.mark.xfail(
    strict=True,
    reason="CF-01: legacy terrain horizon omits the receiver's absolute elevation",
)
def test_flat_nonzero_elevation_should_not_create_terrain_loss():
    heights_m = np.full((5, 5), 500.0, dtype=np.float64)

    blocked, excess_height_m, obstacle_distance_m = directional_occlusion(
        heights_m,
        azimuth_deg=0.0,
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

