# 原生代码审查修复记录

当前状态：Round25原生代码审查通过，无新发现；最终回归496项通过（13.83 s）。以下Round20–24段落保留当时测试与待审状态，当前结论见[通过记录](code-review-pass.md)。

2026-10-12。实现阶段已获 [Round 19 原生审查通过](implementation-gate.md)，hook 自动进入代码审查；[Round 20 发现](code-review-round20.md) 是源码运行缺少安装包元数据时，可见窗口计算在结果组装阶段抛出 `PackageNotFoundError`。

修复仅捕获版本查询的 `PackageNotFoundError`，缺失版本记为 JSON `null`，与现有运行环境记录约定一致。已安装版本照常保留，其他元数据错误不吞掉；不修改轨道、可见窗口和研究实验计算。

回归先验证修复前 1 failed / 7 passed，失败精确复现缺少 `satellite-coverage-sim` 元数据。修复后 `tests/test_visibility.py` 8 passed（1.24 s），全量 `tests` 466 passed（13.82 s）。新增用例覆盖缺少元数据仍返回真实可见窗口、正常版本保留和其他异常继续抛出。

G15 离线包继续是先前冻结的 `70e93f0` 快照（457 项新环境测试），不包含本次元数据修复；当前工作树回归为 466 项。原生代码复审及 Finalize 尚待完成。

## Round 21：身份异常不得转成失败样本

[原生审查发现](code-review-round21.md)：`CacheMismatch` 继承 `ValueError`，方向表 `_solve` 对数值异常的捕获误吞了身份异常。新增独立捕获并立即重新抛出，使建表和直接回退遇到返回范围/上限不一致或求解器主动报告身份错误时均拒绝。

6 个身份反例先全部失败，修复后通过；普通 `ValueError`、`ArithmeticError`、`RuntimeError` 仍记录为失败样本。方向表/E1/E3 相关测试45项通过（0.24 s），全量474项通过（13.23 s）。`output/m2-native-review-20261012` 实际验证84个建表样本、72个已知样本，重现误差0 dB、过期频率缓存拒绝、批量及直接回退通过；所有归档产物 SHA256 已核验。

此修复改变身份不匹配的拒绝行为，不改变合法输入传播数值。模型源码指纹随代码变化使旧缓存失效是预期行为；历史 E1/E3 和 G15 快照保持原样。仍需原生复审和 Finalize。

## Round 22：限定地平线边界遍历范围

[原生审查发现](code-review-round22.md) 指出 `cell_horizon` 枚举了栅格外不存在的边界。修复将列边界限制为0至列数、行边界限制为0至行数，使用向南递增的行索引；仍保留半径终点及越界区间，从而明确返回 `outside_dem`。

原问题范围需说明：前置 `terrain_profile` 已限制不超过100,000个采样点，极端的100 km／0.1 m请求本来就会被拒绝，不存在可绕过该前置保护的无界请求；本次修复解决已接受请求中的多余边界遍历，没有降低原资源门禁。

3×3、0.1 m格网、100 m半径的8个方位，修复前分别遍历708或1001个区间，修复后均为3个；每个均保持 `outside_dem`、不完整状态和按实际边界推导的解析地平线。8个反例先失败、随后通过，另有预算拒绝反例。专项52项通过（0.22 s），全量483项通过（13.67 s）。既有山脊、曲率极值、边界及随机格网对照通过；无传播模型或业务门限变更。

先前474项结果仍对应Round21快照，当前为483项；原生复审和Finalize仍待完成。

## Round 23：Explorer 入口导入保护

[原生审查发现](code-review-round23.md)：导入 `satellite_coverage.explorer.__main__` 会无条件启动服务。为启动调用增加标准 `__name__ == "__main__"` 保护，保持模块正常启动入口。

回归模拟启动函数，先验证普通导入不调用，再通过 `runpy.run_module(..., run_name="__main__")` 验证模块执行恰好启动一次。修复前1 failed/2 passed，修复后专项3 passed（1.13 s），全量484 passed（13.56 s）。独立前端没有变动；原生复审和 Finalize 仍待完成。

## Round 24：非法数值变更证据的明确拒绝

[原生审查发现](code-review-round24.md)：已有非法记录标记后，风险检查仍迭代非法记录，导致 TypeError/AttributeError。现在只对已通过结构检查的记录计算 benchmark 风险，非法记录由原门禁统一抛出含 `numerical_change_records` 的 `RegenerationBlocked`。无审批仍另列审批缺失，合法记录的风险确认规则不变。

12个非法记录／审批状态组合覆盖None、非法元素元组、列表和字符串，修复前6 failed/17 passed，修复后专项23 passed（0.13 s），全量496 passed（13.55 s）。同时清除Round23测试文件末尾多余空行；未放宽任何发布条件，也未进行正式数据重生成。原生复审和Finalize仍待完成。
