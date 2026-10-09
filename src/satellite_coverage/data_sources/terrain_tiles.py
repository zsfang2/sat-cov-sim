"""Bounded coordinate planning and nearest-native-cell reads."""

from dataclasses import dataclass
from time import perf_counter

import numpy as np
from rasterio.windows import Window


class TerrainResourceError(ValueError):
    """A valid terrain request cannot fit the selected read resource budget."""


@dataclass(frozen=True)
class TerrainReadBudget:
    tile_size: int = 128
    target_cells: int = 4_000_000
    source_window_cells: int = 262_144
    memory_bytes: int = 512 * 1024**2
    gdal_cache_bytes: int = 32 * 1024**2

    def __post_init__(self):
        limits = dict(tile_size=128, target_cells=4_000_000,
                      source_window_cells=262_144, memory_bytes=512*1024**2,
                      gdal_cache_bytes=32*1024**2)
        for name, maximum in limits.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f'{name} must be an integer in 1..{maximum}')

    def check_memory(self, size, block_cells=0, itemsize=0):
        if size*size > self.target_cells:
            raise TerrainResourceError('local terrain grid exceeds target budget (maximum four million cells)')
        # Three output copies during TerrainGrid freezing; native block reserve
        # includes source, float64 masked buffer, filled copy and mask.
        estimate = (192*1024**2 + 3*size*size*8 + self.gdal_cache_bytes
                    + block_cells*(itemsize+17) + 32*1024**2)
        if estimate > self.memory_bytes:
            raise TerrainResourceError('terrain estimated memory exceeds read budget')
        return estimate


def tiles(size, tile_size):
    for r in range(0, size, tile_size):
        for c in range(0, size, tile_size):
            yield r, min(r+tile_size, size), c, min(c+tile_size, size)


def transform_points(transformer, *arrays):
    # pyproj's one-element fast path expects scalars (NumPy arrays warn).
    if arrays[0].size == 1:
        result = transformer.transform(*(float(a.item()) for a in arrays), errcheck=True)
        return tuple(np.asarray(value).reshape(arrays[0].shape) for value in result)
    return transformer.transform(*arrays, errcheck=True)


def indices(src, forward, tile, half, resolution):
    r0, r1, c0, c1 = tile
    x, y = np.meshgrid((np.arange(c0, c1)+.5)*resolution-half,
                       half-(np.arange(r0, r1)+.5)*resolution)
    sx, sy = transform_points(forward, x, y)
    cols, rows = (~src.transform)*(sx, sy)
    if not np.isfinite(cols).all() or not np.isfinite(rows).all():
        raise ValueError('nonfinite DEM coordinates')
    # Bound before integer conversion: remote finite coordinates need not fit
    # int64. Invalid positions remain masked and never become source indices.
    valid = (cols >= 0) & (cols < src.width) & (rows >= 0) & (rows < src.height)
    cols = np.floor(np.where(valid, cols, 0)).astype(np.int64)
    rows = np.floor(np.where(valid, rows, 0)).astype(np.int64)
    return cols, rows, valid


def bounds(cols, rows, valid):
    if not valid.any():
        return None
    return (int(cols[valid].min()), int(rows[valid].min()),
            int(cols[valid].max())+1, int(rows[valid].max())+1)


def plan_bounds(src, forward, size, half, resolution, budget):
    union = None
    for tile in tiles(size, budget.tile_size):
        box = bounds(*indices(src, forward, tile, half, resolution))
        if box is not None:
            union = box if union is None else (min(union[0], box[0]), min(union[1], box[1]),
                                              max(union[2], box[2]), max(union[3], box[3]))
    if union is None:
        raise ValueError('requested terrain does not intersect DEM')
    return union


def bounded_tiles(src, forward, tile, half, resolution, budget, stats):
    start = perf_counter()
    cols, rows, valid = indices(src, forward, tile, half, resolution)
    stats['execution_transform_seconds'] += perf_counter()-start
    box = bounds(cols, rows, valid)
    if box is None:
        return
    c0, r0, c1, r1 = box
    if (c1-c0)*(r1-r0) > budget.source_window_cells:
        a, b, c, d = tile
        if b-a == 1 and d-c == 1:
            raise TerrainResourceError('minimum target tile exceeds source window budget')
        stats['subdivisions'] += 1
        # Drop parent coordinate arrays before descending.
        del cols, rows, valid
        if b-a >= d-c:
            mid = (a+b)//2
            children = ((a, mid, c, d), (mid, b, c, d))
        else:
            mid = (c+d)//2
            children = ((a, b, c, mid), (a, b, mid, d))
        for child in children:
            yield from bounded_tiles(src, forward, child, half, resolution, budget, stats)
    else:
        yield tile, cols, rows, valid, box


def read_tiles(src, forward, to_lonlat, vertical, size, half, resolution,
               scale, offset, budget, stats, window_observer=None):
    target = np.full((size, size), np.nan)
    for outer in tiles(size, budget.tile_size):
        for tile, cols, rows, valid, box in bounded_tiles(
                src, forward, outer, half, resolution, budget, stats):
            c0, r0, c1, r1 = box
            window = Window(c0, r0, c1-c0, r1-r0)
            cells = (c1-c0)*(r1-r0)
            stats['read_windows'] += 1
            stats['read_cells'] += cells
            stats['max_read_cells'] = max(stats['max_read_cells'], cells)
            if window_observer is not None:
                window_observer((c0, r0, c1-c0, r1-r0))
            start = perf_counter()
            values = src.read(1, window=window, masked=True, out_dtype='float64').filled(np.nan)
            stats['read_seconds'] += perf_counter()-start
            a, b, c, d = tile
            part = target[a:b, c:d]
            part[valid] = values[rows[valid]-r0, cols[valid]-c0]*scale+offset
            del values
            if vertical is not None:
                start = perf_counter()
                finite = np.isfinite(part)
                if finite.any():
                    cx, cy = src.transform*(cols[finite]+.5, rows[finite]+.5)
                    lon, lat = transform_points(to_lonlat, cx, cy)
                    _, _, shifted = transform_points(vertical, lon, lat, part[finite])
                    part[finite] = shifted
                stats['vertical_seconds'] += perf_counter()-start
    return target
