"""Windowed DEM and building-height loading with CRS alignment."""

from __future__ import annotations

from pathlib import Path
import numpy as np

from .coordinates import LocalGrid


def read_dem(dem_file: str | Path, grid: LocalGrid) -> np.ndarray:
    """Read and bilinearly resample just the requested GeoTIFF window."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds

    with rasterio.open(dem_file) as source:
        if source.crs is None:
            raise ValueError("DEM has no CRS")
        window = from_bounds(*grid.bounds_in(source.crs), transform=source.transform)
        data = source.read(1, window=window, out_shape=(grid.size, grid.size), resampling=Resampling.bilinear).astype(np.float32)
        if source.nodata is not None:
            data[data == source.nodata] = np.nan
    # Rasterio produces north-to-south rows, identical to LocalGrid's row order.
    return np.nan_to_num(data, nan=float(np.nanmedian(data)))


def rasterize_buildings(buildings_file: str | Path, grid: LocalGrid, height_field: str = "height_m") -> np.ndarray:
    """Rasterize intersecting building polygons into metres above ground."""
    import geopandas as gpd
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds
    from shapely.geometry import box

    buildings = gpd.read_file(buildings_file)
    if buildings.crs is None:
        raise ValueError("Building vector data has no CRS")
    bounds = grid.bounds_in(buildings.crs)
    subset = buildings[buildings.geometry.intersects(box(*bounds))].copy()
    if subset.empty:
        return np.zeros((grid.size, grid.size), dtype=np.float32)
    if height_field not in subset:
        raise KeyError(f"Building height field '{height_field}' is absent")
    transform = from_bounds(*bounds, grid.size, grid.size)
    shapes = ((geometry, float(height)) for geometry, height in zip(subset.geometry, subset[height_field]) if geometry is not None and np.isfinite(height))
    return rasterize(shapes, out_shape=(grid.size, grid.size), transform=transform, fill=0.0, dtype="float32")

