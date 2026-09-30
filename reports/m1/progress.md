# M1 基础功能第一批交付

> 历史记录：随后已继续完成统一输入、方向图及分量开关。本文件的“尚未完成”是首批状态；当前结论、186 项回归和最终重算目录以 [M1 阶段验收](acceptance.md) 为准。verification.json 现对应统一入口的最终验收运行。

日期：2026-09-29。工作重点已按用户要求调整为先完善基础功能，暂停扩展 demo。本轮尝试新增的前端展示页及入口已撤回，之前的独立前端保留。

## 已完成及边界

| 项目 | 本轮结果 | 边界 / 备注 |
| --- | --- | --- |
| 高度契约 | 明确天线椭球高；或显式提供地面正高、匹配基准的 geoid undulation 和 AGL，按 h=H+N+AGL 转换 | 不自行猜测 geoid 或 DEM 单位。转换输入一致性由来源证据负责；极点局部坐标方向由声明的经度定义 |
| 几何 | WGS-84 地面 ECEF、椭球法线 ENU、距离/北起顺时针方位/仰角；天顶方位不适用 | 使用 1e-8 m 坐标零值容差处理旋转舍入，非物理精度声明；ITRS/WGS84 未做板块运动历元修正 |
| TLE 政策 | `past_only` 与 `historical_exploration`；整个时段固定同一条 TLE，按整个区间检查最大历元偏差 | 新实验显式配置，默认示例仅历史；旧窗口 API 的省略字段行为仍允许未来历元并标记，以兼容现有演示 |
| 链路预算 | 真实 TLE → ITRS/ECEF → ENU → FSPL → 分量重组 → 条件接收功率/可选裕量 | 人工算例和轨道入口共用标量逻辑；显式 EIRP 或发射功率+增益；当前仍是固定标量增益 |
| 状态 | 无历史 TLE、过期、传播失败、几何不可见、损耗未知分别保留 | 行级 `computed` 指轨道和预算求值完成；必须继续检查 `budget.received_power.status`，不能视作功率已知 |
| 可复现运行 | 保存原始 TLE、配置、选定行哈希、源码 ZIP、环境、样本记录、资源和产物哈希 | 输出目录不可覆盖；缺失轨道的 CLI 返回 2，运行异常记录 failed；验证 passed 只表示执行检查通过 |
| DEM 来源 | 复查现有 README 和项目说明，尚未找到与当前文件绑定的高程单位/垂直基准证据 | 仍未解决；本次使用显式假设的 400 m 天线椭球高，不用 DEM 估计高度 |

## 验证结果

`bash scripts/python_geo.sh -m pytest tests -q`：**168 passed in 6.79s**。此前 148 项仍通过，新增 20 个参数化测试实例。覆盖 PROJ 独立实现对照、解析轴向/天顶/地平线、正高转换、轨道与相对 ENU 一致性、参数变化、未知损耗、TLE 时效、传播失败、UTC 要求、采样上限和运行复现/失败归档。

真实实验：2025-01-01 05:00 UTC 至 2025-01-02 00:00 UTC，10 s 步长，西安测试点 (108.9°, 34.24°)，NORAD 44714。选择 2025-01-01 04:32:50.710846 UTC 历元；无未来元素使用。

- 共 6,841 个采样点，473 个当地地平线以上点产生条件功率；其余 6,368 个点的功率为 `not_applicable`。
- 55 dBm EIRP、14.5 GHz、接收增益 0 dBi、关闭大气/局部/其他损耗，均为测试假设，**不是 Starlink 实际规格**；关闭局部效应不表示已经确认无遮挡。
- 条件功率范围：−129.288357550 至 −116.331106497 dBm。不应用通信门限，也不产生服务窗口。
- 地面 ECEF 与 PROJ 最大误差 0 m（此测试点）；轨道距离对照最大误差 5.402e-8 m，仰角 2.885e-12°，方位 1.564e-12°；标量功率重组最大误差 0 dB。

详细数值、容差和源码身份见 [verification.json](verification.json)。PROJ 仅独立检验地面坐标；Skyfield 站心对照与主计算共享轨道传播，不是独立轨道真值。上述小误差不能解释为卫星实际位置达到该精度。

## 重算方法

在后端仓库目录运行（外部 TLE 路径按本机位置调整；输出必须是新目录）：

```bash
bash scripts/python_geo.sh -m satellite_coverage.experiments.orbit_link \
  --config configs/orbit_link.yaml \
  --tle ../Satellite-Ground-Radiomap/data/starlink-2025-tle/2025-01-01.tle \
  --output output/m1-new-run
bash scripts/python_geo.sh scripts/verify_orbit_link.py \
  --run output/m1-new-run --output output/m1-new-verification.json
```

本次完整归档位于 `output/m1-orbit-final-20260929/`，包括约 21 MiB 的 `links.json`。大结果在 Git 忽略的 output 下，精简报告和验证指标可纳入版本控制。原始 TLE 已归档在运行目录；其哈希为 `e661f17444e4fdc4eed85ccfef437d87f33796193bf8ca000bdb3058715b9b7f`。

## 尚未完成与接下来的基础开发顺序

1. **统一三类输入接口**：已有固定 ECEF 几何函数、人工相对 ENU 入口和新轨道实验，但还不是同一批量输入契约；需要统一样本身份、时间、错误状态与调度。
2. **简单可配置方向图**：增加明确坐标系的波束轴、角度响应和缺参检查；固定标量增益不能视作方向图完成。
3. **完整分量配置与 M1 验收**：目前通过显式零损耗及 reason 表示关闭，仅支持固定大气情景；继续完善开关与适用条件。建立正式 M1 验收矩阵后再判定模块完成。
4. **M3 地形**：确认 DEM 单位/垂直基准或改用有来源证据的小块数据，再做剖面范围、地球曲率、nodata 和地平线遮挡验证。
5. **E1 完整实验**：当前是前置一致性验证；复杂地形、方向缓存与直接计算的对照尚未实现。基础验收后再同步 demo。

本轮没有执行 commit 或 push，不将当前进展标记为 M1 全部完成。

## 公式与实现参考

- [ESA Navipedia：ECEF / ENU transformations](https://gssc.esa.int/navipedia/index.php/Transformations_between_ECEF_and_ENU_coordinates)：椭球法线 ENU 旋转及方向约定。
- [Skyfield reference frames](https://rhodesmill.org/skyfield/api-framelib.html)：ITRS 地固坐标转换。代码使用 `frame_xyz(itrs)`，没有将 SGP4 的 TEME 数值直接当作 ECEF。
