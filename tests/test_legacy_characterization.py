from __future__ import annotations

import numpy as np

import satellite_coverage.scenario as scenario_module
from satellite_coverage.propagation import (
    directional_occlusion,
    knife_edge_loss_db,
)
from satellite_coverage.scenario import CoverageScenario
from satellite_coverage.tle import SatelliteState


class _FixedCatalog:
    def __init__(self, _path: str):
        pass

    def best_visible(
        self,
        _when: object,
        _lat: float,
        _lon: float,
        _min_elevation_deg: float,
    ) -> SatelliteState:
        return SatelliteState(
            norad_id="99999",
            name="TEST SATELLITE",
            elevation_deg=45.0,
            azimuth_deg=30.0,
            slant_range_m=600_000.0,
            altitude_m=550_000.0,
        )


def test_legacy_scenario_without_terrain_is_characterized(monkeypatch):
    monkeypatch.setattr(scenario_module, "TleCatalog", _FixedCatalog)
    scenario = CoverageScenario(
        {
            "region": {"lat": 34.0, "lon": 108.0, "size": 4, "extent_m": 400.0},
            "satellite": {
                "timestamp": "2025-01-01T00:00:00Z",
                "tle_file": "unused-by-fixed-catalog.tle",
                "min_elevation_deg": 25.0,
            },
            "link": {
                "frequency_ghz": 14.5,
                "eirp_dbm": 55.0,
                "rx_gain_dbi": 0.0,
            },
        }
    )

    result = scenario.run()

    assert result.total_loss_db.shape == (4, 4)
    assert result.received_power_dbm.shape == (4, 4)
    assert result.total_loss_db.dtype == np.float32
    assert result.received_power_dbm.dtype == np.float32
    assert set(result.components) == {"fspl_db", "atmosphere_db"}
    assert all(component.shape == (4, 4) for component in result.components.values())
    np.testing.assert_allclose(
        result.total_loss_db,
        result.components["fspl_db"] + result.components["atmosphere_db"],
        rtol=0.0,
        atol=1e-5,
    )
    np.testing.assert_allclose(
        result.received_power_dbm,
        55.0 - result.total_loss_db,
        rtol=0.0,
        atol=1e-5,
    )


def test_flat_zero_datum_remains_unblocked_in_legacy_algorithm():
    heights_m = np.zeros((5, 5), dtype=np.float64)

    blocked, excess_height_m, obstacle_distance_m = directional_occlusion(
        heights_m,
        azimuth_deg=0.0,
        elevation_deg=25.0,
        resolution_m=100.0,
    )
    loss_db = knife_edge_loss_db(
        excess_height_m,
        obstacle_distance_m,
        np.full_like(excess_height_m, 550_000.0),
        14.5e9,
    )

    assert not blocked.any()
    assert not loss_db.any()

