# Dataset Validation and Legacy Status

本文件定义当前仓库的生成物状态和reference release安全门禁。它不改变任何传播公式，也不授权重新生成dataset。

## Current Status

当前源码只能生成legacy单帧coverage result，不能生成`CODE_SPEC.md`定义的完整reference dataset。

审计发现CF-01：`directional_occlusion()`比较terrain horizon时遗漏当前receiver的绝对高程。对于正海拔的平坦DEM，该错误会产生虚假blocked mask和diffraction loss。因此：

- 所有启用legacy terrain path生成的既有输出应标记为`invalidated_by_CF_01`；
- 未启用terrain但缺乏完整provenance的输出应标记为`legacy_unvalidated`；
- 只有required checks全部通过后才可标记为`validated_reference`。

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

门禁实现位于`src/satellite_coverage/domain/validation.py`。当前CLI仍是legacy single-frame接口；未来DatasetWriter和reference CLI必须调用该门禁，不能复制或绕过判定逻辑。

## Known-Failure Evidence

`tests/test_known_failures.py`使用严格xfail记录CF-01：

- 输入为5×5、恒定500 m海拔的平坦DEM；
- elevation为25°，resolution为100 m；
- 正确行为应为无blocked pixel且terrain loss为0；
- legacy实现会错误地产生blocked pixel和diffraction loss。

该测试使用`strict=True`。当未来terrain修复使测试意外通过时，pytest会以XPASS失败，要求维护者显式移除known-failure标记并把测试迁入正常physical validation suite。

## Numerical-Change Record

任何改变radio-map数值的提交必须在commit或迁移文档中记录：

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

## Regeneration Policy

在以下条件全部满足前，禁止把完整dataset regeneration作为普通开发或测试命令执行：

1. terrain、geometry和TLE required checks全部通过；
2. reference config、data source checksums和random-stream derivation已冻结；
3. frame metadata与component maps通过一一对齐测试；
4. small-sequence dry run通过；
5. 已明确legacy dataset的归档/废弃政策；
6. 用户单独批准完整reference regeneration及可能的benchmark重算。
