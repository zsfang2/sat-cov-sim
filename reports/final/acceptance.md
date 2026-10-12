# M0–M6 / E1–E4 最终验收账本

2026-10-12。G01–G15 已获独立审查；G16 实现收尾已获 [Round 16 独立审查](implementation-review.md)，等待原生代码审查阶段交接与 Finalize。此处不宣称 RLCR 已完成。绑定不可变计划 [humanize261009plan.md](../../docs/humanize261009plan.md)。

本轮分析见 [独立收尾分析](closure-analysis.md)。机器账本 [acceptance.json](acceptance.json) 为各证据保存 SHA256。以下“已验收”均限于声明的条件研究范围。

| AC | 当前状态 | 实现/证据 | 不能据此推出 |
| --- | --- | --- | --- |
| AC-1 | ready_for_final_gate | 基线、阶段证据与历史/当前状态分离；[closure](../../reports/week1/closure.md)、[acceptance](../../reports/m1/acceptance.md)、[acceptance](../../reports/m3/acceptance.md)、[gate](../../reports/reproduction/gate.md) | G16 实现收尾已审查；代码审查与最终收尾待执行 |
| AC-2 | accepted_in_declared_scope | 来源/配置/环境身份与可恢复源码，小流程新环境复现；[terrain-contract](../../reports/m3/terrain-contract.md)、[direction-table](../../reports/m2/direction-table.md)、[summary](../../reports/reproduction/summary.json) | DEM 拼接履历和 TLE 上游获取未独立认证 |
| AC-3 | accepted_in_declared_scope | M1 三类输入标量几何、链路与分量回归；[acceptance](../../reports/m1/acceptance.md)、[e1](../../reports/m2/e1.md)、[e1-gate](../../reports/m2/e1-gate.md) | 非实际 Starlink 设备规格；非独立轨道真值 |
| AC-4 | accepted_in_declared_scope | M3 区间地形/单刀刃数值与反例；[domain-matrix](../../reports/m3/domain-matrix.md)、[acceptance](../../reports/m3/acceptance.md) | 理想模型、数值诊断，不是实测传播精度 |
| AC-5 | accepted_in_declared_scope | 有界读取、逐查询半径诊断、有限范围输出契约；[bounded-reader](../../reports/m3/bounded-reader.md)、[radius-48km](../../reports/m3/radius-48km.md)、[terrain-contract](../../reports/m3/terrain-contract.md) | 48 km 实验不等于域外无遮挡或全路径充分 |
| AC-6 | accepted_in_declared_scope | M3 来源假设、适用域和条件软件验收；[acceptance](../../reports/m3/acceptance.md)、[acceptance-review](../../reports/m3/acceptance-review.md) | DSM 不等于裸地；不支持几何仍明确返回不适用/未计算 |
| AC-7 | accepted_in_declared_scope | M4 天空轮廓、单刀刃、多刀刃三路统一配对；[e2](../../reports/m4/e2.md)、[e2-gate](../../reports/m4/e2-gate.md) | 共享 DEM/剖面；V1 离散加密不等于真实物理参考 |
| AC-8 | accepted_in_declared_scope | M2 方向表、查询、回退、身份、磁盘缓存及 E1；[direction-table](../../reports/m2/direction-table.md)、[e1](../../reports/m2/e1.md)、[e1-gate](../../reports/m2/e1-gate.md) | 严格回退未带来加速；普通插值无全域误差保证；有限斜距变化使缓存失效 |
| AC-9 | accepted_in_declared_scope | M5 几何/质量事件、未知积分与完整过境 E3；[events](../../reports/m5/events.md)、[e3](../../reports/m5/e3.md)、[e3-gate](../../reports/m5/e3-gate.md) | 12/12 原实验参考通过仅表示已测时间加密收敛；有限采样仍可能漏更窄事件；不是服务调度 |
| AC-10 | accepted_in_declared_scope | M6 等成本固定高度选点、开发/留出隔离、共同参考评价；[selection](../../reports/m6/selection.md)、[selection-gate](../../reports/m6/selection-gate.md)、[e4](../../reports/m6/e4.md)、[e4-gate](../../reports/m6/e4-gate.md) | 保守未知目标；零 regret 不证明真实最优；本轮另修评分表数量边界 |
| AC-11 | accepted_in_declared_scope | E1–E4 研究闭环，失败和无收益/不确定结果保留；[e1-gate](../../reports/m2/e1-gate.md)、[e2-gate](../../reports/m4/e2-gate.md)、[e3-gate](../../reports/m5/e3-gate.md)、[e4-gate](../../reports/m6/e4-gate.md) | 真实 E4 0/72 严格参考合格，不能判定真实正收益或无收益 |
| AC-12 | accepted_in_declared_scope | 可恢复输入/源码/依赖的离线小流程与新 venv；[gate](../../reports/reproduction/gate.md)、[summary](../../reports/reproduction/summary.json)、[README](../../reproduction/README.md) | 仅同主机 CPython3.12/Linux x86_64 新 venv；不是跨平台、独立硬件或全国 DEM 重建 |
| AC-13 | awaiting_native_code_review_and_finalize | 分轮任务、独立分析/实现审查、原生代码审查与收尾；[closure-analysis](../../reports/final/closure-analysis.md)、[gate](../../reports/reproduction/gate.md) | 当前为进入最终门禁的准备记录；不能替代尚未执行的原生代码审查/Finalize |

## 已解决的最后一个接口问题

候选集允许最多 256 个位置，过境注册表允许最多 1000 个总过境且开发/留出均非空。旧评分表另外限制 100,000 行，使合法组合被错误拒绝。本轮改为恰好要求候选数 × 当前划分过境数行，数量上界由两个已验证对象自然限定（单划分至多 256 × 999 = 255,744）。逐行的身份、唯一性、时间分母和未知保留检查不变。100,096 行正例、缺行/多行提前拒绝、等行数重复/外来/错误划分反例均覆盖。

这是 G15 冻结快照之后的 API 边界修复，不改传播公式、门限、事件积分、排序或 E1–E4 历史数据。G15 包及新环境记录继续对应 `70e93f0` 和明确的源码指纹，不伪称在本轮最终 HEAD 上生成。

## 未关闭问题与后续顺序

| 问题 | 当前处理 | 何时继续 |
| --- | --- | --- |
| 真实多刀刃完整过境参考不稳定 | 原 E4 0/72、留出 0/36 合格；收益判断不确定 | 下一研究主线先分析空间离散、候选极值和独立参考，重新冻结新实验，不放宽旧门限 |
| 严格方向缓存没有测得加速 | 保留真实冷/热成本和无有限盈亏平衡 | 有精度依据后再设计可证明误差的近似/重用，不把直接旁路计为缓存加速 |
| 有限地形范围 | 范围外未验证，条件功率与实际服务分离 | 物理结论升级前取得范围/模型证据 |
| 原始数据来源及设备业务标准未知 | DSM/EGM2008 按用户声明；TLE 以归档字节身份恢复；门限等仍为假设 | 获取原始瓦片/处理链、独立观测与真实业务要求后再升级 |
| 新环境仅同主机验证 | CPython3.12、Linux x86_64 新 venv，源和依赖可恢复 | 需要新平台时单独冻结依赖并复验 |
| 旧 reference 专有主线 | scheduler/25°门限/切换与无服务、beam/weather/clutter/RNG、批量 writer/resume、独立重建 benchmark 均保留原账本 | 依据原 CODE_SPEC 与结构计划另立恢复任务，不以本次标量研究框架代替 |

当前剩余执行顺序：原生实现审查 → 原生代码审查及必要修复 → Finalize。基础门禁真正完成以后才安排阶段 demo；本轮没有修改独立前端。未 push、merge、发布或重新生成正式 reference。

本轮验证：选点测试25项通过（0.98 s），全量464项通过（13.79 s）；`output/m6-bound-closure-20261012` 的17项产物哈希核对通过，人工选点/逆转/无收益摘要与旧G13运行逐字节一致。证据见[verification.json](verification.json)。

## 原生阶段交接

Round 16 独立审查接受实现收尾，并复跑 464 项测试，未提出实现缺陷。Humanize 的实现审查通过信号只用于进入代码审查，并不代表整个循环完成：`humanize/SKILL.md` 将两阶段分开，原生 `loop-codex-stop-hook.sh` 在实现阶段收到审查者的通过信号后设置 `review_started`，随即调用代码审查。代码审查有问题则继续修复，无问题后才进入 Finalize。此账本在这些证据产生前保持最终状态待完成；不通过修改状态、跳过审查或取消循环来交接。
