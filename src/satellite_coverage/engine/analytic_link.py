"""Analytic scalar link calculation, independent of files and orbit selection."""

from ..geometry.local import relative_enu_geometry
from .link_budget import compose_budget, free_space_loss_db  # retained public import


def calculate_link(config):
    data = config.to_mapping()
    geometry = relative_enu_geometry(data["satellite_relative_enu_m"])
    power = data["power"]
    threshold = data["threshold"]
    budget = compose_budget(geometry, data["frequency_hz"], power, data["receiver_gain_dbi"], data["losses"], threshold)
    return {
        "sample_id": data["sample_id"], "input_type": "synthetic_relative_position",
        "receiver": data["receiver"], "satellite_relative_enu_m": data["satellite_relative_enu_m"],
        "height_semantics": "relative vector starts at antenna; AGL height is not added twice",
        "frequency_hz": data["frequency_hz"], "geometry": geometry, "power_input": power,
        **budget,
        "solver": data["solver_version"], "environment_id": data["environment_id"],
        "config_checksum": config.checksum_sha256(), "physical_input_checksum": config.checksum_sha256(),
        "applicability": "synthetic_scalar_mean_power_only; no terrain or actual service validation",
        "absolute_time_status": "not_applicable",
    }
