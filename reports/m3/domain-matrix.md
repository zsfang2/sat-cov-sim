# M3 数值与适用域矩阵（G05）

2026-10-09；实现基线 7179bb7，随后修改的精确源码见各运行的 sources.zip 和 environment.json。
本批已完成诊断矩阵及反例修复，**M3 仍待 G06 独立验收**。没有证明当地网格接近真实传播，也没有提高有限半径结果的全路径资格。

## 输入、控制变量与复现

机器汇总：[domain-matrix.json](domain-matrix.json)，包含两组运行的完整产物哈希、配置、资源、预期/实际状态；汇总前已逐个核对产物 SHA-256。

```bash
bash scripts/python_geo.sh scripts/verify_terrain_domain.py \
  --dem ../Satellite-Ground-Radiomap/data/l2_topo/china_dem_30.tif \
  --geoid output/geoid/egm2008-complete.tif \
  --output output/m3-domain-20261009
bash scripts/python_geo.sh scripts/verify_terrain_cases.py \
  --output output/m3-domain-cases-20261009
bash scripts/python_geo.sh -m pytest tests -q
```

复跑需要指定新的输出目录。真实输入沿用 [Copernicus 声明](copernicus-source.json)与 [geoid 身份](egm2008-grid.json)，源 DEM 哈希 `d796a25eae49bb4390f4905a2a887fe8e550d1bfcc27b74f359e5684285eee5b`；仅在声明的 EGM2008 高度链条件下解释。没有把 DSM 当裸地。

三个固定地点，12 km 半径，2/10 m 高于表面；24 个方位、0/1/5/30/80° 仰角，550 km 距离、14.5 GHz。每种方法每站 240 查询（48 条高度/方位剖面），16 种设置，每站 3840，共 **11520 查询**。所有逐查询 raw/used、截顶、状态和原因均保留。0.1°/1 dB 只是诊断阈值，未据此接受真实精度。

- 原生：从射线点反投影到源栅格，按原像元 floor 索引读取，源中心处做 geoid 转换；不先经过当地栅格。每条射线窗口最多 262144 格。它仍是离散点诊断，未解析源像元的投影边界，不是原生连续地形的精确参考。
- 当地网格：分别独立读取 32/40/60 m，保持同一个源 DEM/接收点；加载器禁止比源最大间距更细的网格。本批没有上采样为独立高分辨率真值。
- 步长：原生点与 60 m 当地网格分别比较 30/15/7.5 m；当地网格同时列 uniform 和 cell_intervals。原生→当地比较固定 15 m；当地网格分辨率比较固定区间模式与 15 m 步长。
- 曲率：60 m 区间模式分别 none、R=6371000 m、4R/3；另在同一 15 m 当地采样点比较二次曲率与显式球面坐标。

## 分离后的实测差异

以下是最大绝对差；损耗仅使用双方均已计算的配对。未知分母完整列出，不能用最大差代替全体误差。

| 对照 | 城市 | 山前 | 山地 |
|---|---:|---:|---:|
| 原生→60 m 当地：地平线差 ° | 12.41943 | 0.30992 | 19.04555 |
| 原生→60 m 当地：raw 差 dB | 34.15136 | 5.94318 | 37.81693 |
| 上行有效配对 / 240 | 209 | 216 | 198 |
| 原生→32 m 当地：raw 差 dB | 25.35301 | 1.76667 | 26.97546 |
| 60→32 m 区间网格：地平线差 ° | 13.54062 | 0.21150 | 15.08967 |
| 60→32 m 区间网格：raw 差 dB（240/240） | 32.40246 | 5.94812 | 37.68910 |
| 原生 15→7.5 m：raw 差 dB | 21.02680 | 0.11255 | 26.79226 |
| 60 m uniform 15→7.5 m：raw 差 dB | 1.56012 | 0.06070 | 4.30463 |
| 60 m cell_intervals 30/15→7.5 m：地平线/raw 差 | 0 / 0 | 0 / 0 | 0 / 0 |
| none→R 曲率：raw 差 dB（240/240） | 4.88839 | 7.76593 | 3.05439 |
| 4R/3→R 曲率：raw 差 dB（240/240） | 1.37646 | 2.16719 | 0.83604 |
| 球面→二次：raw 差 dB | 0.0000929 | 0.0054467 | 0.0029604 |
| 球面对照有效配对 / 240 | 216 | 216 | 198 |

真实矩阵无截顶；每个 variant 的已知损耗数就是 cap_denominator。区间模式所有设置均为 240/240；uniform/native 的部分高仰角点投影超出前向刀刃域，原有明确 `obstacle_projection_outside_link` 保留，未知不能当零。每条 comparison 的 unavailable_pairs 和 state_disagreements 可查机器文件。

**这些结果不支持“60 m 当地网格已满足 0.1°/1 dB”这一判断。** 即使 32 m 与源间距相近，源像元边界与当地网格边界仍不同；接收机附近高度跳变尤其敏感。原生采样自身也未在所有方向收敛，因此不把它当真值。区间剖面解决的是固定当地网格内边界与极值遗漏，不能消除重采样的地形表达差异。M4/E2 必须保留网格/来源条件与精细参考的独立性限制。

机器汇总中的 horizon 计数按查询重复各仰角，分母为 240，不是 240 条独立剖面。`max_point_height_delta_m` 表示左侧当地采样点相对同距离原生点的高度差，仅用于原生/当地诊断，不是 uniform 两步长之间的高度差。

## 曲率近似适用性

将 d 解释为弧长、z 为相对接收点表面的地形高度，显式球面坐标采用：x=(R+z)sin(d/R)，y=z cos(d/R)-2R sin²(d/2R)-AGL。生产模型仍采用 x=d、y=z-AGL-d²/(2R)。这是一项声明几何模型之间的比较，不是 WGS84 椭球或大气真实性认证。

机器文件另列 d=3/12/24/48/100 km、R=1000/6371/8494.667 km 的几何差。R=6371 km、48 km 时，纯球面水平坐标差约 0.45410 m，曲率下降量差约 0.0008553 m；到 100 km 时分别约 4.10609 m / 0.01611 m。允许的极限 R=1000 km、100 km 时增大为约 166.58335 m / 4.16528 m，不能据 12 km 结果对全适用域宣称小误差。实际折射系数仍是独立假设；none/R/4R/3 的损耗差远大于本批球面二次近似差。

## 特殊几何与反例修复矩阵

人工输入的每个数组均已归档；cases.json 保存配置身份、预期、实际完整结果或预期拒绝。全部 16 项通过，详情见机器汇总。独立预期来自直接几何/定义和既有解析测试，不来自生产输出回填。

| 检查 | 预期与实际 | 修复 / 证据 |
|---|---|---|
| 平地 0°、极低仰角、89.9° | 已知有限范围损耗；89.9° 为 0 | 修复全部前向候选为空时无说明的 not_computed；test_flat_supported_elevations_are_finite |
| 区间两端投影在后、内部投影在前 | 内部前向候选不能被遗漏，正损耗 | 新保留投影二次函数顶点；test_projection_vertex_is_retained_between_behind_endpoints |
| 完全没有可用候选的输入剖面 | 未计算并说明 no_forward_knife_edge_candidates | 新明确空域原因，禁止默默完整；test_empty_forward_domain_has_reason |
| 天顶 | 未计算，zenith_profile_not_supported | 保留当前二维方位剖面不支持天顶的边界；没有虚构方向 |
| 100 m 近端、水平距离等于半径、89.999° | 未计算，要求缩短剖面 | 保留 transmitter-inside-radius 原因；不计算穿过发射端的局部刀刃 |
| 单/双山脊、提高接收机、统一基准平移 | 遮挡 / 提高后清晰；raw 对基准平移不变 | 归档场景；既有解析和 2e-6 dB 独立密集表达回归继续通过 |
| raw/used 与 cap | 人工 ridge cap=3 明确触发，raw 保留 | 真实全部未触发亦保留有效分母 |
| 精确像元边界、原生 mask/scale、射线/接收点缺口 | 半开索引；缺口保留；未知不归零 | test_cell_boundary_half_open_and_gaps、test_native_terrain；归档 3 个缺口场景 |
| NaN/Inf 参数与坐标 | ValueError，JSON 不含 NaN/Inf | 显式有限坐标检查；test_nonfinite_query_and_sample_rejected |
| 有限极小频率、极端高程差导致溢出 | 明确 finite numerical range 拒绝 | 修复无限 Fresnel 半径仍给已知损耗；test_finite_but_unrepresentable_fresnel_values_rejected、height overflow |
| 曲率仅一次、原始高度要求 | 拒绝预先施加曲率的网格 | 既有 test_curvature_once_and_effective_radius；本批球面/二次独立公式测试 |

新增 21 项测试；全量 **330 passed in 8.81 s**。数值范围拒绝不是缺失地形，不会把溢出数据作为 nodata 转成无遮挡。修复对历史产生数值影响的可能性记录在 M3-DOMAIN-09；既有归档不会重写或自动升级。

另用 verify_terrain_guard.py 回放原真实 TLE/DSM 运行到 output/m3-domain-guard-20261009；60/15/7.5 m 三档各 571 条记录、38 条已知条件功率、0 个 guard 失败。与上一版 output/m3-contract-guard-20261009 的三个完整 links JSON 及其文件哈希均完全相同；比较与新运行产物清单已加入机器汇总。这保护已测正常域，不抵消人工反例中有意发生的状态/数值修复。

## 资源与未关闭项

真实矩阵 81.33 s、峰值 RSS 184980 KiB（约 180.64 MiB），包含文件身份核对、源码归档和全部查询，未控制系统页缓存，不作为 SLA。大输入留在本地，人工数组和运行源码可从运行归档恢复；G15 的完整小型可移植工作流尚未交付。

半径独立使用 [48 km 证据](radius-48km.md)：城市/山前还在变化，全路径未验证。天顶与近端仍是明确不适用域；原生边界连续求解、真实物理参考、源拼接链和业务阈值没有在本批解决。G06 需要分别判定实现、数值、来源和真实性，不能用这批测试通过覆盖这些限制。
