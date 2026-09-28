"""Analytic scalar link calculation, independent of files and orbit selection."""

from dataclasses import asdict
import math

from ..domain.link_record import Quantity, QuantityStatus, LossComponent, compose_received_power
from ..geometry.local import relative_enu_geometry
from ..propagation import fspl_db


def free_space_loss_db(distance_m, frequency_hz):
    for name, value in (("distance_m", distance_m), ("frequency_hz", frequency_hz)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    # Use the legacy formula at one metre, then apply distance scaling explicitly.
    # This avoids silently clamping valid sub-metre analytic inputs to one metre.
    return float(fspl_db(1.0, frequency_hz)) + 20.0 * math.log10(distance_m)


def calculate_link(config):
    data = config.to_mapping()
    geometry = relative_enu_geometry(data["satellite_relative_enu_m"])
    fspl = free_space_loss_db(geometry["slant_range_m"], data["frequency_hz"])
    components = [LossComponent("fspl", Quantity(fspl, "dB", QuantityStatus.KNOWN,
                                               "free_space_formula"), ("free_space",), "fspl-v1")]
    for name, loss in data["losses"].items():
        components.append(LossComponent(name, Quantity(loss["value"], "dB", QuantityStatus(loss["status"]),
                                                       loss["reason"]), (name,), "declared-scalar-v1"))
    power = data["power"]
    eirp = power["eirp_dbm"] if power["mode"] == "eirp" else power["transmit_power_dbm"] + power["transmit_gain_dbi"]
    received = compose_received_power(eirp, data["receiver_gain_dbi"], tuple(components))
    if not geometry["geometrically_above_local_horizontal"]:
        received = Quantity(None, "dBm", QuantityStatus.NOT_APPLICABLE, "not_above_local_horizontal")
    threshold = data["threshold"]
    margin = Quantity(None, "dB", QuantityStatus.NOT_COMPUTED, "threshold_or_received_power_unavailable")
    if threshold is not None and received.status is QuantityStatus.KNOWN:
        margin = Quantity(received.value - threshold["received_power_dbm"], "dB", QuantityStatus.KNOWN,
                          "received_power_minus_declared_threshold")
    return {
        "sample_id": data["sample_id"], "input_type": "synthetic_relative_position",
        "receiver": data["receiver"], "satellite_relative_enu_m": data["satellite_relative_enu_m"],
        "height_semantics": "relative vector starts at antenna; AGL height is not added twice",
        "frequency_hz": data["frequency_hz"], "geometry": geometry, "power_input": power,
        "eirp_dbm": eirp, "receiver_gain_dbi": data["receiver_gain_dbi"],
        "components": [asdict(c) for c in components], "received_power": received.to_mapping(),
        "threshold": threshold, "margin": margin.to_mapping(), "service_eligibility": "unknown",
        "solver": data["solver_version"], "environment_id": data["environment_id"],
        "config_checksum": config.checksum_sha256(), "physical_input_checksum": config.checksum_sha256(),
        "applicability": "synthetic_scalar_mean_power_only; no terrain or actual service validation",
        "absolute_time_status": "not_applicable",
    }
