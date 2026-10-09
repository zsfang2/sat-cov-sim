# Frozen test oracle from b234bcb; only imports adapted. Never use in production.
"""Bounded GeoTIFF -> local azimuthal-equidistant metre grid for M3.

An explicit file-bound height declaration is mandatory. Display metadata alone
does not authorize interpreting raster values as physical terrain elevations.
"""

import math
import json
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.windows import Window

from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.config.pilot import exact_keys, identity, number, text_field
from satellite_coverage.geometry.terrain import TerrainGrid


def load_terrain_dem(path, declaration, *, lon_deg, lat_deg, radius_m, resolution_m, geoid=None):
    exact_keys(declaration, {"sha256", "height_unit", "vertical_datum", "surface_type", "evidence"}, "DEM declaration")
    text_field(declaration["evidence"], "DEM evidence")
    if declaration["height_unit"] != "m" or declaration["vertical_datum"] not in ("WGS84_ellipsoid", "EGM2008"):
        raise ValueError("M3 accepts declared metre WGS84 ellipsoid or EGM2008 heights only")
    if declaration["surface_type"] not in ("DSM", "DTM", "synthetic"):
        raise ValueError("declare DSM, DTM or synthetic surface_type")
    vertical = None
    vertical_metadata = {"method": "identity; source already ellipsoidal"}
    if declaration["vertical_datum"] == "EGM2008":
        if geoid is None:
            raise ValueError("EGM2008 conversion requires an explicit local geoid grid and checksum")
        exact_keys(geoid, {"path", "sha256", "model", "evidence"}, "geoid")
        text_field(geoid["evidence"], "geoid evidence")
        if geoid["model"] != "EGM2008":
            raise ValueError("geoid model must match EGM2008")
        grid_path = Path(geoid["path"]).resolve()
        if checksum_sha256(grid_path) != geoid["sha256"]:
            raise ValueError("geoid checksum mismatch")
        with rasterio.open(grid_path) as correction:
            tags = correction.tags()
            if (correction.count != 1 or correction.descriptions[0] != "geoid_undulation"
                    or tags.get("target_crs_epsg_code") != "3855"
                    or tags.get("TYPE") != "VERTICAL_OFFSET_GEOGRAPHIC_TO_VERTICAL"):
                raise ValueError("geoid GeoTIFF must declare EGM2008 target EPSG:3855 undulations")
        pipeline = ("+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad "
                    f"+step +proj=vgridshift +grids={json.dumps(str(grid_path))} +multiplier=1 "
                    "+step +proj=unitconvert +xy_in=rad +xy_out=deg")
        vertical = Transformer.from_pipeline(pipeline)
        vertical_metadata = {"method": "h=H+N; PROJ local grid, multiplier=+1, no optional grid or ballpark",
                             "grid": dict(geoid), "pipeline": pipeline, "grid_tags": tags}
    elif geoid is not None:
        raise ValueError("geoid supplied for already ellipsoidal DEM; would double-convert heights")
    for name, value in (("lon_deg", lon_deg), ("lat_deg", lat_deg), ("radius_m", radius_m), ("resolution_m", resolution_m)):
        number(value, name)
    if not -180 <= lon_deg <= 180 or not -89.9 <= lat_deg <= 89.9:
        raise ValueError("invalid terrain origin")
    if not 0 < resolution_m <= radius_m <= 100000:
        raise ValueError("require 0 < resolution <= radius <= 100 km")
    n = math.ceil(radius_m/resolution_m)
    size = 2*n+3  # center pixel at receiver; one-pixel boundary padding
    if size*size > 1_000_000:
        raise ValueError("local terrain grid exceeds one million cells")
    path = Path(path)
    digest = checksum_sha256(path)
    if declaration["sha256"] != digest:
        raise ValueError("DEM checksum does not match height declaration")
    local = CRS.from_proj4(f"+proj=aeqd +lat_0={lat_deg} +lon_0={lon_deg} +datum=WGS84 +units=m")
    half = size*resolution_m/2
    x, y = np.meshgrid((np.arange(size)+.5)*resolution_m-half,
                       half-(np.arange(size)+.5)*resolution_m)
    with rasterio.Env(GDAL_CACHEMAX=32*1024*1024), rasterio.open(path) as src:
        if src.crs is None or src.count != 1:
            raise ValueError("DEM requires CRS and exactly one height band")
        if src.units[0] not in (None, "m", "metre", "meter"):
            raise ValueError("DEM embedded height unit conflicts with declaration")
        if max(a*b for a, b in src.block_shapes) > 4_000_000:
            raise ValueError("DEM native block too large; prepare a tiled source")
        forward = Transformer.from_crs(local, src.crs, always_xy=True)
        reverse = Transformer.from_crs(src.crs, local, always_xy=True)
        sx, sy = forward.transform(x, y, errcheck=True)
        cols, rows = (~src.transform)*(sx, sy)
        if not np.isfinite(cols).all() or not np.isfinite(rows).all():
            raise ValueError("nonfinite DEM coordinates")
        cols, rows = np.floor(cols).astype(np.int64), np.floor(rows).astype(np.int64)
        valid = (cols >= 0) & (cols < src.width) & (rows >= 0) & (rows < src.height)
        if not valid.any():
            raise ValueError("requested terrain does not intersect DEM")
        c0, c1 = int(cols[valid].min()), int(cols[valid].max())+1
        r0, r1 = int(rows[valid].min()), int(rows[valid].max())+1
        if (c1-c0)*(r1-r0) > 4_000_000:
            raise ValueError("native terrain window exceeds four million cells; reduce radius")
        # Estimate source spacing at center and corners; no higher-resolution
        # truth claim is made by interpolating or oversampling native data.
        spacings = []
        for col, row in ((c0,r0), (c1,r0), (c0,r1), (c1,r1), ((c0+c1)/2,(r0+r1)/2)):
            p = [reverse.transform(*(src.transform*q), errcheck=True)
                 for q in ((col,row),(col+1,row),(col,row+1))]
            spacings.extend(math.dist(p[0], q) for q in p[1:])
        native_spacing = max(spacings)
        if resolution_m < native_spacing*(1-1e-6):
            raise ValueError("requested terrain resolution is finer than source spacing")
        values = src.read(1, window=Window(c0,r0,c1-c0,r1-r0), masked=True, out_dtype="float64").filled(np.nan)
        scale, offset = src.scales[0], src.offsets[0]
        if not math.isfinite(scale) or scale <= 0 or not math.isfinite(offset):
            raise ValueError("invalid DEM scale/offset")
        target = np.full((size,size), np.nan)
        target[valid] = values[rows[valid]-r0, cols[valid]-c0]*scale+offset
        if vertical is not None:
            finite = np.isfinite(target)
            # Shift the actual sampled source pixel's center, not a fictitious
            # higher-resolution location in the resampled output raster.
            cx, cy = src.transform*(cols[finite]+.5, rows[finite]+.5)
            lon, lat = Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True).transform(cx,cy,errcheck=True)
            _, _, shifted = vertical.transform(lon,lat,target[finite],errcheck=True)
            target[finite] = shifted
        if np.isinf(target).any():
            raise ValueError("DEM conversion overflow")
        metadata = {"file_sha256": digest, "declaration": dict(declaration), "path": str(path.resolve()),
                    "source_crs": src.crs.to_wkt(), "local_crs": local.to_wkt(),
                    "lon_deg": lon_deg, "lat_deg": lat_deg, "radius_m": radius_m,
                    "resolution_m": resolution_m, "estimated_native_spacing_max_m": native_spacing,
                    "native_window": [c0,r0,c1-c0,r1-r0], "shape": [size,size],
                    "scale": scale, "offset": offset, "resampling": "nearest native cell; no display decimation",
                    "vertical_conversion": vertical_metadata,
                    "scope": "local AEQD distances; ellipsoid heights after declared conversion; DSM is not bare earth"}
    source_id = identity(metadata)
    return TerrainGrid(target, -half, half, resolution_m, "WGS84_ellipsoid", source_id,
                       surface_type=declaration["surface_type"]), metadata
