"""Typed, storage-independent scenario configuration models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any, Mapping

from pyproj import CRS
from pyproj.exceptions import CRSError


class ConfigError(ValueError):
    """Raised when scenario configuration is incomplete or ambiguous."""


class ConfigProfileStatus(str, Enum):
    """Whether every reference-defining input has been frozen."""

    DRAFT = "draft"
    FROZEN = "frozen"


@dataclass(frozen=True)
class RegionConfig:
    """Stable region identity resolved by a later data-source manifest."""

    region_id: str

    def __post_init__(self) -> None:
        _require_text("region_id", self.region_id)


@dataclass(frozen=True)
class SpatialConfig:
    """Shared raster dimensions and geodetic conventions for all regions."""

    regions: tuple[RegionConfig, ...]
    map_height_px: int
    map_width_px: int
    ground_resolution_m: float
    extent_height_m: float
    extent_width_m: float
    geodetic_crs: str
    dem_source: str
    dem_source_resolution_m: float
    output_dem_resolution_m: float

    def __post_init__(self) -> None:
        if not isinstance(self.regions, tuple) or not self.regions:
            raise ConfigError("spatial.regions must be a non-empty tuple")
        if any(not isinstance(region, RegionConfig) for region in self.regions):
            raise ConfigError("spatial.regions must contain RegionConfig values")
        region_ids = tuple(region.region_id for region in self.regions)
        if len(region_ids) != len(set(region_ids)):
            raise ConfigError("spatial.regions must have unique region_id values")

        _require_positive_int("spatial.map_height_px", self.map_height_px)
        _require_positive_int("spatial.map_width_px", self.map_width_px)
        _require_positive_real(
            "spatial.ground_resolution_m", self.ground_resolution_m
        )
        _require_positive_real("spatial.extent_height_m", self.extent_height_m)
        _require_positive_real("spatial.extent_width_m", self.extent_width_m)
        _require_positive_real(
            "spatial.dem_source_resolution_m", self.dem_source_resolution_m
        )
        _require_positive_real(
            "spatial.output_dem_resolution_m", self.output_dem_resolution_m
        )
        _require_text("spatial.dem_source", self.dem_source)

        expected_height_m = self.map_height_px * self.ground_resolution_m
        expected_width_m = self.map_width_px * self.ground_resolution_m
        if not math.isclose(
            self.extent_height_m, expected_height_m, rel_tol=0.0, abs_tol=1e-9
        ):
            raise ConfigError(
                "spatial.extent_height_m must equal map_height_px * "
                "ground_resolution_m"
            )
        if not math.isclose(
            self.extent_width_m, expected_width_m, rel_tol=0.0, abs_tol=1e-9
        ):
            raise ConfigError(
                "spatial.extent_width_m must equal map_width_px * "
                "ground_resolution_m"
            )

        if not isinstance(self.geodetic_crs, str):
            raise ConfigError("spatial.geodetic_crs must be a CRS string")
        try:
            crs = CRS.from_user_input(self.geodetic_crs)
        except (CRSError, ValueError) as exc:
            raise ConfigError("spatial.geodetic_crs is invalid") from exc
        if not crs.equals(CRS.from_epsg(4326)):
            raise ConfigError("spatial.geodetic_crs must identify WGS-84")
        object.__setattr__(self, "geodetic_crs", "EPSG:4326")
        _normalize_real_fields(
            self,
            "ground_resolution_m",
            "extent_height_m",
            "extent_width_m",
            "dem_source_resolution_m",
            "output_dem_resolution_m",
        )

    @property
    def map_shape(self) -> tuple[int, int]:
        return self.map_height_px, self.map_width_px


@dataclass(frozen=True)
class TemporalConfig:
    """Inclusive UTC timeline shared by every configured region."""

    start_time_utc: datetime
    end_time_utc: datetime
    interval_s: int
    frames_per_region: int

    def __post_init__(self) -> None:
        start = _normalize_utc("temporal.start_time_utc", self.start_time_utc)
        end = _normalize_utc("temporal.end_time_utc", self.end_time_utc)
        object.__setattr__(self, "start_time_utc", start)
        object.__setattr__(self, "end_time_utc", end)
        _require_positive_int("temporal.interval_s", self.interval_s)
        _require_positive_int("temporal.frames_per_region", self.frames_per_region)
        if end < start:
            raise ConfigError("temporal.end_time_utc must not precede start_time_utc")

        duration = end - start
        interval = timedelta(seconds=self.interval_s)
        quotient, remainder = divmod(duration, interval)
        if remainder:
            raise ConfigError("temporal range must be divisible by interval_s")
        expected_frames = quotient + 1
        if self.frames_per_region != expected_frames:
            raise ConfigError(
                "temporal.frames_per_region must match the inclusive time range"
            )


@dataclass(frozen=True)
class ServiceConfig:
    """Reference service-availability threshold."""

    minimum_elevation_deg: float

    def __post_init__(self) -> None:
        _require_real_in_range(
            "service.minimum_elevation_deg",
            self.minimum_elevation_deg,
            minimum=0.0,
            maximum=90.0,
        )
        _normalize_real_fields(self, "minimum_elevation_deg")


@dataclass(frozen=True)
class LinkConfig:
    """Power and carrier inputs using explicit units."""

    frequency_hz: float
    transmit_power_dbm: float
    receiver_gain_dbi: float

    def __post_init__(self) -> None:
        _require_positive_real("link.frequency_hz", self.frequency_hz)
        _require_real_in_range(
            "link.transmit_power_dbm",
            self.transmit_power_dbm,
            minimum=-300.0,
            maximum=300.0,
        )
        _require_real_in_range(
            "link.receiver_gain_dbi",
            self.receiver_gain_dbi,
            minimum=-200.0,
            maximum=200.0,
        )
        _normalize_real_fields(
            self, "frequency_hz", "transmit_power_dbm", "receiver_gain_dbi"
        )


@dataclass(frozen=True)
class AntennaConfig:
    """Specified reference-array constants, excluding pending beam semantics."""

    array_rows: int
    array_columns: int
    element_gain_dbi: float
    array_efficiency_loss_db: float
    maximum_off_axis_attenuation_db: float

    def __post_init__(self) -> None:
        _require_positive_int("antenna.array_rows", self.array_rows)
        _require_positive_int("antenna.array_columns", self.array_columns)
        _require_real_in_range(
            "antenna.element_gain_dbi",
            self.element_gain_dbi,
            minimum=-200.0,
            maximum=200.0,
        )
        _require_nonnegative_real(
            "antenna.array_efficiency_loss_db", self.array_efficiency_loss_db
        )
        _require_nonnegative_real(
            "antenna.maximum_off_axis_attenuation_db",
            self.maximum_off_axis_attenuation_db,
        )
        _normalize_real_fields(
            self,
            "element_gain_dbi",
            "array_efficiency_loss_db",
            "maximum_off_axis_attenuation_db",
        )


@dataclass(frozen=True)
class AtmosphereConfig:
    """Fixed zenith-loss approximation parameters."""

    gas_zenith_loss_db: float
    cloud_zenith_loss_db: float

    def __post_init__(self) -> None:
        _require_nonnegative_real(
            "atmosphere.gas_zenith_loss_db", self.gas_zenith_loss_db
        )
        _require_nonnegative_real(
            "atmosphere.cloud_zenith_loss_db", self.cloud_zenith_loss_db
        )
        _normalize_real_fields(
            self, "gas_zenith_loss_db", "cloud_zenith_loss_db"
        )


@dataclass(frozen=True)
class TerrainConfig:
    """Specified profile and reference diffraction-cap parameters."""

    profile_step_m: float
    profile_start_distance_m: float
    effective_earth_radius_factor: float
    diffraction_loss_cap_db: float

    def __post_init__(self) -> None:
        _require_positive_real("terrain.profile_step_m", self.profile_step_m)
        _require_positive_real(
            "terrain.profile_start_distance_m", self.profile_start_distance_m
        )
        _require_positive_real(
            "terrain.effective_earth_radius_factor",
            self.effective_earth_radius_factor,
        )
        _require_nonnegative_real(
            "terrain.diffraction_loss_cap_db", self.diffraction_loss_cap_db
        )
        _normalize_real_fields(
            self,
            "profile_step_m",
            "profile_start_distance_m",
            "effective_earth_radius_factor",
            "diffraction_loss_cap_db",
        )


@dataclass(frozen=True)
class WeatherConfig:
    """High-level synthetic moving-cell configuration."""

    minimum_cell_count: int
    maximum_cell_count: int
    maximum_nominal_attenuation_db: float

    def __post_init__(self) -> None:
        _require_positive_int("weather.minimum_cell_count", self.minimum_cell_count)
        _require_positive_int("weather.maximum_cell_count", self.maximum_cell_count)
        if self.maximum_cell_count < self.minimum_cell_count:
            raise ConfigError(
                "weather.maximum_cell_count must not be below minimum_cell_count"
            )
        _require_nonnegative_real(
            "weather.maximum_nominal_attenuation_db",
            self.maximum_nominal_attenuation_db,
        )
        _normalize_real_fields(self, "maximum_nominal_attenuation_db")


@dataclass(frozen=True)
class ClutterConfig:
    """High-level synthetic region-static clutter parameters."""

    maximum_nominal_attenuation_db: float
    additional_bias_db: float

    def __post_init__(self) -> None:
        _require_nonnegative_real(
            "clutter.maximum_nominal_attenuation_db",
            self.maximum_nominal_attenuation_db,
        )
        _require_nonnegative_real("clutter.additional_bias_db", self.additional_bias_db)
        _normalize_real_fields(
            self, "maximum_nominal_attenuation_db", "additional_bias_db"
        )


@dataclass(frozen=True)
class RandomConfig:
    """Required root entropy; named child-stream policy is added later."""

    root_seed: int

    def __post_init__(self) -> None:
        _require_nonnegative_int("random.root_seed", self.root_seed)
        if self.root_seed > 2**64 - 1:
            raise ConfigError("random.root_seed must fit in an unsigned 64-bit integer")


@dataclass(frozen=True)
class ScenarioConfig:
    """Complete typed input boundary for one versioned scenario profile."""

    schema_version: int
    profile_name: str
    profile_status: ConfigProfileStatus
    spatial: SpatialConfig
    temporal: TemporalConfig
    service: ServiceConfig
    link: LinkConfig
    antenna: AntennaConfig
    atmosphere: AtmosphereConfig
    terrain: TerrainConfig
    weather: WeatherConfig
    clutter: ClutterConfig
    random: RandomConfig

    def __post_init__(self) -> None:
        _require_positive_int("schema_version", self.schema_version)
        if self.schema_version != 1:
            raise ConfigError(f"unsupported schema_version: {self.schema_version}")
        _require_text("profile_name", self.profile_name)
        if not isinstance(self.profile_status, ConfigProfileStatus):
            raise ConfigError("profile_status must be draft or frozen")
        expected_types = {
            "spatial": SpatialConfig,
            "temporal": TemporalConfig,
            "service": ServiceConfig,
            "link": LinkConfig,
            "antenna": AntennaConfig,
            "atmosphere": AtmosphereConfig,
            "terrain": TerrainConfig,
            "weather": WeatherConfig,
            "clutter": ClutterConfig,
            "random": RandomConfig,
        }
        for field_name, field_type in expected_types.items():
            if not isinstance(getattr(self, field_name), field_type):
                raise ConfigError(f"{field_name} must be a {field_type.__name__}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ScenarioConfig":
        """Parse a strict mapping without accepting implicit unit aliases."""

        root = _require_mapping("scenario", value)
        _require_keys(
            "scenario",
            root,
            {
                "schema_version",
                "profile_name",
                "profile_status",
                "spatial",
                "temporal",
                "service",
                "link",
                "antenna",
                "atmosphere",
                "terrain",
                "weather",
                "clutter",
                "random",
            },
        )
        try:
            profile_status = ConfigProfileStatus(root["profile_status"])
        except (TypeError, ValueError) as exc:
            raise ConfigError("profile_status must be draft or frozen") from exc

        return cls(
            schema_version=root["schema_version"],
            profile_name=root["profile_name"],
            profile_status=profile_status,
            spatial=_spatial_from_mapping(root["spatial"]),
            temporal=_temporal_from_mapping(root["temporal"]),
            service=_dataclass_from_mapping(
                "service", root["service"], ServiceConfig
            ),
            link=_dataclass_from_mapping("link", root["link"], LinkConfig),
            antenna=_dataclass_from_mapping(
                "antenna", root["antenna"], AntennaConfig
            ),
            atmosphere=_dataclass_from_mapping(
                "atmosphere", root["atmosphere"], AtmosphereConfig
            ),
            terrain=_dataclass_from_mapping(
                "terrain", root["terrain"], TerrainConfig
            ),
            weather=_dataclass_from_mapping(
                "weather", root["weather"], WeatherConfig
            ),
            clutter=_dataclass_from_mapping(
                "clutter", root["clutter"], ClutterConfig
            ),
            random=_dataclass_from_mapping("random", root["random"], RandomConfig),
        )

    def canonical_json_bytes(self) -> bytes:
        """Return deterministic UTF-8 JSON suitable for provenance hashing."""

        normalized = _canonical_value(asdict(self))
        return json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    def checksum_sha256(self) -> str:
        """Return the content checksum of the canonical representation."""

        digest = hashlib.sha256(self.canonical_json_bytes()).hexdigest()
        return f"sha256:{digest}"

    @property
    def total_frames(self) -> int:
        return len(self.spatial.regions) * self.temporal.frames_per_region


def _spatial_from_mapping(value: Any) -> SpatialConfig:
    data = _require_mapping("spatial", value)
    required = {
        "regions",
        "map_height_px",
        "map_width_px",
        "ground_resolution_m",
        "extent_height_m",
        "extent_width_m",
        "geodetic_crs",
        "dem_source",
        "dem_source_resolution_m",
        "output_dem_resolution_m",
    }
    _require_keys("spatial", data, required)
    regions_value = data["regions"]
    if not isinstance(regions_value, list):
        raise ConfigError("spatial.regions must be a list")
    regions = tuple(
        _dataclass_from_mapping(f"spatial.regions[{index}]", item, RegionConfig)
        for index, item in enumerate(regions_value)
    )
    return SpatialConfig(
        regions=regions,
        **{name: data[name] for name in required if name != "regions"},
    )


def _temporal_from_mapping(value: Any) -> TemporalConfig:
    data = _require_mapping("temporal", value)
    required = {
        "start_time_utc",
        "end_time_utc",
        "interval_s",
        "frames_per_region",
    }
    _require_keys("temporal", data, required)
    return TemporalConfig(
        start_time_utc=_parse_datetime(
            "temporal.start_time_utc", data["start_time_utc"]
        ),
        end_time_utc=_parse_datetime("temporal.end_time_utc", data["end_time_utc"]),
        interval_s=data["interval_s"],
        frames_per_region=data["frames_per_region"],
    )


def _dataclass_from_mapping(path: str, value: Any, model_type: type[Any]) -> Any:
    data = _require_mapping(path, value)
    field_names = set(model_type.__dataclass_fields__)
    _require_keys(path, data, field_names)
    return model_type(**{name: data[name] for name in field_names})


def _require_mapping(path: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise ConfigError(f"{path} keys must be strings")
    return value


def _require_keys(path: str, value: Mapping[str, Any], required: set[str]) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing:
        raise ConfigError(f"{path} missing required keys: {', '.join(missing)}")
    if unknown:
        raise ConfigError(f"{path} has unknown keys: {', '.join(unknown)}")


def _parse_datetime(path: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise ConfigError(f"{path} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigError(f"{path} must be a valid ISO-8601 timestamp") from exc
    return _normalize_utc(path, parsed)


def _normalize_utc(path: str, value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ConfigError(f"{path} must be timezone-aware UTC")
    try:
        offset = value.utcoffset()
    except (OverflowError, TypeError, ValueError) as exc:
        raise ConfigError(f"{path} must be timezone-aware UTC") from exc
    if offset != timedelta(0):
        raise ConfigError(f"{path} must use UTC")
    return value.astimezone(timezone.utc)


def _require_text(path: str, value: Any) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ConfigError(f"{path} must be non-empty and trimmed")


def _require_positive_int(path: str, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{path} must be a positive integer")


def _require_nonnegative_int(path: str, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"{path} must be a non-negative integer")


def _require_finite_real(path: str, value: Any) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ConfigError(f"{path} must be a finite real number")


def _require_positive_real(path: str, value: Any) -> None:
    _require_finite_real(path, value)
    if value <= 0:
        raise ConfigError(f"{path} must be greater than zero")


def _require_nonnegative_real(path: str, value: Any) -> None:
    _require_finite_real(path, value)
    if value < 0:
        raise ConfigError(f"{path} must be non-negative")


def _require_real_in_range(
    path: str,
    value: Any,
    *,
    minimum: float,
    maximum: float,
) -> None:
    _require_finite_real(path, value)
    if not minimum <= value <= maximum:
        raise ConfigError(f"{path} must be in [{minimum}, {maximum}]")


def _normalize_real_fields(instance: Any, *field_names: str) -> None:
    for field_name in field_names:
        object.__setattr__(instance, field_name, float(getattr(instance, field_name)))


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        normalized = _normalize_utc("canonical timestamp", value)
        return normalized.isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    return value
