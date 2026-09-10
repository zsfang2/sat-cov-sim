# SatRM Simulation Engine — Technical Specification

## 1. Purpose

本代码仓库用于构建动态卫星—地面无线电地图（Satellite Radio Map）。

给定：

- 地理区域及其数字高程模型（DEM）
- 卫星轨道数据（TLE）
- 卫星和地面链路参数
- 天线与波束参数
- 大气、地形、天气和环境传播参数
- 仿真时间范围

系统应生成：

1. 随时间变化的卫星—地面接收功率二维地图；
2. 每一帧对应的卫星几何、服务状态和时间元数据；
3. 可选的各传播机制中间物理分量；
4. 可供后续稀疏无线电地图重建任务使用的数据集。

核心原则是：

Satellite orbital dynamics
→ satellite-ground geometry
→ propagation components
→ link-budget composition
→ radio map

无线传播数据生成与后续 sensor sampling / reconstruction benchmark
必须在逻辑上彼此独立。

---

# 2. Reference Dataset Configuration

以下参数定义当前 SatRM reference configuration。

它们应通过配置文件管理，而不应散落为 hard-coded constants。

## 2.1 Spatial configuration

- Geographic regions: 4
- Map height: 768 pixels
- Map width: 768 pixels
- Nominal ground resolution: 100 m/pixel
- Nominal regional coverage: 76.8 km × 76.8 km
- DEM source: Copernicus DEM GLO-30
- DEM source resolution: approximately 30 m
- Output DEM resolution: 100 m

每个像素至少应具有：

- latitude
- longitude
- elevation

如果实际网格使用地图投影建立，
必须明确记录所使用的 CRS / projection。

---

## 2.2 Temporal configuration

Reference simulation interval:

Start:
2025-01-01 00:00:00 UTC

End:
2025-01-01 11:59:40 UTC

Temporal interval:
20 s

Frames per region:
2160

Total reference frames:
8640

所有内部时间应具有明确时区。
TLE propagation 必须使用 UTC-compatible timestamps。

---

# 3. Orbit Propagation

## 3.1 Required behavior

卫星位置应由 TLE 数据通过 SGP4 传播获得。

实现必须明确以下转换链：

TLE
→ SGP4 orbital state
→ Earth-fixed satellite position
→ satellite-ground geometry

必须能够追踪：

- 使用的 TLE 文件
- satellite identifier / NORAD ID
- TLE epoch
- simulation timestamp

---

## 3.2 Coordinate systems

必须明确区分：

- TEME / orbital propagation coordinates
- Earth-centered Earth-fixed (ECEF)
- geodetic coordinates
- local East-North-Up (ENU)

Ground locations 应基于 WGS-84 ellipsoid 转换到 ECEF。

严禁在没有明确说明的情况下将：

spherical Earth approximation

和

WGS-84 ellipsoid calculation

混合使用。

---

# 4. Satellite Visibility and Service Scheduling

## 4.1 Reference availability rule

候选卫星首先在 region center 处计算 elevation。

Reference minimum service elevation:

25 degrees

Satellite is available if:

center elevation >= 25 degrees

---

## 4.2 Reference scheduling policy

Reference scheduler 应满足：

1. 如果当前 serving satellite 的 center elevation 仍 >= 25 degrees，
   则保持当前 satellite；

2. 当当前 serving satellite 低于 25 degrees 后，
   从所有 available satellites 中选择 center elevation 最高者；

3. serving satellite 改变时产生 handover event；

4. 初始 service establishment 可单独记录，
   不应因为实现方便而与普通 handover 的语义混淆。

该策略属于：

Reference Benchmark Scheduling Policy

而不是传播模型本身。

Orbit / propagation engine 不应从架构上依赖这一种 scheduler。

---

# 5. Pixel-wise Satellite-Ground Geometry

对于每一帧和每个 ground pixel，
至少应能够获得：

- slant range d
- elevation angle θ
- azimuth angle ψ
- beam off-axis angle α

Slant range:

d = ||p_sat - p_ground||

其中 satellite 和 ground coordinates 必须位于同一 ECEF coordinate system。

Elevation 和 azimuth 应通过 local ENU coordinates 计算。

所有角度变量必须明确其单位：

degrees or radians

模块接口中不允许依赖隐式单位。

---

# 6. Link Budget

最终 clean received-power field 应由物理分量组合得到。

Reference expression:

P_rx =
P_tx
+ G_tx
+ G_rx
- L_fs
- L_atm
- L_terrain
- L_weather
- L_clutter
- L_bias

其中：

- P_rx: dBm
- P_tx: dBm
- antenna gains: dBi
- losses: dB

内部不得直接混合：

linear power
W
dBW
dBm

除非进行明确的单位转换。

---

# 7. Free-Space Path Loss

Reference model:

L_fs =
32.45
+ 20 log10(f_MHz)
+ 20 log10(d_km)

Reference carrier frequency:

14.5 GHz

实现必须保证：

- frequency conversion 正确；
- distance conversion 正确；
- 不重复进行 Hz/MHz/GHz 转换；
- 输出单位为 dB。

---

# 8. Satellite Antenna and Beam Model

Reference link configuration:

- Transmit power: 40 dBm
- Receiver gain: 0 dBi
- Planar array: 64 × 64
- Element gain: 5 dBi
- Array efficiency loss: 3 dB
- Maximum off-axis attenuation: 35 dB

G_tx 应至少与以下变量有关：

- beam off-axis angle
- array gain
- scanning condition / scanning loss
- element gain
- efficiency loss

代码必须明确：

- beam boresight definition
- array element spacing
- array-factor model
- off-axis attenuation model
- gain clipping mechanism

如果实现并非完整物理阵列模型，
而是经验 beam attenuation model，
必须在代码注释和文档中明确说明。

---

# 9. Atmospheric Propagation

Reference implementation currently包含：

- gaseous attenuation
- cloud attenuation

Reference zenith losses:

Gas:
0.08 dB

Cloud:
0.10 dB

其 slant-path attenuation 应随 elevation 变化。

代码需要明确区分：

完整 ITU-R 模型实现

和

基于固定 zenith attenuation 的简化 elevation scaling。

如果仅实现：

L_slant ≈ L_zenith / sin(θ)

不得在代码文档中称为完整 ITU-R P.676/P.840 implementation。

---

# 10. Terrain Visibility and Diffraction

Terrain model 应基于 extended DEM 计算卫星方向上的 terrain profile。

Reference parameters:

- terrain profile step: 100 m
- profile starting distance: 150 m from receiver
- effective Earth-radius factor: 4/3
- diffraction model: dominant single knife-edge
- maximum terrain attenuation used in reference dataset: 40 dB

---

## 10.1 Terrain profile

对于每个 receiver pixel：

receiver
→ satellite azimuth direction
→ sampled terrain profile

需要考虑：

- receiver elevation
- sampled terrain elevation
- direct propagation path
- effective Earth curvature

系统应识别 dominant obstruction。

---

## 10.2 Fresnel-Kirchhoff diffraction

Diffraction parameter ν 应基于：

- obstruction height relative to direct path
- receiver-obstruction distance d1
- obstruction-satellite distance d2
- wavelength λ

计算。

Reference knife-edge loss:

if ν < -0.78:
    L_diff = 0

otherwise:
    use standard single-knife-edge approximation

实现应保留数值稳定性。

建议内部区分：

L_diff_raw

和

L_diff_used

其中 reference dataset 可采用：

L_diff_used = min(L_diff_raw, 40 dB)

不应因为最终数据采用 clipping，
就过早丢弃 raw physical state。

---

# 11. Weather Attenuation

Reference SatRM implementation 使用：

- 2–4 moving Gaussian attenuation cells
- spatially correlated texture
- temporally evolving attenuation field
- maximum nominal attenuation: 8 dB

这一模块属于：

Synthetic environmental attenuation model

而不是完整 meteorological propagation model。

必须能够回答：

- cell center 如何生成
- cell scale 如何生成
- amplitude 如何生成
- velocity 如何生成
- temporal continuity 如何保持
- spatial texture 如何生成
- random seed 如何控制

Weather realization 必须在连续 frame 间保持时间一致性，
不得无意中逐帧独立重新采样。

---

# 12. Clutter Attenuation

Reference implementation包含：

- region-static correlated clutter field
- nominal maximum attenuation: 2 dB
- additional attenuation bias: 0.4 dB

Reference clutter 当前属于 synthetic spatial field。

如果代码没有引入 land-cover information，
不得将其描述为 land-cover-aware clutter model。

同一 region 的 clutter realization 应在整个时间序列中保持固定。

---

# 13. Static and Dynamic Physical States

代码架构应明确区分不同时间尺度的变量。

## Static state

例如：

- DEM
- latitude/longitude grid
- ground ECEF
- region geometry
- static clutter

## Slowly varying environmental state

例如：

- weather field

## Frame-level dynamic state

例如：

- satellite position
- serving satellite
- elevation
- azimuth
- slant range
- beam geometry
- free-space path loss
- terrain visibility
- diffraction state

不应在每一帧无必要地重复计算 static quantities。

---

# 14. Intermediate Physical Components

Simulation engine 理想情况下应允许输出以下 component maps：

- slant range
- elevation
- azimuth
- off-axis angle
- free-space path loss
- transmit antenna gain
- gaseous attenuation
- cloud attenuation
- terrain LOS mask
- terrain diffraction loss
- weather attenuation
- clutter attenuation
- final received power

这些变量可根据 storage profile 决定是否永久保存，
但 simulation engine 不应只能得到最终 P_rx。

---

# 15. Dataset Output

每个最终 radio-map frame 至少应能够关联：

- region
- timestamp
- map file
- serving satellite ID
- service pass ID
- handover state
- center elevation
- center azimuth
- center slant range

地图应保存为 floating-point received-power array。

Reference target 应为：

clean latent received-power field

即 receiver measurement noise 不属于 dataset ground truth。

---

# 16. Dataset Split

Reference chronological split per region:

Training:
frames 0–1511

Validation:
frames 1512–1835

Test:
frames 1836–2159

Corresponding total counts:

Training: 6048
Validation: 1296
Test: 1296

该 split 的语义是：

known-region temporal extrapolation

而不是：

unseen-region geographical generalization

这一点属于 benchmark design，
不能在实现或文档中混淆。

---

# 17. Sparse Reconstruction Benchmark

Sparse reconstruction 不属于 physical simulation engine。

其输入来自已经生成完成的 clean radio maps。

对于 region r、sensor budget K 和 layout j：

随机选择 K 个 ground pixels，
without replacement。

同一个 sensor layout 应在对应时间序列中保持固定。

Sparse observation:

Y = S × P

其中 S 为 binary sampling mask。

Sensor sampling 不允许改变原始 radio map。

---

# 18. Measurement Noise

Reference benchmark:

noise-free measurements

即只在 sensor locations 读取 clean map values。

未来 measurement noise model 应作为独立 benchmark component：

clean radio map
→ sensor sampling
→ measurement noise

而不是在 dataset generation 阶段写入 ground truth。

---

# 19. Reproducibility Requirements

随机过程至少应逻辑区分：

- weather randomness
- clutter randomness
- sensor-layout randomness
- dataset split randomness
- ML model randomness

推荐使用独立 random streams。

改变 weather 模块的随机调用次数，
不应导致 sensor-layout realization 改变。

每次 dataset generation 至少应记录：

- configuration
- random seeds
- TLE version/source
- DEM source/version
- code version or commit
- generation timestamp

---

# 20. Configuration Requirements

以下参数原则上不得分散 hard-code：

- carrier frequency
- transmit power
- receiver gain
- antenna configuration
- minimum elevation
- spatial resolution
- map size
- simulation interval
- simulation time range
- atmospheric parameters
- terrain profile step
- Earth-radius factor
- diffraction cap
- weather parameters
- clutter parameters
- random seeds

应由统一 ScenarioConfig / configuration system 管理。

---

# 21. Recommended Software Architecture

目标架构：

ScenarioConfig
      ↓
DataSourceManager
 ├─ TLE
 ├─ DEM
 └─ Environment
      ↓
OrbitEngine
      ↓
GeometryEngine
      ↓
PropagationEngine
 ├─ FreeSpaceModel
 ├─ BeamModel
 ├─ AtmosphereModel
 ├─ TerrainModel
 ├─ WeatherModel
 └─ ClutterModel
      ↓
LinkBudgetComposer
      ↓
PhysicalState
      ↓
Scheduler / DatasetProfile
      ↓
DatasetWriter

Benchmark 独立：

Generated Dataset
      ↓
SensorSampler
      ↓
NoiseModel
      ↓
Reconstruction Dataset
      ↓
Evaluation

这代表目标方向，而不是要求现有仓库已经完全采用这些类名。

---

# 22. Numerical Safety Requirements

重点保护：

- log10 input > 0
- arccos input clipped to [-1, 1]
- elevation handling
- sin(elevation) denominator
- sqrt domain
- NaN / Inf detection
- coordinate precision
- float32 / float64 conversion

关键 geometry calculation 建议使用 float64。

---

# 23. Validation Requirements

至少应具备以下独立 sanity checks：

Geometry:
SGP4 / coordinate result 与可信 reference 比较。

Free-space loss:
随机点与独立 analytical calculation 比较。

Terrain:
平坦无遮挡场景应产生近似零 terrain diffraction loss。

Diffraction:
obstruction 增高时 loss 应具有合理趋势。

Weather:
连续 frame 间应具有时间相关性。

Clutter:
同一 region 在所有 frame 中应保持一致。

Link budget:
各 component 手工重新组合后应等于最终 P_rx。

Metadata:
frame、timestamp、satellite state、map file 必须一一对应。

---

# 24. Known Modeling Assumptions

以下内容属于当前 reference model 的建模假设，
不得自动判断为软件 bug：

1. 使用 14.5 GHz 单频点；
2. 使用 single dominant knife-edge diffraction；
3. terrain attenuation 使用 40 dB cap；
4. weather 为 synthetic Gaussian-cell model；
5. clutter 为 synthetic correlated field；
6. serving satellite 采用 elevation-threshold scheduler；
7. benchmark 使用 noise-free observations；
8. official split 只测试 known-region temporal generalization。

审核时必须区分：

software implementation error

和

intentional modeling approximation。

---

# 25. Future Extension Compatibility

当前代码不要求已经实现下列功能，
但架构最好不要阻碍：

- multi-frequency simulation
- ERA5 / IMERG meteorology
- land-cover-aware clutter
- ITU-R rain attenuation
- multiple scheduling policies
- candidate-satellite state generation
- high-fidelity terrain validation
- additional geographic regions
- unseen-region benchmark
- component-map release
- measurement-noise models
- downstream handover / coverage decision tasks

这些属于 extensibility requirements，
不是当前 correctness requirements。