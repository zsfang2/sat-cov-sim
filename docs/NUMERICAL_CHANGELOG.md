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
