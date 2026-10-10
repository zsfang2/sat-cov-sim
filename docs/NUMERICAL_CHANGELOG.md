# Numerical Change Classification and Log

本文件记录可能影响generated radio maps或published benchmark results的实现变化。它不是dataset regeneration授权；授权条件见[`DATASET_VALIDATION.md`](DATASET_VALIDATION.md)。

## Classification

`NumericalChangeKind`使用以下稳定类别：

| Kind | Intended use | Conservative default |
|---|---|---|
| `metadata_or_gate_only` | metadata、validation或release gate变化，不进入数值计算 | maps=`no`, benchmark=`no` |
| `proven_numerically_equivalent` | 有独立证据证明数值等价的实现替换 | maps=`no`, benchmark=`no` |
| `physics_model_correction` | 物理公式、单位、clipping或component修正 | maps=`possibly`，量化后可为`yes` |
| `geometry_or_orbit_change` | TLE、坐标、range/elevation/azimuth变化 | maps=`possibly` |
| `scheduling_or_frame_identity_change` | serving selection、timestamp或frame mapping变化 | maps=`possibly` |
| `rng_or_realization_change` | seed derivation或随机场realization变化 | maps=`possibly` |
| `benchmark_only_change` | split、sensor、preprocessing或evaluation变化 | maps=`no`, benchmark=`possibly`或`yes` |
| `unknown_numerical_risk` | 证据不足、尚不能归入其他类别 | maps=`possibly`, benchmark=`possibly` |

每条记录必须包含稳定change ID、affected components、before/after behavior、validation evidence，以及两个独立三值字段：

- `current_generated_maps_change`: `yes` / `no` / `possibly`；
- `published_benchmark_results_change`: `yes` / `no` / `possibly`。

当map impact为`yes`或`possibly`时，benchmark impact不能在缺少可追踪dataset/benchmark provenance的情况下声明为`no`。

## Applied Changes

### CONDITIONAL-EVENTS-12 — Direct-time conditional event intervals

| Field | Value |
|---|---|
| Kind | `unknown_numerical_risk` for new optional event aggregation; original scalar formulas unchanged |
| Components affected | New conditional geometry/quality event layer; optional arbitrary-time scalar evaluation |
| Before behavior | Scalar sampled candidates and separate geometric display windows; no conditional event integration |
| After behavior | Direct midpoint refinement, explicit unresolved transition/gap intervals, duration-weighted statistics, candidate opportunity and censoring; original-interval TLE selection preserved |
| Validation evidence | tests/test_quality_events.py; scripts/verify_quality_events.py; reports/m5/events.md |
| Current generated maps change | `no` — existing map path does not use this optional event API |
| Published benchmark results change | `no` — no dataset or benchmark regeneration |
| Existing dataset impact | None; event estimates retain finite sampling and propagation limitations |
| Regeneration decision | Small offline software verification only |

### M2-DIRECTION-11 — Bound local response lookup and cache

| Field | Value |
|---|---|
| Kind | `unknown_numerical_risk` for optional off-grid approximation; original solver unchanged |
| Components affected | New local provider, direction table and JSON cache; nearest/bilinear and direct fallback |
| Before behavior | No local direction query/cache interface |
| After behavior | Original sample reproduction, explicit interpolation uncertainty, state/domain/accuracy fallback, input/source/range identity invalidation |
| Validation evidence | reports/m2/direction-table.md/json; 30 new tests, 402 total; 84-sample archive, zero sample roundtrip error |
| Current generated maps change | `no` — no existing generation path switched to lookup |
| Published benchmark results change | `no` — no dataset or benchmark regeneration |
| Existing dataset impact | None; later callers must retain interpolation and finite-range limitations |
| Regeneration decision | Small offline software verification only |

### M4-COMPARISON-10 — Three-role finite-terrain experiment

| Field | Value |
|---|---|
| Kind | `unknown_numerical_risk` for the new optional multi-edge model; existing M3 path unchanged |
| Components affected | New comparison adapters, independent recursive edge kernel, E2 statistics/figures |
| Before behavior | No executable three-role comparison or E2 evidence |
| After behavior | Sky geometry without invented attenuation; original M3 adapter; independent fixed-axis positive-branch reference with bounded recursion and explicit reference eligibility |
| Validation evidence | reports/m4/e2.md/json; 372 tests; 1189 paired cases / 3567 role rows, plus one archived invalid request; M3 direct/adapter exact equality |
| Current generated maps change | `no` — comparison is separate and existing production path unchanged |
| Published benchmark results change | `no` — no benchmark/dataset regeneration or promotion |
| Existing dataset impact | No rewriting; new reference role is not a physical-truth certification |
| Regeneration decision | Frozen E2 diagnostic experiment only |

### M3-DOMAIN-09 — Forward-domain and finite arithmetic counterexamples

| Field | Value |
|---|---|
| Kind | `physics_model_correction` within declared local single-edge domain; numeric validation |
| Components affected | Terrain profile arithmetic, interval projection candidates, scalar local loss |
| Before behavior | All-behind flat rays could report complete LOS with unexplained missing loss; tiny finite frequency could emit infinite Fresnel radius; projection interior vertex not retained explicitly |
| After behavior | Zero local loss for completely known all-behind candidates; include interior projection vertex; explicit empty-domain reason; reject nonfinite derived wavelength/projection/Fresnel/height values |
| Validation evidence | reports/m3/domain-matrix.md/json; 21 new tests, 330 total; 16 archived synthetic cases and 11520 real diagnostic queries |
| Current generated maps change | `possibly` if affected terrain scalar outputs are regenerated; old map-generator path unchanged |
| Published benchmark results change | `possibly` — no provenance to certify downstream independence |
| Existing dataset impact | No rewriting or promotion of old artifacts |
| Regeneration decision | Diagnostic cases/matrix/replay only; no formal reference regeneration |

### M3-CONTRACT-08 — Structured finite-range applicability

| Field | Value |
|---|---|
| Kind | `metadata_or_gate_only` |
| Components affected | M1 terrain record/power metadata and CLI failure/resource records |
| Before behavior | Finite-radius limitations mainly in scope/reason text; resource/input failures shared ValueError |
| After behavior | Mandatory terrain_contract and query binding; full path always not_verified; resource-specific ValueError subclass and structured failure archive |
| Validation evidence | 309 tests; 3×571 real records exactly equal to archived outputs after removing added contract fields; physical checksums unchanged |
| Current generated maps change | `no` |
| Published benchmark results change | `no` |
| Existing dataset impact | Historical outputs untouched and not promoted |
| Regeneration decision | Diagnostic replay only |

### M3-READ-07 — Bounded target tiles and exact source windows

| Field | Value |
|---|---|
| Kind | `proven_numerically_equivalent` within tested small-window domain; expanded read capability |
| Components affected | Declared DEM reader; no propagation solver change |
| Before behavior | Full target coordinate arrays and one source window; 1M output / 4M source-window cell limits |
| After behavior | Two-pass target tiles, recursive source-window subdivision, resource preflight; 4M output / 262144 per-read source cells |
| Validation evidence | 289 tests; frozen oracle, real 3/6/24 km exact values/masks/metadata/source_id; 36/48 km resource records in bounded-reader report |
| Current generated maps change | `no` — old map generator unchanged; tested scalar reader inputs exactly preserved |
| Published benchmark results change | `no` — no published artifacts regenerated |
| Existing dataset impact | No automatic reclassification; larger readable extents do not prove propagation sufficiency |
| Regeneration decision | Diagnostic reader runs only |

### M3-RADIUS-06 — Explicit finite-extent radius audit

| Field | Value |
|---|---|
| Kind | `metadata_or_gate_only` |
| Components affected | Experiment radius comparisons and validation reporting |
| Before behavior | Only comparisons against a fixed 12 km reference; no multi-extension status |
| After behavior | Compare every candidate to all larger tested radii; insufficient outer evidence and unavailable queries cannot claim stability; global sufficiency remains unverified |
| Validation evidence | 272-test regression and 24 km matrix in sixth-batch report |
| Current generated maps change | `no` — solver and map generation unchanged |
| Published benchmark results change | `no` |
| Existing dataset impact | No automatic upgrade of previous outputs |
| Regeneration decision | Diagnostic experiments only |

### M3-LOSS-05 — Interior Fresnel extrema and forward projection domain

| Field | Value |
|---|---|
| Kind | `physics_model_correction` in the optional local scalar solver |
| Components affected | Cell-interval dominant loss and power availability |
| Before behavior | Interior loss extrema could be missed; below-ray terrain projected behind the receiver made the whole profile incomplete |
| After behavior | Add stationary Fresnel-v candidates; exclude below-ray backward projections with a diagnostic count; retain other unsupported projection states |
| Validation evidence | 264-test regression including 200001-point direct interval comparisons; fifth-batch real-data report |
| Current generated maps change | `no` — legacy map generation unchanged; new scalar terrain values/availability can change |
| Published benchmark results change | `no` — no published artifact modified |
| Existing dataset impact | Earlier diagnostic runs retain their original numerical behavior and limitations |
| Regeneration decision | Diagnostic scalar experiments only |

### M3-CELL-04 — Preserve one-sided cell boundaries in local profiles

| Field | Value |
|---|---|
| Kind | `geometry_or_orbit_change` in the opt-in local raster profile |
| Components affected | Scalar terrain horizon, sampled dominant edge and conditional power |
| Before behavior | Uniform distances could skip cell-entry extrema even at 7.5 m spacing |
| After behavior | Explicit cell_intervals mode retains both boundary heights, interior points and analytic horizon extrema; example enables it; receiver endpoint at/below antenna is excluded as a separate knife edge |
| Validation evidence | 249-test regression; same-raster horizon comparisons and TLE replay in fourth-batch M3 report |
| Current generated maps change | `no` — existing map path unchanged; new scalar terrain results change when selected |
| Published benchmark results change | `no` — no published outputs changed |
| Existing dataset impact | Prior scalar runs retained with original settings; no retroactive accuracy certification |
| Regeneration decision | Diagnostic scalar runs only; no dataset regeneration |

### M3-SAMPLING-03 — Cell-interval horizon audit and optional power guard

| Field | Value |
|---|---|
| Kind | `metadata_or_gate_only` for an explicit scalar output gate |
| Components affected | M3 sampling diagnostics and optional M1 terrain-conditioned power availability |
| Before behavior | Complete sampled profiles could produce known scalar power without a horizon sampling audit |
| After behavior | Explicit horizon tolerance rejects known loss/power when a cell-interval raster comparison fails; diagnostic sampled loss retained; example terrain config enables this guard |
| Validation evidence | 233-test regression; three-site sensitivity matrix and archived real TLE guard replay in `reports/m3/progress.md` |
| Current generated maps change | `no` — legacy map path unchanged; scalar availability changes only when guard enabled |
| Published benchmark results change | `no` — no published outputs changed |
| Existing dataset impact | Historical scalar runs retained as unguarded diagnostics, not promoted to converged reference results |
| Regeneration decision | No dataset regeneration; archived scalar inputs replayed for guard verification only |

### M3-LINK-02 — Declared GeoTIFF/geoid inputs and optional M1 local loss

| Field | Value |
|---|---|
| Kind | `geometry_or_orbit_change` and explicit scalar propagation extension |
| Components affected | GeoTIFF height interpretation, EGM2008-to-ellipsoid conversion, optional M1 local loss |
| Before behavior | M3 accepted only local in-memory grids and did not affect M1 powers |
| After behavior | File-bound heights and hashed local geoid grid; local terrain replaces the disabled scalar local component exactly once; incomplete terrain keeps power unavailable |
| Validation evidence | 220-test regression; `tests/test_terrain_integration.py`; real paired run in `reports/m3/progress.md` |
| Current generated maps change | `no` — legacy map path unchanged; new opt-in scalar sequences only |
| Published benchmark results change | `no` — no existing dataset or benchmark outputs changed |
| Existing dataset impact | No reclassification of prior outputs; real DSM experiment remains conditional on declared source lineage and local-radius model |
| Regeneration decision | not performed |

### M3-PROFILE-01 — Explicit local sampled terrain baseline

| Field | Value |
|---|---|
| Kind | `physics_model_correction` in a new isolated experimental solver |
| Components affected | Local DEM profiles, sampled horizon, signed clearance and dominant knife-edge loss |
| Before behavior | Only legacy raster directional occlusion and clipped positive-excess knife-edge losses |
| After behavior | New explicit-radius profile path records nodata/extent gaps, optional curvature once, Fresnel clearance and raw/used loss; legacy unchanged |
| Validation evidence | `tests/test_terrain_profiles.py`, `reports/m3/progress.md`; full 205-test regression |
| Current generated maps change | `no` — new solver not connected to old map generation, no maps regenerated |
| Published benchmark results change | `no` — no existing outputs changed |
| Existing dataset impact | Prior validation states retained; controlled profile records are not reference maps |
| Regeneration decision | not performed |

### M1-01 — Unified scalar geometry and TLE experiments

| Field | Value |
|---|---|
| Kind | `geometry_or_orbit_change` |
| Components affected | New scalar ECEF/ENU geometry, TLE selection, antenna gain, shared scalar budget |
| Before behavior | Synthetic pilot and geometric explorer had separate numerical entry points. |
| After behavior | Fixed positions, artificial directions and TLE candidates share an explicit scalar link contract; stale/missing/failed states are retained. |
| Validation evidence | `reports/m1/acceptance.md`, `tests/test_m1_links.py`, `tests/test_orbit_link.py`; existing legacy regression retained |
| Current generated maps change | `no` — legacy map path unchanged; no existing maps regenerated |
| Published benchmark results change | `no` — no dataset or benchmark outputs changed |
| Existing dataset impact | Existing validation states retained; new scalar records are not reference maps |
| Regeneration decision | not performed |

### GATE-01 — Reference validation and provenance gate

| Field | Value |
|---|---|
| Kind | `metadata_or_gate_only` |
| Components affected | validation, release policy, documentation |
| Before behavior | 仓库没有可执行reference门禁；Round 0初版门禁仍可能仅凭global checks升级任意artifact。 |
| After behavior | 具体frame必须同时通过required checks与metadata/provenance registration；regeneration另需完整release evidence和独立用户批准。 |
| Validation evidence | `tests/test_reference_validation.py`, `tests/test_release_policy.py` |
| Current generated maps change | `no` |
| Published benchmark results change | `no` |
| Existing dataset impact | 既有terrain-enabled legacy output仍为`invalidated_by_CF_01`；其他无provenance output为`legacy_unvalidated`。 |
| Regeneration decision | prohibited |

### PILOT-01 — Independent analytic link and sample audit

| Field | Value |
|---|---|
| Kind | `unknown_numerical_risk` for the new isolated solver; no change to existing execution paths, as checked below |
| Components affected | pilot config, scalar budget, relative ENU geometry, legacy label adapter, run records |
| Before behavior | No executable pilot path or structured single-link result with explicit missingness. |
| After behavior | New experiment entry computes synthetic scalar links and audits declared old arrays/DEM windows; legacy CLI and equations unchanged. |
| Numerical detail | Pilot FSPL uses legacy one-metre formula plus distance scaling to avoid legacy sub-metre clamping; legacy function itself is unchanged. Unknown effects do not become zero. |
| Validation evidence | `tests/test_pilot.py`, unchanged legacy characterization and CF-01 xfail; `reports/week1/reproducibility.json` |
| Current generated maps change | `no` — old execution path unchanged; no maps regenerated |
| Published benchmark results change | `no` — no existing dataset or benchmark outputs changed |
| Existing dataset impact | Existing validation states retained; external golden arrays remain `legacy_unvalidated` |
| Regeneration decision | not performed; pilot results are not reference artifacts |

## Historical Pending Entry

以下保留修复前的计划记录；CF-01 的现行状态见后面的 CF-01-FIX 条目。完整地形 profile/raw-used 扩展仍未完成。

### CF-01 — Receiver-relative terrain visibility correction

| Field | Expected value |
|---|---|
| Kind | `physics_model_correction` |
| Components affected | terrain, diffraction |
| Before behavior | legacy horizon comparison遗漏receiver绝对海拔。 |
| After behavior | 待task14实现receiver-relative terrain profile并保留raw/used diffraction loss。 |
| Expected current generated maps change | `yes` for terrain-enabled output |
| Expected published benchmark results change | `possibly`；仓库缺少既有published artifact provenance，不能进一步收窄。 |
| Current status | not implemented; strict xfail remains active |
| Regeneration decision | prohibited |

后续每个数值相关提交都应新增记录；不得通过覆盖既有条目来隐藏before/after lineage。

## Applied Correction in v0.1.1

### CF-01-FIX — Receiver-relative obstruction horizon

| Field | Value |
| --- | --- |
| Kind | `physics_model_correction` |
| Components affected | terrain horizon, diffraction input; explicit ground receiver semantics for building rasters |
| Before behavior | Receiver absolute elevation was omitted; a 500 m flat plane could create false blockage. |
| After behavior | Compare obstacle height against receiver elevation plus AGL height and ray slope; remove common datum offset; keep tangent rays clear within roundoff tolerance. Invalid surface values fail explicitly. |
| Validation evidence | `tests/test_terrain_regression.py`: translated flat surfaces, relative ridge boundary, AGL response, datum invariance, building receiver semantics and invalid inputs; legacy no-terrain characterization remains passing. |
| Current generated maps change | `yes` if terrain-enabled maps are recomputed with corrected code; existing files are not rewritten |
| Published benchmark results change | `possibly`; affected published artifact provenance is unavailable |
| Existing dataset impact | Previously invalidated artifacts remain invalidated; repaired code does not upgrade their status |
| Remaining scope | Extended terrain profiles, curvature, nodata policy in the old loader, raw/used diffraction and reference cap still need validation |
| Regeneration decision | No formal dataset regeneration performed |
