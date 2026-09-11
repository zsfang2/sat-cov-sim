# Domain State Boundary

`satellite_coverage.domain` defines the immutable values exchanged between data
sources, geometry, propagation, scheduling, the scenario engine, and dataset I/O.
These types validate state only: they do not read configuration or files, select
satellites, calculate propagation, or persist datasets.

## Array contract

Every numerical field is a `DomainArray` containing:

- an owned, read-only NumPy buffer;
- named axes;
- a machine-readable `ArrayUnit`;
- an explicit coordinate-system identifier.

Construction rejects complex/non-numeric values, axis mismatches, and NaN or
infinite values. Geometry and geodetic arrays use `float64`; environmental and
link-budget maps may use `float32` or `float64`. This is an exchange-boundary
validation policy, not an instruction to lower the precision of calculations.

## State lifecycles

- `RegionGrid` identifies the raster shape, resolution, horizontal/vertical CRS,
  and pixel-center affine transform for one region.
- `SourceProvenance` identifies an immutable external source version. Detailed
  manifest/checksum and portable path policies are introduced by task 6.
- `RegionStaticState` owns latitude, longitude, elevation, ground ECEF, local ENU
  basis, static clutter, and source provenance. Build it once per region and reuse
  it across frames.
- `EnvironmentalState` is one timestamped weather realization with a named random
  stream. Deterministic environment lookup/generation is introduced by task 18.
- `OrbitState` is one satellite's Earth-fixed position and TLE identity at one UTC
  timestamp. TLE selection and TEME-to-Earth-fixed calculations remain task 9.
- `PixelGeometry` holds per-pixel slant range, elevation, azimuth, and satellite
  beam off-axis angle. Geometry calculations remain task 10.
- `PhysicalState` holds clean received power and uniquely named component maps.
  Component calculation and link-budget composition remain task 13 onward.
- `FrameState` joins candidate/serving orbit state, service transition, geometry,
  and physical state for one region and timestamp. A `no_service` frame explicitly
  contains no serving orbit, geometry, or physical state.

## Coordinate conventions

- Geodetic latitude/longitude: WGS-84 (`EPSG:4326`), degrees.
- Earth-fixed positions: WGS-84 geocentric (`EPSG:4978`), metres.
- Per-pixel elevation/azimuth: `LOCAL_ENU:<region_id>`, degrees. Azimuth is in
  `[0, 360)`; its north-clockwise computation is enforced by the future geometry
  engine and independent numerical-reference tests.
- Beam off-axis angle: `SATELLITE_BEAM_FRAME`, degrees in `[0, 180]`.
- Raster maps: `REGION_GRID:<region_id>:<projected_crs>`.
- DEM elevation: the grid's explicit `vertical_crs`; the reference vertical datum
  is not silently assumed and must be frozen with the source manifest.

## Deliberate non-goals of this phase

These dataclasses are not wired into the legacy `CoverageScenario` yet. They do
not change generated map values, random seeds, or the known CF-01 terrain behavior.
The compatibility facade and module import boundaries are handled in task 5.
