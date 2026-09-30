from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import math
from pathlib import Path

import pytest
import yaml

from satellite_coverage.config.link import LinkConfig
from satellite_coverage.engine.links import calculate_links
from satellite_coverage.experiments.link import execute
from satellite_coverage.geometry.antenna import receive_gain
from satellite_coverage.orbit.visibility import parse_catalog

ROOT = Path(__file__).resolve().parents[1]
TLE = b"1 44714U 19074B   25001.18947582  .00035730  00000-0  24039-2 0  9991\n2 44714  53.0572 328.1885 0001289 107.3927 252.7203 15.06423914283568\n"


def config(name="fixed"):
    return yaml.safe_load((ROOT / f"configs/m1_{name}.yaml").read_text())


def test_three_sources_share_geometry_budget_and_contract():
    tle = config("tle")
    tle.update(end="2025-01-01T05:00:10Z", step_s=10)
    orbit = calculate_links(tle, parse_catalog(TLE))
    for i, sample in enumerate(orbit["records"]):
        # Every orbit sample is also a fixed ECEF position and an ENU vector.
        fixed, relative = deepcopy(tle), deepcopy(tle)
        fixed["source"] = {"mode": "fixed_ecef", "candidate_id": "equivalent",
                           "position_ecef_m": sample["geometry"]["satellite_ecef_m"]}
        relative["source"] = {"mode": "relative_enu_sequence", "candidate_id": "equivalent",
                              "positions_enu_m": [sample["geometry"]["satellite_relative_enu_m"]]*2}
        for alternative in (calculate_links(fixed), calculate_links(relative)):
            record = alternative["records"][i]
            assert set(record) == set(sample)
            for field in ("slant_range_m", "elevation_deg", "azimuth_deg"):
                assert record["geometry"][field] == pytest.approx(sample["geometry"][field], abs=1e-8)
            assert record["budget"] == sample["budget"]
    analytic = calculate_links(config())
    assert all(r["budget"]["received_power"]["value"] == pytest.approx(-115.48239703458438)
               for r in analytic["records"])


def test_direction_pattern_axis_rotation_and_no_double_gain():
    data = config("sequence")
    pattern = data["budget"]["receiver_antenna"]
    assert receive_gain(pattern, [0, 0, 1])["gain_dbi"] == 12
    gain60 = receive_gain(pattern, [math.sqrt(3), 0, 1])
    assert gain60["off_axis_deg"] == pytest.approx(60)
    assert gain60["gain_dbi"] == pytest.approx(12+20*math.log10(.5))
    for vector in ([1, 0, 0], [0, 0, -1]):
        assert receive_gain(pattern, vector)["gain_dbi"] == -20
    rotated = {**pattern, "boresight_enu": [10, 0, 0]}
    assert receive_gain(rotated, [1, 0, 0])["gain_dbi"] == 12
    records = calculate_links(data)["records"]
    assert records[0]["budget"]["received_power"]["value"] == pytest.approx(-115.48239703458438+12-1)
    assert all(r["budget"]["received_power"]["status"] == "not_applicable" for r in records[-2:])
    assert records[-1]["timestamp_utc"].startswith("2025-01-02")
    data["budget"]["power"] = {"mode": "eirp", "eirp_dbm": 55}
    changed = calculate_links(data)["records"]
    assert [r["budget"] for r in changed] == [r["budget"] for r in records]
    assert changed[0]["config_checksum"] != records[0]["config_checksum"]


def test_losses_switches_missingness_and_effect_metadata():
    data = config()
    base = calculate_links(data)["records"][0]["budget"]
    data["budget"]["losses"]["atmosphere"] = {"enabled": True, "value": 2, "status": "known", "reason": "fixed scenario"}
    atmospheric = calculate_links(data)["records"][0]["budget"]
    assert atmospheric["received_power"]["value"] == pytest.approx(base["received_power"]["value"]-2)
    assert atmospheric["margin"]["value"] == pytest.approx(base["margin"]["value"]-2)
    for component in atmospheric["components"]:
        assert component["reference_power"] == "eirp_plus_receive_gain"
        assert component["averaging"] and component["solver"] and component["effects"]
    data["budget"]["losses"]["local"] = {"enabled": True, "value": None, "status": "unknown", "reason": "unresolved terrain"}
    missing = calculate_links(data)
    assert missing["complete"]
    assert missing["records"][0]["budget"]["received_power"]["status"] == "not_computed"
    assert missing["records"][0]["service_eligibility"] == "unknown"
    data["budget"]["losses"]["local"]["status"] = "failed"
    failed = calculate_links(data)
    assert failed["records"][0]["budget"]["received_power"]["status"] == "failed"
    assert not failed["complete"] and failed["records"][0]["status"] == "failed"


@pytest.mark.parametrize("change", [
    lambda d: d["budget"].update(frequency_hz=0),
    lambda d: d["budget"]["receiver_antenna"].pop("exponent"),
    lambda d: d["budget"]["receiver_antenna"].update(boresight_enu=[0, 0, 0]),
    lambda d: d["budget"]["receiver_antenna"].update(floor_gain_dbi=13),
    lambda d: d["budget"]["receiver_antenna"].update(exponent=-1),
    lambda d: d["budget"]["losses"]["atmosphere"].update(value=-1),
    lambda d: d["budget"]["losses"]["local"].update(value=0),
    lambda d: d["budget"]["losses"]["local"].update(enabled="false"),
    lambda d: d["source"]["directions"].pop(),
    lambda d: d["source"]["directions"][0].update(slant_range_m=0),
    lambda d: d["source"]["directions"][0].update(elevation_deg=float("nan")),
])
def test_invalid_m1_parameters_rejected(change):
    data = config("sequence")
    change(data)
    with pytest.raises(ValueError):
        calculate_links(data)


def test_coincident_fixed_candidate_is_failed_not_invisible():
    data = config()
    data["source"]["position_ecef_m"] = [6378137, 0, 0]
    result = calculate_links(data)
    assert not result["complete"]
    assert all(r["status"] == "failed" and r["budget"] is None for r in result["records"])


def test_immutable_config_and_common_runner(tmp_path):
    source = config()
    snapshot = LinkConfig.from_mapping(source)
    expected = snapshot.checksum
    source["budget"]["frequency_hz"] = 1
    snapshot.to_mapping()["budget"]["frequency_hz"] = 2
    assert snapshot.checksum == expected
    with pytest.raises(FrozenInstanceError):
        snapshot.serialized = b"{}"
    result = execute(ROOT / "configs/m1_fixed.yaml", None, tmp_path / "run", ROOT)
    replay = calculate_links(json.loads((tmp_path / "run/config.json").read_text()))
    assert result == replay
    assert not (tmp_path / "run/input.tle").exists()
    assert json.loads((tmp_path / "run/validation.json").read_text())["status"] == "passed"


def test_subsecond_grid_no_duplicate_endpoint():
    data = config()
    data.update(start="2025-01-01T00:00:00Z", end="2025-01-01T00:00:00.070Z", step_s=.01)
    records = calculate_links(data)["records"]
    assert len(records) == 8
    times = [r["timestamp_utc"] for r in records]
    assert len(set(times)) == len(times)


def test_direction_angles_and_range_share_enu_semantics():
    data = config()
    data["source"] = {"mode": "direction_sequence", "candidate_id": "directions", "directions": [
        {"azimuth_deg": 90, "elevation_deg": 30, "slant_range_m": 550000},
        {"azimuth_deg": 180, "elevation_deg": 90, "slant_range_m": 550000},
        {"azimuth_deg": 0, "elevation_deg": 0, "slant_range_m": 550000}]}
    records = calculate_links(data)["records"]
    assert records[0]["geometry"]["azimuth_deg"] == pytest.approx(90)
    assert records[0]["geometry"]["elevation_deg"] == pytest.approx(30)
    assert records[1]["geometry"]["azimuth_deg"] is None
    assert records[2]["budget"]["received_power"]["status"] == "not_applicable"
    data["source"]["directions"][0]["slant_range_m"] = 0
    with pytest.raises(ValueError):
        calculate_links(data)
