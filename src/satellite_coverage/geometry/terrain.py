"""Local metric DEM profiles and sampled horizon, with explicit coverage gaps.

Coordinates are local east/north metres; raster rows run southward. Elevations
must already be in metres in one declared vertical datum. This module never
infers that contract from unverified GeoTIFF values.
"""

from dataclasses import dataclass
import math

import numpy as np

from .geodetic import finite_number


@dataclass(frozen=True)
class TerrainGrid:
    elevations_m: np.ndarray
    west_m: float
    north_m: float
    resolution_m: float
    vertical_datum: str
    source_id: str
    curvature_applied: bool = False
    surface_type: str = "unspecified"

    def __post_init__(self):
        array = np.array(self.elevations_m, dtype=np.float64, copy=True)
        if array.ndim != 2 or min(array.shape) < 1 or np.isinf(array).any():
            raise ValueError("terrain must be a nonempty 2D grid; nodata must be NaN, not infinity")
        for key in ("west_m", "north_m", "resolution_m"):
            finite_number(getattr(self, key), key)
        if self.resolution_m <= 0:
            raise ValueError("resolution_m must be positive")
        for key in ("vertical_datum", "source_id"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip() or value.lower() == "unknown":
                raise ValueError(f"{key} must be explicitly declared")
        if type(self.curvature_applied) is not bool:
            raise ValueError("curvature_applied must be boolean")
        if self.surface_type not in ("unspecified", "DSM", "DTM", "synthetic"):
            raise ValueError("invalid surface type")
        # Immutable bytes backing prevents re-enabling ndarray write access.
        frozen = np.frombuffer(array.tobytes(), dtype=np.float64).reshape(array.shape)
        object.__setattr__(self, "elevations_m", frozen)

    def sample(self, east_m, north_m):
        finite_number(east_m, "east_m")
        finite_number(north_m, "north_m")
        col = math.floor((east_m-self.west_m)/self.resolution_m)
        row = math.floor((self.north_m-north_m)/self.resolution_m)
        if not 0 <= row < self.elevations_m.shape[0] or not 0 <= col < self.elevations_m.shape[1]:
            return None, "outside_dem"
        value = float(self.elevations_m[row, col])
        return (value, "known") if math.isfinite(value) else (None, "nodata")


def terrain_profile(grid, *, receiver_east_m, receiver_north_m, antenna_agl_m,
                    azimuth_deg, radius_m, step_m, effective_radius_m=None):
    """Nearest-cell ray sampling. Completeness is relative to the requested radius.

    Optional curvature subtracts d²/(2 R_eff) once from terrain elevations.
    R_eff is an explicit independent assumption, e.g. k times an Earth radius.
    Samples closer than native resolution do not improve source resolution.
    """
    for name, value in locals().copy().items():
        if name not in ("grid", "effective_radius_m"):
            finite_number(value, name)
    if antenna_agl_m < 0 or not 0 <= azimuth_deg < 360:
        raise ValueError("require nonnegative AGL and azimuth in [0,360)")
    if not 0 < step_m <= radius_m <= 100000 or math.ceil(radius_m/step_m) > 100000:
        raise ValueError("require 0 < step <= radius <= 100 km and <= 100000 profile samples")
    if grid.curvature_applied:
        raise ValueError("profile requires raw elevations; pre-applied curvature is unsupported")
    if effective_radius_m is not None:
        finite_number(effective_radius_m, "effective_radius_m")
        if effective_radius_m < 1e6:
            raise ValueError("effective radius must be >= 1000 km for local quadratic approximation")
    ground, ground_status = grid.sample(receiver_east_m, receiver_north_m)
    antenna = None if ground is None else ground+antenna_agl_m
    if antenna is not None and not math.isfinite(antenna):
        raise ValueError("terrain antenna height outside finite numerical range")
    az = math.radians(azimuth_deg)
    count = math.ceil(radius_m/step_m)
    distances = sorted(set(min(i*step_m, radius_m) for i in range(1, count+1)))
    samples = []
    for distance in distances:
        elevation, status = grid.sample(receiver_east_m+distance*math.sin(az),
                                        receiver_north_m+distance*math.cos(az))
        drop = 0.0 if effective_radius_m is None else distance**2/(2*effective_radius_m)
        relative = None if elevation is None or antenna is None else elevation-antenna-drop
        if relative is not None and not math.isfinite(relative):
            raise ValueError("terrain relative height outside finite numerical range")
        samples.append({"distance_m": distance, "elevation_m": elevation, "status": status,
                        "curvature_drop_m": drop, "relative_height_m": relative,
                        "angle_deg": None if relative is None else math.degrees(math.atan2(relative, distance))})
    known = [s for s in samples if s["angle_deg"] is not None]
    limiting = max(known, key=lambda s: s["angle_deg"]) if known else None
    reasons = sorted({s["status"] for s in samples if s["status"] != "known"})
    if ground_status != "known":
        reasons.append("receiver_"+ground_status)
    if step_m > grid.resolution_m:
        reasons.append("step_exceeds_native_resolution")
    return {"schema_version": 1, "azimuth_deg": azimuth_deg, "radius_m": radius_m, "step_m": step_m,
            "native_resolution_m": grid.resolution_m, "sampling": "nearest_cell; sampled rays, not continuous terrain guarantee",
            "source_id": grid.source_id, "vertical_datum": grid.vertical_datum,
            "surface_type": grid.surface_type,
            "height_reference": "height above raster surface; DSM surface is not bare ground",
            "receiver_ground_m": ground, "antenna_agl_m": antenna_agl_m,
            "effective_radius_m": effective_radius_m, "curvature_model": "none" if effective_radius_m is None else "local_d2_over_2R",
            "coverage_complete": not reasons, "incomplete_reasons": reasons,
            "horizon_deg": limiting["angle_deg"] if limiting else None,
            "limiting_distance_m": limiting["distance_m"] if limiting else None,
            "horizon_status": "known_within_radius" if not reasons else "lower_bound_or_unknown",
            "radius_sufficiency": "not_verified_beyond_requested_radius",
            "sampling_convergence": "not_verified; step <= cell size is not a convergence certificate",
            "samples": samples}


def horizon_profile(grid, azimuths_deg, **options):
    if not azimuths_deg or len(azimuths_deg) > 720:
        raise ValueError("require 1..720 azimuths")
    return [terrain_profile(grid, azimuth_deg=az, **options) for az in azimuths_deg]
