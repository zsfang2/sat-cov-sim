from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import timezone
from pathlib import Path

import pytest
import yaml

from satellite_coverage.config import (
    ConfigError,
    ConfigProfileStatus,
    ScenarioConfig,
    load_scenario_config,
)


REFERENCE_CONFIG = Path(__file__).parents[1] / "configs" / "reference.yaml"


def _reference_mapping() -> dict:
    return yaml.safe_load(REFERENCE_CONFIG.read_text(encoding="utf-8"))


def test_reference_profile_matches_specified_dimensions_and_timing():
    config = load_scenario_config(REFERENCE_CONFIG)

    assert config.profile_status is ConfigProfileStatus.DRAFT
    assert len(config.spatial.regions) == 4
    assert config.spatial.map_shape == (768, 768)
    assert config.spatial.ground_resolution_m == 100.0
    assert config.spatial.extent_height_m == 76_800.0
    assert config.spatial.extent_width_m == 76_800.0
    assert config.spatial.geodetic_crs == "EPSG:4326"
    assert config.temporal.interval_s == 20
    assert config.temporal.frames_per_region == 2160
    assert config.total_frames == 8640
    assert config.temporal.start_time_utc.utcoffset() == timezone.utc.utcoffset(None)
    assert config.temporal.end_time_utc.utcoffset() == timezone.utc.utcoffset(None)
    assert config.service.minimum_elevation_deg == 25.0
    assert config.link.frequency_hz == 14.5e9
    assert config.link.transmit_power_dbm == 40.0
    assert config.link.receiver_gain_dbi == 0.0
    assert (config.antenna.array_rows, config.antenna.array_columns) == (64, 64)
    assert config.antenna.element_gain_dbi == 5.0
    assert config.antenna.array_efficiency_loss_db == 3.0
    assert config.antenna.maximum_off_axis_attenuation_db == 35.0
    assert config.atmosphere.gas_zenith_loss_db == 0.08
    assert config.atmosphere.cloud_zenith_loss_db == 0.10
    assert config.terrain.profile_step_m == 100.0
    assert config.terrain.profile_start_distance_m == 150.0
    assert config.terrain.effective_earth_radius_factor == pytest.approx(4.0 / 3.0)
    assert config.terrain.diffraction_loss_cap_db == 40.0
    assert (config.weather.minimum_cell_count, config.weather.maximum_cell_count) == (
        2,
        4,
    )
    assert config.weather.maximum_nominal_attenuation_db == 8.0
    assert config.clutter.maximum_nominal_attenuation_db == 2.0
    assert config.clutter.additional_bias_db == 0.4
    assert config.random.root_seed == 20_250_101


def test_canonical_serialization_is_independent_of_yaml_mapping_order():
    mapping = _reference_mapping()
    reversed_mapping = dict(reversed(tuple(mapping.items())))

    first = ScenarioConfig.from_mapping(mapping)
    second = ScenarioConfig.from_mapping(reversed_mapping)

    assert first.canonical_json_bytes() == second.canonical_json_bytes()
    assert first.checksum_sha256() == second.checksum_sha256()
    assert first.checksum_sha256().startswith("sha256:")


def test_canonical_serialization_normalizes_equivalent_real_number_spelling():
    first_mapping = _reference_mapping()
    second_mapping = deepcopy(first_mapping)
    second_mapping["spatial"]["ground_resolution_m"] = 100
    second_mapping["link"]["frequency_hz"] = 14_500_000_000

    first = ScenarioConfig.from_mapping(first_mapping)
    second = ScenarioConfig.from_mapping(second_mapping)

    assert first.canonical_json_bytes() == second.canonical_json_bytes()


def test_config_objects_are_frozen():
    config = load_scenario_config(REFERENCE_CONFIG)

    with pytest.raises(FrozenInstanceError):
        config.link.frequency_hz = 2.0e9


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["temporal"].update(
                start_time_utc="2025-01-01T00:00:00"
            ),
            "start_time_utc",
        ),
        (lambda value: value["link"].update(frequency_hz=0), "frequency_hz"),
        (
            lambda value: value["service"].update(minimum_elevation_deg=91),
            "minimum_elevation_deg",
        ),
        (lambda value: value["spatial"].update(map_height_px=0), "map_height_px"),
        (
            lambda value: value["spatial"].update(extent_width_m=0),
            "extent_width_m",
        ),
        (
            lambda value: value["spatial"].update(geodetic_crs="not-a-crs"),
            "geodetic_crs",
        ),
        (lambda value: value.pop("random"), "random"),
        (lambda value: value["random"].update(root_seed=True), "root_seed"),
        (
            lambda value: value["terrain"].update(diffraction_loss_cap_db=-1),
            "diffraction_loss_cap_db",
        ),
    ],
)
def test_invalid_reference_inputs_fail_explicitly(mutate, message):
    mapping = deepcopy(_reference_mapping())
    mutate(mapping)

    with pytest.raises(ConfigError, match=message):
        ScenarioConfig.from_mapping(mapping)


@pytest.mark.parametrize(
    ("section", "alias"),
    [
        ("link", "frequency_ghz"),
        ("link", "transmit_power_dbw"),
    ],
)
def test_conflicting_or_ambiguous_unit_aliases_are_rejected(section, alias):
    mapping = deepcopy(_reference_mapping())
    mapping[section][alias] = 14.5

    with pytest.raises(ConfigError, match=alias):
        ScenarioConfig.from_mapping(mapping)


def test_unknown_nested_keys_are_rejected():
    mapping = deepcopy(_reference_mapping())
    mapping["terrain"]["silent_clip_db"] = 60.0

    with pytest.raises(ConfigError, match="silent_clip_db"):
        ScenarioConfig.from_mapping(mapping)


def test_frame_count_must_match_inclusive_time_range():
    mapping = deepcopy(_reference_mapping())
    mapping["temporal"]["frames_per_region"] = 2159

    with pytest.raises(ConfigError, match="frames_per_region"):
        ScenarioConfig.from_mapping(mapping)
