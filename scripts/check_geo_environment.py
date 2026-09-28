"""Check EPSG lookup and actual reprojection against the active library stack."""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pyproj
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform


def check():
    geographic = rasterio.crs.CRS.from_epsg(4326)
    projected = rasterio.crs.CRS.from_epsg(3857)
    point = (108.9016839, 34.2427189)
    x, y = transform(geographic, projected, [point[0]], [point[1]])
    independent = pyproj.Transformer.from_crs(4326, 3857, always_xy=True).transform(*point)
    np.testing.assert_allclose([x[0], y[0]], independent, rtol=0, atol=1e-6)
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", width=8, height=8, count=1, dtype="float32",
                         crs="EPSG:4326", transform=from_origin(108, 35, .01, .01)) as source:
            source.write(np.full((8, 8), 500, dtype="float32"), 1)
            dst_transform, width, height = calculate_default_transform(
                source.crs, projected, source.width, source.height, *source.bounds)
            destination = np.full((height, width), np.nan, dtype="float32")
            reproject(source=rasterio.band(source, 1), destination=destination,
                      dst_transform=dst_transform, dst_crs=projected,
                      dst_nodata=np.nan, resampling=Resampling.nearest)
            valid = np.isfinite(destination)
            assert valid.any(), "reprojection produced no valid pixels"
            np.testing.assert_array_equal(destination[valid], 500)
    return {"status": "passed", "epsg_lookup": [4326, 3857],
            "reprojection_valid_pixels": int(valid.sum()),
            "coordinate_cross_library_difference_m": float(np.max(np.abs(np.array([x[0], y[0]]) - independent))),
            "executable": sys.executable, "isolated_venv": sys.prefix != sys.base_prefix,
            "rasterio": rasterio.__version__, "gdal": rasterio.__gdal_version__,
            "pyproj": pyproj.__version__, "proj": pyproj.proj_version_str,
            "pyproj_database": str(Path(pyproj.datadir.get_data_dir()) / "proj.db"),
            "rasterio_database": str(Path(rasterio.__file__).parent / "proj_data/proj.db"),
            "foreign_data_overrides": {key: os.environ.get(key) for key in ("PROJ_DATA", "PROJ_LIB", "GDAL_DATA")},
            "scope": "software CRS lookup/reprojection consistency; no terrain vertical-datum validation"}


if __name__ == "__main__":
    report = check()
    if len(sys.argv) == 2:
        output = Path(sys.argv[1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
