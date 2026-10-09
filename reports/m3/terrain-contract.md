# 有限范围输出契约接入验证

2026-10-09，G04 / RLCR Round 3；G03 已由 Round 2 正式审查验证。

`calculate_links(..., terrain=...)` 的顶层、全部逐候选记录及非空 received_power
均新增 `terrain_contract`。`TerrainContext.evaluate()` 的直接输出也包含范围声明。
强制字段包括实际 radius/step/sampling、`finite_radius_conditional`、
`full_path_status=not_verified`、业务与服务未知状态；逐记录包含失败类别、
候选/时间/几何/频率/接收高度/地形栅格/物理输入 checksum 绑定及 query_id。
未自动附加任何外层矩阵摘要，`radius_audit_status=not_attached`，避免错配查询。

资源拒绝统一使用 `TerrainResourceError(ValueError)`，继续兼容原捕获方式。
CLI 新增可选只收紧预算的 `read_budget`，独立保存 `terrain_read.json`；
失败归档的 `validation.json.failure_kind` 区分资源、非法输入、上游输入不可用和 solver。
正常有限功率、缺失、采样未验证、域外、低于水平面等按
[冻结契约](../../docs/TERRAIN_RANGE_CONTRACT.md)判定。
对已有 M1 可含未知非地形损耗的场景补充 `component_unavailable`，不把它误判成地形失败。

## 验证

- 完整回归：**309 passed in 8.61 s**；新增 17 个场景。
- 覆盖所有输出层级、条件功率不升级为全路径、query_id 随候选时间/频率/高度/方向/栅格改变、
  原物理 checksum 构造不变、nodata/receiver nodata、采样不通过、天顶/近端、低于水平面、
  TLE 不可用、solver 失败、非地形分量未知、CLI 精确 JSON 归档及资源/非法预算区分。
- 真实回放 `output/m3-contract-guard-20261009` 对比
  `output/m3-loss-guard-20261009`：60/15/7.5 m 三步长各 571 个样本，
  每组 38 个有限条件已知功率、零采样审计失败。
- 递归移除新增 `terrain_contract` 后，三个完整 links JSON 与旧归档精确相等，
  包括所有几何、剖面、raw/used loss、功率、状态及 physical_input_checksum。
  新声明全路径仍未验证，不修改旧文件。

[机器验证记录](terrain-contract-verification.json) 保存新旧运行及完整 artifact manifests。
实际回放含输入哈希验证、源码 ZIP、依赖环境及原始逐记录输出。
回放命令：

```bash
bash scripts/python_geo.sh scripts/verify_terrain_guard.py \
  --run output/m3-real-copernicus-final-20260930 \
  --output output/m3-contract-guard-replay --sampling-method cell_intervals
```

G04 待本轮审查，M3 仍未整体验收。后续 G05 完成原生网格/当地网格、曲率和特殊几何
的数值矩阵；G06 按实际证据判断验收。业务指标及源拼接历史未知状态继续保留。
