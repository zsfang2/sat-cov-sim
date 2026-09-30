"""Bound an M3 grid to one M1 receiver; never add two local-loss models."""

from dataclasses import dataclass
import hashlib

from ..config.pilot import number
from ..geometry.terrain import TerrainGrid, terrain_profile
from ..geometry.cell_horizon import cell_horizon
from .terrain_link import evaluate_profile


@dataclass(frozen=True)
class TerrainContext:
    grid: TerrainGrid
    lon_deg: float
    lat_deg: float
    radius_m: float
    step_m: float
    effective_radius_m: float | None = None
    loss_cap_db: float = 60.0
    horizon_tolerance_deg: float | None = None

    def __post_init__(self):
        if self.grid.vertical_datum != "WGS84_ellipsoid":
            raise ValueError("M1 integration requires terrain in WGS84 ellipsoid heights")
        for key in ("lon_deg", "lat_deg", "loss_cap_db"):
            number(getattr(self, key), key)
        if not -180 <= self.lon_deg <= 180 or not -89.9 <= self.lat_deg <= 89.9 or self.loss_cap_db < 0:
            raise ValueError("invalid terrain origin or loss cap")
        if self.horizon_tolerance_deg is not None:
            number(self.horizon_tolerance_deg,"horizon_tolerance_deg",nonnegative=True)
        # Validate profile parameters even if every link is below the horizon.
        terrain_profile(self.grid, receiver_east_m=0, receiver_north_m=0, antenna_agl_m=0,
                        azimuth_deg=0, radius_m=self.radius_m, step_m=self.step_m,
                        effective_radius_m=self.effective_radius_m)

    def descriptor(self):
        return {"solver": "local-dominant-knife-edge-v1", "source_id": self.grid.source_id,
                "grid_sha256": hashlib.sha256(self.grid.elevations_m.tobytes()).hexdigest(),
                "grid_geometry": [self.grid.west_m, self.grid.north_m, self.grid.resolution_m, *self.grid.elevations_m.shape],
                "lon_deg": self.lon_deg, "lat_deg": self.lat_deg, "radius_m": self.radius_m,
                "step_m": self.step_m, "effective_radius_m": self.effective_radius_m,
                "loss_cap_db": self.loss_cap_db, "vertical_datum": self.grid.vertical_datum,
                "surface_type": self.grid.surface_type,"horizon_tolerance_deg":self.horizon_tolerance_deg}

    def validate_receiver(self, receiver):
        if abs(receiver["lon_deg"]-self.lon_deg) > 1e-10 or abs(receiver["lat_deg"]-self.lat_deg) > 1e-10:
            raise ValueError("terrain grid origin does not match M1 receiver")
        ground, _ = self.grid.sample(0, 0)
        if ground is not None and receiver["antenna_ellipsoid_height_m"] < ground:
            raise ValueError("M1 antenna is below DEM ground; check height datum")

    def evaluate(self, geometry, receiver):
        ground, _ = self.grid.sample(0, 0)
        agl = 0 if ground is None else receiver["antenna_ellipsoid_height_m"]-ground
        if not geometry["geometrically_above_local_horizontal"]:
            return {"loss_status": "not_computed", "used_loss_db": None, "los_status": "not_applicable",
                    "coverage_complete": False, "reason": "not_above_local_horizontal"}
        if geometry["azimuth_deg"] is None:
            return {"loss_status": "not_computed", "used_loss_db": None, "los_status": "unknown",
                    "coverage_complete": False, "reason": "zenith_profile_not_supported"}
        profile = terrain_profile(self.grid, receiver_east_m=0, receiver_north_m=0, antenna_agl_m=agl,
                                  azimuth_deg=geometry["azimuth_deg"], radius_m=self.radius_m,
                                  step_m=self.step_m, effective_radius_m=self.effective_radius_m)
        result = evaluate_profile(profile, elevation_deg=geometry["elevation_deg"],
                                  slant_range_m=geometry["slant_range_m"], frequency_hz=geometry["frequency_hz"],
                                  loss_cap_db=self.loss_cap_db)
        result["profile"] = profile
        if self.horizon_tolerance_deg is not None:
            reference = cell_horizon(self.grid,receiver_east_m=0,receiver_north_m=0,antenna_agl_m=agl,
                                     azimuth_deg=geometry["azimuth_deg"],radius_m=self.radius_m,
                                     effective_radius_m=self.effective_radius_m)
            error = (abs(profile["horizon_deg"]-reference["horizon_deg"])
                     if profile["horizon_deg"] is not None and reference["horizon_deg"] is not None else None)
            passed = (profile["coverage_complete"] and reference["coverage_complete"]
                      and error is not None and error <= self.horizon_tolerance_deg)
            result["sampling_audit"] = {"cell_horizon":reference,"horizon_error_deg":error,
                                        "tolerance_deg":self.horizon_tolerance_deg,"passed":passed,
                                        "scope":"horizon diagnostic only; passing does not certify loss accuracy or radius sufficiency"}
            if not passed:
                result["diagnostic_sampled_loss_db"] = result["raw_loss_db"]
                result.update(raw_loss_db=None,used_loss_db=None,loss_status="not_computed",coverage_complete=False,
                              cap_triggered=False)
                result["incomplete_reasons"].append("horizon_sampling_tolerance_not_met")
                if result["los_status"] != "blocked":
                    result["los_status"] = "unknown"
        return result
