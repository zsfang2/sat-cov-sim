# Satellite Coverage Sim 阶段性项目结构改造计划

计划依据：[`CODE_SPEC.md`](CODE_SPEC.md) 与 [`CODE_AUDIT_REPORT.md`](CODE_AUDIT_REPORT.md)  
计划日期：2026-09-10  
计划性质：结构改造、正确性修复和 reference pipeline 建设；不在本计划阶段直接重新生成正式 dataset

## Goal Description

将当前“单区域、单时刻、单体式 `CoverageScenario.run()`”逐步改造成可验证、可替换、可复现的 Modular Satellite Radio-Map Simulation Engine，同时保持 physical dataset generation 与 sparse reconstruction benchmark 的代码、状态和随机流相互独立。

改造必须遵循以下顺序：

1. 先冻结和表征当前行为，建立会阻止错误地图进入正式数据集的测试与发布门禁；
2. 再建立 config、domain state、data source、orbit、geometry、scheduler、propagation、composer、writer 的明确边界；
3. 每次只替换一个可独立验证的物理或数据模块；
4. 所有会改变现有地图数值的修改均记录 migration note 和 component-level 差异；
5. 只有在 P0 correctness、metadata 和 reproducibility 验收全部通过后，才允许另行批准重新生成 reference dataset；
6. benchmark 只消费已完成且带 manifest 的 clean radio-map dataset，不得调用 simulation internals。

本计划不把审计中的性能实测值视为硬性 SLA。0.19 s TLE parse、0.89 s satellite selection、0.36 s/768² terrain sweep 等只作为优化前基线；硬性验收重点是正确性、调用次数、缓存边界、确定性和数据可追踪性。

## Acceptance Criteria

Following TDD philosophy, each criterion includes positive and negative tests for deterministic verification.

- AC-1: 建立现状保护、错误数据隔离和 reference generation 门禁
  - Positive Tests (expected to PASS):
    - 当前 CLI 的无 terrain 最小场景能够通过 compatibility test 生成 shape、dtype 和命名明确的单帧结果。
    - 标记为 `reference` 的生成命令只有在 required validation suite 全部通过时才允许启动。
    - terrain-enabled legacy 输出能够被 manifest 标记为 `legacy_unvalidated` 或 `invalidated_by_CF_01`。
  - Negative Tests (expected to FAIL):
    - 未通过 terrain、geometry 或 TLE validation 时尝试生成 reference dataset。
    - 把没有 metadata/provenance 的现有 NPY 文件注册为 validated reference frame。

- AC-2: 建立无循环依赖的模块边界
  - Positive Tests (expected to PASS):
    - `config`、`domain`、`data_sources`、`orbit`、`geometry`、`scheduling`、`propagation`、`engine`、`io` 可分别导入。
    - simulation engine 不导入 benchmark package；benchmark 只通过公开 dataset schema 读取结果。
    - `CoverageScenario` compatibility adapter 只调用公开 engine API，不再直接组合所有物理函数。
  - Negative Tests (expected to FAIL):
    - propagation model 直接读取 YAML、TLE、DEM 或写文件。
    - scheduler 直接调用 terrain/weather/link-budget implementation。
    - simulation package 导入 sensor sampler、ML preprocessing 或 evaluation implementation。

- AC-3: ScenarioConfig 统一管理参数、单位和 reference profile
  - Positive Tests (expected to PASS):
    - reference config解析为4 regions、768×768、100 m、20 s、每region 2160 frames、UTC时间范围和25° minimum elevation。
    - frequency、power、gain、angle、distance、loss cap、seed等字段具有显式单位命名和范围验证。
    - 配置可序列化为canonical representation并写入dataset manifest。
  - Negative Tests (expected to FAIL):
    - naive timestamp、frequency≤0、map size≤0、extent≤0、非法 CRS、负数组尺寸或缺失 required seed。
    - 同时提供互相冲突的 `frequency_hz` 与 `frequency_ghz`，或把 dBW 值传入 dBm 字段。
    - reference profile仍使用示例中的256²、10°、单时刻配置。

- AC-4: 明确区分 static、environmental、frame-level physical state
  - Positive Tests (expected to PASS):
    - `RegionStaticState`包含 grid、CRS、lat/lon/elevation、ground ECEF、ENU basis、static clutter和source provenance。
    - `EnvironmentalState`包含可按时间查询的weather realization及独立随机流信息。
    - `FrameState`包含timestamp、candidate/serving satellite、geometry、service state和component maps。
    - state arrays具有验证过的shape、dtype、unit、coordinate system和只读/不可变语义。
  - Negative Tests (expected to FAIL):
    - frame state中的map shape与region grid不一致。
    - static state在frame iteration期间被原地修改。
    - angle、range或power字段缺乏明确单位。

- AC-5: TLE data source、orbit engine和TLE历元政策可追踪且确定
  - Positive Tests (expected to PASS):
    - 每个NORAD ID在指定timestamp仅产生一个按配置政策选定的TLE record。
    - exact duplicate TLE不会增加candidate数量或改变selection。
    - orbit output记录NORAD ID、name、TLE line 1/2、TLE epoch、age、source checksum、timestamp和SGP4 status。
    - satellite altitude使用真实geodetic height，不再恒为0。
  - Negative Tests (expected to FAIL):
    - TLE checksum错误、line 1/2 NORAD不一致、超过允许age且未配置fallback、SGP4 propagation error。
    - 同一NORAD的多个历元被当作多个同时存在的卫星参与最高仰角竞争。
    - future TLE在禁止future-record的policy下被静默采用。

- AC-6: Pixel-wise geometry使用统一WGS-84/ECEF/ENU链路
  - Positive Tests (expected to PASS):
    - ground geodetic坐标和DEM/receiver高度通过WGS-84转换为float64 ECEF。
    - satellite Earth-fixed与ground ECEF相减得到slant range，并通过pixel-local ENU得到elevation/azimuth。
    - center和随机pixel与独立Skyfield/pyproj reference在预先确定的数值容差内一致。
    - azimuth采用北起顺时针定义；所有三角函数输入单位明确。
  - Negative Tests (expected to FAIL):
    - TEME位置未经Earth-fixed转换直接与ground ECEF相减。
    - degree直接传给要求radian的函数、m/km混用或用球形Earth radius替代WGS-84 reference geometry。
    - `arccos`输入未clip到[-1, 1]或最终geometry包含未解释的NaN/Inf。

- AC-7: Scheduler与orbit/propagation解耦并实现reference policy
  - Positive Tests (expected to PASS):
    - scheduler输入仅为candidate satellite states、previous service state和timestamp。
    - 当前serving satellite在center elevation仍≥25°时保持不变。
    - 当前卫星跌破阈值后选择available candidates中center elevation最高者。
    - initial acquisition、handover和no-service具有不同、可序列化的事件语义。
  - Negative Tests (expected to FAIL):
    - 每帧无条件切换到最高elevation satellite。
    - no-service通过未捕获异常中止整段时间序列。
    - scheduler读取DEM、weather或received-power map决定reference serving satellite。

- AC-8: Propagation component接口和LinkBudgetComposer可替换、可复算
  - Positive Tests (expected to PASS):
    - 每个模型声明required inputs、output name、shape、dtype、unit及frequency dependence。
    - composer以显式分量实现 `Ptx + Gtx + Grx - losses`，手工重组与输出在float精度容差内相等。
    - storage profile可选择保存component maps，但engine即使不落盘也保留完整PhysicalState。
    - legacy building model作为optional extension注册，reference profile默认是否启用由明确配置决定。
  - Negative Tests (expected to FAIL):
    - 同一loss重复计入、reflection credit符号错误、dBm/dBW或linear/dB隐式混合。
    - component返回错误shape、非finite值或未声明单位仍进入composer。
    - BeamModel或TerrainModel直接覆盖final received-power array。

- AC-9: Terrain visibility和diffraction通过P0物理回归测试
  - Positive Tests (expected to PASS):
    - 任意正的常数海拔平坦DEM产生零blocked mask和近似零terrain loss。
    - 单障碍高度增加时dominant knife-edge `v`和raw loss具有合理单调趋势。
    - terrain profile使用extended DEM、100 m step、150 m起点和4/3 effective Earth radius。
    - 同时输出dominant obstruction、LOS mask、`diffraction_loss_raw_db`和最大40 dB的`diffraction_loss_used_db`。
  - Negative Tests (expected to FAIL):
    - receiver elevation被省略，导致常数海拔DEM大面积遮挡。
    - raw loss在TerrainModel内部被覆盖或clip到60 dB。
    - profile越界时静默把map外terrain当作0 m。
    - `v < -0.78`仍产生非零reference knife-edge loss。

- AC-10: Reference beam、atmosphere、weather和clutter分别实现并可独立验证
  - Positive Tests (expected to PASS):
    - beam输出依赖64×64 array、element gain、efficiency、scan/off-axis condition及35 dB attenuation cap，并记录boresight定义。
    - atmosphere分别输出0.08 dB gas和0.10 dB cloud zenith scaling，且不宣称为完整ITU-R P.676/P.840。
    - weather由2–4个moving Gaussian cells和correlated texture构成，相邻frame保持时间连续。
    - clutter为同region全时序固定的synthetic correlated field，包含2 dB nominal max和0.4 dB bias。
  - Negative Tests (expected to FAIL):
    - scalar EIRP替代所有pixel beam gain。
    - cloud缺失、gas/cloud合并为无法追踪的单一loss，或把经验式标成完整ITU实现。
    - weather逐帧独立重采样。
    - synthetic clutter被描述为land-cover-aware，或同region随frame改变。

- AC-11: 所有随机过程使用独立、可重建的命名random streams
  - Positive Tests (expected to PASS):
    - weather、clutter、sensor layout、split和ML分别从root seed派生稳定的命名子流。
    - 增加weather内部随机调用不会改变clutter或sensor layout realization。
    - 给定canonical config、source checksums、code/environment version和seed可逐bit或按声明容差重建指定frame。
  - Negative Tests (expected to FAIL):
    - 使用模块级`np.random` global state。
    - 不同region、layout或机制意外复用相同stream状态。
    - manifest缺少seed derivation/version仍宣称可精确复现。

- AC-12: DatasetWriter产生原子、可恢复且一一对齐的frame与metadata
  - Positive Tests (expected to PASS):
    - 每帧至少关联region、frame index、UTC timestamp、map path、serving NORAD、TLE epoch、pass ID、handover state和center geometry。
    - map为floating-point clean latent received power，measurement noise不写入ground truth。
    - manifest记录canonical config、source checksums、code version、dependency versions和generation timestamp。
    - 中断后可从最后一个完整frame恢复，且不会接受partial frame/component集合。
  - Negative Tests (expected to FAIL):
    - metadata和map数量或frame ID不一致。
    - rerun静默覆盖不同配置产生的同名文件。
    - timestamp无timezone、component shape不一致或ground-truth中混入measurement noise。

- AC-13: Sparse benchmark与physical engine完全隔离并防止数据泄漏
  - Positive Tests (expected to PASS):
    - benchmark只读取validated dataset schema，不导入orbit、geometry或propagation internals。
    - 每region chronological split严格为0–1511、1512–1835、1836–2159。
    - sensor layout在同一region/time series内固定，K个pixel无放回采样，且不改变clean map。
    - normalization/statistics仅从training split拟合，再应用到validation/test。
  - Negative Tests (expected to FAIL):
    - random frame split、跨split拟合normalization、sensor mask逐帧变化或修改原始map。
    - benchmark触发新的卫星传播、weather生成或terrain计算。
    - 把known-region temporal split报告为unseen-region generalization。

- AC-14: Static缓存、多region和多频率执行边界正确
  - Positive Tests (expected to PASS):
    - 一次dataset run中每region的grid、DEM、ground ECEF、building raster和clutter最多构建一次。
    - 同一TLE catalog最多解析一次；相同timestamp的orbit states可跨region复用。
    - 增加frequency只重算frequency-dependent components，不重复scheduler、geometry和terrain obstruction search。
    - 4→20 regions和1→多frequency的benchmark报告调用次数、wall time、峰值内存和输出容量趋势。
  - Negative Tests (expected to FAIL):
    - frame loop中重复读取DEM/Shapefile、解析TLE或重建static grid。
    - 外层frequency loop重新执行完整`ScenarioEngine.run()`。
    - 性能优化改变固定fixture的物理结果而没有明确容差和差异报告。

## Path Boundaries

Path boundaries define the acceptable range of implementation quality and choices.

### Upper Bound (Maximum Acceptable Scope)

完成一个符合`CODE_SPEC.md`的reference simulation engine：拥有typed config、版本化data sources、WGS-84 geometry、可注入scheduler、component-based propagation、static/environment/frame state、可恢复dataset writer、完整manifest、独立benchmark package、多region和多frequency复用，并覆盖所有P0/P1 correctness tests。

上界不包括：完整三维电磁ray tracing、CIR/相位/MIMO信道、ERA5/IMERG数据接入、完整ITU-R P.676/P.840/P.618、高阶多刀刃模型、分布式集群调度或重新训练论文模型。这些属于未来extension，不是本轮结构改造的完成条件。

### Lower Bound (Minimum Acceptable Scope)

至少完成：

- typed ScenarioConfig和canonical reference config；
- domain state与清晰的package边界；
- TLE去重/epoch provenance；
- 正确WGS-84/ECEF pixel geometry；
- 修正terrain receiver-relative visibility和40 dB raw/used分离；
- 可注入reference scheduler；
- component-based link composer；
- atomic frame metadata/manifest；
- simulation与benchmark的单向dataset接口；
- 阻止错误reference generation的测试门禁。

如果没有以上最小范围，不得通过简单移动文件或增加空class声称“模块化改造完成”。

### Allowed Choices

- Can use:
  - Python dataclass、frozen dataclass、Protocol或轻量ABC定义边界；
  - NumPy、Skyfield、pyproj、Rasterio等当前依赖；
  - Pydantic或dataclass-based config validation，但必须避免让物理模块依赖YAML实现；
  - Zarr、HDF5或chunked NumPy加manifest作为dataset backend，最终由用户决策确定；
  - compatibility facade保留现有`CoverageScenario`和CLI一段迁移期；
  - pytest fixture、property-based test和小型synthetic DEM/TLE assets；
  - 先保留Python实现，再基于profile使用Numba/Cython/vectorized kernel优化terrain sweep。
- Cannot use:
  - 在未通过P0 validation前重新生成或覆盖正式reference dataset；
  - 用重新排列旧函数文件代替真实数据流解耦；
  - 在核心物理模块中直接读取全局config、环境变量或绝对路径；
  - 使用global RNG或依赖调用顺序派生randomness；
  - 把intentional approximation改名为完整ITU或full ray tracing；
  - 为追求性能在没有数值差异测试的情况下改用低精度geometry；
  - 一次性删除legacy API而不给出迁移适配和deprecation说明；
  - 在simulation package中加入训练框架依赖。

## Feasibility Hints and Suggestions

> **Note**: 本节仅提供一种可行实现路线，不是强制的文件命名或class设计。

### Conceptual Approach

建议目标结构：

```text
src/
├─ satellite_coverage/
│  ├─ __init__.py                 # stable public simulation API
│  ├─ config/
│  │  ├─ models.py                # ScenarioConfig and nested typed configs
│  │  └─ loader.py                # YAML → canonical config
│  ├─ domain/
│  │  ├─ units.py                 # explicit conventions/validation
│  │  ├─ grid.py                  # RegionGrid and affine/CRS metadata
│  │  └─ state.py                 # Static, Environmental, Orbit, Frame, Physical states
│  ├─ data_sources/
│  │  ├─ manifest.py
│  │  ├─ tle.py
│  │  ├─ dem.py
│  │  └─ buildings.py
│  ├─ orbit/
│  │  ├─ engine.py
│  │  └─ tle_policy.py
│  ├─ geometry/
│  │  ├─ wgs84.py
│  │  └─ engine.py
│  ├─ scheduling/
│  │  ├─ base.py
│  │  └─ elevation_hold.py
│  ├─ propagation/
│  │  ├─ base.py
│  │  ├─ free_space.py
│  │  ├─ beam.py
│  │  ├─ atmosphere.py
│  │  ├─ terrain.py
│  │  ├─ weather.py
│  │  ├─ clutter.py
│  │  └─ urban.py                 # optional non-reference extension
│  ├─ engine/
│  │  ├─ composer.py
│  │  └─ simulator.py
│  ├─ io/
│  │  ├─ schema.py
│  │  ├─ writer.py
│  │  └─ reader.py
│  ├─ compatibility/
│  │  └─ legacy_scenario.py
│  └─ cli.py
└─ satrm_benchmark/
   ├─ dataset.py                  # public generated-dataset reader only
   ├─ split.py
   ├─ sampling.py
   ├─ noise.py
   ├─ preprocessing.py
   └─ evaluation.py

tests/
├─ unit/
├─ physical_reference/
├─ integration/
├─ reproducibility/
├─ architecture/
└─ performance/
```

推荐数据流：

```text
ScenarioConfig
   ├─ DataSourceRegistry ──> source manifest/checksums
   ├─ RegionStaticStateBuilder ──> grid/DEM/ground ECEF/static clutter
   ├─ OrbitEngine ──> timestamp-indexed candidate states
   └─ EnvironmentFactory ──> deterministic environmental realization
                              │
                              v
ReferenceScheduler ──> serving state
                              │
                              v
GeometryEngine ──> PixelGeometry
                              │
                              v
PropagationComponents ──> component maps/raw states
                              │
                              v
LinkBudgetComposer ──> PhysicalState/clean P_rx
                              │
                              v
DatasetWriter ──> immutable dataset + manifest

immutable dataset + manifest
   └─ satrm_benchmark ──> split → sensor sampling → optional noise → preprocessing/evaluation
```

迁移策略：

1. 先让legacy API调用新domain/config facade，但仍运行旧物理函数；
2. 按TLE、geometry、terrain、beam/environment顺序逐个替换，每一步保留component diff报告；
3. 新engine通过验证后，将legacy路径标记deprecated；
4. reference regeneration作为计划之外的独立、有明确批准的release operation。

### Relevant References

- [`CODE_SPEC.md`](CODE_SPEC.md) - 唯一intended technical specification。
- [`CODE_AUDIT_REPORT.md`](CODE_AUDIT_REPORT.md) - correctness、reproducibility、performance和architecture审计依据。
- [`src/satellite_coverage/scenario.py`](src/satellite_coverage/scenario.py) - 当前需要拆分的orchestrator与link composer。
- [`src/satellite_coverage/propagation.py`](src/satellite_coverage/propagation.py) - 当前FSPL、atmosphere、geometry、terrain和urban实现。
- [`src/satellite_coverage/tle.py`](src/satellite_coverage/tle.py) - 当前TLE catalog与selection耦合点。
- [`src/satellite_coverage/coordinates.py`](src/satellite_coverage/coordinates.py) - 当前球形grid与目标WGS-84 geometry的迁移起点。
- [`src/satellite_coverage/geodata.py`](src/satellite_coverage/geodata.py) - DEM bounds、reprojection、static cache和building ingestion改造点。
- [`tests/test_core.py`](tests/test_core.py) - 现有测试必须保留并扩展，不能视为完整validation suite。

## Dependencies and Sequence

### Milestones

1. Milestone 0 — Safety baseline and generation freeze
   - Phase 0A: 建立legacy characterization fixtures、CF-01失败复现、reference generation gate。
   - Phase 0B: 定义旧数据状态、迁移日志格式和“数值结果改变”报告模板。
   - Exit gate: AC-1通过；不修改或重新生成正式dataset。

2. Milestone 1 — Domain skeleton and configuration boundary
   - Phase 1A: 引入typed config、canonical reference config和input validation。
   - Phase 1B: 定义grid、units、static/environment/frame/physical state。
   - Phase 1C: 建立package import规则和legacy compatibility facade。
   - Depends on: Milestone 0。
   - Exit gate: AC-2、AC-3、AC-4通过；现有CLI最小场景仍可运行。

3. Milestone 2 — Data sources, orbit and geometry correctness
   - Phase 2A: DataSource manifest、checksum、DEM affine/reprojection和static cache。
   - Phase 2B: TLE去重、epoch policy、SGP4 status和correct altitude。
   - Phase 2C: WGS-84/ECEF/ENU pixel geometry及独立reference tests。
   - Depends on: Milestone 1。
   - Exit gate: AC-5、AC-6通过；geometry变化必须有component diff报告。

4. Milestone 3 — Scheduling and physical component architecture
   - Phase 3A: Candidate state timeline和reference elevation-hold scheduler。
   - Phase 3B: PropagationModel接口、LinkBudgetComposer和storage profile。
   - Phase 3C: 修正terrain profile/visibility/diffraction并保留raw state。
   - Depends on: Milestone 2。
   - Exit gate: AC-7、AC-8、AC-9通过；CF-01关闭。

5. Milestone 4 — Reference environmental and antenna completion
   - Phase 4A: BeamModel和boresight/scan policy。
   - Phase 4B: Reference gas/cloud elevation scaling。
   - Phase 4C: Synthetic moving weather、static clutter和命名RNG streams。
   - Depends on: Milestone 3及相关Pending User Decisions。
   - Exit gate: AC-10、AC-11通过；所有reference link-budget components可独立输出。

6. Milestone 5 — Dataset engine, writer and provenance
   - Phase 5A: 多region/time simulation iterator，复用static/orbit state。
   - Phase 5B: Atomic DatasetWriter、schema、manifest、resume和integrity checks。
   - Phase 5C: 单frame和small-sequence end-to-end reproducibility validation。
   - Depends on: Milestone 4。
   - Exit gate: AC-12通过；仍不自动生成完整reference dataset。

7. Milestone 6 — Independent sparse benchmark
   - Phase 6A: 建立`satrm_benchmark` sibling package和只读dataset API。
   - Phase 6B: Chronological split、fixed sensor layout、noise接口和preprocessing。
   - Phase 6C: Leakage tests和evaluation schema。
   - Depends on: Milestone 5的stable dataset schema。
   - Exit gate: AC-13通过，architecture tests证明simulation不依赖benchmark。

8. Milestone 7 — Scaling, migration and release readiness
   - Phase 7A: 调用次数instrumentation、static cache、跨region orbit reuse、多frequency execution plan。
   - Phase 7B: 4→20 regions及1→multiple frequencies benchmark，不设置未经验证的wall-time硬阈值。
   - Phase 7C: Legacy API deprecation、文档、release checklist和reference regeneration proposal。
   - Depends on: Milestones 5–6。
   - Exit gate: AC-14和所有此前AC通过；完整dataset regeneration需新的显式批准。

关键依赖关系：

```text
Safety gate
  → Config/domain
    → Data sources/TLE/geometry
      → Scheduler/component interfaces/terrain
        → Beam/atmosphere/weather/clutter/RNG
          → Dataset writer/provenance
            ├─ Independent benchmark
            └─ Scaling optimization
                 → Release readiness
```

## Task Breakdown

Each task includes exactly one routing tag: `coding` or `analyze`.

| Task ID | Description | Target AC | Tag (`coding`/`analyze`) | Depends On |
|---------|-------------|-----------|----------------------------|------------|
| task1 | 建立CF-01平坦非零海拔失败fixture、legacy output characterization和reference generation gate | AC-1, AC-9 | coding | - |
| task2 | 定义legacy dataset状态、结果差异分类和regeneration release checklist | AC-1 | analyze | task1 |
| task3 | 设计并实现typed ScenarioConfig、canonical serialization和reference YAML | AC-3 | coding | task1 |
| task4 | 定义unit、grid、provenance及static/environment/frame/physical state dataclasses | AC-4 | coding | task3 |
| task5 | 建立architecture import tests和legacy CoverageScenario compatibility facade | AC-2 | coding | task4 |
| task6 | 设计source manifest/checksum schema及portable path resolution | AC-5, AC-12 | coding | task3 |
| task7 | 修正DEM pixel-edge affine、reprojection和static region loader | AC-4, AC-6, AC-14 | coding | task4, task6 |
| task8 | 比较并确定TLE epoch policy行为、fallback和maximum-age语义 | AC-5 | analyze | task6 |
| task9 | 实现TLE去重、epoch policy、SGP4 status、orbit provenance和satellite altitude | AC-5 | coding | task8 |
| task10 | 实现WGS-84 ground ECEF、satellite Earth-fixed和pixel ENU geometry | AC-6 | coding | task7, task9 |
| task11 | 建立geometry独立reference、degree/radian、m/km及NaN/Inf tests | AC-6 | coding | task10 |
| task12 | 实现candidate timeline、ReferenceScheduler和no-service/handover events | AC-7 | coding | task9, task11 |
| task13 | 定义PropagationModel contract、component registry和LinkBudgetComposer | AC-8 | coding | task4, task11 |
| task14 | 重写terrain profile state和receiver-relative visibility，输出raw/used diffraction | AC-9 | coding | task7, task10, task13 |
| task15 | 对terrain算法执行synthetic/real-DEM数值审核并确认CF-01关闭 | AC-9 | analyze | task14 |
| task16 | 决定beam boresight、array-factor与scan-loss reference语义 | AC-10 | analyze | task12, task13 |
| task17 | 实现BeamModel及reference gas/cloud AtmosphereModel | AC-10 | coding | task16 |
| task18 | 实现命名RNG stream、moving Gaussian weather和static synthetic clutter | AC-10, AC-11 | coding | task3, task4, task13 |
| task19 | 实现多region/time ScenarioEngine和static/orbit/environment state reuse | AC-4, AC-7, AC-14 | coding | task12, task14, task17, task18 |
| task20 | 确定dataset backend和versioned public schema | AC-12 | analyze | task13, task19 |
| task21 | 实现atomic DatasetWriter/Reader、manifest、resume和integrity checks | AC-12 | coding | task6, task20 |
| task22 | 建立指定frame和small-sequence端到端复现测试 | AC-11, AC-12 | coding | task19, task21 |
| task23 | 建立独立`satrm_benchmark` package、chronological split和sensor sampler | AC-13 | coding | task21 |
| task24 | 实现training-only preprocessing、noise接口和leakage tests | AC-13 | coding | task23 |
| task25 | Profile 4/20-region及single/multi-frequency调用图、内存和I/O | AC-14 | analyze | task19, task21 |
| task26 | 实现经profile证明必要的TLE、static state、terrain和frequency reuse优化 | AC-14 | coding | task25 |
| task27 | 审核全部AC、迁移说明、public API和reference regeneration readiness | AC-1–AC-14 | analyze | task22, task24, task26 |

## Claude-Codex Deliberation

> 透明性说明：本轮没有可调用的独立 Claude reviewer。下列“Agreements”表示由`CODE_SPEC.md`与审计证据直接约束、当前不存在实质争议的事项；“Claude Position”是计划模板要求保留的待复核方案角色，不代表已经完成外部Claude审议。

### Agreements

- 结构改造不能先于correctness characterization，否则无法判断数值变化来自bug fix还是重构。
- CF-01 terrain bug必须作为第一个关闭的物理问题，且现有terrain-enabled数据需要隔离。
- WGS-84/ECEF geometry、TLE epoch policy和scheduler必须位于propagation之外。
- static、environmental和frame state必须显式分层，才能支持20 regions和multi-frequency。
- benchmark应使用独立package并只依赖versioned dataset schema。
- 正式dataset regeneration不是普通测试动作，必须在validation和provenance完成后另行批准。

### Resolved Disagreements

- 先全面重构还是先修单点bug：选择“先加入失败测试和门禁，再在新TerrainModel边界内修复”，原因是既保留可追踪证据，也避免继续扩散错误实现。
- 是否立即采用高保真ITU/多刀刃模型：选择保持`CODE_SPEC.md`定义的reference approximations，高保真模型仅作为未来可插拔扩展，避免把intentional approximation误当bug。
- 是否以wall time作为阶段验收：选择以调用次数、复用边界和结果不变性为硬验收；wall time只记录趋势，因为当前测量依赖机器和数据环境。
- benchmark放在simulation子包还是独立包：选择独立 sibling package，降低反向依赖和训练依赖污染simulation core的风险。

### Convergence Status

- Final Status: `partially_converged`
- Reason: 总体分层、顺序和验收门禁已收敛；TLE epoch policy、beam boresight、dataset backend和building reference scope仍需用户决策。

## Pending User Decisions

- DEC-1: TLE epoch selection policy
  - Claude Position: 优先选择不晚于simulation timestamp的最近TLE，并对无prior record情况显式fallback或失败。
  - Codex Position: 将`closest_prior`作为reference候选政策，但必须由数据集生成语义确认；对当前日内文件在00:00全部为future record的事实不能静默fallback。
  - Tradeoff Summary: closest-prior具有因果语义，但可能在时段开头无数据；closest-absolute覆盖完整但允许未来TLE。两者都会改变部分orbit结果。
  - Decision Status: `PENDING`

- DEC-2: Beam boresight和array gain reference定义
  - Claude Position: 明确采用serving region center steering，并实现可验证的64×64 planar array factor。
  - Codex Position: center steering最符合当前scheduler和pixel off-axis需求，但element spacing、scan loss和empirical attenuation必须先固定，不能从64×64自行推断。
  - Tradeoff Summary: 完整array factor可解释性强但需要更多参数；经验模型更简单但必须被规范明确标注。
  - Decision Status: `PENDING`

- DEC-3: Dataset storage backend
  - Claude Position: 使用Zarr类chunked storage以支持component profile、resume和多frequency。
  - Codex Position: schema和manifest应先于backend固定；Zarr、HDF5或chunked NPY都可接受，但必须支持原子性、checksum和partial-write检测。
  - Tradeoff Summary: Zarr扩展性好但增加依赖；HDF5成熟但并发写限制较多；NPY简单但海量小文件和resume成本高。
  - Decision Status: `PENDING`

- DEC-4: Building/urban model是否属于reference composition
  - Claude Position: 保留为optional extension，默认不进入reference composer，除非`CODE_SPEC.md`补充定义。
  - Codex Position: 同意默认排除；现有building penetration/reflection缺乏receiver语义和独立物理验证，不应与synthetic clutter混合。
  - Tradeoff Summary: 排除可保持reference可解释性；纳入则必须扩展规范、配置、metadata和validation。
  - Decision Status: `PENDING`

## Implementation Notes

### Code Style Requirements

- Implementation code and comments must NOT contain plan-specific terminology such as `AC-`、`Milestone`、`Task`、`Step`或`Phase`。
- 这些标记仅用于计划和验收文档；源码使用领域名称，如`RegionStaticState`、`ElevationHoldScheduler`、`TerrainProfileResult`。
- 公共API、state field和component key必须使用显式单位后缀，例如`frequency_hz`、`range_m`、`elevation_deg`、`power_dbm`、`loss_db`。
- geometry和orbit关键计算使用float64；最终dataset dtype由schema明确规定，不依赖隐式cast。
- 任何clipping都必须同时保留raw和used state，或在schema中明确说明raw不可用的原因。
- 新模块先写失败测试，再实现；不得通过放宽容差掩盖坐标或单位错误。
- 任何改变地图数值的pull request必须附component-level before/after摘要、受影响模块和dataset invalidation判断。

## Plan Completion Definition

本计划完成不等于自动完成reference dataset regeneration。只有同时满足以下条件，才可提出独立的regeneration执行计划：

1. AC-1至AC-14全部通过；
2. 所有Pending User Decisions已经落入`CODE_SPEC.md`或versioned dataset profile；
3. P0 findings全部关闭并由独立数值测试验证；
4. canonical config、source checksums、seed derivation、code/environment version和writer schema冻结；
5. small-sequence dry run验证frame/metadata/component完全对齐；
6. 已明确旧dataset的保留、标记、归档或废弃政策；
7. 用户对完整reference regeneration和可能改变论文benchmark结果给予单独批准。
