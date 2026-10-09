# 扩展到 48 km 的传播半径证据

2026-10-09，G03 / Round 2，代码基线 `5e122bd`。G02 已由正式 Round 1 审查验证。

使用原三站点、2/10 m 高于 DSM、72 方位、1/5/10/30° 仰角、550 km 斜距、
14.5 GHz、地球有效半径 6371000 m、60 m 当地网格及内部步长、cell_intervals。
每个站点只加载一次最大 48 km 网格，其所有较小半径共享同一输入，测试半径为
3/6/12/18/24/36/48 km。运行共 3024 条剖面、12096 个查询，全部完成；
没有数据缺口/不支持查询或资源拒绝。完整传播运行 47.71 s，进程峰值 RSS 224920 KiB
（约 219.65 MiB）；不将本次单机耗时作为业务性能承诺。

## 关键比较

| 比较 | 城市 | 山前 | 山地 |
|---|---:|---:|---:|
| 24→48 km 最大地平线差，° | 2.73044 | 0.60721 | 0 |
| 24→48 km 最大原始损耗差，dB | 50.04346 | 3.38826 | 0 |
| 24→48 km LOS 变化数 / 576 | 36 | 0 | 0 |
| 36→48 km 最大地平线差，° | 1.62770 | 0.50585 | 0 |
| 36→48 km 最大原始损耗差，dB | 42.60115 | 1.78284 | 0 |
| 36→48 km LOS 变化数 / 576 | 6 | 0 | 0 |

按既有 0.1° / 1 dB / 零 LOS 翻转 / 至少两次外层扩展的诊断规则：

- 城市、山前仍没有整组查询稳定的候选半径；36 km 仍随扩展变化。
- 山地 18 km 与 24 km 均在已测范围内稳定，最小整组稳定候选为 18 km。
- 三站点 48 km 都缺更外层证据；山地 36 km 虽与 48 km 相同，也只有一次扩展。
- 所有全局充分性仍是 `not_verified`，不能声称 48 km 已足够。

## 全部查询保留

每站点 576 个方向/高度/仰角查询，各包含 7 个半径判定及所有更大半径比较。
逐查询保存实际 horizon、raw loss、LOS、coverage/status、误差及输入绑定，
不只保留失败样本或汇总最大值。

| 全半径查询判定计数 | 城市 | 山前 | 山地 |
|---|---:|---:|---:|
| 随扩展变化 | 1556 | 1639 | 65 |
| 已测范围内稳定 | 1472 | 1379 | 2815 |
| 外层证据不足 | 1004 | 1014 | 1152 |
| 缺失/不适用 | 0 | 0 | 0 |

24 km 时，城市 204/576、山前 146/576 查询仍随扩展变化；山地 576 个均满足有限范围诊断。
不以单个稳定查询替代整站点/全路径结论。

原始完整运行：`output/m3-radius-48km-20261009/`。
逐查询压缩 JSONL：`output/m3-radius-48km-queries-20261009/*-queries.jsonl.gz`。
[跟踪摘要](radius-48km-summary.json) 保存所有逐查询文件的哈希、完整运行 manifest、
配置摘要、资源和比较结果。分析前逐一验证输入运行文件哈希，输入运行失败则分析也失败，
不将没有执行的样本算稳定。两次运行均有源码 ZIP 和环境记录。

## 复现及后续

```bash
bash scripts/python_geo.sh scripts/verify_terrain_sensitivity.py \
  --dem ../Satellite-Ground-Radiomap/data/l2_topo/china_dem_30.tif \
  --geoid output/geoid/egm2008-complete.tif --output output/radius48-replay \
  --sampling-method cell_intervals --radii-m 3000 6000 12000 18000 24000 36000 48000 --steps-m 60
bash scripts/python_geo.sh scripts/summarize_radius_queries.py \
  --input output/radius48-replay --output output/radius48-query-replay
```

官方 G03 分析调用成功（150 s），建议保留有限半径数值、强制机器可读范围声明和逐样本绑定，
不把稳定诊断升级成全路径证明。已据此冻结 [G04 契约](../../docs/TERRAIN_RANGE_CONTRACT.md)。
业务门限仍待定，DEM 拼接历史仍未知；48 km 的几何/曲率误差属于 G05，M3 未整体验收。
