"""Declared receive antenna patterns, evaluated along receiver-to-satellite ENU."""

import math

from ..config.pilot import exact_keys, number, text_field


def validate_antenna(spec):
    if not isinstance(spec, dict):
        raise ValueError("receiver_antenna must be a mapping")
    model = spec.get("model")
    if model == "isotropic":
        exact_keys(spec, {"model", "gain_dbi", "basis"}, "isotropic antenna")
        number(spec["gain_dbi"], "gain_dbi")
    elif model == "cosine":
        exact_keys(spec, {"model", "peak_gain_dbi", "floor_gain_dbi", "exponent", "boresight_enu", "basis"}, "cosine antenna")
        peak = number(spec["peak_gain_dbi"], "peak_gain_dbi")
        floor = number(spec["floor_gain_dbi"], "floor_gain_dbi")
        number(spec["exponent"], "exponent", positive=True)
        vector = spec["boresight_enu"]
        if not isinstance(vector, list) or len(vector) != 3:
            raise ValueError("boresight_enu must be a three-number vector")
        norm = math.hypot(*(number(v, "boresight_enu") for v in vector))
        if not 0 < norm < math.inf or floor > peak:
            raise ValueError("nonzero finite boresight and floor <= peak are required")
    else:
        raise ValueError("receiver antenna model must be isotropic or cosine")
    text_field(spec["basis"], "receiver_antenna.basis")


def receive_gain(spec, enu):
    validate_antenna(spec)
    if spec["model"] == "isotropic":
        return {"gain_dbi": spec["gain_dbi"], "off_axis_deg": None,
                "model": "isotropic", "basis": spec["basis"]}
    norm, axis_norm = math.hypot(*enu), math.hypot(*spec["boresight_enu"])
    cosine = max(-1.0, min(1.0, math.fsum((a / norm) * (b / axis_norm)
                                          for a, b in zip(enu, spec["boresight_enu"]))))
    gain = spec["floor_gain_dbi"]
    if cosine > 0:
        gain = max(gain, spec["peak_gain_dbi"] + 10 * spec["exponent"] * math.log10(cosine))
    return {"gain_dbi": gain, "off_axis_deg": math.degrees(math.acos(cosine)),
            "model": "cosine", "basis": spec["basis"],
            "formula": "max(floor, peak + 10*exponent*log10(cos(theta))); rear hemisphere=floor",
            "axis": "fixed receiver ENU; direction from antenna to satellite"}
