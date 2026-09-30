"""LOS and a local dominant knife-edge baseline; not a multi-edge solver."""

import math

from ..geometry.geodetic import finite_number


def evaluate_profile(profile, *, elevation_deg, slant_range_m, frequency_hz, loss_cap_db=60.0):
    for name, value in (("elevation_deg", elevation_deg), ("slant_range_m", slant_range_m),
                        ("frequency_hz", frequency_hz), ("loss_cap_db", loss_cap_db)):
        finite_number(value, name)
    if not 0 <= elevation_deg < 90 or min(slant_range_m, frequency_hz) <= 0 or loss_cap_db < 0:
        raise ValueError("require elevation in [0,90), positive range/frequency and nonnegative cap")
    el = math.radians(elevation_deg)
    horizontal_range = slant_range_m*math.cos(el)
    usable = [s for s in profile["samples"] if s["distance_m"] < horizontal_range]
    reasons = list(profile["incomplete_reasons"])
    if horizontal_range <= profile["radius_m"]:
        reasons.append("satellite_within_profile_radius; shorten_profile")
    if not usable:
        reasons.append("no_interior_samples")
    detailed = []
    wavelength = 299792458.0/frequency_hz
    for sample in usable:
        relative = sample["relative_height_m"]
        if relative is None:
            continue
        x = sample["distance_m"]
        # Projection onto the direct ray, and perpendicular signed height.
        d1 = x*math.cos(el)+relative*math.sin(el)
        h = relative*math.cos(el)-x*math.sin(el)
        if not 0 < d1 < slant_range_m:
            reasons.append("obstacle_projection_outside_link")
            continue
        d2 = slant_range_m-d1
        fresnel = math.sqrt(wavelength*d1*d2/slant_range_m)
        v = math.sqrt(2)*h/fresnel
        # ITU-R P.526 single ideal knife-edge approximation. Signed clearance
        # matters: geometric LOS alone does not imply zero diffraction loss.
        raw = 0.0 if v <= -.78 else max(0.0, 6.9 + 20/math.log(10)*math.asinh(v-.1))
        detailed.append({"distance_m": x, "clearance_m": -h,
                         "first_fresnel_radius_m": fresnel, "fresnel_v": v, "raw_loss_db": raw})
    dominant = max(detailed, key=lambda s: s["raw_loss_db"]) if detailed else None
    blocked = any(s["clearance_m"] < -1e-8 for s in detailed)
    complete = not reasons
    raw_loss = dominant["raw_loss_db"] if dominant else None
    return {"los_status": "blocked" if blocked else ("clear_within_radius" if complete else "unknown"),
            "coverage_complete": complete, "incomplete_reasons": sorted(set(reasons)),
            "radius_m": profile["radius_m"], "truncated_before_satellite": horizontal_range > profile["radius_m"],
            "scope": "sampled local terrain only; LOS is not Fresnel clearance; single ideal edge approximation",
            "solver": "local-dominant-knife-edge-v1", "raw_loss_db": raw_loss if complete else None,
            "used_loss_db": min(raw_loss, loss_cap_db) if complete and raw_loss is not None else None,
            "loss_status": "known" if complete and raw_loss is not None else "not_computed",
            "loss_cap_db": loss_cap_db, "cap_triggered": bool(complete and raw_loss is not None and raw_loss > loss_cap_db),
            "dominant_edge": dominant, "samples": detailed}
