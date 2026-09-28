"""Analytic receiver-relative ENU geometry; no orbit or Earth model implied."""

import math


def relative_enu_geometry(satellite_relative_enu_m):
    if len(satellite_relative_enu_m) != 3:
        raise ValueError("relative ENU position must contain east, north, up")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in satellite_relative_enu_m):
        raise ValueError("relative ENU position must be finite")
    east, north, up = satellite_relative_enu_m
    distance = math.hypot(east, north, up)
    if distance <= 0 or not math.isfinite(distance):
        raise ValueError("slant range must be finite and positive")
    horizontal = math.hypot(east, north)
    return {
        "slant_range_m": distance,
        "azimuth_deg": math.degrees(math.atan2(east, north)) % 360 if horizontal else None,
        "azimuth_status": "known" if horizontal else "not_applicable",
        "elevation_deg": math.degrees(math.atan2(up, horizontal)),
        "coordinate_system": "RECEIVER_RELATIVE_ENU",
        "azimuth_convention": "north_clockwise",
        "geometrically_above_local_horizontal": up > 0,
        "terrain_visibility": "not_computed",
    }
