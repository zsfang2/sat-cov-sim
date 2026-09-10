"""Fast link-budget and directional raster propagation approximations."""

from __future__ import annotations

import numpy as np

SPEED_OF_LIGHT_M_S = 299_792_458.0


def fspl_db(distance_m: np.ndarray | float, frequency_hz: float) -> np.ndarray:
    distance = np.maximum(np.asarray(distance_m, dtype=float), 1.0)
    return 20 * np.log10(distance) + 20 * np.log10(frequency_hz) - 147.5522168


def atmospheric_loss_db(elevation_deg: np.ndarray | float, frequency_ghz: float, rain_rate_mm_h: float = 0.0) -> np.ndarray:
    """Engineering clear-air plus rain approximation, not a full ITU P.618 chain."""
    elevation = np.asarray(elevation_deg, dtype=float)
    sine = np.sin(np.radians(np.clip(elevation, 0.1, 90.0)))
    gaseous = 0.047 * (frequency_ghz / 10.0) / sine
    # Conservative smooth approximation useful for scenario comparison.
    rain = 0.0008 * max(rain_rate_mm_h, 0.0) ** 1.1 * frequency_ghz ** 0.9 / sine
    return np.where(elevation > 0.0, gaseous + rain, np.inf)


def link_geometry(grid_x_m: np.ndarray, grid_y_m: np.ndarray, center_azimuth_deg: float, center_elevation_deg: float, center_range_m: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Local tangent-plane geometry for a satellite state at the grid centre."""
    elevation = np.radians(center_elevation_deg)
    azimuth = np.radians(center_azimuth_deg)
    sat_x = center_range_m * np.cos(elevation) * np.sin(azimuth)
    sat_y = center_range_m * np.cos(elevation) * np.cos(azimuth)
    sat_z = center_range_m * np.sin(elevation)
    dx, dy = sat_x - grid_x_m, sat_y - grid_y_m
    horizontal = np.hypot(dx, dy)
    return np.degrees(np.arctan2(dx, dy)) % 360.0, np.degrees(np.arctan2(sat_z, horizontal)), np.hypot(horizontal, sat_z)


def directional_occlusion(height_m: np.ndarray, azimuth_deg: float, elevation_deg: float, resolution_m: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return blocked mask, maximum obstacle excess height and distance.

    A ray-aligned cumulative horizon sweep approximates parallel incoming waves.
    It captures terrain/building shadows in O(N² log N), while deliberately
    avoiding a costly per-pixel 3D ray tracer.
    """
    heights = np.asarray(height_m, dtype=float)
    if heights.ndim != 2 or elevation_deg <= 0:
        empty = np.zeros_like(heights, dtype=bool)
        return empty, np.zeros_like(heights), np.zeros_like(heights)
    rows, cols = heights.shape
    xx, yy = np.meshgrid((np.arange(cols) + .5) * resolution_m, (rows - np.arange(rows) - .5) * resolution_m)
    # The sweep begins at the satellite-facing edge, hence direction is opposite
    # the azimuth at which the satellite is observed.
    incoming = np.radians((azimuth_deg + 180.0) % 360.0)
    ux, uy = np.sin(incoming), np.cos(incoming)
    u = xx * ux + yy * uy
    v = xx * (-uy) + yy * ux
    ray_id = np.floor(v / resolution_m).astype(np.int64)
    order = np.lexsort((u.ravel(), ray_id.ravel()))
    slope = np.tan(np.radians(elevation_deg))
    blocked = np.zeros(heights.size, dtype=bool)
    excess = np.zeros(heights.size, dtype=float)
    distance = np.zeros(heights.size, dtype=float)
    last_ray, max_term, max_u = None, -np.inf, 0.0
    for index in order:
        ray = ray_id.ravel()[index]
        if ray != last_ray:
            last_ray, max_term, max_u = ray, -np.inf, 0.0
        current_u = u.ravel()[index]
        horizon = slope * current_u
        if max_term > horizon:
            blocked[index] = True
            excess[index] = max_term - horizon
            distance[index] = max(current_u - max_u, resolution_m)
        term = heights.ravel()[index] + slope * current_u
        if term > max_term:
            max_term, max_u = term, current_u
    return blocked.reshape(heights.shape), excess.reshape(heights.shape), distance.reshape(heights.shape)


def knife_edge_loss_db(excess_height_m: np.ndarray, obstacle_distance_m: np.ndarray, slant_range_m: np.ndarray, frequency_hz: float) -> np.ndarray:
    wavelength = SPEED_OF_LIGHT_M_S / frequency_hz
    d1 = np.maximum(obstacle_distance_m, 1.0)
    d2 = np.maximum(slant_range_m - d1, 1.0)
    fresnel_v = excess_height_m * np.sqrt(2.0 * (d1 + d2) / (wavelength * d1 * d2))
    loss = 6.9 + 20.0 * np.log10(np.sqrt((fresnel_v - .1) ** 2 + 1.0) + fresnel_v - .1)
    return np.clip(np.where(excess_height_m > 0, loss, 0.0), 0.0, 60.0)


def urban_losses(building_height_m: np.ndarray, azimuth_deg: float, elevation_deg: float, resolution_m: float, penetration_db: float = 18.0, reflection_db: float = 3.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Building shadow, penetration and small first-order reflection proxy."""
    blocked, excess, distance = directional_occlusion(building_height_m, azimuth_deg, elevation_deg, resolution_m)
    occupied = building_height_m > 0
    loss = np.where(blocked, penetration_db, 0.0) + np.where(occupied, penetration_db, 0.0)
    reflection = np.where(blocked & ~occupied, reflection_db, 0.0)
    return loss.astype(np.float32), reflection.astype(np.float32), blocked

