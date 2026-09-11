# Scenario Configuration

`satellite_coverage.config`是simulation的typed configuration边界。它负责把YAML转换为冻结的domain-neutral配置对象；传播、轨道、geometry等模块不应自行读取YAML。

## Public API

```python
from satellite_coverage.config import load_scenario_config

config = load_scenario_config("configs/reference.yaml")
canonical_bytes = config.canonical_json_bytes()
config_checksum = config.checksum_sha256()
```

canonical representation使用UTF-8 JSON、排序后的mapping keys、无额外空白、UTC `Z` timestamps和规范化的`EPSG:4326`标识。它不受YAML mapping顺序影响，可在后续manifest中作为配置identity；当前阶段不会自动写manifest。

## Unit Contract

公共字段通过名称声明单位：

- frequency: `frequency_hz`；
- power: `transmit_power_dbm`；
- gain: `*_dbi`；
- attenuation/loss: `*_db`；
- angle: `*_deg`；
- distance/resolution/extent: `*_m`；
- time cadence: `interval_s`；
- raster dimensions: `*_px`。

loader不接受`frequency_ghz`、`transmit_power_dbw`等alias，也不执行隐式Hz/GHz或dBm/dBW转换。未知字段、缺失字段、bool伪装成数值、NaN/Inf、非法范围和不一致的extent/timeline都会触发`ConfigError`。

## Reference Profile Status

[`configs/reference.yaml`](../configs/reference.yaml)包含`CODE_SPEC.md`已经明确的reference数值：

- 4 regions；
- 768×768 pixels，100 m/pixel，76.8 km×76.8 km；
- 2025-01-01 00:00:00至11:59:40 UTC，20 s间隔，2160 frames/region；
- 25° minimum elevation和14.5 GHz carrier；
- specification中列出的antenna、atmosphere、terrain、weather与clutter常数。

该文件保持`profile_status: draft`，原因是`CODE_SPEC.md`没有给出四个region的真实footprint/center/source identity，也没有冻结root seed。文件中的`reference-region-01`至`04`和`20250101`是显式的provisional inputs，用于完成schema和determinism测试，不是对reference dataset地理范围或随机realization的授权决定。

后续data-source manifest必须把region ID解析到有checksum的DEM/CRS/footprint；root seed也必须在reference profile决策中冻结。在这些条件、P0 correctness checks和独立用户批准全部满足前，`profile_status`不得改为`frozen`，且该配置不得用于正式dataset regeneration。

## Legacy Compatibility

当前`CoverageScenario.from_yaml()`仍读取legacy single-frame YAML，例如`examples/xian.yaml`。本轮没有把它切换到新schema，因为compatibility facade属于后续任务。新旧配置格式目前并存且语义不同：

- legacy YAML只支持当前单region/single-frame演示路径；
- typed ScenarioConfig描述目标engine输入，不直接调用legacy物理函数；
- 迁移完成前，不应把两种schema静默互换或自动猜测单位。
