"""Coordinate alignment and local simulation-grid utilities."""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from pyproj import Transformer

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class LocalGrid:
    """Square, north-up grid centred on a WGS84 coordinate.

    ``x_m`` grows eastward and ``y_m`` grows northward. Array row 0 is the
    northern edge; this convention keeps raster and map displays aligned.
    """

    center_lat: float
    center_lon: float
    size: int = 256
    extent_m: float = 25_600.0

    @property
    def resolution_m(self) -> float:
        return self.extent_m / self.size

    def enu_mesh(self) -> tuple[np.ndarray, np.ndarray]:
        pixel = self.resolution_m
        offsets = np.arange(self.size, dtype=float) * pixel - self.extent_m / 2 + pixel / 2
        return np.meshgrid(offsets, offsets[::-1])

    def latlon_mesh(self) -> tuple[np.ndarray, np.ndarray]:
        x_m, y_m = self.enu_mesh()
        lat = self.center_lat + np.degrees(y_m / EARTH_RADIUS_M)
        lon = self.center_lon + np.degrees(x_m / (EARTH_RADIUS_M * np.cos(np.radians(self.center_lat))))
        return lat, lon

    def bounds_wgs84(self) -> tuple[float, float, float, float]:
        lat, lon = self.latlon_mesh()
        return float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max())

    def bounds_in(self, crs: str) -> tuple[float, float, float, float]:
        transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        west, south, east, north = self.bounds_wgs84()
        xs, ys = transformer.transform([west, east, west, east], [south, south, north, north])
        return min(xs), min(ys), max(xs), max(ys)

