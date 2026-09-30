import math

import numpy as np
import pytest

from satellite_coverage.geometry.cell_horizon import cell_horizon
from satellite_coverage.geometry.terrain import TerrainGrid, terrain_profile


def evaluate(values, **options):
    grid = TerrainGrid(values,-205,205,10,"synthetic","fixture")
    params = dict(receiver_east_m=0,receiver_north_m=0,antenna_agl_m=2,azimuth_deg=0,radius_m=150)
    params.update(options)
    return cell_horizon(grid,**params)


def test_exact_cell_edge_recovers_missed_uniform_peak():
    heights = np.zeros((41,41))
    heights[10,:] = 102
    result = evaluate(heights)
    # The near face of a cell centered at 100 m begins at 95 m.
    assert result["limiting_distance_m"] == pytest.approx(95)
    assert result["horizon_deg"] == pytest.approx(math.degrees(math.atan2(100,95)))
    assert result["coverage_complete"]


def test_flat_curvature_interior_maximum_and_translation():
    radius = 1e6
    result = evaluate(np.zeros((41,41)),antenna_agl_m=.001,effective_radius_m=radius)
    assert result["limiting_distance_m"] == pytest.approx(math.sqrt(2*radius*.001))
    moved = evaluate(np.full((41,41),500.),antenna_agl_m=.001,effective_radius_m=radius)
    assert moved["horizon_deg"] == pytest.approx(result["horizon_deg"],abs=1e-10)


@pytest.mark.parametrize("az",[0,45,90,180,270,359.99])
def test_flat_axes_and_corner_crossings(az):
    result = evaluate(np.zeros((41,41)),azimuth_deg=az)
    assert result["coverage_complete"]
    assert result["horizon_deg"] == pytest.approx(math.degrees(math.atan2(-2,150)))


def test_missing_cells_prevent_complete_horizon():
    heights = np.zeros((41,41))
    heights[10,20] = np.nan
    assert not evaluate(heights)["coverage_complete"]
    assert not evaluate(np.zeros((41,41)),radius_m=300)["coverage_complete"]
