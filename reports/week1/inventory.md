# 第一周代码与数据盘点

> 以下为首次交付盘点。最终变更、回归和环境验收见 [closure.md](closure.md)；保留原始缺陷记录以说明修复前状态。

盘点日期：2026-09-28。起点提交：`ddc467bfc3ab0dea00a04a22b733f714981133b1`。
开始时工作区仅有未跟踪的 `plan.md` 与 `week1-plan.md`；本次开发尚未提交，不能用起点提交号代表新代码。实际源码逐文件哈希见 [environment.json](environment.json)。

## 代码能力与复用

| 模块 | 原有实现与局限 | 本周交付与入口 | 后续缺口 |
| --- | --- | --- | --- |
| M0 | `config/models.py`、`domain/`、`data_sources/manifest.py` 已有类型、单位、来源和发布约束；未贯通 legacy CLI | 独立 `config/pilot.py`、`domain/link_record.py`、`io/run_record.py`；由 `experiments/pilot.py` 接通；复用 SourceResolver | 通用数据集 writer、缓存失效执行、全系统状态契约、依赖环境锁定 |
| M1 | `tle.py` 最高仰角选星；`propagation.py` 局部几何、FSPL、经验大气；旧 engine 单帧编排 | `geometry/local.py` 人工接收点相对 ENU 几何，`engine/analytic_link.py` 标量预算、门限裕量和分量状态 | WGS-84 逐像素几何、TLE 历元政策、轨道集成、方向图、完整 E1 |
| M2 | 无方向查询器 | 只保存可辨识配置与输入哈希，不实现缓存 | 建表、插值、周期性、域外与状态边界 |
| M3 | `geodata.py` 旧读取会填充 nodata；`directional_occlusion()` 仍有 CF-01 | `data_sources/dem_audit.py` 保留原始窗口及掩码；准备平地和山脊解析定义 | CF-01、地平线、接收高度、地形基准、剖面与范围验证 |
| M4 | 有验证及发布门禁，无求解器配对系统 | 对旧存储分量检查算术重组；不作为独立物理参考 | 配对求解器、收敛性、模型误差与数值误差分离 |
| M5 | 有 FrameState 类型，没有过境执行器 | 准备含缺测、截尾的人工时间曲线定义 | 全候选过境、窗口提取、门限细化 |
| M6 | 无选址评价器 | 固定任务定义和假设参数 | 开发/测试过境划分、穷举、排序与后悔值 |

旧 `sat-cover` / `CoverageScenario` 的数值逻辑没有修改。新 `SourceKind` 增加 `legacy_output` 和 `source_metadata`，使旧数组与来源说明不必伪装成 DEM 或环境求解数据。

## 实际数据

1. `Satellite-Ground-Radiomap/benchmarks/golden_scenes`：选择同一帧的 composite、L1、L2、L3 四个 256×256 float32 数组，配套 manifest 与配置快照。四个输出的实际 SHA-256 与上游 manifest 一致，声明帧时间为 `2025-01-03T00:00:00+00:00`。
2. 标签为净损耗/局部损耗 dB，不是接收功率 dBm，也不是归一化数组。当前可见生成代码的 L1 定义含 `FSPL + atmosphere + ionosphere + polarization - transmit_gain`；原生成提交号缺失，因此这是有代码和元数据支持的适配声明，不是原生成版本已完整恢复。
3. 上游记录了 IONEX 与 ERA5 回退，卫星元数据为空；保留这些记录，所有样本保持 `legacy_unvalidated`。上游 L2 全零只描述存储值，不能据此证明地形无遮挡。
4. `data/l2_topo/china_dem_30.tif`：全文件哈希与上游记录一致。以旧示例位置 `(108.9016839, 34.2427189)` 裁取原生 64×64 窗口，未插值、未填充。窗口不是已认证地形参考。
5. DEM 水平坐标可读，垂直基准、波段高程单位和供应商版本没有充分证据。该文件以待补元数据的审计对象保存，不写入要求完整垂直基准的严格 DEM source record。
6. `examples/xian.yaml` 所指 2025-01-01 TLE 文件和建筑 `.shp` 文件存在；本周没有用于计算。建筑多文件集合未做完整性核验，不声称已完成建筑源适配。

来源文件与固定哈希见 [pilot-sources.yaml](../../data_manifest/pilot-sources.yaml)，待补 DEM 及审计声明见 [pilot-audit.yaml](../../data_manifest/pilot-audit.yaml)。样本数组没有复制进 Git。

## 测试与环境

- 基线：`100 passed, 1 xfailed`；开发后：`120 passed, 1 xfailed`。CF-01 的 strict xfail 保留。
- 当前 Python 3.12.2；NumPy 1.26.4、PyYAML 6.0.1、Rasterio 1.4.3、PyProj 3.7.2、Skyfield 1.53。详细原生库、CPU、线程环境和代码哈希见 `environment.json`。
- 包尚未 editable 安装，运行使用 `env PYTHONPATH=src python -m ...`，未改动全局 Python 环境。
- 测试期间发现继承的 `PROJ_DATA=/home/zsfang/anaconda3/share/proj` 与 Rasterio 使用的 PROJ 数据库版本不匹配。合成 GeoTIFF 测试改为嵌入完整 WGS-84 WKT，真实 DEM 也读取其自身 WKT；未修改全局变量或伪造 CRS。后续 EPSG authority lookup / reprojection 仍需专门解决环境一致性，当前通过测试不消除该问题。

本次执行没有调用原生成器、轨道传播、建筑栅格化或正式 reference regeneration。
