# Humanize CLI 兼容修复

2026-10-09，用户明确授权修复后继续当前 RLCR。安装根目录：
`/home/zsfang/.codex/skills/humanize`。Codex CLI 为 0.156.0。

实际修改两份安装脚本：`scripts/ask-codex.sh` 和
`hooks/loop-codex-stop-hook.sh`；各自原文件备份为同路径追加
`.pre-cli-compat-20261009`。仓库保留 [完整补丁](humanize-cli-compat.patch)，
安装目录不属于本仓库 Git，因此提交补丁以便复查和升级后重用。

默认参数从不再支持的 `--full-auto` 改为数组参数
`--sandbox workspace-write`；不使用危险绕过参数。原来显式环境变量控制的
绕过分支保持原有行为，本次调用没有启用它。
一次性分析子进程增加 `--disable codex_hooks`，防止子咨询再次进入主循环；
Stop hook 原有子审查防递归逻辑保持不变。主进程的 hook 配置、信任配置、
state.md、finalize-state.md、审查模型与阶段转换代码均未修改。

验证：

- 两份脚本 `bash -n` 通过。
- 在清除绕过环境变量的子 shell 中提取并执行实际参数构造片段；两处均得到
  `--sandbox workspace-write -C /tmp`，没有废弃参数或默认绕过参数。
- 官方 ask-codex.sh 的 G01 调用成功退出 0，耗时 120 秒，保存有效分析结果。
  日志报告 `sandbox: workspace-write`、`approval: never`；无需 Claude Code。
  调用目录：`.humanize/skill/2026-10-09_08-08-51-2208192-228e951a/`。
- 主 Stop hook 注册仍存在；没有手动运行替代审查或伪造 phase transition。
  本轮结束后由原生 hook 执行审查，成功的任务咨询不等于轮次审查通过。

CLI 对 `codex_hooks` 输出弃用提醒，提示新名 `hooks`；本次该别名仍能工作。
后续升级时可单独迁移并验证，不将弃用提醒当作已发生的失败。
