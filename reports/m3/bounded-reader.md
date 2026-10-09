# 有界 DEM 读取验证

2026-10-09，RLCR Round 1 / G02，AC-2、AC-5。前置 G01 已由官方 Round 0
审查验证，门禁生成 Round 1 后开始编码。本报告不代表 M3 整体验收。

## 实现与兼容性

读取器采用两遍目标分块。第一遍不读取高程数组，逐块投影和 floor，汇总准确的
合法源像元包围范围，继续按原五位置检查 native spacing；第二遍按局部最小窗口读值。
目标块初始 128×128，源窗口大于 262144 格时沿较长目标边递归细分。
全输出最多四百万格，原生存储块最多四百万格，GDAL cache 32 MiB，
分配输出前检查 G01 的 512 MiB 估计预算。`TerrainReadBudget` 只能收紧这些上限。

最近原像元、nodata/NaN、scale/offset、源像元中心 geoid、高程声明/文件哈希、
返回类型及物理 metadata 保持一致。执行诊断通过可选字典和窗口回调输出，
不混入物理 `identity(metadata)`；CLI 旧调用不需要增加参数。
原始数值求解器、传播窗口和半径充分性判定没有修改。

预算为执行前估计及本机资源验证门限，不是任意宿主环境的操作系统内存保证。
源 dtype 与原生存储块副本计入估计。输出仍是不可变内存网格，因此没有引入
memmap 的文件生命周期或隐藏全量复制问题。

## 验证结果

完整回归：`bash scripts/python_geo.sh -m pytest tests -q` → **289 passed in 8.54 s**。
新增 17 个测试案例，包括冻结旧读取器对照、旋转 affine、随机高度、scale/offset、
内部缺失、部分/空交叠、geoid、像元边界、非有限投影、预算预检、参数类型、
存储块内存预留、极细分单像元读取，以及超过旧四百万源格限制的人工大窗口。
旧 oracle 来源 `b234bcb`，仅调整 imports，存于 `tests/fixtures/terrain_dem_legacy.py`。

单像元读取是递归的最小成功条件；合法预算最少允许一个源格，因而不可能再超限。
零格预算在入口拒绝；代码仍保留最小块超限错误以防内部契约破坏。
不能把测试中的人工地形或旧读取器当成独立物理传播真值。

真实数据使用同一哈希绑定的 Copernicus DSM / EGM2008 网格，站点 108.9/34.24，
60 m 分辨率。每个模式/半径在新进程顺序执行：

| 半径 | 目标格数 | 读取窗口数（128 tile） | 单次最大源格数 | 重复读取格数 | 峰值 RSS MiB |
|---|---:|---:|---:|---:|---:|
| 3 km | 103² | 1 | 47760 | 0 | 151.43 |
| 6 km | 203² | 4 | 74451 | 0 | 151.23 |
| 24 km | 803² | 49 | 74700 | 0 | 154.93 |
| 36 km | 1203² | 100 | 75250 | 0 | 154.69 |
| 48 km | 1603² | 169 | 75500 | 1145 | 183.30 |

3/6/24 km 与旧读取器比较：数组逐值相等（包括缺失掩码）、metadata 完全相等、
source_id 完全相等；另以 64×64 tile 重复验证分块大小不改变结果。
36/48 km 在当前 512 MiB 预算内成功，但尚未运行扩大范围后的传播查询矩阵。
24 km 旧路径峰值约 204.80 MiB；新路径約 154.93 MiB。
RSS 含 imports 和源码归档历史峰值，不等同于纯读取增量；缓存未控制，不能当吞吐 SLA。
重复格数由访问矩形的精确并集计算，不包含 GDAL 原生存储块内部解压的重复字节。

详细窗口、规划/执行投影、geoid、哈希、读写耗时、版本和源码哈希见
[机器记录](bounded-reader-summary.json)。完整原始结果、NPY、实际工作源码 ZIP 在
`output/{legacy,bounded,bounded64}-reader-<半径>km-20261009/`。

## 复现

```bash
bash scripts/python_geo.sh scripts/verify_terrain_reader.py \
  --dem ../Satellite-Ground-Radiomap/data/l2_topo/china_dem_30.tif \
  --geoid output/geoid/egm2008-complete.tif --radius-m 48000 \
  --output output/bounded-reader-replay
```

小窗口可分别使用 `--mode legacy`、默认 bounded 及 `--tile-size 64`，
每次指定不同输出目录。输入声明仍来自仓库的文件绑定来源证据，参数化路径不等于
允许任意无声明 DEM。脚本保存失败记录，不覆盖旧运行。
G01 的 `measure_terrain_reader.py` 是针对旧函数行标记的历史探针，会拒绝不匹配的新读取器；
当前复现使用上面的新脚本，历史探针可在 `b234bcb` 版本复现。

## 后续

G02 实现及本轮验证已交付，待原生审查；G03 将使用扩大范围生成传播矩阵并冻结
有限范围/未验证/未计算契约。G05 的几何/曲率适用域、G06 的 M3 验收仍待完成。
用户声明的产品来源及未知拼接历史不变，不修改正式 reference 数据，不扩展 demo。
