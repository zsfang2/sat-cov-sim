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

## Pending Numerical Changes

下列项尚未应用，不应被解释为当前地图已经改变。

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
