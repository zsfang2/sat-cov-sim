"""Immutable M1 experiment contract shared by three geometry input modes."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
import json
import math

from .pilot import canonical_bytes, exact_keys, identity, number, text_field, validate_scalar_budget
from ..geometry.antenna import validate_antenna
from ..geometry.geodetic import antenna_position
from ..geometry.local import relative_enu_geometry, direction_to_enu
from ..orbit.visibility import utc


def sample_times(data):
    start, end = utc(data["start"]), utc(data["end"])
    duration = (end - start).total_seconds()
    step = number(data["step_s"], "step_s", positive=True)
    if step < 0.001 or not 0 < duration <= 7*86400:
        raise ValueError("require step >= 0.001 s, interval in (0, 7 days], <= 10001 samples")
    if step >= duration:
        return [start, end]
    step_us, duration_us = round(step*1e6), round(duration*1e6)
    if not math.isclose(step_us/1e6, step, rel_tol=0, abs_tol=1e-12):
        raise ValueError("step_s must be representable as whole microseconds")
    if (duration_us + step_us-1)//step_us + 1 > 10001:
        raise ValueError("maximum 10001 samples")
    # Integer ticks avoid duplicate end samples from floating-point ceil errors.
    return [start + timedelta(microseconds=i) for i in range(0, duration_us, step_us)] + [end]


def enabled_losses(losses):
    exact_keys(losses, {"atmosphere", "local", "misc"}, "losses")
    normalized = {}
    for name, spec in losses.items():
        if not isinstance(spec, dict) or type(spec.get("enabled")) is not bool:
            raise ValueError(f"{name}.enabled must be boolean")
        fields = {"enabled", "reason"} | ({"value", "status"} if spec["enabled"] else set())
        exact_keys(spec, fields, name)
        text_field(spec["reason"], name + ".reason")
        normalized[name] = ({k: spec[k] for k in ("value", "status", "reason")} if spec["enabled"] else
                            {"value": 0.0, "status": "known", "reason": "disabled_by_config: " + spec["reason"]})
    return normalized


@dataclass(frozen=True)
class LinkConfig:
    serialized: bytes

    def __post_init__(self):
        if not isinstance(self.serialized, bytes):
            raise ValueError("configuration must contain JSON bytes")
        data = json.loads(self.serialized)
        exact_keys(data, {"schema_version", "experiment_id", "start", "end", "step_s", "receiver", "source", "budget"}, "M1 link")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError("schema_version must be 1")
        text_field(data["experiment_id"], "experiment_id")
        times = sample_times(data)
        antenna_position(data["receiver"])
        source = data["source"]
        if not isinstance(source, dict):
            raise ValueError("source must be a mapping")
        mode = source.get("mode")
        if mode == "tle":
            exact_keys(source, {"mode", "candidate_id", "norad_id", "tle_policy", "max_age_days"}, "TLE source")
            if not isinstance(source["norad_id"], str) or not source["norad_id"].isdigit():
                raise ValueError("norad_id must be a numeric string")
            if source["tle_policy"] not in ("past_only", "historical_exploration"):
                raise ValueError("invalid tle_policy")
            if not 0 < number(source["max_age_days"], "max_age_days") <= 30:
                raise ValueError("max_age_days must be in (0, 30]")
        elif mode == "fixed_ecef":
            exact_keys(source, {"mode", "candidate_id", "position_ecef_m"}, "fixed ECEF source")
            vector = source["position_ecef_m"]
            if not isinstance(vector, list) or len(vector) != 3:
                raise ValueError("position_ecef_m must have three coordinates")
            for v in vector:
                number(v, "position_ecef_m")
        elif mode == "direction_sequence":
            exact_keys(source, {"mode", "candidate_id", "directions"}, "direction sequence source")
            directions = source["directions"]
            if not isinstance(directions, list) or len(directions) != len(times):
                raise ValueError("directions must contain one direction per timestamp")
            for direction in directions:
                exact_keys(direction, {"azimuth_deg", "elevation_deg", "slant_range_m"}, "direction")
                direction_to_enu(**direction)
        elif mode == "relative_enu_sequence":
            exact_keys(source, {"mode", "candidate_id", "positions_enu_m"}, "ENU sequence source")
            vectors = source["positions_enu_m"]
            if not isinstance(vectors, list) or len(vectors) != len(times):
                raise ValueError("positions_enu_m must contain one position per timestamp")
            for vector in vectors:
                if not isinstance(vector, list):
                    raise ValueError("each ENU position must be a list")
                relative_enu_geometry(vector)
        else:
            raise ValueError("source mode must be tle, fixed_ecef, direction_sequence or relative_enu_sequence")
        text_field(source["candidate_id"], "candidate_id")
        budget = data["budget"]
        exact_keys(budget, {"frequency_hz", "power", "receiver_antenna", "losses", "threshold", "assumption_basis"}, "budget")
        text_field(budget["assumption_basis"], "assumption_basis")
        validate_antenna(budget["receiver_antenna"])
        scalar = {k: deepcopy(budget[k]) for k in ("frequency_hz", "power", "threshold")}
        scalar.update(receiver_gain_dbi=0.0, losses=enabled_losses(budget["losses"]))
        validate_scalar_budget(scalar)
        # Positive loss convention: gains belong in the power/antenna fields.
        if any(v["value"] is not None and v["value"] < 0 for v in scalar["losses"].values()):
            raise ValueError("loss components must be nonnegative; declare gains separately")
        object.__setattr__(self, "serialized", canonical_bytes(data))

    @classmethod
    def from_mapping(cls, data):
        return cls(canonical_bytes(data))

    def to_mapping(self):
        return json.loads(self.serialized)

    @property
    def checksum(self):
        return identity(self.to_mapping())
