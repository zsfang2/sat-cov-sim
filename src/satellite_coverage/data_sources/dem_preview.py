"""Bounded, nodata-preserving DEM previews for a geographic display."""

from pathlib import Path
import math

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds as window_from_bounds


def dem_info(path):
    path = Path(path)
    with rasterio.Env(GDAL_CACHEMAX=32 * 1024 * 1024), rasterio.open(path) as source:
        if source.crs is None:
            raise ValueError("DEM 缺少 CRS，无法定位显示")
        if source.count < 1:
            raise ValueError("DEM 没有栅格波段")
        area = transform_bounds(source.crs, "EPSG:4326", *source.bounds, densify_pts=21)
        if not all(math.isfinite(x) for x in area):
            raise ValueError("DEM 地理范围无法转换")
        return {"name": path.name, "path": str(path), "size_bytes": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns, "crs": source.crs.to_string(),
                "shape": [source.height, source.width], "bounds_wgs84": list(area),
                "resolution_native": list(source.res), "dtype": source.dtypes[0],
                "block_shapes": [list(shape) for shape in source.block_shapes],
                "nodata": str(source.nodata), "unit": source.units[0] or "unknown",
                "scale": source.scales[0], "offset": source.offsets[0],
                "vertical_datum": "unverified", "physical_use_ready": False,
                "identity_note": "path/size/mtime only; this interactive viewer does not hash the full large file"}


def dem_preview(path, area, size=384):
    from ..orbit.visibility import bounds
    west, south, east, north = bounds(area)
    if type(size) is not int or not 64 <= size <= 640:
        raise ValueError("预览边长必须在 64 到 640 之间")
    info = dem_info(path)
    left, bottom, right, top = info["bounds_wgs84"]
    if east <= left or west >= right or north <= bottom or south >= top:
        raise ValueError("当前视图不与 DEM 相交；请定位到 DEM 范围")
    with rasterio.Env(GDAL_CACHEMAX=32 * 1024 * 1024), rasterio.open(path) as source:
        native_bounds = transform_bounds("EPSG:4326", source.crs, west, south, east, north, densify_pts=21)
        raw_window = window_from_bounds(*native_bounds, transform=source.transform)
        col, row = math.floor(raw_window.col_off), math.floor(raw_window.row_off)
        stop_col, stop_row = math.ceil(raw_window.col_off + raw_window.width), math.ceil(raw_window.row_off + raw_window.height)
        try:
            window = Window(col, row, stop_col-col, stop_row-row).intersection(Window(0, 0, source.width, source.height))
        except rasterio.errors.WindowError as exc:
            raise ValueError("当前视图不与 DEM 栅格相交") from exc
        # Decimate BEFORE reprojection. Warping the full native country-wide
        # raster can read tens of billions of pixels even for a tiny output.
        sample_width, sample_height = min(size * 2, int(window.width)), min(size * 2, int(window.height))
        sample = source.read(1, window=window, out_shape=(sample_height, sample_width), masked=True,
                             resampling=Resampling.nearest, out_dtype="float32")
        sample_transform = source.window_transform(window) * Affine.scale(window.width/sample_width, window.height/sample_height)
        array = np.full((size, size), np.nan, dtype=np.float32)
        reproject(source=sample.filled(np.nan), destination=array,
                  src_transform=sample_transform, src_crs=source.crs, src_nodata=np.nan,
                  dst_transform=from_bounds(west, south, east, north, size, size), dst_crs="EPSG:4326",
                  dst_nodata=np.nan, resampling=Resampling.nearest, num_threads=1, warp_mem_limit=32)
    array = array.astype(float) * info["scale"] + info["offset"]
    valid = np.isfinite(array)
    selected = array[valid]
    low, high = (float(np.min(selected)), float(np.max(selected))) if selected.size else (None, None)
    pixels = np.where(valid, array, 0).ravel().tolist()
    for index in np.flatnonzero(~valid.ravel()):
        pixels[int(index)] = None
    return {"info": info, "bounds": [west, south, east, north], "width": size, "height": size,
            "values": pixels, "min": low, "max": high, "valid_fraction": float(valid.mean()),
            "resampling": "nearest native decimation then nearest reprojection", "gdal_cache_limit_mib": 32,
            "intermediate_shape": [sample_height, sample_width],
            "scope": "resampled display pixels only; not native DEM statistics or terrain propagation"}
