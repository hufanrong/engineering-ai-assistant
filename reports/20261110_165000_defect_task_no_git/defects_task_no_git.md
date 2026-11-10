# 缺陷档案 · 每 5 小时的自动回传，一次都没真跑起来（D17）

| 项 | 值 |
|---|---|
| 报告时间 | 2026-11-10 16:50 |
| 被测版本 | `0.1.231`（commit `f2ffb6c`） |
| 组件 | Windows 计划任务 `FangongAI-AutoFeedback` → `workbench/tools/wb_loop.py` |
| 现象 | 任务**按时触发**，`LastResult=2`，报告目录一个没新增，`_loop.log` 一行没写 |
| 严重度 | **最高** —— 回传通道整个是断的，开发端收不到任何东西 |

---

## 一、怎么发现的

老板问「有没有完成反馈」。查远端：`origin/main` = `f2ffb6c`，两单缺陷（`d13dcf2` / `f2ffb6c`）
在 —— **但那是我手工 `git push` 推的**，不是自动回传推的。

再看计划任务：

```
TaskName    : FangongAI-AutoFeedback
State       : Ready
LastRunTime : 2026-11-10 16:04:10     ← 准时触发了
LastResult  : 2                        ← 失败
NextRunTime : 2026-11-10 21:04:10
```

`_loop.log` 最后一条还停在 `11:30:15`（上一轮是我手工跑的），
16:04 那轮**连"本轮开始"都没写**。

## 二、根因：裸环境里没有 git

`LastResult = 2` 对应 `wb_loop.main()` 的这一条：

```python
is_repo, git_dir, common = git_dir_info()
if not is_repo:
    print(f"[错误] {REPO_DIR} 不是 git 仓库，请先确认路径")
    return 2
```

`git_dir_info()` 的实现是 `git rev-parse --git-dir`。而 **`git` 不在系统 PATH 里**：

```
Machine PATH 含 git : C:\Program Files\GitHub CLI\     （只有 gh，没有 git）
User    PATH 含 git : （空）
Get-Command git     : 找不到
```

本机唯一可用的 git 是 WorkBuddy 自带的 PortableGit：

```
C:\Users\hufanrong\.workbuddy\binaries\PortableGit\versions\1.3.0\cmd\git.exe
```

它**只由 WorkBuddy 的终端注入 PATH**。计划任务用 `pythonw.exe` 起在纯系统环境里，
自然找不到。于是 `git rev-parse` 失败 → `is_repo=False` → `return 2`。

**这就是「5 小时一次、拔电也跑、上限 3 小时」全都配对了，却一次都没回传的原因。**

## 三、比失败更糟的是「不吭声」

`return 2` 之前那句提示走的是 `print()`。而 `pythonw.exe` 下 `sys.stdout` 是 `None`，
`print` 抛 `AttributeError` —— 这个坑 v0.1.228 已经修过（`log()` 包住 `print` 并写文件），
但 **`main()` 里这条 `print` 没有被 `log()` 包**，所以：

- 任务计划程序只看到一个退出码 2；
- `_loop.log` 里什么都没有；
- 从外面看，"任务按时跑了，没报错"。

**失败的证据链在第一步就断了。** 这比失败本身更贵 —— 它让所有人以为通道是通的。

## 四、修复建议

### R1 · 自己找 git，别指望 PATH（治本）

`git()` 里先解析可执行文件，再调用：

```python
def _find_git():
    p = shutil.which("git")
    if p: return p
    p = os.environ.get("GIT_EXECUTABLE")          # 允许显式指定
    if p and os.path.isfile(p): return p
    cands = [
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
    ]
    # WorkBuddy 自带的 PortableGit（版本号目录，取最新）
    port = os.path.expanduser(r"~\.workbuddy\binaries\PortableGit\versions")
    if os.path.isdir(port):
        for d in sorted(os.listdir(port), reverse=True):
            cands.append(os.path.join(port, d, "cmd", "git.exe"))
    for c in cands:
        if os.path.isfile(c): return c
    return ""
```

找不到时**明确报错并写日志**，别退回"不是 git 仓库"这种误导性结论。

### R2 · 启动即写日志，失败更要写（治「不吭声」）

`main()` 一进来就先 `log(f"启动：argv=... cwd=...")`，
把 `sys.executable` / `sys.version` / `PATH` / git 解析结果一起打进去。

然后把 `main()` 里所有裸 `print` 换成 `log`；`return 2` / `return 3` 之前
必须落一行**带原因**的日志。现在这几个分支全是"静默返回"。

### R3 · 区分三种「起不来」

| 情况 | 现在 | 应该 |
|---|---|---|
| 找不到 git | 「不是 git 仓库」（误导） | 「找不到 git，已尝试路径 …」 |
| 目录真不是仓库 | 「不是 git 仓库」 | 保留 |
| 锁被占 | 有提示 ✅ | 保留（这条写得对） |

### R4 · 自检接口

建议加 `wb_loop.py --preflight`：只做「git 能不能用 / 仓库能不能读 / 远端能不能连 /
服务在不在」四项检查并打印结论，不跑测试、不提交。
计划任务可以每隔几次先跑一次 preflight，失败就明显暴露。

## 五、今天的临时处置（不改仓库代码）

按老板「本地不擅自改业务代码，要由主代码库根治」的要求，代码一行没动。
只在**环境层**补了一个启动器，让通道今晚能跑：

```
C:\Users\hufanrong\AppData\Local\fangong\run_loop.cmd
```

内容要点：

```bat
set "GITROOT=C:\Users\hufanrong\.workbuddy\binaries\PortableGit\versions\1.3.0"
set "PATH=%GITROOT%\cmd;%GITROOT%\usr\bin;%GITROOT%\mingw64\bin;%PATH%"
cd /d "D:\fangong-workbench\workbench"
"D:\...\pythonw.exe" "D:\...\tools\wb_loop.py" --once --phases 1,2,3,5
```

计划任务动作改为指向它。**这是绕，不是修** —— WorkBuddy 升级后 PortableGit
的版本目录一变，它又会断。所以 R1 必须在主代码库里做掉。

验证（2026-11-10 16:45 手动触发）：

```
[2026-11-10 16:45:17] ===== 本轮开始 20261110_164517，本地 f2ffb6ce1e45 =====
[2026-11-10 16:45:19] 远端没有新提交（本地领先 0 个未推送提交），跳过拉取
[2026-11-10 16:45:20]    服务在线且版本一致(0.1.231)，跳过重启（不打断正在使用的人）
```

有日志了、git 通了、也正确判断了不用重启 —— 通道恢复。

## 六、验收

1. 在**没有 git 的 PATH** 下直接跑 `pythonw.exe tools\wb_loop.py --once`，
   能正常跑完一轮并推送（不依赖外部启动器）；
2. 找不到 git 时，`_loop.log` 有一行写明「找不到 git，已尝试：…」；
3. `main()` 的三个 `return 2 / return 3` 分支都留有日志；
4. `--preflight` 能在 10 秒内给出四项检查结论；
5. 计划任务连续 3 轮（15 小时）都有「本轮开始 / 本轮结束」两行日志。

## 七、复现

```powershell
# 1) 看任务状态
Get-ScheduledTask -TaskName "FangongAI-AutoFeedback" | Get-ScheduledTaskInfo
#    LastResult = 2

# 2) 确认 git 不在系统 PATH
[Environment]::GetEnvironmentVariable('Path','Machine') -split ';' | Select-String git
(Get-Command git -ErrorAction SilentlyContinue).Source    # 空

# 3) 用裸环境跑，看它怎么退出
#    （在 PATH 里没有 git 的 cmd 里执行）
pythonw.exe D:\fangong-workbench\workbench\tools\wb_loop.py --once
#    exit code 2，_loop.log 无任何新增
```
