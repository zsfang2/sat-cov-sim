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

The move behind `engine.run_legacy_scenario` is structural. The legacy equations,
defaults, component names, output dtypes, and single-frame semantics are preserved.
In particular, this does not correct the known CF-01 terrain issue and does not make
legacy output eligible for reference-dataset registration.

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
