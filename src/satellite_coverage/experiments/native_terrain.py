"""Direct native-cell point sampling for local-grid diagnostics.

This deliberately does not build a local raster or infer continuous native
cell boundaries along a projected ray. It is a sampled numerical comparison,
not a finer-resolution terrain truth or an independent propagation model.
Callers provide the already validated loader metadata (including datum chain).
"""

import math

import numpy as np
from pyproj import Transformer
from rasterio.windows import Window

from ..data_sources.terrain_tiles import TerrainResourceError, transform_points


def native_heights(src, metadata, east, north, *, max_window_cells=262144):
    east, north = np.asarray(east, dtype=float), np.asarray(north, dtype=float)
    if east.shape != north.shape or east.ndim != 1 or not np.isfinite([east, north]).all():
        raise ValueError("native diagnostic requires finite paired coordinate vectors")
    if type(max_window_cells) is not int or not 1 <= max_window_cells <= 262144:
        raise ValueError("invalid native diagnostic window budget")
    forward = Transformer.from_crs(metadata["local_crs"], src.crs, always_xy=True)
    x, y = transform_points(forward, east, north)
    cols, rows = (~src.transform)*(x, y)
    valid = np.isfinite(cols) & np.isfinite(rows) & (cols >= 0) & (cols < src.width) & (rows >= 0) & (rows < src.height)
    cols = np.floor(np.where(valid, cols, 0)).astype(np.int64)
    rows = np.floor(np.where(valid, rows, 0)).astype(np.int64)
    heights = np.full(east.shape, np.nan)
    statuses = np.full(east.shape, "outside_dem", dtype=object)
    if valid.any():
        c0, c1 = int(cols[valid].min()), int(cols[valid].max())+1
        r0, r1 = int(rows[valid].min()), int(rows[valid].max())+1
        if (c1-c0)*(r1-r0) > max_window_cells:
            raise TerrainResourceError("native diagnostic ray window exceeds budget")
        data = src.read(1, window=Window(c0, r0, c1-c0, r1-r0), masked=True,
                        out_dtype="float64").filled(np.nan)
        heights[valid] = data[rows[valid]-r0, cols[valid]-c0]*metadata["scale"]+metadata["offset"]
        statuses[valid] = np.where(np.isfinite(heights[valid]), "known", "nodata")
        pipeline = metadata["vertical_conversion"].get("pipeline")
        keep = np.isfinite(heights)
        if pipeline and keep.any():
            cx, cy = src.transform*(cols[keep]+.5, rows[keep]+.5)
            lonlat = Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True)
            lon, lat = transform_points(lonlat, cx, cy)
            _, _, shifted = transform_points(Transformer.from_pipeline(pipeline), lon, lat, heights[keep])
            heights[keep] = shifted
        if not np.isfinite(heights[keep]).all():
            raise ValueError("native diagnostic height conversion nonfinite")
    return heights, statuses.tolist()


def sampled_profile(distances, heights, statuses, *, ground, agl, radius, step,
                    azimuth, effective_radius, spherical=False):
    """Independent sampled construction; spherical uses arc d -> R sin(d/R).

    For the sphere comparison, terrain is R+(height-ground) from the center.
    Tangent x=(R+height-ground)*sin(d/R); vertical subtracts the antenna AGL.
    It compares declared geometric models.
    """
    samples, reasons = [], set(s for s in statuses if s != "known")
    if ground is None:
        reasons.add("receiver_missing")
    for d, height, status in zip(distances, heights, statuses):
        relative = None if status != "known" or ground is None else float(height)-ground-agl
        x = float(d)
        if relative is not None and effective_radius is not None:
            if spherical:
                angle = d/effective_radius
                surface_delta = float(height)-ground
                x = (effective_radius+surface_delta)*math.sin(angle)
                relative = surface_delta*math.cos(angle)-2*effective_radius*math.sin(angle/2)**2-agl
            else:
                relative -= d*d/(2*effective_radius)
        samples.append(dict(distance_m=x, relative_height_m=relative))
    angles = [math.degrees(math.atan2(s["relative_height_m"], s["distance_m"]))
              for s in samples if s["relative_height_m"] is not None]
    return dict(samples=samples, incomplete_reasons=sorted(reasons), radius_m=radius,
                step_m=step, azimuth_deg=azimuth, horizon_deg=max(angles) if angles else None,
                coverage_complete=not reasons)
