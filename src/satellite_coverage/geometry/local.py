"""Analytic receiver-relative ENU geometry; no orbit or Earth model implied."""

import math


def direction_to_enu(azimuth_deg, elevation_deg, slant_range_m):
    for value in (azimuth_deg, elevation_deg, slant_range_m):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("direction angles/range must be finite numbers")
    if not 0 <= azimuth_deg < 360 or not -90 <= elevation_deg <= 90 or slant_range_m <= 0:
        raise ValueError("require azimuth in [0,360), elevation in [-90,90], positive range")
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    horizontal = 0.0 if abs(elevation_deg) == 90 else slant_range_m * math.cos(el)
    return [horizontal * math.sin(az), horizontal * math.cos(az), slant_range_m * math.sin(el)]


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
