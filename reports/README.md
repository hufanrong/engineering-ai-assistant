# WORKbuddy 回传目录

本目录由 `workbench/tools/wb_loop.py` 自动写入，**不要手工改**。

每次自测生成一个 `reports/<日期_时分秒>/` 子目录：

| 文件 | 内容 |
|---|---|
| `report.json` | 机器可读的完整记录（状态、步骤、各阶段通过/失败/跳过、代码版本） |
| `report.md` | 人读版摘要 |
| `env.json` | 运行环境（系统、Python 版本、是否管理员、依赖是否安装、服务是否在跑） |
| `console.log` | selftest 的完整控制台输出 |
| `selftest_report.json` / `report.md` | selftest 原始产物 |

`.wb_loop_state.json` 记录「最近一次测过的 commit」，用于判断远端有没有新东西。

**为什么要有这个目录**：AI 侧的沙箱访问不到用户的 Windows 本机，本机也访问不到沙箱。
GitHub 仓库是双方唯一都能读写的通道 —— 代码推上去（AI 侧），测试结果推回来（本机），
AI 读测试结果 → 修复 → 再推 → 本机再测，如此闭环。
