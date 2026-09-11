from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import numpy as np
import pytest

from satellite_coverage.domain import (
    ArrayUnit,
    DomainArray,
    DomainStateError,
    EnvironmentalState,
    FrameState,
    OrbitState,
    PhysicalState,
    PixelGeometry,
    RegionGrid,
    RegionStaticState,
    ServiceState,
    SourceProvenance,
    WGS84_ECEF_CRS,
    WGS84_GEODETIC_CRS,
)


def _grid(region_id: str = "region-a") -> RegionGrid:
    return RegionGrid(
        region_id=region_id,
        height_px=2,
        width_px=3,
        resolution_m=100.0,
        geodetic_crs=WGS84_GEODETIC_CRS,
        projected_crs="EPSG:32649",
        vertical_crs="EPSG:3855",
        pixel_center_affine=(100.0, 0.0, 500_000.0, 0.0, -100.0, 3_800_000.0),
    )


def _array(values, unit: ArrayUnit, coordinate_system: str, axes):
    return DomainArray(
        values=np.asarray(values),
        unit=unit,
        coordinate_system=coordinate_system,
        axes=axes,
    )


def _provenance(kind: str = "dem") -> SourceProvenance:
    return SourceProvenance(
        source_id=f"{kind}-source",
        source_kind=kind,
        version="2025-01-01",
        checksum=f"sha256:{kind}-digest",
    )


def _static_state(grid: RegionGrid | None = None) -> RegionStaticState:
    grid = grid or _grid()
    shape = grid.shape
    return RegionStaticState(
        grid=grid,
        latitude_deg=_array(
            np.full(shape, 34.0, dtype=np.float64),
            ArrayUnit.DEGREE,
            WGS84_GEODETIC_CRS,
            ("row", "column"),
        ),
        longitude_deg=_array(
            np.full(shape, 108.0, dtype=np.float64),
            ArrayUnit.DEGREE,
            WGS84_GEODETIC_CRS,
            ("row", "column"),
        ),
        elevation_m=_array(
            np.full(shape, 500.0, dtype=np.float64),
            ArrayUnit.METER,
            grid.vertical_crs,
            ("row", "column"),
        ),
        ground_ecef_m=_array(
            np.ones(shape + (3,), dtype=np.float64),
            ArrayUnit.METER,
            WGS84_ECEF_CRS,
            ("row", "column", "xyz"),
        ),
        ecef_to_enu_basis=_array(
            np.broadcast_to(np.eye(3), shape + (3, 3)).copy(),
            ArrayUnit.DIMENSIONLESS,
            f"ECEF_TO_ENU:{grid.region_id}",
            ("row", "column", "enu", "ecef"),
        ),
        static_clutter_loss_db=_array(
            np.zeros(shape, dtype=np.float32),
            ArrayUnit.DB,
            grid.grid_coordinate_system,
            ("row", "column"),
        ),
        source_provenance=(_provenance(),),
    )


def _orbit(timestamp: datetime | None = None) -> OrbitState:
    timestamp = timestamp or datetime(2025, 1, 1, tzinfo=timezone.utc)
    return OrbitState(
        norad_id="99999",
        satellite_name="TEST SATELLITE",
        timestamp_utc=timestamp,
        position_ecef_m=_array(
            np.array([7_000_000.0, 0.0, 0.0], dtype=np.float64),
            ArrayUnit.METER,
            WGS84_ECEF_CRS,
            ("xyz",),
        ),
        geodetic_altitude_m=550_000.0,
        tle_epoch_utc=datetime(2024, 12, 31, 12, tzinfo=timezone.utc),
        tle_provenance=_provenance("tle"),
        sgp4_status=0,
    )


def _geometry(grid: RegionGrid | None = None) -> PixelGeometry:
    grid = grid or _grid()
    shape = grid.shape
    return PixelGeometry(
        grid=grid,
        slant_range_m=_array(
            np.full(shape, 600_000.0, dtype=np.float64),
            ArrayUnit.METER,
            WGS84_ECEF_CRS,
            ("row", "column"),
        ),
        elevation_deg=_array(
            np.full(shape, 45.0, dtype=np.float64),
            ArrayUnit.DEGREE,
            f"LOCAL_ENU:{grid.region_id}",
            ("row", "column"),
        ),
        azimuth_deg=_array(
            np.full(shape, 30.0, dtype=np.float64),
            ArrayUnit.DEGREE,
            f"LOCAL_ENU:{grid.region_id}",
            ("row", "column"),
        ),
        off_axis_angle_deg=_array(
            np.full(shape, 2.0, dtype=np.float64),
            ArrayUnit.DEGREE,
            "SATELLITE_BEAM_FRAME",
            ("row", "column"),
        ),
    )


def _physical(grid: RegionGrid | None = None) -> PhysicalState:
    grid = grid or _grid()
    shape = grid.shape
    return PhysicalState(
        grid=grid,
        received_power_dbm=_array(
            np.full(shape, -100.0, dtype=np.float32),
            ArrayUnit.DBM,
            grid.grid_coordinate_system,
            ("row", "column"),
        ),
        component_maps=(
            (
                "fspl_db",
                _array(
                    np.full(shape, 170.0, dtype=np.float32),
                    ArrayUnit.DB,
                    grid.grid_coordinate_system,
                    ("row", "column"),
                ),
            ),
        ),
    )


def test_domain_array_owns_immutable_copy_with_metadata():
    source = np.arange(6, dtype=np.float64).reshape(2, 3)
    field = _array(
        source,
        ArrayUnit.METER,
        WGS84_ECEF_CRS,
        ("row", "column"),
    )
    source[0, 0] = 999.0

    assert field.values[0, 0] == 0.0
    assert field.shape == (2, 3)
    assert field.dtype == np.dtype("float64")
    assert not field.values.flags.writeable
    with pytest.raises(ValueError):
        field.values[0, 0] = 1.0
    with pytest.raises(ValueError):
        field.values.setflags(write=True)


def test_domain_array_rejects_nonfinite_values():
    with pytest.raises(DomainStateError, match="finite"):
        _array(
            np.array([np.nan], dtype=np.float64),
            ArrayUnit.METER,
            WGS84_ECEF_CRS,
            ("xyz",),
        )


def test_static_state_validates_shapes_dtypes_units_and_coordinates():
    state = _static_state()

    assert state.grid.shape == (2, 3)
    assert state.ground_ecef_m.shape == (2, 3, 3)
    assert state.ecef_to_enu_basis.shape == (2, 3, 3, 3)
    assert state.latitude_deg.dtype == np.dtype("float64")
    assert state.static_clutter_loss_db.dtype == np.dtype("float32")
    assert not state.elevation_m.values.flags.writeable
    with pytest.raises(FrozenInstanceError):
        state.grid = _grid("other")


def test_static_state_rejects_wrong_shape_and_dtype():
    state = _static_state()
    wrong_shape = _array(
        np.zeros((3, 2), dtype=np.float32),
        ArrayUnit.DB,
        state.grid.grid_coordinate_system,
        ("row", "column"),
    )
    with pytest.raises(DomainStateError, match="static_clutter_loss_db.*shape"):
        replace(state, static_clutter_loss_db=wrong_shape)

    wrong_dtype = _array(
        state.latitude_deg.values.astype(np.float32),
        ArrayUnit.DEGREE,
        WGS84_GEODETIC_CRS,
        ("row", "column"),
    )
    with pytest.raises(DomainStateError, match="latitude_deg.*float64"):
        replace(state, latitude_deg=wrong_dtype)


def test_environmental_state_carries_time_and_random_stream_identity():
    grid = _grid()
    state = EnvironmentalState(
        grid=grid,
        timestamp_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
        realization_id="weather-region-a-v1",
        random_stream_id="weather:region-a",
        weather_loss_db=_array(
            np.ones(grid.shape, dtype=np.float32),
            ArrayUnit.DB,
            grid.grid_coordinate_system,
            ("row", "column"),
        ),
    )

    assert state.weather_loss_db.shape == grid.shape
    assert state.timestamp_utc.tzinfo is timezone.utc


def test_orbit_and_pixel_geometry_use_explicit_float64_coordinate_frames():
    orbit = _orbit()
    geometry = _geometry()

    assert orbit.position_ecef_m.coordinate_system == WGS84_ECEF_CRS
    assert orbit.position_ecef_m.dtype == np.dtype("float64")
    assert geometry.slant_range_m.dtype == np.dtype("float64")
    assert geometry.azimuth_deg.coordinate_system == "LOCAL_ENU:region-a"


def test_pixel_geometry_rejects_invalid_ranges_and_angles():
    geometry = _geometry()
    negative_range = _array(
        np.full(geometry.grid.shape, -1.0, dtype=np.float64),
        ArrayUnit.METER,
        WGS84_ECEF_CRS,
        ("row", "column"),
    )
    with pytest.raises(DomainStateError, match="slant_range_m.*positive"):
        replace(geometry, slant_range_m=negative_range)

    invalid_azimuth = _array(
        np.full(geometry.grid.shape, 360.0, dtype=np.float64),
        ArrayUnit.DEGREE,
        "LOCAL_ENU:region-a",
        ("row", "column"),
    )
    with pytest.raises(DomainStateError, match="azimuth_deg"):
        replace(geometry, azimuth_deg=invalid_azimuth)


def test_physical_state_rejects_duplicate_or_misaligned_components():
    state = _physical()
    component = state.component_maps[0]

    with pytest.raises(DomainStateError, match="duplicate component"):
        replace(state, component_maps=(component, component))

    other_grid = _grid("other-region")
    with pytest.raises(DomainStateError, match="received_power_dbm.*coordinate"):
        replace(state, grid=other_grid)


def test_complete_frame_state_validates_candidate_and_component_alignment():
    grid = _grid()
    timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    orbit = _orbit(timestamp)
    frame = FrameState(
        region_id=grid.region_id,
        frame_index=0,
        timestamp_utc=timestamp,
        grid=grid,
        candidate_orbits=(orbit,),
        serving_orbit=orbit,
        service_state=ServiceState.INITIAL_ACQUISITION,
        geometry=_geometry(grid),
        physical_state=_physical(grid),
    )

    assert frame.serving_orbit is orbit
    assert frame.physical_state.component_for("fspl_db").unit is ArrayUnit.DB


def test_frame_state_rejects_region_map_and_candidate_mismatches():
    grid = _grid()
    timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    orbit = _orbit(timestamp)
    frame = FrameState(
        region_id=grid.region_id,
        frame_index=0,
        timestamp_utc=timestamp,
        grid=grid,
        candidate_orbits=(orbit,),
        serving_orbit=orbit,
        service_state=ServiceState.HELD,
        geometry=_geometry(grid),
        physical_state=_physical(grid),
    )

    with pytest.raises(DomainStateError, match="region_id"):
        replace(frame, region_id="other-region")
    with pytest.raises(DomainStateError, match="serving_orbit.*candidate"):
        replace(frame, candidate_orbits=())
    with pytest.raises(DomainStateError, match="physical_state.*grid"):
        replace(frame, physical_state=_physical(_grid("other-region")))


def test_no_service_frame_has_no_serving_geometry_or_physical_state():
    grid = _grid()
    frame = FrameState(
        region_id=grid.region_id,
        frame_index=4,
        timestamp_utc=datetime(2025, 1, 1, 0, 1, 20, tzinfo=timezone.utc),
        grid=grid,
        candidate_orbits=(),
        serving_orbit=None,
        service_state=ServiceState.NO_SERVICE,
        geometry=None,
        physical_state=None,
    )

    assert frame.serving_orbit is None


def test_frame_state_rejects_naive_timestamp():
    grid = _grid()
    with pytest.raises(DomainStateError, match="timestamp_utc"):
        FrameState(
            region_id=grid.region_id,
            frame_index=0,
            timestamp_utc=datetime(2025, 1, 1),
            grid=grid,
            candidate_orbits=(),
            serving_orbit=None,
            service_state=ServiceState.NO_SERVICE,
            geometry=None,
            physical_state=None,
        )
