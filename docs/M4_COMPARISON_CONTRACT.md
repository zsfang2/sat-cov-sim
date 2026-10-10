# M4 / E2 三类模型比较契约 v1

冻结：2026-10-10，G07；实现基线 `8bc752c`。本文件与 [E2 配置](../configs/m4_e2.yaml)在 G08 运行结果产生前冻结。
G06 已正式接受[有限范围 M3 软件基线](../reports/m3/acceptance.md)，原计划 AC-7/11 尚未因本设计完成。
独立分析见 [G07 审查](../reports/m4/design-review.md)，来源与调用身份见 [design-sources.json](../reports/m4/design-sources.json)。

## 三类角色和比较边界

| role_id | 实现选择 | 正常输出 | 不能声称 |
|---|---|---|---|
| sky_horizon_outline_v1 | cell_horizon 的天空轮廓与仰角比较 | 地平线、限制距离、遮挡/清晰/未知 | 不输出地形损耗或功率；不把 blocked 换成任意 dB |
| m3_current_single_edge_v1 | 现有 evaluate_profile / TerrainContext 的主导单刀刃 | LOS、raw/used 损耗、条件功率 | 不是旧 reference 的 scheduler/beam/weather/RNG 全流水线验收 |
| reference_multi_edge_deygout_v1 | 单独实现的递归主导多刀刃数值模型 | 逐边损耗、递归证据、raw/used、条件功率 | 不是 M3 加密别名，不是电磁实测真值，不保证比单刀刃更准确 |

三路必须同时存在。天空角色的 `local_loss.status=not_applicable`、`received_power.status=not_applicable`，value=null；visibility 可为已知。
它参与 LOS 状态比较和失败分母，不参与 dB/功率误差。另两路才进行损耗、功率、门限比较。仅有两路或给天空角色伪造衰减，不能通过验收。

三路均继承同一地形、接收机、方位、仰角、距离、频率、曲率和有限半径限制。只把 local 分量替换为各自模型，FSPL、EIRP、接收增益和其他分量共用 M1 的标量平均功率口径。无相位合成、随机快衰落或服务调度。

## 参考算法和来源

单刀刃近似依据 [ITU-R P.526-16 §4.1](https://www.itu.int/dms_pubrec/itu-r/rec/p/R-REC-P.526-16-202511-I%21%21PDF-E.pdf)。多边分区思想与检查案例依据 [NTIA TR-26-580 §3.3.3、表 2、附录 C](https://its.ntia.gov/publications/download/TR-26-580.pdf)。原 Deygout 1966 论文仅作书目来源，原文未直接访问，不能宣称逐式复现原论文或实现完整 ITU 标准。NTIA 的比较也说明多边启发式在部分几何下会高估损耗。

本工程冻结一个明确变体 `recursive_dominant_edge_positive_branch_v1`：

1. 在原始直达射线坐标系保存有限域候选 (s,h)。s 为沿射线投影距离，h 为有符号法向高度，端点 (0,0)、(L,0)。地形曲率已在剖面中处理一次。射线后方且低于射线的点排除；非前向的正障碍和超出发射端的障碍按不适用返回。
2. 每个分区 [a,b] 按端点直线计算候选相对高度，沿固定 s 轴计算左右距离与 Fresnel 参数。选最大参数，完全相等时选最小 s。单边公式由参考模块独立实现，不调用 M3 的损耗函数或极值求解器。
3. 无候选贡献零；最大参数 ≤−0.78 时该分区零损耗；介于 −0.78 与 0 时只计该主导边后停止；大于 0 时计主导边并递归左右分区。固定轴距离及正主导分支停止是本变体的近似，不宣称完整复现所有 Deygout 版本。
4. raw 为各分区损耗之和，最后只截顶一次。记录选中边、层数、访问节点和终止原因。点数/深度/节点超限返回 resource_limit，不把提前终止的部分和当已知结果。阈值见配置。

对于栅格，公共剖面保持 cell_intervals 的边界两侧与内部采样；生成初始射线的驻点候选作为公共几何候选补充，不能在参考模块复用 M3 损耗判定。保存原剖面、公共候选及其哈希。参考模块按 s 排序；同 s 取最高 h，记录合并数量，声明投影轮廓近似。不得静默填补 nodata 或半径外地形。M3 保持现有计算接口；G08 必须证明适配前后 M3 输出一致。栅格三路差异同时涉及各模型内的数值处理，必须配套加密表，不能把全部差异称为真实模型误差。

另设纯离散刀刃案例，所有模型获得相同明确坐标列表，用于隔离多边累加与单主导边的区别。V0 单/双边公式直接写解析预期；NTIA 表 2 的四边几何用于额外外部数值检查。表格舍入比较容差 0.05 dB，不替代 T07 解析测试的 1e-6 dB 与既有密集表达的 2e-6 dB 容差。

## 输入、身份与输出结构

使用嵌套结构而非把所有字段平铺；下列对象的字段均必需，可为有解释的 null，禁止默默缺字段。

| 对象 | 必需字段 / 约束 |
|---|---|
| identity | schema_version、sample_id、candidate_id、timestamp_utc、pass_id、satellite_id、scene_id、query_id、pair_id、config_hash、input_checksum；合成时间/卫星无适用值可 null |
| geometry | azimuth_deg、elevation_deg、slant_range_m、geometrically_above_local_horizontal、receiver_lon_deg、receiver_lat_deg、receiver_ellipsoid_height_m、height_above_surface_m；有限数、角度范围、UTC 时间 |
| terrain | source_id、grid_sha256、grid_geometry、vertical_datum、surface_type、native_spacing_m、radius_m、step_m、sampling_method、effective_radius_m、profile_sha256、candidate_sha256 |
| budget | frequency_hz、power_mode、eirp_dbm、transmit_power_dbm、transmit_gain_dbi、receiver_gain_dbi、antenna_model_id、pointing、mean_power_definition、nonlocal_components、threshold_offsets_db |
| model | role_id、version、model_family、solver_source、code_commit、source_fingerprint、included_effects、excluded_effects、evidence_level、reference_eligibility、independence_limits |
| result | status、failure_kind、reasons、visibility、horizon_deg、limiting_distance_m、local_loss、raw_loss_db、used_loss_db、loss_cap_db、cap_triggered、received_power、margin_by_threshold、terrain_contract、warnings |
| resources | wall_time_s、point_count、node_count、depth、process_peak_rss_kib；不可逐角色归因的 RSS 明确标 process_shared，不以进程高水位差冒充单模型内存 |

`local_loss` 和 `received_power` 复用 Quantity 的 value/unit/status/reason；单位分别 dB/dBm。不可用值必须 null。`visibility` 独立取 clear_within_radius/blocked/unknown/not_applicable。

query_id 绑定物理查询与场景；pair_id 绑定查询、地形/剖面和本次公共参数，不含 role_id。模型结果身份另含 role/version/source_fingerprint。任何频率、位置、高度、网格、曲率、半径、步长、天线、平均功率或输入身份变化均不得错配。不同步长的加密比较用同 query_id 并验证除了指定变化因子其余字段相同。

共享预算效应槽为 free_space、gas、rain、clutter、other、local；local 只能计一次。各模型的 local 实现标签可以不同，这正是实验变量；其他已包含效应、单位、功率参考和平均方式必须相同。禁止将含 FSPL 的总路径损耗再次塞入 local。

每个 pair_id 必须有三个唯一 role_id。缺角色、重复角色、配对字段不等、非法单位、重复效应视为校验失败；求解失败保留原 pair 的该角色 failed 记录，不删除整个 pair。

## 状态、参考等级与范围

- 数据缺口、采样审计失败、上游缺失、几何不适用、资源拒绝、数值异常沿用明确 failure_kind/reasons。已知遮挡与未知损耗可同时存在。
- 地平线以下：not_applicable；天顶与近端二维剖面不适用：not_computed。所有角色都保留记录。
- full_path_status=not_verified、service_eligibility=unknown、business_threshold_status=undetermined 恒保留；raw 已知不代表全路径功率已验证。
- V0 表示人工构造/解析验证证据；V1 表示较精细数值参考且有针对当前查询的实现/加密证据；V2 要求真实测量元数据，本批无 V2。这不是从 V0 自动升级到物理真值的阶梯。
- 栅格参考需相邻两次步长减半，raw 差均 ≤0.1 dB、LOS/cap 状态相同且三档均完成，才标 `reference_eligibility=eligible_within_tested_discretization`。否则为 unverified 或 unavailable；保留模型数值用于假设对照，但不得纳入“已收敛参考误差”统计。此 0.1 dB 是预冻结的数值诊断量，不是业务精度。
- 单纯复用 M3 并加密只能进入 same_model_discretization，不能作为第三角色或独立物理验证。多刀刃实现也共享源地形与理想刀刃假设，独立性限制必须写入每份报告。

## E2 参数与输出冻结

完整数值见 configs/m4_e2.yaml。人工五类地形固定：flat 全零；single_ridge 第 10 行=42 m；double_ridge 第 10 行=42、第 7 行=72 m；terrace 第 8–12 行=22 m；deep_ridge 第 10 行=502 m。接收机位于中心；原生分辨率 10 m，不因剖面加密而改称高分辨率真值。

基础扫描固定八方位、四仰角、三步长；单因素扫描只改变频率/高度/曲率/cap/半径中的一项，方位 0°、仰角 1/5/30°。特殊失败案例和纯刀刃解析案例另列。合成当前地形高度、其他配置均在结果之前写死，不根据是否有利选案例。

真实补充用 G05 已归档的城市/山前/山区 60 m 网格，固定 3 km 半径、30/15/7.5 m 步长、两高度、八方位、1/5/30°，保持原 DEM/geoid/来源条件。必须验证源运行产物哈希。输入暂不可得时留 missing_input 记录，不伪造已完成真实扫描；本机已存在这些输入，G08 应实际执行。

功率门限为每个查询无 local 损耗的功率加配置中的 −10/−6/−3/0/3/6/10 dB 偏移。它是条件门限扫描，不能称为真实业务要求。

要求归档配置、输入身份、源码、环境、逐 pair/role JSONL、汇总 JSON/CSV、图、资源、失败和校验清单：

1. 三路 visibility 混淆/未知表；仅两路数值损耗/功率可计算，表头明确天空角色无 dB。
2. 当前模型 vs 多边模型：有符号差、MAE、P95、最大差，按场景/仰角/遮挡/频率分组；默认普通误差使用双已知且未截顶配对，截顶 raw/used 专表及全部失败分母另列。
3. 全部门限偏移的条件通过分歧；未知不算通过或失败，独立列出。
4. 同模型三步长加密表与逐查询 V1 eligibility；同时报告模型对照和已收敛参考子集的分母，不能只展示通过子集。
5. raw 散点/差值分布、门限分歧图、三路耗时图；无有利差异也应正常出图。冷数据准备与求解时间分开，运行高水位说明归因限制。

## G08 必须通过的反例

两角色冒充完成；天空遮挡伪造损耗；dBW/dBm 或几何/频率/高度错配；重复 FSPL/增益/local；缺失角色或重复 ID；删除失败/域外/截顶样本；未知算零；未收敛参考升级 V1；同核加密称物理独立；源码/地形身份不一致；半径平台期宣称全路径；达到递归预算仍返回部分损耗为已知；看完结果修改容差。

若实现暴露契约问题，先记录具体原因和变更、保留原失败运行，再在后续轮审查；不得为通过 E2 静默改冻结参数。
