# Satellite Coverage Sim

Satellite Coverage Sim 是一个面向科研的动态卫星—地面无线电地图仿真项目。项目目标是把卫星轨道、地理环境、逐像素链路几何和无线传播机制组合成可验证、可复现的接收功率时空数据集，并为后续稀疏无线电地图重建提供独立、清晰的数据接口。

项目的预期行为和reference configuration以 [`CODE_SPEC.md`](CODE_SPEC.md) 为唯一技术规范。当前仓库正在按照 [`PROJECT_STRUCTURE_MODIFICATION_PLAN.md`](PROJECT_STRUCTURE_MODIFICATION_PLAN.md) 分阶段建设，下面将目标功能与当前实现状态分别说明。

## 项目目标功能

### 场景配置与地理数据

- 统一管理区域、时间、频率、发射功率、天线、传播参数和随机种子；
- 从DEM构建具有明确CRS、分辨率、latitude、longitude和elevation的地面网格；
- 缓存ground ECEF、DEM、region geometry和static environment等静态状态；
- 记录TLE、DEM及其他外部数据源的版本、checksum和provenance。

### 卫星轨道、几何与服务状态

- 使用TLE和SGP4传播卫星轨道；
- 明确处理TEME、Earth-fixed、WGS-84 geodetic和local ENU坐标；
- 逐像素计算slant range、elevation、azimuth和beam off-axis angle；
- 根据minimum elevation、当前serving satellite和candidate states执行可替换的调度策略；
- 记录initial acquisition、service pass、handover和no-service状态。

### 无线传播与链路预算

- 计算自由空间路径损耗；
- 建模卫星阵列天线、波束指向、扫描损耗和off-axis attenuation；
- 分别输出gaseous、cloud、terrain、weather和clutter attenuation；
- 基于extended DEM执行terrain profile tracing、LOS判定和dominant single knife-edge diffraction；
- 区分raw physical state与用于reference dataset的clipped state；
- 通过显式dBm、dBi和dB分量组成clean received-power map。

### 时序数据集与可复现性

- 生成多区域、多时刻和可扩展到多频率的radio-map sequence；
- 为每一帧保存region、UTC timestamp、satellite、pass、handover和center geometry metadata；
- 按storage profile选择保存geometry及各传播component maps；
- 使用相互独立的weather、clutter、sensor、split和ML random streams；
- 支持带manifest、完整性校验、断点恢复和确定性重建的数据输出。

### 独立稀疏重建benchmark

- 从已生成完成的clean radio maps读取数据，不反向调用physical simulation internals；
- 实现固定、无放回的sensor layout和可选measurement-noise接口；
- 提供known-region chronological train/validation/test split；
- 保证normalization只由training split拟合，避免数据泄漏；
- 为后续reconstruction和evaluation提供稳定、版本化的数据schema。

## 当前实现状态

当前版本仍是迁移前的legacy单帧仿真器，已经具备：

- 读取YAML中的单区域和单时刻配置；
- 使用Skyfield从TLE计算region center的卫星可见性，并选择最高仰角候选；
- 创建north-up局部网格，按窗口读取GeoTIFF DEM；
- 将建筑Shapefile栅格化为building-height map；
- 计算FSPL、经验大气损耗、方向性terrain/building遮挡、单刀刃绕射和简化urban loss；
- 输出单帧received power、total loss和当前已有components的NumPy数组及PNG预览。

尚未完成的核心部分包括：统一WGS-84/ECEF逐像素geometry、stateful scheduler、reference beam、weather、clutter、批量时序生成、完整metadata、chronological split和独立benchmark pipeline。

> [!WARNING]
> 当前实现不是已经验证的reference dataset generator。审计确认legacy terrain遮挡算法存在CF-01：使用绝对DEM高程时会产生大面积虚假遮挡。启用terrain生成的现有输出不得标记为validated reference data。详见 [`CODE_AUDIT_REPORT.md`](CODE_AUDIT_REPORT.md) 和 [`docs/DATASET_VALIDATION.md`](docs/DATASET_VALIDATION.md)。

## 建模边界

当前reference方向包含若干有意采用的工程近似，例如fixed zenith atmospheric scaling、synthetic weather、synthetic clutter和dominant single knife-edge diffraction。这些近似不等同于软件bug，但必须在component metadata中明确标注。

本项目不把方向性栅格遮挡称为完整三维电磁ray tracing，也不声称当前实现能够产生CIR、相位、多径或MIMO channel。ERA5/IMERG、land-cover-aware clutter、完整ITU-R模型和高保真ray tracing属于未来可插拔扩展。

## 项目文档

- [`CODE_SPEC.md`](CODE_SPEC.md)：当前唯一intended technical specification；
- [`CODE_AUDIT_REPORT.md`](CODE_AUDIT_REPORT.md)：规范一致性、物理、数值、复现性、性能和架构审查；
- [`PROJECT_STRUCTURE_MODIFICATION_PLAN.md`](PROJECT_STRUCTURE_MODIFICATION_PLAN.md)：分阶段结构改造计划和验收标准；
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)：当前过渡调用图、public namespace与依赖方向；
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)：typed config边界与draft reference profile；
- [`docs/DOMAIN_STATE.md`](docs/DOMAIN_STATE.md)：不可变domain state、array unit与coordinate contract；
- [`docs/DATASET_VALIDATION.md`](docs/DATASET_VALIDATION.md)：legacy数据状态和reference generation门禁。

## 安装与当前单帧示例

```bash
cd satellite-coverage-sim
python -m pip install -e .
sat-cover examples/xian.yaml --output output/xian
```

示例配置引用仓库外部的TLE、DEM和建筑数据。运行前需要根据本机数据目录修改`dem_file`、`buildings_file`和`tle_file`。该命令仅用于legacy单帧实验，不生成正式reference dataset。

## 来源与许可说明

本项目作为独立的卫星无线电地图simulation engine进行规范、验证和维护。仓库早期部分地理数据读取、方向性栅格遮挡与链路预算代码参考并重新组织自工作区中的`Satellite-Ground-Radiomap`（MIT License）；这一历史来源不定义本项目的功能范围，项目行为以本仓库的`CODE_SPEC.md`为准。
