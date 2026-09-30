"""Shared scalar mean-power composition for synthetic and orbital geometry."""

from dataclasses import asdict
import math

from ..domain.link_record import Quantity, QuantityStatus, LossComponent, compose_received_power
from ..propagation import fspl_db


def free_space_loss_db(distance_m, frequency_hz):
    for name, value in (("distance_m", distance_m), ("frequency_hz", frequency_hz)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    # Evaluate at 1 m then scale: legacy FSPL clamps sub-metre distances.
    return float(fspl_db(1.0, frequency_hz)) + 20.0 * math.log10(distance_m)


def compose_budget(geometry, frequency_hz, power, receiver_gain_dbi, losses, threshold):
    fspl = free_space_loss_db(geometry["slant_range_m"], frequency_hz)
    components = [LossComponent("fspl", Quantity(fspl, "dB", QuantityStatus.KNOWN,
                                               "free_space_formula"), ("free_space",), "fspl-v1")]
    for name, loss in losses.items():
        components.append(LossComponent(name, Quantity(loss["value"], "dB", QuantityStatus(loss["status"]),
                                                       loss["reason"]), (name,), "declared-scalar-v1"))
    eirp = power["eirp_dbm"] if power["mode"] == "eirp" else power["transmit_power_dbm"] + power["transmit_gain_dbi"]
    received = compose_received_power(eirp, receiver_gain_dbi, tuple(components))
    if not geometry["geometrically_above_local_horizontal"]:
        received = Quantity(None, "dBm", QuantityStatus.NOT_APPLICABLE, "not_above_local_horizontal")
    margin = Quantity(None, "dB", QuantityStatus.NOT_COMPUTED, "threshold_or_received_power_unavailable")
    if threshold is not None and received.status is QuantityStatus.KNOWN:
        margin = Quantity(received.value - threshold["received_power_dbm"], "dB", QuantityStatus.KNOWN,
                          "received_power_minus_declared_threshold")
    return {"eirp_dbm": eirp, "receiver_gain_dbi": receiver_gain_dbi,
            "components": [asdict(c) for c in components], "received_power": received.to_mapping(),
            "threshold": threshold, "margin": margin.to_mapping(), "service_eligibility": "unknown"}
