"""Strict, independent configuration for an analytic scalar link experiment."""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from ..domain.link_record import Quantity, QuantityStatus
from ..geometry.local import relative_enu_geometry


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def identity(value):
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def exact_keys(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{name} requires exactly these fields: {', '.join(sorted(keys))}")


def text_field(value, name):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty trimmed text")


def number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if positive and value <= 0 or nonnegative and value < 0:
        raise ValueError(f"{name} is outside its allowed range")
    return float(value)


def validate_scalar_budget(data):
    """Validate and normalize the common scalar budget fields in a mapping."""
    data["frequency_hz"] = number(data["frequency_hz"], "frequency_hz", positive=True)
    data["receiver_gain_dbi"] = number(data["receiver_gain_dbi"], "receiver_gain_dbi")
    power = data["power"]
    if not isinstance(power, dict):
        raise ValueError("power must be a mapping")
    if power.get("mode") == "eirp":
        exact_keys(power, {"mode", "eirp_dbm"}, "power")
    elif power.get("mode") == "transmit_power_gain":
        exact_keys(power, {"mode", "transmit_power_dbm", "transmit_gain_dbi"}, "power")
    else:
        raise ValueError("power.mode must be eirp or transmit_power_gain")
    for k in power.keys() - {"mode"}:
        power[k] = number(power[k], k)
    exact_keys(data["losses"], {"atmosphere", "local", "misc"}, "losses")
    for name, loss in data["losses"].items():
        exact_keys(loss, {"value", "status", "reason"}, name)
        text_field(loss["reason"], f"{name}.reason")
        if loss["value"] is not None:
            loss["value"] = number(loss["value"], name)
        Quantity(loss["value"], "dB", QuantityStatus(loss["status"]), loss["reason"])
    threshold = data["threshold"]
    if threshold is not None:
        exact_keys(threshold, {"received_power_dbm", "basis"}, "threshold")
        threshold["received_power_dbm"] = number(threshold["received_power_dbm"], "threshold")
        text_field(threshold["basis"], "threshold.basis")


@dataclass(frozen=True)
class PilotConfig:
    """Immutable canonical snapshot; callers receive independent mappings."""

    serialized: bytes

    def __post_init__(self):
        if not isinstance(self.serialized, bytes):
            raise ValueError("configuration must contain canonical JSON bytes")
        data = json.loads(self.serialized)
        self._validate(data)
        object.__setattr__(self, "serialized", canonical_bytes(data))

    @staticmethod
    def _validate(data):
        exact_keys(data, {"schema_version", "sample_id", "seed", "environment_id", "solver_version",
                          "receiver", "satellite_relative_enu_m", "frequency_hz", "power", "receiver_gain_dbi",
                          "losses", "threshold", "task", "audit_spec"}, "pilot")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError("schema_version must be 1")
        if type(data["seed"]) is not int or data["seed"] < 0:
            raise ValueError("seed must be a nonnegative integer")
        for name in ("sample_id", "environment_id", "solver_version"):
            text_field(data[name], name)
        if data["solver_version"] != "analytic-scalar-v1":
            raise ValueError("unsupported solver_version")
        if data["audit_spec"] is not None:
            text_field(data["audit_spec"], "audit_spec")
        exact_keys(data["receiver"], {"position_id", "height_agl_m"}, "receiver")
        text_field(data["receiver"]["position_id"], "position_id")
        data["receiver"]["height_agl_m"] = number(data["receiver"]["height_agl_m"], "height_agl_m", nonnegative=True)
        xyz = data["satellite_relative_enu_m"]
        if not isinstance(xyz, list) or len(xyz) != 3:
            raise ValueError("satellite_relative_enu_m must be a list of three numbers")
        data["satellite_relative_enu_m"] = [number(v, "ENU position") for v in xyz]
        relative_enu_geometry(data["satellite_relative_enu_m"])
        validate_scalar_budget(data)
        task = data["task"]
        exact_keys(task, {"objective", "candidate_cost", "minimum_useful_gain", "max_compute_budget", "allowed_event_error"}, "task")
        if task["objective"] != "cumulative_conditional_insufficiency_s" or task["candidate_cost"] != "equal":
            raise ValueError("pilot task requires equal cost and conditional insufficiency objective")
        for name in ("minimum_useful_gain", "max_compute_budget", "allowed_event_error"):
            if task[name] != "undetermined":
                raise ValueError(f"{name} remains undetermined in the pilot contract")

    @classmethod
    def from_mapping(cls, data):
        return cls(canonical_bytes(data))

    def to_mapping(self):
        return json.loads(self.serialized)

    def checksum_sha256(self):
        return "sha256:" + hashlib.sha256(self.serialized).hexdigest()


def load_pilot_config(path):
    import yaml
    return PilotConfig.from_mapping(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
