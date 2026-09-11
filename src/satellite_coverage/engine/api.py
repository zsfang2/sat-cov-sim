"""Dependency-light public interfaces for scenario execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


class SatelliteStateView(Protocol):
    """Legacy satellite fields exposed to callers of the compatibility API."""

    norad_id: str
    name: str
    elevation_deg: float
    azimuth_deg: float
    slant_range_m: float
    altitude_m: float


class GridView(Protocol):
    """Legacy grid fields exposed to callers of the compatibility API."""

    center_lat: float
    center_lon: float
    size: int
    extent_m: float


@dataclass
class CoverageResult:
    """Characterized output from the legacy single-frame runner."""

    satellite: SatelliteStateView
    grid: GridView
    total_loss_db: np.ndarray
    received_power_dbm: np.ndarray
    components: dict[str, np.ndarray]


def run_legacy_scenario(config: dict[str, Any]) -> CoverageResult:
    """Run the preserved implementation without importing it at package import."""
    from ._legacy import run_legacy_scenario as run

    return run(config)
