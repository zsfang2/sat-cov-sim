# Satellite Coverage Sim 代码与物理模型审查报告

审查日期：2026-09-10  
规范基线：[`CODE_SPEC.md`](CODE_SPEC.md)  
审查范围：仓库源码、测试、示例配置，以及示例配置引用的 TLE/DEM 文件的只读 spot check

## Executive Summary

审计结论：**当前仓库不符合 `CODE_SPEC.md` 所定义的 SatRM reference dataset generator。** 它实际是一个单区域、单时刻、单卫星的轻量覆盖图脚本。

发现 1 个 Critical bug：地形遮挡判据错误。示例西安 DEM 下，99.46% 像素被误判遮挡，地形损耗中位数达到内部 60 dB 上限。**如果已有数据通过当前 terrain 路径生成，接收功率图很可能失效。**

本次仅进行了只读审计和内存内数值检查；未修改物理模型、随机种子，也未重新生成 dataset。

# 1. Repository Architecture

## Repository inventory

| 文件 | 实际职责 |
|---|---|
| [`src/satellite_coverage/cli.py`](src/satellite_coverage/cli.py) | 单次运行入口，保存固定文件名 NPY/PNG |
| [`src/satellite_coverage/scenario.py`](src/satellite_coverage/scenario.py) | 单体式场景编排和链路预算 |
| [`src/satellite_coverage/coordinates.py`](src/satellite_coverage/coordinates.py) | 球形地球近似的本地二维网格 |
| [`src/satellite_coverage/geodata.py`](src/satellite_coverage/geodata.py) | DEM 窗口读取和建筑矢量栅格化 |
| [`src/satellite_coverage/tle.py`](src/satellite_coverage/tle.py) | TLE 解析、Skyfield SGP4、最高仰角卫星选择 |
| [`src/satellite_coverage/propagation.py`](src/satellite_coverage/propagation.py) | FSPL、大气经验式、本地几何、栅格遮挡、刀刃绕射、建筑损耗 |
| [`tests/test_core.py`](tests/test_core.py) | 3 个基础单元测试 |
| [`examples/xian.yaml`](examples/xian.yaml) | 单区域、单时刻示例，不是 reference config |

真实执行图：

```text
sat-cover
└─ cli.main()
   ├─ CoverageScenario.from_yaml()
   └─ CoverageScenario.run()
      ├─ LocalGrid()
      │  └─ enu_mesh()
      ├─ TleCatalog(tle_file)
      │  └─ best_visible(timestamp, center_lat, center_lon)
      │     ├─ Skyfield EarthSatellite / SGP4
      │     ├─ center topocentric altaz
      │     └─ select maximum elevation
      ├─ link_geometry()
      │  └─ center look-angle → flat local Cartesian pixel geometry
      ├─ fspl_db()
      ├─ atmospheric_loss_db()
      ├─ optional read_dem()
      │  └─ directional_occlusion()
      │     └─ knife_edge_loss_db()
      ├─ optional rasterize_buildings()
      │  └─ urban_losses()
      ├─ scalar EIRP link-budget composition
      └─ CoverageResult
         └─ cli saves fixed-name NPY files and one PNG
```

仓库内不存在实际 frame loop、stateful scheduler、weather、clutter、beam model、dataset writer、metadata writer、split、sensor sampler、preprocessing 或 evaluation。

# 2. Specification-to-Code Matrix

| Module | Intended Behavior | Actual Implementation | Status | Code Evidence |
|---|---|---|---|---|
| Configuration | 统一 reference config，4 regions、768²、20 s、2160 frames | 无 schema；示例为 1 region、256²、单时刻、10°、55 dBm EIRP | [Spec-Code Mismatch] | [`xian.yaml`](examples/xian.yaml), [`scenario.py:36`](src/satellite_coverage/scenario.py#L36) |
| DEM/grid | 100 m 网格，明确 CRS，lat/lon/elevation、ground ECEF | float64 球形近似 lat/lon；无 ground ECEF；DEM 为 float32 | [Spec-Code Mismatch] | [`coordinates.py:29`](src/satellite_coverage/coordinates.py#L29), [`geodata.py:11`](src/satellite_coverage/geodata.py#L11) |
| TLE/SGP4 | 可追踪 TLE、NORAD、epoch、timestamp | Skyfield SGP4 存在；但不保存 epoch/path，且重复历元被当作独立卫星 | [Bug] | [`tle.py:24`](src/satellite_coverage/tle.py#L24) |
| Coordinate transforms | TEME→ECEF→ENU，地面用 WGS-84 | center altaz 由 Skyfield/WGS-84 完成；pixel geometry 改用球形平地近似 | [Spec-Code Mismatch] | [`tle.py:49`](src/satellite_coverage/tle.py#L49), [`propagation.py:25`](src/satellite_coverage/propagation.py#L25) |
| Visibility | center elevation ≥25° | center elevation正确计算；默认 5°，示例 10° | [Spec-Code Mismatch] | [`tle.py:41`](src/satellite_coverage/tle.py#L41), [`xian.yaml:10`](examples/xian.yaml#L10) |
| Scheduling | 保持当前卫星，低于阈值才 handover | 每次独立选择最高仰角卫星，无保持状态、pass、handover | [Spec-Code Mismatch] | [`tle.py:64`](src/satellite_coverage/tle.py#L64) |
| Pixel geometry | ECEF slant range、ENU elevation/azimuth、off-axis | flat tangent-plane range/elevation/azimuth；无 off-axis | [Spec-Code Mismatch] | [`propagation.py:25`](src/satellite_coverage/propagation.py#L25) |
| Beam/antenna | 64×64 array、element/scan/off-axis gain | 完全缺失；以空间常数 `eirp_dbm` 替代 | [Spec-Code Mismatch] | [`scenario.py:66`](src/satellite_coverage/scenario.py#L66) |
| FSPL | 14.5 GHz，MHz/km 公式 | 等价的 Hz/m 精确公式；正常输入下正确 | [Correct] | [`propagation.py:10`](src/satellite_coverage/propagation.py#L10) |
| Atmosphere | 0.08 gas + 0.10 cloud zenith，按 elevation scaling | `0.047*(f/10)/sin(e)` + 非规范 rain 经验式；无 cloud | [Spec-Code Mismatch] | [`propagation.py:15`](src/satellite_coverage/propagation.py#L15) |
| Terrain profile | extended DEM、150 m 起点、100 m step、4/3 Earth | 区域内方向性栅格 sweep；无 extended DEM、150 m、曲率 | [Spec-Code Mismatch] | [`propagation.py:37`](src/satellite_coverage/propagation.py#L37) |
| Terrain visibility | receiver-relative LOS | 遮挡判据漏掉 receiver elevation | [Bug] | [`propagation.py:68`](src/satellite_coverage/propagation.py#L68) |
| Diffraction | dominant single knife-edge，40 dB used cap，保留 raw | 单刀刃近似；函数内部立即 clip 到 60 dB；无 raw | [Spec-Code Mismatch] | [`propagation.py:79`](src/satellite_coverage/propagation.py#L79) |
| Weather | 2–4 moving Gaussian cells、连续纹理 | 不存在；仅有空间均匀 rain-rate 标量 | [Spec-Code Mismatch] | [`propagation.py:15`](src/satellite_coverage/propagation.py#L15) |
| Clutter | region-static synthetic correlated field | 不存在；建筑 Shapefile 模型不是 clutter | [Spec-Code Mismatch] | [`scenario.py:53`](src/satellite_coverage/scenario.py#L53) |
| Link budget | Ptx+Gtx+Grx−全部 losses−bias | EIRP+Grx−FSPL−atmos−terrain−urban+reflection | [Spec-Code Mismatch] | [`scenario.py:60`](src/satellite_coverage/scenario.py#L60) |
| Clean target | ground truth 不加测量噪声 | 未加入测量噪声 | [Correct] | [`scenario.py:66`](src/satellite_coverage/scenario.py#L66) |
| Dataset output | frame collection及关联 metadata | 只写单帧固定文件名 NPY/PNG | [Spec-Code Mismatch] | [`cli.py:17`](src/satellite_coverage/cli.py#L17) |
| Intermediate states | 几何、beam、各 loss、raw/used state | 保存部分已有 component；不保存 geometry、DEM、raw diffraction | [Spec-Code Mismatch] | [`scenario.py:43`](src/satellite_coverage/scenario.py#L43) |
| Metadata | region/time/TLE/satellite/pass/handover/map mapping | 无 metadata 文件；仅 stdout 打印 NORAD/elevation | [Spec-Code Mismatch] | [`cli.py:29`](src/satellite_coverage/cli.py#L29) |
| Chronological split | 1512/324/324 per region | 不存在 | [Spec-Code Mismatch] | 仓库无相关实现 |
| Sensor sampling | 固定无放回 layout、独立随机流 | 不存在 | [Spec-Code Mismatch] | 仓库无相关实现 |
| Preprocessing/evaluation | 独立 benchmark pipeline，避免 leakage | 不存在，无法审核 leakage/normalization | [Unable to Verify] | 仓库无相关实现 |

# 3. Critical Findings

## CF-01

- ID: CF-01
- Title: 地形遮挡判据遗漏当前 receiver elevation
- Category: [Bug]
- Severity: Critical
- Location: [`propagation.py:68`](src/satellite_coverage/propagation.py#L68)
- Expected behavior: 对上游障碍，应比较 `h_obstacle + slope*u_obstacle` 与 `h_receiver + slope*u_receiver`。
- Actual behavior: 代码只使用 `horizon = slope * current_u`，相当于假定每个 receiver 海拔为 0 m。
- Evidence: 5×5、500 m 完全平坦 DEM 在 25° elevation 下有 20/25 像素被判遮挡；西安实际 DEM 有 99.46% 像素被判遮挡，terrain loss 中位数为 60 dB。
- Impact: 大面积虚假地形阴影和最大绕射损耗。
- Changes current generated maps? Yes
- Changes published benchmark results? Possibly
- Recommended action: 在任何再生成前修正 receiver-relative 判据，并增加平坦非零海拔、斜坡、单障碍和真实 DEM regression tests。已有 terrain-enabled 数据应标记为需重新验证，不能继续视为可信 reference data。

## CF-02

- ID: CF-02
- Title: 同一卫星多个 TLE 历元被当作独立候选
- Category: [Bug]
- Severity: High
- Location: [`tle.py:24`](src/satellite_coverage/tle.py#L24), [`tle.py:51`](src/satellite_coverage/tle.py#L51)
- Expected behavior: 每个 NORAD ID 应依据明确政策选择适用历元，并记录 TLE epoch/age。
- Actual behavior: 所有 TLE pair 都进入候选集合，再从所有记录中选择最高 elevation。
- Evidence: 示例文件有 14,918 条记录、6,490 个 NORAD ID、763 条完全重复记录；5,166 个 ID 有多个记录。示例时刻有 1,761 个 ID 的最高-elevation记录不是其最近历元记录。
- Impact: 卫星 elevation、availability、selection 和 handover 可能由非适用、甚至未来历元的 TLE 决定。
- Changes current generated maps? Possibly
- Changes published benchmark results? Possibly
- Recommended action: 明确 snapshot/closest-prior/closest-epoch 政策；按 NORAD 去重；验证 TLE age、SGP4 error；保存使用的两行元素和 epoch。

## CF-03

- ID: CF-03
- Title: Reference 时间序列和 stateful scheduler 未实现
- Category: [Spec-Code Mismatch]
- Severity: High
- Location: [`scenario.py:35`](src/satellite_coverage/scenario.py#L35)
- Expected behavior: 20 s frame loop；当前卫星保持到低于25°；区分 initial service 与 handover。
- Actual behavior: 每次 `run()` 仅计算一个 timestamp，并始终选最高 elevation。
- Evidence: 无 previous-serving state、pass ID、handover state 或 frame index。
- Impact: 不能产生规范规定的 service sequence；若逐帧外部调用，会产生不必要的卫星切换。
- Changes current generated maps? Possibly
- Changes published benchmark results? Possibly
- Recommended action: 在传播引擎外引入可注入 scheduler，并先建立候选卫星时序状态。

## CF-04

- ID: CF-04
- Title: Reference beam/antenna model完全缺失
- Category: [Spec-Code Mismatch]
- Severity: High
- Location: [`scenario.py:66`](src/satellite_coverage/scenario.py#L66)
- Expected behavior: Gtx 依赖 64×64 array、element gain、efficiency、scan condition 和 pixel off-axis。
- Actual behavior: 全图使用单一 `eirp_dbm=55`，无 boresight、off-axis、array factor 或 35 dB attenuation cap。
- Evidence: 仓库中不存在 beam/off-axis 计算。
- Impact: 地图缺少重要空间方向性，无法称为 reference SatRM link configuration。
- Changes current generated maps? Yes
- Changes published benchmark results? Possibly
- Recommended action: 明确 boresight/scheduler 关系后实现独立 BeamModel；分别输出 raw/used gain。

## CF-05

- ID: CF-05
- Title: Pixel geometry 未使用统一 ECEF/WGS-84
- Category: [Spec-Code Mismatch]
- Severity: High
- Location: [`coordinates.py:9`](src/satellite_coverage/coordinates.py#L9), [`propagation.py:25`](src/satellite_coverage/propagation.py#L25)
- Expected behavior: ground WGS-84 geodetic→ECEF，与 satellite Earth-fixed position相减，再转 local ENU。
- Actual behavior: grid 用半径 6,371 km 球形近似；satellite center look vector被放入平坦局部坐标；ground z 永远为0。
- Evidence: 76.8 km 尺度 spot check 中，边缘误差最高约 0.78° azimuth、0.29° elevation、177 m range；某 near-threshold pixel 近似 elevation 25.238°、Skyfield point calculation 24.896°。
- Impact: FSPL影响较小，但 elevation-dependent loss、pixel visibility、terrain direction及未来窄波束增益会偏差。
- Changes current generated maps? Yes
- Changes published benchmark results? Possibly
- Recommended action: 建立一次性 ground ECEF/ENU basis static state，所有 pixel geometry从同一 Earth-fixed satellite state计算。

## CF-06

- ID: CF-06
- Title: Terrain reference model关键参数缺失且 cap 错误
- Category: [Spec-Code Mismatch]
- Severity: High
- Location: [`propagation.py:37`](src/satellite_coverage/propagation.py#L37), [`propagation.py:85`](src/satellite_coverage/propagation.py#L85)
- Expected behavior: extended DEM、150 m 起点、100 m profile step、4/3 Earth、single dominant knife edge、40 dB used cap并保留 raw。
- Actual behavior: 只扫描当前 map；无 curvature/start distance；使用 center az/elevation；内部立即 clip 到 60 dB。
- Evidence: `np.clip(..., 0, 60)`；没有任何 earth-radius/profile configuration。
- Impact: 边界像素缺失 map 外障碍，绕射状态不可复核，最高损耗比规范大20 dB。
- Changes current generated maps? Yes
- Changes published benchmark results? Possibly
- Recommended action: 先修 CF-01，再建立显式 profile state、`loss_raw`/`loss_used` 和40 dB dataset profile。

## CF-07

- ID: CF-07
- Title: Weather 和 clutter reference mechanisms不存在
- Category: [Spec-Code Mismatch]
- Severity: High
- Location: [`propagation.py:15`](src/satellite_coverage/propagation.py#L15), [`scenario.py:43`](src/satellite_coverage/scenario.py#L43)
- Expected behavior: moving Gaussian weather、correlated texture、region-static synthetic clutter和0.4 dB bias。
- Actual behavior: 只有 uniform rain-rate 标量及可选建筑模型；无天气状态、clutter或随机种子。
- Evidence: 全仓库没有 weather/clutter/random/seed 实现。
- Impact: 输出缺少规范中的时变环境结构和静态相关环境结构。
- Changes current generated maps? Yes
- Changes published benchmark results? Possibly
- Recommended action: 在静态/慢变状态层分别实现，使用独立 RNG stream。

## CF-08

- ID: CF-08
- Title: 输出缺失 frame-level metadata 和 provenance
- Category: [Reproducibility Issue]
- Severity: High
- Location: [`cli.py:17`](src/satellite_coverage/cli.py#L17)
- Expected behavior: map 与 region、timestamp、satellite、TLE epoch、pass、handover、配置、数据版本和 commit 一一对应。
- Actual behavior: 固定文件名 NPY；只在 stdout 打印 NORAD/elevation；重复运行会覆盖。
- Evidence: 无 metadata writer；审查时当前目录也不能识别为有效 Git repository。
- Impact: 输出文件无法独立证明由哪个时刻、TLE、DEM或代码生成。
- Changes current generated maps? No
- Changes published benchmark results? Possibly
- Recommended action: 在任何正式生成前定义原子 manifest、frame ID、checksums、code/environment provenance。

## CF-09

- ID: CF-09
- Title: Reference split、sensor sampling和evaluation pipeline缺失
- Category: [Spec-Code Mismatch]
- Severity: High
- Location: 整个仓库
- Expected behavior: clean dataset完成后执行独立 chronological split、fixed sensor layouts 和 evaluation。
- Actual behavior: README 明确说明不包含批量数据集、训练或产品流水线。
- Evidence: [`README.md:3`](README.md#L3)
- Impact: 无法复核 frame counts、split边界、sensor随机性、normalization leakage或论文指标。
- Changes current generated maps? No
- Changes published benchmark results? Possibly
- Recommended action: 保持 benchmark 为独立 package/pipeline，并以不可变 generated dataset manifest作为唯一输入。

# 4. H1–H10 Verification

| Hypothesis | Result | 依据 |
|---|---|---|
| H1 Weather 是 moving Gaussian field | **Rejected** | Weather 模块不存在；只有 [`atmospheric_loss_db`](src/satellite_coverage/propagation.py#L15) 的空间均匀 rain-rate 标量。它也不是 meteorological-data-driven。 |
| H2 Clutter 是 synthetic correlated field且不用 land cover | **Rejected** | Clutter 模块不存在。建筑 Shapefile 在 [`scenario.py:53`](src/satellite_coverage/scenario.py#L53) 中作为 urban loss，不是规范 clutter。 |
| H3 Gas/cloud只是 fixed zenith elevation scaling | **Partially Confirmed** | 确实是简单 `1/sin(elevation)`，不是完整 ITU；但 gas 系数为频率相关0.047基值，cloud完全缺失，和0.08/0.10 reference不符。 |
| H4 Dominant single knife-edge且内部过早40 dB clipping | **Partially Confirmed** | horizon sweep选择一个支配项后进入单刀刃公式；确实过早 clipping，但上限是60 dB而不是40 dB，且 raw state丢失。 |
| H5 Scheduling 与 propagation generation 强耦合 | **Confirmed** | [`CoverageScenario.run`](src/satellite_coverage/scenario.py#L35) 内直接构建 catalog、选卫星并立即传播；无法注入 scheduler 或已有 satellite state。 |
| H6 只保存最终 map，不保存重要 intermediate states | **Partially Confirmed** | 不只保存 final；FSPL、atmos、terrain等现有 components 会保存。但 range/elevation/azimuth/off-axis/DEM/raw diffraction和metadata均不保存。 |
| H7 Static calculations 在 frame loop 中重复 | **Partially Confirmed** | 无内部 frame loop；但每次单帧 `run()` 都重建 grid、解析 TLE、读 DEM、读建筑并重新栅格化。外部循环必然重复。 |
| H8 Weather/clutter/sensor共享 global random stream | **Rejected** | 仓库没有任何随机调用，也没有这三个模块。不是正确的独立流设计，而是功能缺失。 |
| H9 参数大量 hard-code | **Partially Confirmed** | frequency/EIRP/grid可配置；但 Earth radius、大气系数、elevation clip、diffraction 60 dB cap等硬编码，antenna/weather/clutter参数体系不存在。 |
| H10 Physical generation与sparse benchmark未完全解耦 | **Rejected** | 当前 physical single-map代码不依赖 benchmark；benchmark完全缺失。此结论不代表规范所需的独立 benchmark 已实现。 |

# 5. Newly Discovered Issues

## ND-01

- ID: ND-01
- Title: DEM/建筑输出栅格存在约半像素范围收缩
- Category: [Bug]
- Severity: Medium
- Location: [`coordinates.py:40`](src/satellite_coverage/coordinates.py#L40), [`geodata.py:20`](src/satellite_coverage/geodata.py#L20)
- Expected behavior: raster bounds应使用外部 pixel edges。
- Actual behavior: `bounds_wgs84()` 返回最外层 pixel centers，却被当作 raster edges传给 `from_bounds()`。
- Evidence: 西安256²网格中，输出最外像素中心相对请求中心向内移动约0.000542° lon、0.000448° lat，约半个100 m pixel。
- Impact: DEM、建筑与 LocalGrid 坐标存在系统性缩放/错位；非线性 CRS 下还缺少 pointwise reprojection。
- Changes current generated maps? Yes
- Changes published benchmark results? Possibly
- Recommended action: 明确 center/edge affine transform，并使用目标-grid transform执行真正的 reproject/resample。

## ND-02

- ID: ND-02
- Title: Satellite altitude metadata恒为0
- Category: [Bug]
- Severity: Medium
- Location: [`tle.py:56`](src/satellite_coverage/tle.py#L56)
- Expected behavior: satellite geodetic altitude。
- Actual behavior: 对 satellite state调用 `wgs84.subpoint_of()`，取得的是地表 subpoint，其 elevation为0。
- Evidence: 示例选中 NORAD 58010，slant range 619.7 km，但 `altitude_m=0.0`。
- Impact: altitude metadata错误；当前链路预算未使用该字段，因此不改变当前 map。
- Changes current generated maps? No
- Changes published benchmark results? Possibly
- Recommended action: 使用 satellite geographic position height，并增加LEO altitude范围测试。

## ND-03

- ID: ND-03
- Title: 无可用卫星时无法表达 no-service frame
- Category: [Architecture Issue]
- Severity: Medium
- Location: [`tle.py:62`](src/satellite_coverage/tle.py#L62)
- Expected behavior: dataset中明确记录服务状态。
- Actual behavior: `LookupError` 中止整个运行。
- Evidence: `No satellite meets the visibility threshold` 直接抛异常。
- Impact: 时间序列存在coverage gap时无法继续生成或记录空服务状态。
- Changes current generated maps? No
- Changes published benchmark results? Possibly
- Recommended action: 用显式 `NoServiceState`/nullable serving state建模。

## ND-04

- ID: ND-04
- Title: 数值安全仅局部实现
- Category: [Bug]
- Severity: Medium
- Location: [`propagation.py:10`](src/satellite_coverage/propagation.py#L10), [`propagation.py:15`](src/satellite_coverage/propagation.py#L15)
- Expected behavior: 验证 frequency/range/elevation，并检测最终 NaN/Inf。
- Actual behavior: distance≤0 被静默夹到1 m；frequency≤0未验证；pixel elevation≤0产生 Inf；输出前没有 finite check。
- Evidence: `np.maximum(distance,1.0)` 和 `np.where(elevation > 0, ..., np.inf)`。
- Impact: 配置或几何错误可被静默变成有限 FSPL 或 `-Inf` received power。
- Changes current generated maps? Possibly
- Changes published benchmark results? Possibly
- Recommended action: 对物理无效输入 fail fast；对 below-horizon pixel使用显式 mask而非将状态隐含在 Inf 中。

## ND-05

- ID: ND-05
- Title: Example和环境不可移植
- Category: [Reproducibility Issue]
- Severity: Medium
- Location: [`xian.yaml:9`](examples/xian.yaml#L9), [`pyproject.toml:10`](pyproject.toml#L10)
- Expected behavior: 数据资产可定位、带版本/checksum；依赖环境可锁定。
- Actual behavior: 三个绝对 `/home/...` 路径；依赖仅有宽松下界，无 lockfile。
- Evidence: TLE、DEM、Shapefile均位于仓库外；无数据 manifest。
- Impact: 换机器后示例失效，不同 NumPy/Skyfield/Rasterio版本可能产生不同结果。
- Changes current generated maps? No
- Changes published benchmark results? Possibly
- Recommended action: 使用相对数据根目录或 URI manifest，记录 SHA256、版本和完整环境。

## ND-06

- ID: ND-06
- Title: 建筑加载和损耗模型存在额外限制
- Category: [Modeling Limitation]
- Severity: Low
- Location: [`geodata.py:35`](src/satellite_coverage/geodata.py#L35), [`propagation.py:88`](src/satellite_coverage/propagation.py#L88)
- Expected behavior: 当前规范未定义建筑传播。
- Actual behavior: 整个 Shapefile先读入内存再过滤；重叠 polygon按输入顺序覆盖；building shadow和occupied pixel可能各加一次 penetration。
- Evidence: `gpd.read_file()` 无 bbox；urban loss由两个独立 `np.where`相加。
- Impact: 大矢量文件性能差；建筑损耗语义依赖数据顺序和receiver定义。
- Changes current generated maps? Yes，启用 buildings 时
- Changes published benchmark results? Possibly
- Recommended action: 在纳入正式模型前明确 rooftop/indoor receiver语义、polygon merge规则和物理验证；使用读取时空间过滤。

# 6. Physical and Numerical Validation

| Component | Result | Validation |
|---|---|---|
| Orbit | **Partially Verified** | Skyfield `EarthSatellite`确实使用SGP4，center altaz接口正确；未与独立轨道reference比较，且TLE历元政策、SGP4 error检查和provenance缺失。 |
| Geometry | **Partially Verified** | center geometry与Skyfield一致；azimuth采用北起顺时针的常规定义，未发现degree/radian交换；pixel geometry未满足ECEF要求并出现最高约0.29° elevation误差。 |
| FSPL | **Verified** | 14.5 GHz、550 km得到170.482397 dB；与`4πdf/c`相差约2.2×10⁻⁸ dB，与规范32.45常数版本相差−0.002217 dB。Hz/m转换正确，无MHz/GHz或m/km重复转换。 |
| Beam | **Unverified** | 未实现。 |
| Atmosphere | **Partially Verified** | `1/sin(e)`和角度转换数值正确，但物理参数不符合规范。90°时0.06815 dB而reference gas+cloud为0.18 dB；25°时0.1613 vs 0.4259 dB。 |
| Terrain | **Unverified — validation failed** | 非零海拔平坦面错误地产生遮挡；真实DEM出现99.46%遮挡和60 dB中位损耗。 |
| Weather | **Unverified** | 未实现。 |
| Clutter | **Unverified** | 未实现。 |
| Link Budget | **Partially Verified** | 对当前已有分量，手工重组与float32输出最大差7.63×10⁻⁶ dB；但beam、weather、clutter、bias、gas/cloud分量缺失。 |

现有测试为 `3 passed`，但没有轨道reference、非零海拔平地、坐标reference、atmosphere reference、40 dB cap、metadata或时间连续性测试。

没有发现现有 FSPL 中的 Hz/MHz/GHz、m/km 或 dBm/dBW混用。没有 arccos 代码，因此不存在当前 arccos domain错误；off-axis本身缺失。

# 7. Reproducibility Assessment

## 能否从给定 config 和 seed 精确重新生成一个指定 frame？

严格回答：**不能仅凭 config 和 seed 保证。**

当前计算没有随机过程，因此在同一机器、同一依赖版本、同一外部文件字节下，单帧通常是确定性的。但 config 不包含或不固定：

- TLE/DEM/building文件 checksum和版本；
- 实际采用的TLE两行及epoch；
- code commit；
- Python、Skyfield、PROJ、GDAL、Rasterio、NumPy版本；
- output metadata；
- 地理数据vertical datum；
- seed字段或独立random streams。

## 能否从零完整重新生成整个 reference dataset？

**不能。** 缺失：

- 4-region reference config和数据manifest；
- UTC 20 s时间序列生成器；
- stateful scheduler、pass/handover状态；
- reference beam；
- weather和clutter状态；
- 正确的 terrain profile；
- dataset writer和metadata；
- frame ID及文件关联；
- chronological split；
- sensor layouts、preprocessing和evaluation；
- 所有随机种子与环境锁定信息。

Train/test leakage与normalization leakage均为 **[Unable to Verify]**，因为相关代码和已生成dataset都不在仓库中。

# 8. Performance Bottlenecks

本机只读测量：

| 操作 | 测量 |
|---|---:|
| 解析14,918条TLE记录 | 0.19 s/run |
| 单时刻遍历并选择卫星 | 0.89 s/region-frame |
| 768²单次 directional sweep | 约0.36 s |
| 768² geometry+FSPL+atmosphere | 约0.028 s |
| 256²示例DEM窗口读取 | 约0.16 s |
| 768²测试过程峰值RSS，含TLE对象 | 约140 MB |

这些是局部测量，不是完整端到端benchmark。

## 4 regions → 20 regions

最严重瓶颈：

1. 每个 region-frame重新传播全部14,918个TLE记录。
2. 每帧重新解析TLE并创建Timescale。
3. 每帧重复读取/resample DEM。
4. 每帧完整读取建筑Shapefile。
5. 每帧对terrain和building分别执行`O(N² log N)`排序及Python逐像素循环。
6. 相同时间戳的轨道状态不能跨region复用。

仅按实测外推，20 regions×2160 frames的TLE选择约需10.6小时；一个768² sweep累计约4.3小时。完整运行还会叠加I/O、两类遮挡和写盘。

## 1 frequency → multiple frequencies

当前若外层按频率调用 `run()`，会重复：

- TLE解析和传播；
- scheduler；
- DEM/building I/O；
- geometry；
- terrain obstruction search。

实际上只应按频率重算：

- FSPL；
- frequency-dependent atmosphere；
- wavelength-dependent diffraction；
- beam frequency response。

ground ECEF、satellite geometry、terrain dominant obstruction和environment state应复用。

存储也会迅速成为瓶颈：单张768² float32约2.36 MB；8640帧每个component约20.4 GB，20 regions约101.9 GB/component。多个float64 component、多频率和逐帧NPY会很快进入TB级，需要chunked/compressed storage profile。

# 9. Architecture Assessment

当前距离“Modular Satellite Radio-Map Simulation Engine”较远，核心结构问题是：

- `CoverageScenario.run()`同时负责配置解释、数据源、轨道选择、geometry、propagation和composition。
- 无明确 `StaticState / EnvironmentalState / FrameState`。
- scheduler不是可替换策略；卫星选择直接嵌入生成路径。
- 配置是无验证的嵌套字典，没有单位、范围、shape或reference profile约束。
- 数据源没有manifest、缓存、版本或checksum接口。
- 各传播函数可以单独调用，但在scenario中是硬编码组合，不能配置替换。
- geometry没有权威的ECEF state对象，模块间依赖隐式角度和距离单位。
- diffraction raw state在模型函数内部丢失。
- writer只认识单帧固定文件名，不能支持事务性dataset、恢复、分片或metadata。
- benchmark虽然没有和simulation耦合，但原因是完全缺失，而非形成了清晰接口。
- 多频率会迫使重复整个场景调用，缺乏“frequency-independent geometry + frequency-dependent propagation”的层次。

可保留的基础包括：Skyfield SGP4接入、纯函数形式的FSPL/部分传播计算、北向上grid约定、窗口化DEM读取以及已有component dictionary思路。

# 10. Modification Priority

## P0

可能改变现有地图或论文结果，必须先处理：

1. 修复 CF-01 receiver-relative terrain遮挡判据；为所有已有terrain-enabled数据建立失效清单。
2. 暂停把当前输出称为 SatRM reference dataset；当前实现缺少beam、weather、clutter和reference scheduler。
3. 将 diffraction cap改为规范40 dB，并保留raw/used；同时补齐profile起点、extended DEM和Earth curvature。
4. 明确并实现TLE去重/历元选择政策，保存TLE epoch并检查SGP4错误和age。
5. 将pixel geometry改为统一WGS-84/ECEF/ENU，并纳入DEM/receiver altitude语义。
6. 在任何数据重生成前建立可审计的reference config和最小物理validation suite。

## P1

不一定证明既有结果错误，但下一版本强烈建议：

1. 实现stateful scheduler、no-service、pass ID、initial acquisition和handover metadata。
2. 建立typed `ScenarioConfig`，显式单位、范围和默认reference profile。
3. 修复DEM pixel-edge transform及真正的CRS reproject。
4. 实现完整frame manifest、数据源checksum、依赖版本、code version和原子写入。
5. 为 weather、clutter、sensor使用独立命名 RNG streams。
6. 增加NaN/Inf、invalid frequency/range、below-horizon mask和dtype检查。
7. 增加独立reference测试：orbit、ECEF、FSPL、flat terrain、knife-edge趋势、link recomposition、metadata alignment。
8. 独立实现chronological split、sensor sampling及preprocessing，并明确防止normalization leakage。

## P2

长期扩展、性能和维护：

1. 拆分 DataSource、Orbit、Geometry、Scheduler、Propagation、Composer、Writer接口。
2. 缓存ground ECEF、DEM、building raster、clutter和TLE catalog。
3. 预传播共享timestamp的卫星状态，跨region复用。
4. 复用terrain obstruction geometry支持多频率。
5. 优化/编译directional sweep，避免Python逐像素循环和每帧排序。
6. 使用chunked、compressed、多component storage和storage profile。
7. 明确建筑传播模型边界，避免与synthetic clutter混称。
8. 增加可恢复批处理、并行任务划分和完整性校验。

# Final Assessment

**当前代码可以作为单帧快速演示器继续维护，但不能视为 `CODE_SPEC.md` 所定义的 reference simulation engine，也不能据此证明既有 reference dataset 或 benchmark 可复现。最紧急的是地形遮挡错误；它足以使当前带DEM生成的地图失效。**
