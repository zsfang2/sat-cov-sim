import math

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from satellite_coverage.experiments.native_terrain import native_heights, sampled_profile
from satellite_coverage.data_sources.terrain_tiles import TerrainResourceError


def test_native_point_sampling_preserves_cells_scale_mask_and_boundary(tmp_path):
    path = tmp_path/"native.tif"
    with rasterio.open(path, "w", driver="GTiff", width=3, height=3, count=1,
                       dtype="float64", crs="EPSG:3857", transform=from_origin(0, 30, 10, 10), nodata=-999) as out:
        out.write(np.array([[1,2,3],[4,-999,6],[7,8,9]], dtype=float), 1)
    meta = dict(local_crs="EPSG:3857", scale=2, offset=1, vertical_conversion={})
    with rasterio.open(path) as src:
        heights, statuses = native_heights(src, meta, [0,10,15,30], [30,30,15,15])
        assert heights[:2].tolist() == [3,5]
        assert statuses == ["known","known","nodata","outside_dem"]
        with pytest.raises(TerrainResourceError):
            native_heights(src, meta, [0,25], [30,5], max_window_cells=1)


def test_quadratic_and_spherical_drops_have_independent_expected_values():
    d, radius = 48000., 6371000.
    opts = dict(ground=0, agl=0, radius=d, step=d, azimuth=0, effective_radius=radius)
    quadratic = sampled_profile([d],[0],["known"], **opts)["samples"][0]
    sphere = sampled_profile([d],[0],["known"], **opts, spherical=True)["samples"][0]
    assert quadratic["relative_height_m"] == -d*d/(2*radius)
    assert sphere["relative_height_m"] == pytest.approx(-radius*(1-math.cos(d/radius)), abs=1e-9)
    assert sphere["distance_m"] == pytest.approx(radius*math.sin(d/radius))
    # Taylor remainder from the declared sphere, not a terrestrial truth bound.
    assert abs(quadratic["relative_height_m"]-sphere["relative_height_m"]) <= d**4/(24*radius**3)


def test_native_nodata_retained():
    p = sampled_profile([10,20], [0,np.nan], ["known","nodata"], ground=0, agl=2,
                        radius=20, step=10, azimuth=0, effective_radius=None)
    assert p["incomplete_reasons"] == ["nodata"]
    assert p["samples"][1]["relative_height_m"] is None
