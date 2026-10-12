# Small offline research reproduction

Supported locked target: CPython 3.12, Linux x86_64, glibc compatible with the included manylinux wheels. Other platforms require a separately verified lock. This is a retrospective small reproduction subset of accepted E1–E4, not a new blind experiment or a physical/service certification.

## Build and run

From an installed development checkout:

```bash
bash scripts/python_geo.sh -m pip download --require-hashes -r requirements-reproduce.lock --dest output/reproduce-wheels
bash scripts/python_geo.sh scripts/reproduce_small.py --output output/reproduce-baseline
bash scripts/python_geo.sh scripts/package_reproduction.py --output output/reproduce-bundle --wheel-dir output/reproduce-wheels --baseline output/reproduce-baseline
python3 output/reproduce-bundle/replay_reproduction.py --bundle output/reproduce-bundle --output output/reproduce-fresh
```

Download is the only network step. Transfer the entire `reproduce-bundle` directory to another supported host, then run its `replay_reproduction.py` with Python 3.12. It verifies all bundled hashes, extracts exact source, creates a new venv without system packages, installs exclusively from the hashed wheelhouse, runs `pip check`, all tests, then the full small workflow against `expected.json`. Run directories are exclusive: choose a new output path for every attempt. Failure status and logs remain on disk. No original 9 GB DEM, external project, previous output directory or online orbit service is needed by the replay.

The baseline and fresh workflow must pass; costs/RSS are measured again, never assumed equal. `semantic.json` compares explicit scientific projections: all E1 factor budgets and held-out error statistics, every E2 role result and input geometry, E3 convergence/comparison/selection and direct-level windows, E4 common-holdout decisions and final windows, synthetic event and selection results. Strings, statuses, input hashes and collection structure are exact; numerical absolute tolerance is 1e-6 with no relative tolerance. Wall time, RSS, code commit and environment-dependent cache/record IDs are separately archived rather than compared as scientific values. Cache identity deliberately includes environment and source fingerprint; it is rebuilt, not reused across environments.

## Scope and frozen subsets

| Workflow | Inputs and coverage |
| --- | --- |
| M0 | Byte-hashed bundled source/config/terrain/TLE, CRS/vertical datum provenance, isolated dependencies and native library records |
| M1/M2/E1 | Artificial flat and Qinling terrain; all eight original power/antenna/frequency/direction/height/joint factors; 8 tables, sparse held-out directions; direct M1 crosschecks, strict fallback, ordinary query errors and costs |
| M3/M4/E2 | Flat/double-ridge and small real terrain; all original special failure/domain cases; three roles, three spatial refinements, full raw/used/cap/unknown records |
| M5/E3 | First development and first holdout of original E3, entire padded passes, threshold -150 dBm; original convergence tolerances, actual direct-time refinement and guarded cache sidecar costs |
| M6/E4 | First two separately centered original sites, first development and first holdout of original E4; EIRP 55/-150 dBm; all four information layers, original spatial/time qualification, receipt barrier before holdout |
| Artificial event/selection | Analytic short/contact/crossing/unknown events; known optimal selection, reversal and no-benefit tables, tamper/leakage rejection |

The small subset retains formerly observed outcomes; it is selected by original index and documented before this replay. It does not replace the larger archived matrices. Real multi-edge whole-pass stability remains unqualified; an unknown E4 result is expected to remain unknown. Business gain/budget/event tolerances remain undetermined. Old reference scheduler/beam/weather/clutter/RNG/writer/resume/benchmark requirements remain separate.

## Data recovery and provenance

`inputs/` contains the exact derived grids and archived TLE, not merely their checksums. `input-manifest.json` binds every fixture and all four small configs. Terrain metadata preserves original source hashes, coordinate system, local grid geometry and source/conversion records; historical absolute paths in this metadata are provenance only and are never opened during replay.

- Copernicus DEM: user identified the original China mosaic as ESA Copernicus GLO30, metre EGM2008 DSM. Attribution: Copernicus DEM / European Union, ESA and Airbus; source documentation and URLs are in `inputs/copernicus-source.json`. Original local mosaic lineage is unverified. These small declared derived excerpts are distributed for reproducing the research; they are not authenticated upstream tiles and are not bare-earth DTM.
- Geoid: PROJ distribution of NGA EGM2008, original `https://cdn.proj.org/us_nga_egm08_25.tif`; source/hash documentation is in `inputs/egm2008-grid.json`. Packaged heights already apply h=H+N once; do not apply geoid correction again.
- TLE: exact archived 2025-01-01 input from the existing project data, SHA in the manifest, NORAD44714 / past_only. Upstream acquisition provenance is not independently established; the bundled bytes make the experiment recoverable without claiming a newly authenticated orbit source.
- Artificial terrains and analytic cases are generated by included Python source. All derived source bytes are included in `source.zip`. Large original data and phase archives are unnecessary for replay; full reprocessing from the original mosaic is a separate workflow using `prepare_information_value.py` and requires the original declared files.

`requirements-reproduce.lock` includes the existing verified base lock and exact plotting wheels with SHA256. `source-environment.json`, per-run `environment.json`, stage source ZIPs, recursive artifact manifest and bootstrap logs distinguish source identity, physical-input identity and environment identity. No dynamic online input is used while computing results.
