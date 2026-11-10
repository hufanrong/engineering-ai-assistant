# WORKbuddy 缺陷报告 20261110_165000_defect_task_no_git

- 状态：**failed**
- 被测版本：`0.1.231`（commit `f2ffb6c`）
- 组件：计划任务 `FangongAI-AutoFeedback` → `workbench/tools/wb_loop.py`
- 详细档案：**[`defects_task_no_git.md`](defects_task_no_git.md)**
- 机读证据：[`evidence_task_no_git.json`](evidence_task_no_git.json)

## 一句话

**每 5 小时一次的自动回传，从配上到现在一次都没真正跑过。** 任务准时触发，
立刻以退出码 2 结束，日志一行不写 —— 外面看起来"跑了、没报错"。

## 实测

| 项 | 值 |
|---|---|
| LastRunTime | 2026-11-10 16:04:10（准时） |
| LastResult | **2** |
| NextRunTime | 2026-11-10 21:04:10 |
| `_loop.log` 最后一条 | `11:30:15`（我手工跑的上一轮） |
| 16:04 之后新增报告目录 | **0 个** |

远端 `origin/main` 现在是 `f2ffb6c`，今日三单缺陷都在 —— **但全是我手工 `git push` 推的**，
没有一条是自动回传推上去的。

## 根因

`LastResult = 2` 来自 `wb_loop.main()`：

```python
is_repo, git_dir, common = git_dir_info()
if not is_repo:
    print(f"[错误] {REPO_DIR} 不是 git 仓库，请先确认路径")
    return 2
```

`git_dir_info()` 调的是 `git rev-parse --git-dir`。而**系统 PATH 里根本没有 git**：

```
Machine PATH 含 git : C:\Program Files\GitHub CLI\    ← 只有 gh
User    PATH 含 git : （空）
Get-Command git     : 找不到
```

本机唯一的 git 是 WorkBuddy 自带的 PortableGit，只由 WorkBuddy 的终端注入 PATH：

```
C:\Users\hufanrong\.workbuddy\binaries\PortableGit\versions\1.3.0\cmd\git.exe
```

计划任务用 `pythonw.exe` 起在纯系统环境，找不到 git → `is_repo=False` → `return 2`。

## 比失败更糟：它不吭声

`return 2` 之前那句走的是裸 `print()`。`pythonw.exe` 下 `sys.stdout` 是 `None`，
`print` 抛 `AttributeError` —— 这个坑 v0.1.228 修过（`log()` 包住 print 并落盘），
**但 `main()` 里这几条 `print` 没被包**。

于是：任务计划程序只看到一个 2；`_loop.log` 零痕迹；从外面看是"按时跑了，没报错"。
**失败的证据链在第一步就断了。**

## 修复要点

1. **R1（治本）** `_find_git()`：`shutil.which("git")` → `GIT_EXECUTABLE` →
   `C:\Program Files\Git\cmd\git.exe` 等常见路径 → WorkBuddy PortableGit 的
   `versions/*` 取最新。找不到就**明说找不到 git**，别报"不是 git 仓库"这种误导结论。
2. **R2（治不吭声）** `main()` 一进来先 `log()` 一行：`argv` / `cwd` / `sys.executable` /
   `PATH` / git 解析结果。把 `main()` 里所有裸 `print` 换成 `log`，每个 `return` 前留原因。
3. **R3** 区分三种起不来：找不到 git / 真不是仓库 / 锁被占（锁那条写得对，保留）。
4. **R4** 加 `wb_loop.py --preflight`：只查 git / 仓库 / 远端 / 服务四项，10 秒出结论。

## 今天的临时处置（代码一行没改）

按老板「本地不擅自改业务代码，要由主代码库根治」，只在**环境层**补了个启动器：

```
C:\Users\hufanrong\AppData\Local\fangong\run_loop.cmd
```

它把 PortableGit 显式加进 PATH 再调 `wb_loop.py`，计划任务动作改为指向它。
**这是绕，不是修** —— WorkBuddy 升级后 PortableGit 版本目录一变又会断，R1 必须在主库做掉。

验证（16:45 手动触发）：

```
[16:45:17] ===== 本轮开始 20261110_164517，本地 f2ffb6ce1e45 =====
[16:45:19] 远端没有新提交（本地领先 0 个未推送提交），跳过拉取
[16:45:20]    服务在线且版本一致(0.1.231)，跳过重启（不打断正在使用的人）
```

有日志、git 通了、也正确判断了不该重启 —— 通道恢复。

## 验收

1. **PATH 里没有 git** 时直接跑 `pythonw.exe tools\wb_loop.py --once` 能正常跑完一轮并推送；
2. 找不到 git 时 `_loop.log` 有一行写明「找不到 git，已尝试：…」；
3. `main()` 的 `return 2` / `return 3` 分支都留日志；
4. `--preflight` 10 秒内给出四项结论；
5. 计划任务连续 3 轮（15 小时）都有「本轮开始 / 本轮结束」两行。

## 这条为什么排第一

前两单（D15 归类、D16 重启）都得靠这条通道送到开发端。通道本身是断的，
意味着**之前所有"已回传"其实都是我在手工推**；一旦没人盯着，回传就永久静默。
