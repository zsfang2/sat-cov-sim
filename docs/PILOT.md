# 小样本解析链路与数据审计

## v0.1.1 隔离环境与完整验收

验收目标为 CPython 3.12、Linux x86_64。`requirements-week1.lock` 固定所有运行/测试依赖的版本与轮子哈希；其他平台需要单独验证适用轮子。

```bash
python -m venv .venv
# 由能访问网络的现有 pip 下载；隔离环境可完全离线安装。
python -m pip download --require-hashes -r requirements-week1.lock --dest output/wheelhouse
.venv/bin/python -m pip install --no-index --find-links output/wheelhouse --require-hashes -r requirements-week1.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .

bash scripts/python_geo.sh scripts/check_geo_environment.py
bash scripts/python_geo.sh scripts/verify_week1.py --source-root ../Satellite-Ground-Radiomap --output output/week1-acceptance
```

`python_geo.sh` 只清理子进程继承的外部 PROJ/GDAL 和 Python 路径覆盖，让当前虚拟环境的库选择配套数据；不改全局环境。可设置 `SATCOVER_PYTHON` 指向另一个解释器。坐标自检直接使用 EPSG authority lookup、创建栅格并执行重投影，不再仅靠 WKT 创建 fixture 避开原问题。

完整验收命令执行依赖检查、全部测试、真实样本审计及两次解析运行，保存日志和 `acceptance.json`。有任何步骤失败都返回失败；未知 DEM 垂直条件按审计合同明确保存，不伪造为物理合格。

运行目录新增 `source_snapshot.zip`，包含实际源码、测试、配置、来源声明、脚本和锁文件，逐文件哈希记录在 `environment.json` 中。解压快照可以恢复这些未提交或已提交文件；原始数据仍通过固定来源清单获取。

## 单项命令

在仓库根目录运行。已有依赖环境中无需安装项目，使用 `PYTHONPATH=src` 即可；如已执行 `python -m pip install -e .`，可省略该前缀。

在上述隔离环境中，建议将下例 `env PYTHONPATH=src python` 换成 `bash scripts/python_geo.sh`；测试使用 `bash scripts/python_geo.sh -m pytest tests -q`。旧全局解释器的地理数据覆盖可能仍然不匹配。

```bash
# 独立的真实数据审计：需要相邻的 Satellite-Ground-Radiomap 数据目录
env PYTHONPATH=src python -m satellite_coverage.experiments.pilot validate-data --config configs/pilot.yaml --output output/pilot-audit

# 解析链路：不依赖外部 DEM、旧输出、轨道或网络
env PYTHONPATH=src python -m satellite_coverage.experiments.pilot run --config configs/pilot.yaml --output output/pilot-a
env PYTHONPATH=src python -m satellite_coverage.experiments.pilot run --config configs/pilot.yaml --output output/pilot-b

python -m pytest tests -q
```

输出目录必须不存在；重跑请换目录或省略 `--output`，自动创建带 UTC 时间的目录。失败返回非零退出码，并在已经创建的运行目录保存原因、日志和已收集输入。已有目录始终拒绝覆盖。

数据不在默认位置时，为 `validate-data` 传入 `--source-root /absolute/path/to/Satellite-Ground-Radiomap`。固定哈希不匹配会失败，不能用“更新哈希”代替对新数据版本的重新审计。原始 DEM 的全文件校验会读取约 8.6 GiB，本次机器耗时数秒；解析 `run` 不进行这一步。

## 输出解释

| 文件 | 内容 |
| --- | --- |
| `config.json` / `config_source.json` | 校验后的规范配置、原配置文本及哈希 |
| `inputs.json` | 实际使用的输入身份；解析运行明确声明未消费外部文件 |
| `environment.json` | 提交号、dirty 状态、包含未跟踪源码的逐文件哈希、依赖和硬件 |
| `link_records.json` | 解析链路的几何、功率声明、分量、状态和结果；纯审计运行为空列表 |
| `sample-audit.json` | 旧标签、单位、分量重组、DEM 元数据和限制；只在成功完成审计时存在 |
| `dem_window.npy` / `dem_nodata_mask.npy` | 原始像元与独立掩码；不重采样、不填充 |
| `upstream_manifest.json` / `upstream_config_snapshot.json` | 上游证据和回退记录 |
| `validation.json` / `run.log` | 完成或失败状态、原因及运行日志 |
| `timings.json` / `resources.json` | 分阶段开销、重复计时和进程峰值内存 |
| `artifacts.json` | 运行目录内输出文件的 SHA-256 清单；不包含清单自身 |

可逐字节比较两次解析运行的 `config.json`、`inputs.json`、`link_records.json`。时间、计时、内存和工作区状态记录不要求相同。源码变化应反映为新的源码指纹。

`completed` 表示程序完成，`completed_with_limitations` 表示审计完成但有未决条件，二者均不等同于 `validated_reference`。未知损耗不会作为零参与预算；未设门限时裕量为 `not_computed`。无实际服务信息时 `service_eligibility` 始终为 `unknown`。

## 物理和接口范围

- `run` 仅支持人工接收点相对 ENU 向量与标量平均功率，不支持轨道、路径级相位、多径或方向图。
- EIRP 与发射功率加增益为互斥模式。重复效应被拒绝；负局部附加损耗允许表示明确声明的增强。
- 接收点 AGL 高度作为输入身份保存。当前相对向量已从天线起算，改变 AGL 元数据本身不会重新计算地形或卫星位置。
- 旧数组适配支持显式 dBm、dBW、dB，以及带完整参数的仿射反归一化。未知单位和缺失反归一化参数不能用于物理误差比较。
- 本批上游 L1 的净损耗已减去发射增益，不能把它当作纯 FSPL 再叠加同一增益。原生成提交未恢复，所有旧样本保持未验证状态。
- 真实 DEM 的垂直条件仍未知；审计不提供地形损耗。人工平地、山脊和时间曲线定义位于 `tests/fixtures/analytic/`，后两者还没有完整求解器。
- 本周结果与复现证据见 `reports/week1/summary.md`。该功能不接入正式 reference 注册或 regeneration 流程。
