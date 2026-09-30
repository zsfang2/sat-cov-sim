# Architecture Boundaries

The repository is migrating from one monolithic single-frame runner to a modular
simulation engine. The current transitional call path is:

```text
satellite_coverage.CoverageScenario       (lazy public export)
  -> satellite_coverage.scenario          (stable import path)
  -> compatibility.legacy_scenario        (legacy dict/YAML facade)
  -> engine.run_legacy_scenario            (public execution entry point)
  -> engine._legacy                        (loaded only when run() is called)
     -> coordinates / TLE / geodata / propagation legacy modules
```

The original move behind `engine.run_legacy_scenario` was structural. The
v0.1.1 propagation update separately corrects CF-01 using receiver-relative
elevation. Component names, output dtypes and single-frame orchestration remain.
This local correction does not qualify old or new maps as reference datasets.

## Public namespaces

The following namespaces are importable without reading source data, running a
simulation, or writing output:

- `satellite_coverage.config`
- `satellite_coverage.domain`
- `satellite_coverage.data_sources`
- `satellite_coverage.orbit`
- `satellite_coverage.geometry`
- `satellite_coverage.scheduling`
- `satellite_coverage.propagation`
- `satellite_coverage.engine`
- `satellite_coverage.io`
- `satellite_coverage.compatibility`
- `satrm_benchmark`

Some namespaces are intentionally interface-only at this stage. They establish the
dependency direction for later implementations; they are not claims that orbit,
geometry, scheduling, dataset I/O, or benchmark behavior has been implemented.

The independent pilot path is now executable:

```text
experiments.pilot
  -> config.pilot -> domain.link_record / geometry.local (validation only)
  -> engine.analytic_link -> geometry.local / propagation.fspl_db / domain.link_record
  -> adapters.legacy_output / data_sources.manifest / data_sources.dem_audit
  -> io.run_record (run records, not a reference DatasetWriter)
```

The M1 path now unifies scalar fixed ECEF, artificial directions/ENU and TLE inputs:

```text
experiments.link -> config.link.LinkConfig -> engine.links.calculate_links
  -> orbit selection / geometry.geodetic / geometry.local
  -> geometry.antenna -> engine.link_budget -> domain.link_record
  -> io.run_record
```

`engine.orbit_link` is an adapter for the first-batch orbit request. The pilot
and unified M1 engine share `engine.link_budget`; they do not maintain separate
power formulas. The new path is a scalar candidate sequence, not a per-pixel
reference dataset engine. See `docs/M1.md` for units, states and scope.

External-data audits and analytic links have separate input records; auditing a
DEM does not make that DEM an input to the synthetic free-space calculation.

## Dependency rules

- Domain state does not read YAML, TLE, DEM, environment, or output files.
- Propagation calculations do not read configuration/data sources or write output.
- Scheduling does not call propagation or engine implementations.
- Simulation code does not import benchmark, sensor, preprocessing, evaluation, or
  machine-learning internals.
- `satrm_benchmark` may consume the future public `satellite_coverage.io` dataset
  schema, but it must not call orbit, geometry, scheduling, or propagation internals.
- Importing the root or compatibility package does not load the legacy runner. YAML
  is loaded only when `CoverageScenario.from_yaml()` is called; physical dependencies
  are loaded only when `CoverageScenario.run()` is called.
