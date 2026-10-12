# Humanize 原生审查阶段交接修复

2026-10-12。Round 16/17 已接受实现且未发现实现缺陷，却因 AC-13 尚待代码审查/Finalize 而拒绝实现通过信号。安装模板要求全部阶段先完成，原生 hook 又仅在实现通过信号后启动代码审查，形成循环依赖。[独立分析](phase-handoff-analysis.md) 通过官方 ask-codex 调用确认此问题。

只修改安装目录 `/home/zsfang/.codex/skills/humanize/prompt-template/codex/` 内 `regular-review.md`、`full-alignment-review.md` 的输出规则：[完整补丁](humanize-phase-handoff.patch)。各自原文件备份为同路径追加 `.pre-phase-handoff-20261012`。实现阶段信号仅授权进入原生代码审查；未完成的实现、测试、证据或被掩盖的限制仍阻断；依赖后续审查/收尾的 AC 状态仍保持待完成。

没有改动 hook、官方 wrapper、ask-codex、审查模型、沙箱、不可变计划、当前循环状态或阶段标记。安装目录不在仓库 Git 内，因此保留补丁、修改前后 SHA256 及审计记录。

[验证记录](phase-handoff-verification.json) 核对保护脚本哈希未变，并隔离提取原生 `run_and_handle_code_review` 实际函数，注入模拟审查结果验证四条控制路径：审查命令失败阻断、空结果阻断、有问题继续修复、干净结果进入 Finalize。此测试只验证门禁控制路径，不冒充项目独立代码审查；真正的实现判定、代码审查和 Finalize 仍交由当前原生循环执行。
