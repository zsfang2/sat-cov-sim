# 有限范围地形结果契约（G03 冻结，G04 待实现）

2026-10-09。依据 [48 km 证据](../reports/m3/radius-48km.md) 和官方分析调用
`.humanize/skill/2026-10-09_08-49-37-2257283-e5eed4fd/output.md`。
本文件冻结下一步接口实现，不冒称当前 API 已包含这些字段。

## 不改变的物理语义

`received_power.status == known` 只表示声明模型、输入与有限半径条件下可计算。
`clear_within_radius`、`coverage_complete`、顶层 `complete` 都不能证明全路径无遮挡。
业务状态仍未知；用户输入的门限可用于条件裕量，但不是经过认证的业务 SLA。
已有 raw/used 损耗、接收功率和物理输入哈希不因增加解释字段而改变。

## 强制结构

所有启用地形的 M1 结果，在顶层、逐记录以及非空 received_power 对象中提供
`terrain_contract`。顶层存公共范围字段，逐记录再加入状态与绑定，功率对象至少含
version/scope/full_path_status；消费者不必从报告文字或其他记录推断功率含义。

公共字段固定为：

| 字段 | 值/约束 |
|---|---|
| version | 1 |
| scope | `finite_radius_conditional` |
| radius_m | 实际使用半径，不能改成最大测试半径 |
| sampling_method / step_m | 实际求解配置 |
| full_path_status | `not_verified`；当前实现没有升级为 verified 的路径 |
| business_threshold_status | `undetermined`；不覆盖输入的诊断门限数值 |
| service_eligibility | `unknown` |
| limitations | 明确有限范围、数值模型和 DSM 非裸地的条件 |

逐记录增加：

- `finite_loss_status` / `finite_power_status`：复用实际求解/预算状态，不从 LOS 推导。
- `failure_kind`：下表枚举；正常条件求值为 null。
- `radius_audit_status`：没有精确配对的外层实验时为 `not_attached`。本批接口不自动加载
  三站点摘要，更不能把它套用到其他频率、天线高度或任意 TLE 时刻。
- `audit_binding`：`sample_id`、`timestamp_utc`、`candidate_id`、
  实际 azimuth/elevation/slant_range/frequency、receiver 椭球高、terrain radius/step、
  grid_sha256/source_id、physical_input_checksum；对这组字段计算 `query_id`。
  无几何时几何字段为 null，仍保留样本/候选/输入身份及失败原因，不伪造可求值方向。

顶层配置身份和 `physical_input_checksum` 不包含执行时间、tile 大小或本契约的冗余字段。
运行归档必须包含这些字段，但旧归档不能回填为已遵守新契约。

## 状态与优先级

| 场景 | failure_kind | 正式功率 | 对外行为 |
|---|---|---|---|
| 错误单位/基准/hash、重复模型、位置不匹配等 | `invalid_input` | 无 | 原 API 抛 ValueError；CLI 失败归档带结构化类别，不产生假结果 |
| 目标/窗口/内存/原生块预算超限 | `resource_budget_exceeded` | 无 | 专用 ValueError 子类，CLI 明确归档；不得降采样或缩半径继续 |
| 低于当地水平面 | `not_applicable` | not_applicable | 保留几何及有限范围声明 |
| TLE 缺失/过期、上游几何未生成 | `upstream_unavailable` | not_computed | 保留候选和绑定的 null 几何 |
| receiver nodata、剖面缺失 | `data_gap` | not_computed | 正式损耗为 null；已发现阻挡证据可保留 |
| 天顶/近端/求解域外 | `unsupported_geometry` | not_computed | 保留原因，不冒充无遮挡 |
| 采样审计未通过 | `sampling_not_verified` | not_computed | 保留诊断损耗，正式损耗撤回 |
| 数值异常/意外 solver 失败 | `solver_failure` | failed 或 not_computed，依原状态 | 不吞掉失败记录 |
| 范围内输入完整、数值可算 | null | known（仅条件功率） | full_path_status 仍 not_verified |

非法输入和资源拒绝发生在构建阶段，优先于任何正常结果；运行阶段首先保留上游
不可用/几何不适用事实，再判数据缺口、域外、采样失败和正常条件值。
`failure_kind` 不取代原来的详细 reason/incomplete_reasons。资源不足不等于数据 nodata。

## 半径审计与绑定边界

分析输出沿用四种有限实验状态：`stable_within_tested_extent`、`changed_with_expansion`、
`insufficient_larger_radius_evidence`、`unknown_missing_or_unsupported_queries`。
候选半径必须比较所有更大测试半径，默认至少两次扩展；最大半径本身不能自证充分。
稳定只说明同一栅格/位置/高度/方位/仰角/频率/距离/曲率/求解器配置内的本次比较，
不是连续方向保证、真实传播精度或全路径证明。

本批 G04 提供每个实际样本的 query binding，并显式报告 `not_attached`；
不接入跨运行外层证据的自动授权/功率升级。以后若接入，必须验证完整物理条件、
输入栅格与求解器身份及方向精确匹配，独立保存证据 hash；不匹配必须拒绝关联。
分析阶段每个查询的 binding_id 已绑定站点、完整矩阵配置、terrain 元数据和数组哈希。

## G04 必须验证

1. 正常有限范围功率数值不变，功率对象就地携带条件声明；physical_input_checksum 不变。
2. 远处山脊、单次平台期、地平线不变但损耗改变、最大半径缺证据都不提升 full_path_status。
3. nodata、采样失败、天顶/近端、TLE 不可用、低于水平面逐项保留对应状态和空值。
4. 资源异常与非法输入分别归档；旧 ValueError 捕获仍有效；不产生假已知功率。
5. 每个候选/时间/方向/频率/高度/网格变化在绑定中可识别，不把分析矩阵摘要自动附到无关查询。
6. CLI/API 和运行归档保持一致；历史记录不自动升级；完整现有回归继续通过。

该契约选择显式限定已知值适用范围，保留有限条件研究能力；它没有证明半径充分，
没有将其未验证状态藏进非结构化备注，也不扩展模型的实际适用域。
