# 原生代码审查修复记录

2026-10-12。实现阶段已获 [Round 19 原生审查通过](implementation-gate.md)，hook 自动进入代码审查；[Round 20 发现](code-review-round20.md) 是源码运行缺少安装包元数据时，可见窗口计算在结果组装阶段抛出 `PackageNotFoundError`。

修复仅捕获版本查询的 `PackageNotFoundError`，缺失版本记为 JSON `null`，与现有运行环境记录约定一致。已安装版本照常保留，其他元数据错误不吞掉；不修改轨道、可见窗口和研究实验计算。

回归先验证修复前 1 failed / 7 passed，失败精确复现缺少 `satellite-coverage-sim` 元数据。修复后 `tests/test_visibility.py` 8 passed（1.24 s），全量 `tests` 466 passed（13.82 s）。新增用例覆盖缺少元数据仍返回真实可见窗口、正常版本保留和其他异常继续抛出。

G15 离线包继续是先前冻结的 `70e93f0` 快照（457 项新环境测试），不包含本次元数据修复；当前工作树回归为 466 项。原生代码复审及 Finalize 尚待完成。

## Round 21：身份异常不得转成失败样本

[原生审查发现](code-review-round21.md)：`CacheMismatch` 继承 `ValueError`，方向表 `_solve` 对数值异常的捕获误吞了身份异常。新增独立捕获并立即重新抛出，使建表和直接回退遇到返回范围/上限不一致或求解器主动报告身份错误时均拒绝。

6 个身份反例先全部失败，修复后通过；普通 `ValueError`、`ArithmeticError`、`RuntimeError` 仍记录为失败样本。方向表/E1/E3 相关测试45项通过（0.24 s），全量474项通过（13.23 s）。`output/m2-native-review-20261012` 实际验证84个建表样本、72个已知样本，重现误差0 dB、过期频率缓存拒绝、批量及直接回退通过；所有归档产物 SHA256 已核验。

此修复改变身份不匹配的拒绝行为，不改变合法输入传播数值。模型源码指纹随代码变化使旧缓存失效是预期行为；历史 E1/E3 和 G15 快照保持原样。仍需原生复审和 Finalize。
