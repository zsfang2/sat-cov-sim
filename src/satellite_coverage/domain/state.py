"""Immutable physical state exchanged across simulation boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import math

import numpy as np

from .arrays import DomainArray
from .grid import RegionGrid
from .units import (
    ArrayUnit,
    DomainStateError,
    WGS84_ECEF_CRS,
    WGS84_GEODETIC_CRS,
)


_FLOAT_DTYPES = (np.dtype("float32"), np.dtype("float64"))


@dataclass(frozen=True)
class SourceProvenance:
    """Storage-neutral identity for one immutable source version."""

    source_id: str
    source_kind: str
    version: str
    checksum: str

    def __post_init__(self) -> None:
        for name in ("source_id", "source_kind", "version", "checksum"):
            _require_text(name, getattr(self, name))


@dataclass(frozen=True)
class RegionStaticState:
    """Region arrays that must be built once and reused across frames."""

    grid: RegionGrid
    latitude_deg: DomainArray
    longitude_deg: DomainArray
    elevation_m: DomainArray
    ground_ecef_m: DomainArray
    ecef_to_enu_basis: DomainArray
    static_clutter_loss_db: DomainArray
    source_provenance: tuple[SourceProvenance, ...]

    def __post_init__(self) -> None:
        _require_grid(self.grid)
        grid_shape = self.grid.shape
        _require_array(
            "latitude_deg",
            self.latitude_deg,
            shape=grid_shape,
            dtypes=(np.dtype("float64"),),
            unit=ArrayUnit.DEGREE,
            coordinate_system=WGS84_GEODETIC_CRS,
            axes=("row", "column"),
        )
        _require_array(
            "longitude_deg",
            self.longitude_deg,
            shape=grid_shape,
            dtypes=(np.dtype("float64"),),
            unit=ArrayUnit.DEGREE,
            coordinate_system=WGS84_GEODETIC_CRS,
            axes=("row", "column"),
        )
        _require_array(
            "elevation_m",
            self.elevation_m,
            shape=grid_shape,
            dtypes=(np.dtype("float64"),),
            unit=ArrayUnit.METER,
            coordinate_system=self.grid.vertical_crs,
            axes=("row", "column"),
        )
        _require_array(
            "ground_ecef_m",
            self.ground_ecef_m,
            shape=grid_shape + (3,),
            dtypes=(np.dtype("float64"),),
            unit=ArrayUnit.METER,
            coordinate_system=WGS84_ECEF_CRS,
            axes=("row", "column", "xyz"),
        )
        _require_array(
            "ecef_to_enu_basis",
            self.ecef_to_enu_basis,
            shape=grid_shape + (3, 3),
            dtypes=(np.dtype("float64"),),
            unit=ArrayUnit.DIMENSIONLESS,
            coordinate_system=f"ECEF_TO_ENU:{self.grid.region_id}",
            axes=("row", "column", "enu", "ecef"),
        )
        _require_map(
            "static_clutter_loss_db",
            self.static_clutter_loss_db,
            self.grid,
            unit=ArrayUnit.DB,
        )
        _require_provenance(self.source_provenance)


@dataclass(frozen=True)
class EnvironmentalState:
    """One timestamped realization from an independently named stream."""

    grid: RegionGrid
    timestamp_utc: datetime
    realization_id: str
    random_stream_id: str
    weather_loss_db: DomainArray

    def __post_init__(self) -> None:
        _require_grid(self.grid)
        object.__setattr__(
            self,
            "timestamp_utc",
            _normalize_utc("timestamp_utc", self.timestamp_utc),
        )
        _require_text("realization_id", self.realization_id)
        _require_text("random_stream_id", self.random_stream_id)
        _require_map(
            "weather_loss_db", self.weather_loss_db, self.grid, unit=ArrayUnit.DB
        )


@dataclass(frozen=True)
class OrbitState:
    """One satellite's Earth-fixed state and TLE provenance at a UTC instant."""

    norad_id: str
    satellite_name: str
    timestamp_utc: datetime
    position_ecef_m: DomainArray
    geodetic_altitude_m: float
    tle_epoch_utc: datetime
    tle_provenance: SourceProvenance
    sgp4_status: int

    def __post_init__(self) -> None:
        _require_text("norad_id", self.norad_id)
        _require_text("satellite_name", self.satellite_name)
        object.__setattr__(
            self,
            "timestamp_utc",
            _normalize_utc("timestamp_utc", self.timestamp_utc),
        )
        object.__setattr__(
            self,
            "tle_epoch_utc",
            _normalize_utc("tle_epoch_utc", self.tle_epoch_utc),
        )
        _require_array(
            "position_ecef_m",
            self.position_ecef_m,
            shape=(3,),
            dtypes=(np.dtype("float64"),),
            unit=ArrayUnit.METER,
            coordinate_system=WGS84_ECEF_CRS,
            axes=("xyz",),
        )
        _require_finite_real("geodetic_altitude_m", self.geodetic_altitude_m)
        object.__setattr__(
            self, "geodetic_altitude_m", float(self.geodetic_altitude_m)
        )
        if not isinstance(self.tle_provenance, SourceProvenance):
            raise DomainStateError("tle_provenance must be SourceProvenance")
        _require_nonnegative_int("sgp4_status", self.sgp4_status)


@dataclass(frozen=True)
class PixelGeometry:
    """Per-pixel WGS-84/ECEF/ENU and satellite beam geometry."""

    grid: RegionGrid
    slant_range_m: DomainArray
    elevation_deg: DomainArray
    azimuth_deg: DomainArray
    off_axis_angle_deg: DomainArray

    def __post_init__(self) -> None:
        _require_grid(self.grid)
        _require_array(
            "slant_range_m",
            self.slant_range_m,
            shape=self.grid.shape,
            dtypes=(np.dtype("float64"),),
            unit=ArrayUnit.METER,
            coordinate_system=WGS84_ECEF_CRS,
            axes=("row", "column"),
        )
        _require_array(
            "elevation_deg",
            self.elevation_deg,
            shape=self.grid.shape,
            dtypes=(np.dtype("float64"),),
            unit=ArrayUnit.DEGREE,
            coordinate_system=f"LOCAL_ENU:{self.grid.region_id}",
            axes=("row", "column"),
        )
        _require_array(
            "azimuth_deg",
            self.azimuth_deg,
            shape=self.grid.shape,
            dtypes=(np.dtype("float64"),),
            unit=ArrayUnit.DEGREE,
            coordinate_system=f"LOCAL_ENU:{self.grid.region_id}",
            axes=("row", "column"),
        )
        _require_array(
            "off_axis_angle_deg",
            self.off_axis_angle_deg,
            shape=self.grid.shape,
            dtypes=(np.dtype("float64"),),
            unit=ArrayUnit.DEGREE,
            coordinate_system="SATELLITE_BEAM_FRAME",
            axes=("row", "column"),
        )
        if np.any(self.slant_range_m.values <= 0):
            raise DomainStateError("slant_range_m values must be positive")
        _require_array_range("elevation_deg", self.elevation_deg, -90.0, 90.0)
        _require_array_range(
            "azimuth_deg", self.azimuth_deg, 0.0, 360.0, upper_inclusive=False
        )
        _require_array_range("off_axis_angle_deg", self.off_axis_angle_deg, 0.0, 180.0)


@dataclass(frozen=True)
class PhysicalState:
    """Clean received power and named component maps before persistence."""

    grid: RegionGrid
    received_power_dbm: DomainArray
    component_maps: tuple[tuple[str, DomainArray], ...]

    def __post_init__(self) -> None:
        _require_grid(self.grid)
        _require_map(
            "received_power_dbm",
            self.received_power_dbm,
            self.grid,
            unit=ArrayUnit.DBM,
        )
        if not isinstance(self.component_maps, tuple):
            raise DomainStateError("component_maps must be a tuple")
        names: set[str] = set()
        for item in self.component_maps:
            if not isinstance(item, tuple) or len(item) != 2:
                raise DomainStateError("component_maps entries must be name/value pairs")
            name, field = item
            _require_text("component name", name)
            if name in names:
                raise DomainStateError(f"duplicate component name: {name}")
            names.add(name)
            if not isinstance(field, DomainArray):
                raise DomainStateError(f"component {name} must be a DomainArray")
            allowed_dtypes = (
                (np.dtype("bool"),)
                if field.unit is ArrayUnit.BOOLEAN
                else _FLOAT_DTYPES
            )
            _require_array(
                f"component {name}",
                field,
                shape=self.grid.shape,
                dtypes=allowed_dtypes,
                unit=field.unit,
                coordinate_system=self.grid.grid_coordinate_system,
                axes=("row", "column"),
            )

    def component_for(self, name: str) -> DomainArray:
        for component_name, field in self.component_maps:
            if component_name == name:
                return field
        raise KeyError(name)


class ServiceState(str, Enum):
    """Serializable service transition semantics for a complete frame."""

    NO_SERVICE = "no_service"
    INITIAL_ACQUISITION = "initial_acquisition"
    HELD = "held"
    HANDOVER = "handover"


@dataclass(frozen=True)
class FrameState:
    """One complete region/timestamp simulation result or no-service state."""

    region_id: str
    frame_index: int
    timestamp_utc: datetime
    grid: RegionGrid
    candidate_orbits: tuple[OrbitState, ...]
    serving_orbit: OrbitState | None
    service_state: ServiceState
    geometry: PixelGeometry | None
    physical_state: PhysicalState | None

    def __post_init__(self) -> None:
        _require_text("region_id", self.region_id)
        _require_nonnegative_int("frame_index", self.frame_index)
        timestamp = _normalize_utc("timestamp_utc", self.timestamp_utc)
        object.__setattr__(self, "timestamp_utc", timestamp)
        _require_grid(self.grid)
        if self.region_id != self.grid.region_id:
            raise DomainStateError("region_id must match grid.region_id")
        if not isinstance(self.service_state, ServiceState):
            raise DomainStateError("service_state must be a ServiceState")
        if not isinstance(self.candidate_orbits, tuple) or any(
            not isinstance(orbit, OrbitState) for orbit in self.candidate_orbits
        ):
            raise DomainStateError("candidate_orbits must contain OrbitState values")
        candidate_ids = tuple(orbit.norad_id for orbit in self.candidate_orbits)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise DomainStateError("candidate_orbits must have unique NORAD IDs")
        if any(orbit.timestamp_utc != timestamp for orbit in self.candidate_orbits):
            raise DomainStateError("candidate_orbits timestamps must match frame timestamp")

        if self.service_state is ServiceState.NO_SERVICE:
            if any(
                value is not None
                for value in (self.serving_orbit, self.geometry, self.physical_state)
            ):
                raise DomainStateError(
                    "no_service frame cannot have serving geometry or physical state"
                )
            return

        if not isinstance(self.serving_orbit, OrbitState):
            raise DomainStateError("serving_orbit is required for service state")
        if not any(
            self.serving_orbit is candidate for candidate in self.candidate_orbits
        ):
            raise DomainStateError(
                "serving_orbit must be an actual state from candidate_orbits"
            )
        if self.serving_orbit.timestamp_utc != timestamp:
            raise DomainStateError("serving_orbit timestamp must match frame timestamp")
        if not isinstance(self.geometry, PixelGeometry):
            raise DomainStateError("geometry is required for service state")
        if self.geometry.grid != self.grid:
            raise DomainStateError("geometry grid must match frame grid")
        if not isinstance(self.physical_state, PhysicalState):
            raise DomainStateError("physical_state is required for service state")
        if self.physical_state.grid != self.grid:
            raise DomainStateError("physical_state grid must match frame grid")


def _require_grid(value: object) -> None:
    if not isinstance(value, RegionGrid):
        raise DomainStateError("grid must be a RegionGrid")


def _require_provenance(values: object) -> None:
    if not isinstance(values, tuple) or not values:
        raise DomainStateError("source_provenance must be a non-empty tuple")
    if any(not isinstance(value, SourceProvenance) for value in values):
        raise DomainStateError("source_provenance must contain SourceProvenance values")
    source_ids = tuple(value.source_id for value in values)
    if len(source_ids) != len(set(source_ids)):
        raise DomainStateError("source_provenance must have unique source IDs")


def _require_map(
    name: str,
    field: DomainArray,
    grid: RegionGrid,
    *,
    unit: ArrayUnit,
) -> None:
    _require_array(
        name,
        field,
        shape=grid.shape,
        dtypes=_FLOAT_DTYPES,
        unit=unit,
        coordinate_system=grid.grid_coordinate_system,
        axes=("row", "column"),
    )


def _require_array(
    name: str,
    field: object,
    *,
    shape: tuple[int, ...],
    dtypes: tuple[np.dtype, ...],
    unit: ArrayUnit,
    coordinate_system: str,
    axes: tuple[str, ...],
) -> None:
    if not isinstance(field, DomainArray):
        raise DomainStateError(f"{name} must be a DomainArray")
    if field.shape != shape:
        raise DomainStateError(f"{name} shape must be {shape}, got {field.shape}")
    if field.dtype not in dtypes:
        expected = " or ".join(str(dtype) for dtype in dtypes)
        raise DomainStateError(f"{name} dtype must be {expected}")
    if field.unit is not unit:
        raise DomainStateError(f"{name} unit must be {unit.value}")
    if field.coordinate_system != coordinate_system:
        raise DomainStateError(
            f"{name} coordinate system must be {coordinate_system}"
        )
    if field.axes != axes:
        raise DomainStateError(f"{name} axes must be {axes}")


def _require_array_range(
    name: str,
    field: DomainArray,
    minimum: float,
    maximum: float,
    *,
    upper_inclusive: bool = True,
) -> None:
    below = np.any(field.values < minimum)
    above = (
        np.any(field.values > maximum)
        if upper_inclusive
        else np.any(field.values >= maximum)
    )
    if below or above:
        closing = "]" if upper_inclusive else ")"
        raise DomainStateError(
            f"{name} values must be in [{minimum}, {maximum}{closing}"
        )


def _normalize_utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DomainStateError(f"{name} must be timezone-aware UTC")
    try:
        offset = value.utcoffset()
    except (OverflowError, TypeError, ValueError) as exc:
        raise DomainStateError(f"{name} must be timezone-aware UTC") from exc
    if offset != timedelta(0):
        raise DomainStateError(f"{name} must use UTC")
    return value.astimezone(timezone.utc)


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DomainStateError(f"{name} must be non-empty and trimmed")


def _require_nonnegative_int(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DomainStateError(f"{name} must be a non-negative integer")


def _require_finite_real(name: str, value: object) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise DomainStateError(f"{name} must be a finite real number")
