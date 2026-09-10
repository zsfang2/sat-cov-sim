# Satellite Coverage Sim

一个从 SG-MRM 提炼出的轻量卫星—地面覆盖仿真器。它保留地理坐标对齐、TLE 卫星选择、GeoTIFF DEM、建筑 Shapefile 与快速的传播损耗估计；不包含多尺度数据集构建、批量拼接、训练或产品导出流水线。

## 包含的能力

- WGS84 / Web Mercator / 栅格 CRS 对齐，统一到本地 ENU 风格网格；
- 从 TLE 中选择指定时刻和地点可见度最高的卫星；
- 按仿真窗口读取 GeoTIFF DEM；从 Shapefile 栅格化建筑高度；
- 计算自由空间损耗、大气近似损耗、地形/建筑遮挡、单刀刃绕射、建筑穿透和一阶反射近似；
- 输出接收功率、总损耗、遮挡与各损耗分量的 NumPy 数组及 PNG 图。

“类射线追踪”是方向性栅格遮挡扫描，不是完整三维电磁路径追踪。若需要每条多径的 CIR、相位或 MIMO 信道，应把局部几何转换至 Sionna RT。

## 安装与运行

```bash
cd satellite-coverage-sim
python -m pip install -e .
sat-cover examples/xian.yaml --output output/xian
```

示例配置引用同级工作区的 SG-MRM 数据。运行前按本机目录修改 `dem_file`、`buildings_file` 与 `tle_file`。

## 致谢

坐标网格、DEM 窗口读取、方向遮挡与链路预算的设计由本工作区的 `Satellite-Ground-Radiomap`（MIT License）提炼并重新组织。

