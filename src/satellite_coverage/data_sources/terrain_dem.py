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
from time import perf_counter
from dataclasses import asdict

from .terrain_tiles import TerrainReadBudget, TerrainResourceError, plan_bounds, read_tiles

from .manifest import checksum_sha256
from ..config.pilot import exact_keys, identity, number, text_field
from ..geometry.terrain import TerrainGrid


def load_terrain_dem(path, declaration, *, lon_deg, lat_deg, radius_m, resolution_m, geoid=None,
                     read_budget=None, diagnostics=None, window_observer=None):
    budget = TerrainReadBudget() if read_budget is None else read_budget
    if not isinstance(budget, TerrainReadBudget):
        raise ValueError("read_budget must be TerrainReadBudget")
    stats = dict(read_windows=0, read_cells=0, max_read_cells=0, subdivisions=0,
                 execution_transform_seconds=0.0, read_seconds=0.0, vertical_seconds=0.0)
    started = perf_counter()
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
    budget.check_memory(size)
    path = Path(path)
    stats["validation_geoid_seconds"] = perf_counter()-started
    started = perf_counter()
    digest = checksum_sha256(path)
    stats["dem_hash_seconds"] = perf_counter()-started
    if declaration["sha256"] != digest:
        raise ValueError("DEM checksum does not match height declaration")
    local = CRS.from_proj4(f"+proj=aeqd +lat_0={lat_deg} +lon_0={lon_deg} +datum=WGS84 +units=m")
    half = size*resolution_m/2
    with rasterio.Env(GDAL_CACHEMAX=budget.gdal_cache_bytes), rasterio.open(path) as src:
        if src.crs is None or src.count != 1:
            raise ValueError("DEM requires CRS and exactly one height band")
        if src.units[0] not in (None, "m", "metre", "meter"):
            raise ValueError("DEM embedded height unit conflicts with declaration")
        if max(a*b for a, b in src.block_shapes) > 4_000_000:
            raise TerrainResourceError("DEM native block too large; prepare a tiled source")
        estimate = budget.check_memory(size, max(a*b for a, b in src.block_shapes),
                                       np.dtype(src.dtypes[0]).itemsize)
        forward = Transformer.from_crs(local, src.crs, always_xy=True)
        reverse = Transformer.from_crs(src.crs, local, always_xy=True)
        started = perf_counter()
        c0, r0, c1, r1 = plan_bounds(src, forward, size, half, resolution_m, budget)
        stats["planning_transform_seconds"] = perf_counter()-started
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
        scale, offset = src.scales[0], src.offsets[0]
        if not math.isfinite(scale) or scale <= 0 or not math.isfinite(offset):
            raise ValueError("invalid DEM scale/offset")
        to_lonlat = Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True)
        target = read_tiles(src, forward, to_lonlat, vertical, size, half, resolution_m,
                            scale, offset, budget, stats, window_observer)
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
    started = perf_counter()
    grid = TerrainGrid(target, -half, half, resolution_m, "WGS84_ellipsoid", source_id,
                       surface_type=declaration["surface_type"])
    stats["freeze_seconds"] = perf_counter()-started
    if diagnostics is not None:
        diagnostics.update(stats, budget=asdict(budget), estimated_memory_bytes=estimate,
                           source_block_shapes=[list(s) for s in src.block_shapes],
                           strategy="two_pass_target_tiles")
    return grid, metadata
