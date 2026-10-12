# 原生代码审查修复记录

2026-10-12。实现阶段已获 [Round 19 原生审查通过](implementation-gate.md)，hook 自动进入代码审查；[Round 20 发现](code-review-round20.md) 是源码运行缺少安装包元数据时，可见窗口计算在结果组装阶段抛出 `PackageNotFoundError`。

修复仅捕获版本查询的 `PackageNotFoundError`，缺失版本记为 JSON `null`，与现有运行环境记录约定一致。已安装版本照常保留，其他元数据错误不吞掉；不修改轨道、可见窗口和研究实验计算。

回归先验证修复前 1 failed / 7 passed，失败精确复现缺少 `satellite-coverage-sim` 元数据。修复后 `tests/test_visibility.py` 8 passed（1.24 s），全量 `tests` 466 passed（13.82 s）。新增用例覆盖缺少元数据仍返回真实可见窗口、正常版本保留和其他异常继续抛出。

G15 离线包继续是先前冻结的 `70e93f0` 快照（457 项新环境测试），不包含本次元数据修复；当前工作树回归为 466 项。原生代码复审及 Finalize 尚待完成。
