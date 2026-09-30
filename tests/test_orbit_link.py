from copy import deepcopy
from pathlib import Path
import math

import numpy as np
from pyproj import Transformer
import pytest
import yaml

from satellite_coverage.engine.orbit_link import calculate_orbit_links
from satellite_coverage.engine.link_budget import compose_budget
from satellite_coverage.geometry.geodetic import antenna_position, ecef_and_basis, ecef_geometry
from satellite_coverage.geometry.local import relative_enu_geometry
from satellite_coverage.orbit.visibility import altitude, calculate_visibility, parse_catalog, satellite_track, utc
from satellite_coverage.experiments.orbit_link import execute

TLE = b"1 44714U 19074B   25001.18947582  .00035730  00000-0  24039-2 0  9991\n2 44714  53.0572 328.1885 0001289 107.3927 252.7203 15.06423914283568\n"
ROOT = Path(__file__).resolve().parents[1]


def config():
    data = yaml.safe_load((ROOT / "configs/orbit_link.yaml").read_text())
    data.update(end="2025-01-01T05:03:00Z", step_s=60)
    return data


@pytest.mark.parametrize("lon,lat,height", [(0, 0, 0), (90, 0, 100), (108.9, 34.24, 400),
                                            (-179, -65, -20), (0, 90, 0), (120, -90, 3)])
def test_ecef_independent_proj_and_basis(lon, lat, height):
    spec = config()["receiver"]
    spec.update(lon_deg=lon, lat_deg=lat, antenna_ellipsoid_height_m=height)
    receiver = antenna_position(spec)
    xyz, basis = ecef_and_basis(receiver)
    expected = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True).transform(lon, lat, height)
    np.testing.assert_allclose(xyz, expected, rtol=0, atol=1e-8)
    np.testing.assert_allclose(np.array(basis) @ np.array(basis).T, np.eye(3), atol=1e-15)
    assert np.linalg.det(basis) == pytest.approx(1)
    zenith = np.array(xyz) + 550000 * np.array(basis[2])
    geometry = ecef_geometry(receiver, list(zenith))
    assert geometry["slant_range_m"] == pytest.approx(550000, abs=1e-8)
    assert geometry["azimuth_deg"] is None
    assert geometry["elevation_deg"] == pytest.approx(90)


def test_equatorial_axes_and_height_contract():
    spec = config()["receiver"]
    spec.update(lon_deg=0, lat_deg=0, antenna_ellipsoid_height_m=0)
    receiver = antenna_position(spec)
    # At lon=lat=0, ECEF +Y is east, +Z north, +X up.
    east = ecef_geometry(receiver, [6378137, 1000, 0])
    north = ecef_geometry(receiver, [6378137, 0, 1000])
    assert (east["azimuth_deg"], north["azimuth_deg"]) == (90, 0)
    assert east["elevation_deg"] == 0 and not east["geometrically_above_local_horizontal"]
    assert ecef_geometry(receiver, [6378137-100, 0, 0])["elevation_deg"] == -90
    with pytest.raises(ValueError, match="slant range"):
        ecef_geometry(receiver, [6378137, 0, 0])
    converted = dict(lon_deg=0, lat_deg=0, height_basis="orthometric_plus_geoid",
                     ground_orthometric_height_m=380, geoid_undulation_m=18, antenna_agl_m=2,
                     vertical_datum="declared test datum", basis="analytic fixture")
    assert antenna_position(converted)["antenna_ellipsoid_height_m"] == 400
    del converted["geoid_undulation_m"]
    with pytest.raises(ValueError):
        antenna_position(converted)
    spec["antenna_ellipsoid_height_m"] = True
    with pytest.raises(ValueError):
        antenna_position(spec)


def test_orbit_matches_topocentric_and_relative_input():
    data = config()
    catalog = parse_catalog(TLE)
    result = calculate_orbit_links(catalog, data)
    assert result["complete"] and not result["selection"]["uses_future_epoch"]
    samples = result["records"]
    stamps = [utc(r["timestamp_utc"]).timestamp() for r in samples]
    alt, az, distance = altitude(catalog.records["44714"][0], {"lon": 108.9, "lat": 34.24, "height_m": 400}, stamps)
    for i, record in enumerate(samples):
        g = record["geometry"]
        assert g["slant_range_m"] == pytest.approx(distance[i] * 1000, abs=1e-5)
        assert g["elevation_deg"] == pytest.approx(alt[i], abs=1e-8)
        assert g["azimuth_deg"] == pytest.approx(az[i], abs=1e-8)
        relative = relative_enu_geometry(g["satellite_relative_enu_m"])
        assert relative["slant_range_m"] == g["slant_range_m"]
        b = data["budget"]
        assert compose_budget(relative, b["frequency_hz"], b["power"], b["receiver_gain_dbi"], b["losses"], b["threshold"]) == record["budget"]


def test_power_sensitivity_unknown_and_horizon():
    b = config()["budget"]
    def power(distance=550000, frequency=None, eirp=55, losses=None, threshold=None):
        return compose_budget(relative_enu_geometry([0, 0, distance]), frequency or b["frequency_hz"],
                              {"mode": "eirp", "eirp_dbm": eirp}, 0, losses or b["losses"], threshold)
    base = power()["received_power"]["value"]
    assert base == pytest.approx(-115.48239703458438, abs=1e-10)
    assert power(eirp=58)["received_power"]["value"] - base == pytest.approx(3)
    for changed in (power(distance=1100000), power(frequency=2*b["frequency_hz"])):
        assert changed["received_power"]["value"] - base == pytest.approx(-20*math.log10(2))
    unknown = deepcopy(b["losses"])
    unknown["local"] = {"value": None, "status": "unknown", "reason": "DEM datum unresolved"}
    assert power(losses=unknown)["received_power"]["status"] == "not_computed"
    assert power(distance=-550000)["received_power"]["status"] == "not_applicable"
    assert power(threshold={"received_power_dbm": -120, "basis": "test"})["margin"]["value"] == pytest.approx(base+120)
    for f in (0, -1, float("nan")):
        invalid = config()
        invalid["budget"]["frequency_hz"] = f
        with pytest.raises(ValueError):
            calculate_orbit_links(parse_catalog(TLE), invalid)


def test_no_future_leakage_stale_and_failed_propagation(monkeypatch):
    data = config()
    catalog = parse_catalog(TLE)
    data.update(start="2025-01-01T00:00:00Z", end="2025-01-01T00:01:00Z")
    result = calculate_orbit_links(catalog, data)
    assert not result["complete"]
    assert all(r["status"] == "not_computed" and r["budget"] is None for r in result["records"])
    data["tle_policy"] = "historical_exploration"
    result = calculate_orbit_links(catalog, data)
    assert result["complete"] and result["selection"]["uses_future_epoch"]
    data.update(start="2026-01-01T00:00:00Z", end="2026-01-01T00:01:00Z")
    assert calculate_orbit_links(catalog, data)["records"][0]["reason"] == "tle_epoch_exceeds_max_age_days"
    def failed(*args):
        raise ValueError("simulated propagation failure")
    monkeypatch.setattr(catalog.records["44714"][0], "at", failed)
    result = calculate_orbit_links(catalog, config())
    assert not result["complete"] and all(r["status"] == "failed" for r in result["records"])


def test_visibility_and_track_share_policy_and_age():
    catalog = parse_catalog(TLE)
    data = {"start": "2025-01-01T00:00:00Z", "end": "2025-01-01T01:00:00Z",
            "observer": {"lon": 108.9, "lat": 34.24}, "tle_policy": "past_only"}
    result = calculate_visibility(catalog, data)
    assert not result["complete"] and result["skipped"][0]["reason"] == "no_tle_at_or_before_start"
    with pytest.raises(ValueError, match="no_tle"):
        satellite_track(catalog, data, "44714")
    data.update(start="2026-01-01T00:00:00Z", end="2026-01-01T01:00:00Z")
    with pytest.raises(ValueError, match="max_age"):
        satellite_track(catalog, data, "44714")


def test_run_record_replays_and_refuses_overwrite(tmp_path):
    import json
    cfg, tle = tmp_path / "config.yaml", tmp_path / "fixture.tle"
    data = config()
    data["step_s"] = 70
    cfg.write_text(yaml.safe_dump(data))
    tle.write_bytes(TLE)
    output = tmp_path / "run"
    result = execute(cfg, tle, output, ROOT)
    assert len(result["records"]) == 4
    assert utc(result["records"][-1]["timestamp_utc"]) == utc(data["end"])
    assert json.loads((output / "validation.json").read_text())["status"] == "passed"
    replay = calculate_orbit_links(parse_catalog((output / "input.tle").read_bytes()), json.loads((output / "config.json").read_text()))
    assert replay == result
    assert {"sources.zip", "links.json", "input.tle"} <= set(json.loads((output / "artifacts.json").read_text())["files"])
    with pytest.raises(FileExistsError):
        execute(cfg, tle, output, ROOT)


@pytest.mark.parametrize("field,value", [("step_s", 0), ("step_s", 1e-300), ("step_s", True),
                                        ("tle_policy", "guess"), ("receiver", None),
                                        ("start", "2025-01-01T05:00:00"), ("max_age_days", 31)])
def test_invalid_contract_rejected(field, value):
    data = config()
    data[field] = value
    with pytest.raises(ValueError):
        calculate_orbit_links(parse_catalog(TLE), data)


def test_step_larger_than_interval_and_failed_run_audit(tmp_path):
    import json
    data = config()
    data["step_s"] = 1e100
    result = calculate_orbit_links(parse_catalog(TLE), data)
    assert len(result["records"]) == 2
    cfg, tle = tmp_path / "bad.yaml", tmp_path / "bad.tle"
    cfg.write_text(yaml.safe_dump(data))
    tle.write_bytes(b"invalid TLE")
    with pytest.raises(ValueError):
        execute(cfg, tle, tmp_path / "failed", ROOT)
    assert json.loads((tmp_path / "failed/validation.json").read_text())["status"] == "failed"
    assert (tmp_path / "failed/artifacts.json").exists()
