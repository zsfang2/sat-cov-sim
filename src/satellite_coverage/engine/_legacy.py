"""Preserved single-frame orchestration behind the public engine entry point."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from ..coordinates import LocalGrid
from ..geodata import read_dem, rasterize_buildings
from ..propagation import (
    atmospheric_loss_db,
    directional_occlusion,
    fspl_db,
    knife_edge_loss_db,
    link_geometry,
    urban_losses,
)
from ..tle import TleCatalog
from .api import CoverageResult


def run_legacy_scenario(config: dict[str, Any]) -> CoverageResult:
    """Execute the legacy configuration with the current propagation functions."""
    region, link = config["region"], config["link"]
    grid = LocalGrid(
        center_lat=float(region["lat"]),
        center_lon=float(region["lon"]),
        size=int(region.get("size", 256)),
        extent_m=float(region.get("extent_m", 25_600.0)),
    )
    timestamp = datetime.fromisoformat(
        config["satellite"]["timestamp"].replace("Z", "+00:00")
    )
    satellite = TleCatalog(config["satellite"]["tle_file"]).best_visible(
        timestamp,
        grid.center_lat,
        grid.center_lon,
        float(config["satellite"].get("min_elevation_deg", 5.0)),
    )
    x_m, y_m = grid.enu_mesh()
    azimuth, elevation, range_m = link_geometry(
        x_m,
        y_m,
        satellite.azimuth_deg,
        satellite.elevation_deg,
        satellite.slant_range_m,
    )
    frequency_hz = float(link["frequency_ghz"]) * 1e9
    components: dict[str, np.ndarray] = {
        "fspl_db": fspl_db(range_m, frequency_hz),
        "atmosphere_db": atmospheric_loss_db(
            elevation,
            float(link["frequency_ghz"]),
            float(link.get("rain_rate_mm_h", 0.0)),
        ),
    }
    terrain_config = config.get("terrain", {})
    if terrain_config.get("dem_file"):
        dem = read_dem(terrain_config["dem_file"], grid)
        blocked, excess, obstacle_distance = directional_occlusion(
            dem,
            satellite.azimuth_deg,
            satellite.elevation_deg,
            grid.resolution_m,
        )
        components["terrain_diffraction_db"] = knife_edge_loss_db(
            excess,
            obstacle_distance,
            range_m,
            frequency_hz,
        )
        components["terrain_blocked"] = blocked.astype(np.float32)
    buildings_config = config.get("buildings", {})
    if buildings_config.get("file"):
        heights = rasterize_buildings(
            buildings_config["file"],
            grid,
            buildings_config.get("height_field", "height_m"),
        )
        urban, reflection, blocked = urban_losses(
            heights,
            satellite.azimuth_deg,
            satellite.elevation_deg,
            grid.resolution_m,
            float(buildings_config.get("penetration_db", 18.0)),
            float(buildings_config.get("reflection_credit_db", 3.0)),
        )
        components["urban_loss_db"] = urban
        components["reflection_credit_db"] = reflection
        components["building_blocked"] = blocked.astype(np.float32)
    total_loss = components["fspl_db"] + components["atmosphere_db"]
    for key in ("terrain_diffraction_db", "urban_loss_db"):
        if key in components:
            total_loss = total_loss + components[key]
    if "reflection_credit_db" in components:
        total_loss = total_loss - components["reflection_credit_db"]
    received = (
        float(link["eirp_dbm"])
        + float(link.get("rx_gain_dbi", 0.0))
        - total_loss
    )
    return CoverageResult(
        satellite,
        grid,
        total_loss.astype(np.float32),
        received.astype(np.float32),
        components,
    )
