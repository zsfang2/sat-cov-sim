"""Immutable region-grid identity and coordinate metadata."""

from __future__ import annotations

from dataclasses import dataclass
import math

from pyproj import CRS
from pyproj.exceptions import CRSError

from .units import DomainStateError, WGS84_GEODETIC_CRS


@dataclass(frozen=True)
class RegionGrid:
    """Raster shape and pixel-center transform for one projected region."""

    region_id: str
    height_px: int
    width_px: int
    resolution_m: float
    geodetic_crs: str
    projected_crs: str
    vertical_crs: str
    pixel_center_affine: tuple[float, float, float, float, float, float]

    def __post_init__(self) -> None:
        _require_text("region_id", self.region_id)
        _require_positive_int("height_px", self.height_px)
        _require_positive_int("width_px", self.width_px)
        _require_positive_real("resolution_m", self.resolution_m)
        _require_text("vertical_crs", self.vertical_crs)

        geodetic = _parse_crs("geodetic_crs", self.geodetic_crs)
        if not geodetic.equals(CRS.from_epsg(4326)):
            raise DomainStateError("geodetic_crs must identify WGS-84")
        projected = _parse_crs("projected_crs", self.projected_crs)
        if not projected.is_projected:
            raise DomainStateError("projected_crs must use projected coordinates")

        if (
            not isinstance(self.pixel_center_affine, tuple)
            or len(self.pixel_center_affine) != 6
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                for value in self.pixel_center_affine
            )
        ):
            raise DomainStateError(
                "pixel_center_affine must contain six finite coefficients"
            )

        object.__setattr__(self, "resolution_m", float(self.resolution_m))
        object.__setattr__(self, "geodetic_crs", WGS84_GEODETIC_CRS)
        object.__setattr__(self, "projected_crs", projected.to_string())
        object.__setattr__(
            self,
            "pixel_center_affine",
            tuple(float(value) for value in self.pixel_center_affine),
        )

    @property
    def shape(self) -> tuple[int, int]:
        return self.height_px, self.width_px

    @property
    def grid_coordinate_system(self) -> str:
        return f"REGION_GRID:{self.region_id}:{self.projected_crs}"


def _parse_crs(name: str, value: object) -> CRS:
    if not isinstance(value, str):
        raise DomainStateError(f"{name} must be a CRS string")
    try:
        return CRS.from_user_input(value)
    except (CRSError, ValueError) as exc:
        raise DomainStateError(f"{name} is invalid") from exc


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DomainStateError(f"{name} must be non-empty and trimmed")


def _require_positive_int(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise DomainStateError(f"{name} must be a positive integer")


def _require_positive_real(name: str, value: object) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise DomainStateError(f"{name} must be a positive finite number")
