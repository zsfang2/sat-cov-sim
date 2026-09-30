"""WGS-84 antenna coordinates and ECEF -> local ENU (metres).

The up axis is the ellipsoid normal, not the geocentric radial direction.
Formula reference: ESA Navipedia, Transformations between ECEF and ENU coordinates.
"""

import math

from .local import relative_enu_geometry


def finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def antenna_position(spec):
    """Explicit antenna ellipsoid height OR H_ground + N_geoid + h_AGL.

    Orthometric conversion requires the caller to supply a geoid undulation
    consistent with the ground vertical datum; no DEM inference is performed.
    """
    if not isinstance(spec, dict):
        raise ValueError("receiver must be a mapping")
    common = {"lon_deg", "lat_deg", "height_basis", "basis"}
    mode = spec.get("height_basis")
    fields = ({"antenna_ellipsoid_height_m"} if mode == "ellipsoid" else
              {"ground_orthometric_height_m", "geoid_undulation_m", "antenna_agl_m", "vertical_datum"})
    if mode not in ("ellipsoid", "orthometric_plus_geoid") or set(spec) != common | fields:
        raise ValueError("explicit height basis and matching height fields are required")
    for key in {"basis"} | ({"vertical_datum"} if mode != "ellipsoid" else set()):
        if not isinstance(spec[key], str) or not spec[key].strip():
            raise ValueError(f"{key} must identify the source or declared assumption")
    lon, lat = (finite_number(spec[k], k) for k in ("lon_deg", "lat_deg"))
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError("longitude/latitude outside valid range")
    if mode == "ellipsoid":
        height = finite_number(spec["antenna_ellipsoid_height_m"], "antenna height")
    else:
        values = [finite_number(spec[k], k) for k in
                  ("ground_orthometric_height_m", "geoid_undulation_m", "antenna_agl_m")]
        if values[2] < 0:
            raise ValueError("antenna AGL must be nonnegative")
        height = math.fsum(values)
    if not -1000 <= height <= 10000:
        raise ValueError("ground-terminal ellipsoid height must be in [-1000, 10000] m")
    return {"lon_deg": lon, "lat_deg": lat, "antenna_ellipsoid_height_m": height,
            "height_input": dict(spec), "crs": "WGS84"}


def ecef_and_basis(receiver):
    lon, lat = map(math.radians, (receiver["lon_deg"], receiver["lat_deg"]))
    height = receiver["antenna_ellipsoid_height_m"]
    sl, cl, sp, cp = math.sin(lon), math.cos(lon), math.sin(lat), math.cos(lat)
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    n = a / math.sqrt(1 - e2 * sp * sp)
    position = ((n + height) * cp * cl, (n + height) * cp * sl, (n * (1 - e2) + height) * sp)
    basis = ((-sl, cl, 0.0), (-sp * cl, -sp * sl, cp), (cp * cl, cp * sl, sp))
    return position, basis


def ecef_geometry(receiver, satellite_ecef_m):
    if len(satellite_ecef_m) != 3:
        raise ValueError("satellite ECEF must have three coordinates")
    satellite = [finite_number(v, "satellite ECEF") for v in satellite_ecef_m]
    position, basis = ecef_and_basis(receiver)
    delta = [s - r for s, r in zip(satellite, position)]
    enu = [math.fsum(v * d for v, d in zip(axis, delta)) for axis in basis]
    # Coordinate subtraction/rotation at Earth radius introduces nanometre noise.
    # Resolve a numerically vertical ray explicitly instead of inventing azimuth.
    if math.hypot(*enu[:2]) <= 1e-8:
        enu[:2] = [0.0, 0.0]
    if abs(enu[2]) <= 1e-8:
        enu[2] = 0.0
    geometry = relative_enu_geometry(enu)
    return {**geometry, "satellite_relative_enu_m": enu,
            "receiver_ecef_m": list(position), "satellite_ecef_m": satellite,
            "ecef_frame": "ITRS/WGS84; no tectonic epoch correction",
            "coordinate_zero_tolerance_m": 1e-8}
