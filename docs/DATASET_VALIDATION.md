# Dataset Validation and Legacy Status

本文件定义当前仓库的生成物状态和reference release安全门禁。它不改变任何传播公式，也不授权重新生成dataset。

## Current Status

当前源码只能生成legacy单帧coverage result，不能生成`CODE_SPEC.md`定义的完整reference dataset。

审计发现CF-01：`directional_occlusion()`比较terrain horizon时遗漏当前receiver的绝对高程。对于正海拔的平坦DEM，该错误会产生虚假blocked mask和diffraction loss。因此：

- 所有启用legacy terrain path生成的既有输出应标记为`invalidated_by_CF_01`；
- 未启用terrain但缺乏完整provenance的输出应标记为`legacy_unvalidated`；
- 只有required checks全部通过，并且具体frame具有完整metadata/provenance时，才可通过注册边界标记为`validated_reference`。

## Artifact Lifecycle

| Status | Meaning |
|---|---|
| `legacy_unvalidated` | provenance未知、不完整或尚未通过reference registration；这是未知legacy output的保守默认值。 |
| `invalidated_by_CF_01` | 已知启用受CF-01影响的legacy terrain path；不能原地升级为reference。 |
| `reference_candidate` | 已通过`qualify_reference_candidate()`确认具有完整frame evidence、内容identity和provenance，正在等待required physical checks与registration。 |
| `validated_reference` | 只可由`register_reference_frame()`产生；global checks和具体frame evidence均已通过。 |
| `superseded_reference` | 曾经validated、现已由可识别的新reference替代；保留历史lineage但不作为当前reference。 |

允许的状态迁移为：

- unknown artifact → `legacy_unvalidated`；
- `legacy_unvalidated` → `reference_candidate`，仅当完整evidence能够恢复并验证；
- `reference_candidate` → `validated_reference`，仅通过注册边界；
- `validated_reference` → `superseded_reference`，且必须记录replacement identity；
- 任意非invalidated状态 → `invalidated_by_CF_01`，当后续证据确认其使用了受影响terrain path。

禁止`invalidated_by_CF_01`原地迁移到`validated_reference`。修复代码后产生的地图是具有新checksum和provenance的新artifact，不是对旧artifact改标签。任何仅凭全局test/check结果、没有具体frame evidence的promotion同样禁止。

## Required Reference Checks

最小release gate要求以下检查全部为`passed`：

| Check | Current status | Blocking reason |
|---|---|---|
| `terrain` | failed | CF-01以及reference profile/cap尚未完成 |
| `geometry` | not_run | 尚未实现统一WGS-84/ECEF/ENU pixel geometry |
| `tle` | not_run | 尚未实现TLE去重、epoch policy和完整provenance |

任何`failed`、`not_run`或缺失的required check都会触发`ReferenceGenerationBlocked`。

```python
from satellite_coverage.domain.validation import ReferenceValidationReport

report = ReferenceValidationReport()
report.require_reference_ready()  # raises ReferenceGenerationBlocked
```

全局检查通过本身不能升级任何legacy文件。`artifact_status()`只负责legacy分类；正式状态必须由具体frame候选经过`register_reference_frame()`产生：

```python
from datetime import datetime, timezone

from satellite_coverage.domain.validation import (
    GenerationStatus,
    ReferenceFrameCandidate,
    register_reference_frame,
)

candidate = ReferenceFrameCandidate(
    map_path="frames/region-a/000012/received_power_dbm.npy",
    map_checksum="sha256:...",
    component_paths=(),  # 空tuple表示显式声明无component输出；None表示未声明
    region_id="region-a",
    frame_index=12,
    timestamp_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
    config_checksum="sha256:...",
    source_checksums=(("dem", "sha256:..."), ("tle", "sha256:...")),
    code_version="git:...",
    generation_status=GenerationStatus.COMPLETE,
    terrain_enabled=True,
)
status = register_reference_frame(candidate, report)
```

缺少任一frame identity、UTC timestamp、map/config/source checksum、component输出声明、code version、完成状态或terrain声明时，注册会触发`ArtifactRegistrationBlocked`。因此，即使required checks已经通过，裸NPY也不能成为validated reference。

如果candidate声明其prior status为`invalidated_by_CF_01`、`validated_reference`或`superseded_reference`，注册同样拒绝。后两者必须通过未来writer的replacement/supersession流程管理，不能重复注册或覆盖。

门禁实现位于`src/satellite_coverage/domain/validation.py`。它目前是storage-neutral domain boundary，不会自行读取或写入manifest。当前CLI仍是legacy single-frame接口；未来DatasetWriter和reference CLI必须调用该门禁并持久化同等证据，不能复制或绕过判定逻辑。

## Known-Failure Evidence

`tests/test_known_failures.py`使用严格xfail记录CF-01：

- 输入为5×5、恒定500 m海拔的平坦DEM；
- elevation为25°，resolution为100 m；
- 正确行为应为无blocked pixel且terrain loss为0；
- legacy实现会错误地产生blocked pixel和diffraction loss。

该测试使用`strict=True`。当未来terrain修复使测试意外通过时，pytest会以XPASS失败，要求维护者显式移除known-failure标记并把测试迁入正常physical validation suite。

## Numerical-Change Record

详细记录与当前条目见[`NUMERICAL_CHANGELOG.md`](NUMERICAL_CHANGELOG.md)。任何可能改变radio-map或benchmark数值的提交必须在commit或该迁移文档中记录：

| Field | Required content |
|---|---|
| Change ID | 对应audit finding或稳定的问题编号 |
| Components affected | geometry、beam、terrain等具体component |
| Before behavior | legacy公式、状态或数值摘要 |
| After behavior | corrected公式、状态或数值摘要 |
| Expected map impact | Yes / No / Possibly以及方向和范围 |
| Existing dataset impact | validated / invalidated / unable to verify |
| Validation evidence | synthetic fixture、reference comparison和测试命令 |
| Regeneration decision | prohibited / pending approval / approved |

影响字段只能使用`yes`、`no`或`possibly`。物理、geometry/orbit、scheduler/frame identity、RNG/realization以及unknown change默认至少为`possibly`，除非独立数值证据证明为`yes`或`no`。只要map impact不是`no`，在仓库尚无可追踪published benchmark provenance时，benchmark impact不得声明为`no`。

## Regeneration Policy

`ReferenceValidationReport.require_reference_ready()`只回答terrain/geometry/TLE检查是否通过，不代表允许重新生成数据。完整regeneration必须另行调用`require_regeneration_ready(evidence, approval)`，并在以下条件全部满足前保持blocked：

1. 全部计划acceptance criteria通过、pending reference decisions已解决且P0 findings全部关闭；
2. terrain、geometry和TLE required checks全部通过；
3. canonical reference config checksum、data source checksums、random-stream derivation、code version、environment fingerprint和writer schema version已冻结；
4. frame metadata与component maps通过一一对齐测试；
5. small-sequence dry run通过；
6. 已明确legacy dataset的归档/废弃政策，并确认numerical change inventory完整；
7. 用户通过独立的`RegenerationApproval`记录明确批准完整reference regeneration；
8. 只要任一change record对published benchmark的影响为`yes`或`possibly`，approval必须明确确认benchmark重算风险。

普通unit/integration test全部通过不能替代第7项批准。approval存在也不能替代前6项evidence。当前仓库不满足上述条件，完整reference regeneration仍被禁止。
