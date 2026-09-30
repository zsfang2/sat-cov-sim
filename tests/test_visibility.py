from datetime import timedelta

import numpy as np
import pytest

from satellite_coverage.orbit.visibility import (
    altitude, calculate_visibility, merge_intervals, observers, parse_catalog,
    point_windows, select_record, utc,
)


TLE = b"1 44714U 19074B   25001.18947582  .00035730  00000-0  24039-2 0  9991\n2 44714  53.0572 328.1885 0001289 107.3927 252.7203 15.06423914283568\n"
LATER = b"1 44714U 19074B   25001.91929161  .00066395  00000-0  44286-2 0  9992\n2 44714  53.0569 324.9117 0003247 103.9087 256.2264 15.06447158283675\n"


def request():
    return {"start": "2025-01-01T00:00:00Z", "end": "2025-01-02T00:00:00Z",
            "observer": {"mode": "point", "lon": 108.9, "lat": 34.24, "height_m": 400},
            "min_elevation_deg": 10, "region_rule": "any", "max_age_days": 7}


def test_catalog_duplicates_epoch_policy_and_malformed_input():
    catalog = parse_catalog(TLE + LATER + TLE)
    assert catalog.summary()["satellites"] == 1
    assert catalog.duplicate_count == 1 and catalog.record_count == 3
    assert select_record(catalog.records["44714"], utc("2025-01-01T12:00:00Z")).epoch.utc_datetime().hour == 4
    assert select_record(catalog.records["44714"], utc("2025-01-02T12:00:00Z")).epoch.utc_datetime().hour == 22
    with pytest.raises(ValueError, match="校验和"):
        parse_catalog(TLE.replace(b"9991", b"9992"))
    with pytest.raises(ValueError):
        parse_catalog(TLE.splitlines()[0])
    with pytest.raises(ValueError, match="时区"):
        utc("2025-01-01T00:00:00")


def test_interval_union_intersection_and_touching_edges():
    groups = [[(0, 5), (8, 10)], [(3, 8)]]
    assert merge_intervals(groups) == [(0, 10)]
    assert merge_intervals(groups, True) == [(3, 5)]
    assert merge_intervals([[(0, 10)], []], True) == []
    assert merge_intervals([[(0, 10)], []]) == [(0, 10)]


def test_events_match_dense_altitude_and_clip_inside_pass():
    catalog = parse_catalog(TLE)
    data = request()
    result = calculate_visibility(catalog, data)
    assert result["windows"] and result["complete"]
    sat = catalog.records["44714"][0]
    point = result["points"][0]
    start, end = utc(data["start"]), utc(data["end"])
    times = np.arange(start.timestamp(), end.timestamp(), 10)
    elevations = altitude(sat, point, times)[0]
    predicted = np.zeros(times.shape, dtype=bool)
    away_from_edge = np.ones(times.shape, dtype=bool)
    for window in result["windows"]:
        a, b = window["start_timestamp"], window["end_timestamp"]
        predicted |= (times >= a) & (times <= b)
        away_from_edge &= (abs(times - a) > 1) & (abs(times - b) > 1)
        assert altitude(sat, point, [(a+b)/2])[0][0] >= 10
        assert abs(altitude(sat, point, [a])[0][0] - 10) < 0.2
    np.testing.assert_array_equal(predicted[away_from_edge], elevations[away_from_edge] >= 10)
    first = result["windows"][0]
    a, b = utc(first["start"]), utc(first["end"])
    clipped = point_windows(sat, point, a + timedelta(seconds=2), b - timedelta(seconds=2), 10)
    assert len(clipped) == 1 and clipped[0]["start_clipped"] and clipped[0]["end_clipped"]


def test_region_sampling_and_stale_tle_not_reported_as_clear_sky():
    data = request()
    data["observer"] = {"mode": "region", "bounds": [108.8, 34.1, 109, 34.3], "grid": 2, "height_m": 0}
    assert len(observers(data["observer"])) == 4
    catalog = parse_catalog(TLE)
    any_result = calculate_visibility(catalog, data)
    data["region_rule"] = "all"
    all_result = calculate_visibility(catalog, data)
    assert any_result["covered_seconds"] >= all_result["covered_seconds"] > 0
    data.update(start="2026-01-01T00:00:00Z", end="2026-01-02T00:00:00Z")
    stale = calculate_visibility(catalog, data)
    assert not stale["complete"] and stale["skipped"] and not stale["satellites_computed"]


def test_real_catalog_if_available():
    """The external archive is optional; portable analytic tests above are not."""
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "Satellite-Ground-Radiomap/data/starlink-2025-tle/2025-01-01.tle"
    if not path.exists():
        pytest.skip("external Starlink archive not installed")
    catalog = parse_catalog(path.read_bytes())
    assert len(catalog.records) > 1000


def test_failed_propagation_and_cancellation_are_not_empty_success(monkeypatch):
    catalog = parse_catalog(TLE)
    with pytest.raises(InterruptedError):
        calculate_visibility(catalog, request(), cancelled=lambda: True)
    def fail(*args):
        raise ValueError("SGP4 propagation failed")
    monkeypatch.setattr("satellite_coverage.orbit.visibility.point_windows", fail)
    result = calculate_visibility(catalog, request())
    assert not result["complete"] and len(result["failed"]) == 1
    assert result["satellites_computed"] == 0 and result["windows"] == []
