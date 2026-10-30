# WORKbuddy 自动循环通道 · 使用说明

这条通道让 WORKbuddy 在用户本地 Windows 电脑上**无人值守**地跑闭环：
AI 侧推代码 → 本机自动拉取、重启、自测 → 报告自动回传仓库 → AI 侧读报告继续修。
不再需要人工传 zip、手贴测试结果。

---

## 一、启动前只做一次的准备

### 1. 确认本机能 push 到这个仓库

通道回传报告靠 `git push`。在仓库目录先跑一次：

```bat
cd /d "D:\hufanrong\Documents\workBudd\工程"
git remote -v
git push origin main
```

- 能推上去（或提示 `Everything up-to-date`）→ 凭据没问题，可以继续。
- 提示要账号密码 / `Authentication failed` → 先在 Windows 凭据管理器或
  `git config --global credential.helper manager` 配一次 GitHub 凭据。
  **不配也能跑**，只是报告会留在本机推不出去（通道会自动保住这些提交，
  不会丢，见第五节），但 AI 侧读不到结果，闭环就断了。

### 2. 确认依赖齐

```bat
cd /d "D:\hufanrong\Documents\workBudd\工程\workbench"
python -c "import fastapi, docx, openpyxl; print('ok')"
```

缺就运行 `install.bat`。`ezdxf`（DXF 图纸样本）和 `pywinauto`（阶段④清稿）
是可选的，缺了对应项会 skip，不影响其余阶段。

---

## 二、启动循环

**方式一（推荐）：双击 `workbench\run_loop.bat`**
它会自己找 Python（优先项目内 `.venv`），然后每 5 分钟检查一次。关窗口即停。

**方式二：命令行**

```bat
cd /d "D:\hufanrong\Documents\workBudd\工程"
python workbench\tools\wb_loop.py                :: 常驻，默认 5 分钟一轮
python workbench\tools\wb_loop.py --once         :: 只跑一轮，跑完退出（首次验证用）
python workbench\tools\wb_loop.py --interval 120 :: 改成 2 分钟一轮
python workbench\tools\wb_loop.py --phases 1,2   :: 只测阶段 1、2
```

**第一次请务必先跑 `--once`**，确认完整链路通了再挂常驻。

### 参数

| 参数 | 作用 |
|---|---|
| `--once` | 跑一轮就退出 |
| `--interval N` | 常驻检查间隔秒，默认 300 |
| `--phases 1,2,3,4` / `all` | 测哪些阶段，默认 all |
| `--no-restart` | 不重启服务（服务已在跑、只想测时用） |
| `--no-push` | 不回传报告（调试用） |
| `--no-pull` | 跳过拉取（只想验证 TEST→REPORT 时用） |

---

## 三、一轮里到底做了什么

```
WATCH  查远端有没有本地还没有的提交（git fetch + rev-list 计数）
  │      有新提交 ↓
PULL   stash 本地改动 → 快进 / rebase → 恢复改动
  │
TEST   停掉旧服务 → 拉起新代码 → 跑 selftest（阶段 1/2/3/4）
  │      服务起不来时自动降级为「进程内模式」，仍能跑出真实结论
REPORT 把报告写进 reports/<时间戳>/ 并 commit + push 回仓库
```

**结果状态**：`passed`（全过）/ `failed`（有失败项）/ `error`（通道自身出错，
例如拉取失败、报告没生成）。三者都如实写进 `report.json`，不装成功。

---

## 四、我（AI 侧）会怎么用这些报告

AI 侧用 `workbench/tools/ai_side.py` 读远端报告（凭据在沙箱内，不进公开仓库）：

```
python3 ai_side.py            # 最新一轮摘要 + 下一步该做什么
python3 ai_side.py --list     # 列出所有轮次
python3 ai_side.py --fails    # 只列最新一轮失败项
python3 ai_side.py --run <id> # 读指定轮次
```

判定规则：

- `status=passed` → 该阶段验收通过，推进下一阶段
- `status=failed` → 从 `--fails` + `console.log` 定位，改代码、再推
- `status=error` → 先修通道本身（拉取/依赖/服务），不把它当成代码问题

`env.json` 里有 Windows 版本、Python 版本、是否管理员、依赖是否安装 —— 阶段④
清稿需要管理员权限，这一项直接影响能不能测。

---

## 五、几个已处理好的坑（不用你操心，但值得知道）

1. **报告不会被 `reset --hard` 抹掉。** 早期版本用 `reset --hard origin/main`，
   一旦「报告已 commit 但 push 失败」（断网很常见），下一轮就把这些报告删了。
   现在改成 stash → 快进 / rebase → 恢复，本地提交一律保住。
2. **不会每轮弹浏览器。** 服务重启时会带 `FANGONG_NO_BROWSER=1`，跑一夜不会堆
   几十个窗口。手动 `run_workbench.bat` 启动时行为不变，照常自动开浏览器。
3. **不会把上一轮的旧结论当本轮结果。** 每轮开跑前先清旧报告，跑完校验报告
   生成时间是否落在本轮窗口内，拿不到新报告就标 `error`，不会回传陈旧数据。
4. **不会重复启动两个循环。** 单实例锁在共享 git 目录（`.git/wb_loop.lock`），
   主仓库和 worktree 共用同一把，第二个会直接拒绝启动；上一个异常退出留下的
   死锁会按 PID 自动接管。
5. **自测样本不进仓库。** `_samples/`、`selftest_report.*`、`service.log` 已加进
   `.gitignore`，仓库里只有 `reports/<run_id>/` 的正式报告。
6. **worktree 里也能跑（v0.1.170）。** 你日常在 `D:\fangong-workbench` 的 worktree
   里开发，`.git` 是指针文件不是目录，旧版用 `os.path.isdir` 判定仓库会直接退出
   （rc=2）。现在改用 `git rev-parse --git-dir` 判定，worktree 正常识别；单实例锁
   也移到共享 git 目录，主仓库与 worktree 共用同一把锁，不会各跑一份。
7. **`--once` 单轮回传也完整（v0.1.170）。** 旧版 `report.json` / `report.md` 在
   commit 之后才写，单轮跑完远端只有 `console.log`，AI 侧读不到结论。现在顺序是
   「先落盘 → 再提交 → 最后记账」。
8. **阶段④断言按真实返回取字段（v0.1.170）。** `/api/tools/dwg-cleaner/process`
   返回的是 `{status,total,success,failed,results[],out_dir}`，`pdf` / `log_file`
   在 `results[0]` 里、不在顶层。旧断言在顶层找，于是磁盘上明明产出了 PDF 和日志，
   却被判成失败。现在从 `results[0]` 取（顶层兜底兼容旧接口），并且校验文件真实
   存在且非 0 字节；`清稿执行` 也不再只看 `ok`（真实返回根本没这个键），改为同时
   看 `status` 与 `failed` 条数。
9. **环境不满足不算代码缺陷（v0.1.170）。** AutoCAD 没有 Linux/macOS 版，
   非 Windows 平台 `ready` 必然为 False。旧版记成 `failed`，AI 侧每轮去追一个
   不存在的 bug。现在非 Windows 记 `skipped`；Windows 上 `ready=false` 仍记
   `failed`（那是真的缺依赖，要修）。

---

## 六、出问题时看哪里

| 现象 | 先看 |
|---|---|
| 循环不启动，退出码 2 | 窗口里会打印「不是 git 仓库」；v0.1.170 起 worktree 也支持，若仍报错就跑 `git rev-parse --git-dir` 看本目录是否真被 git 认 |
| 循环不启动，退出码 3 | 已有循环在跑（会打印持锁 PID）；确认没有残留进程后删掉窗口提示的那个 `.git/wb_loop.lock` |
| 一直 `error` 且提示拉取失败 | 本机 `git fetch` 能否连通（代理/防火墙）；本地报告提交没丢，日志里能看到 `rebase 已中止` |
| `status=error` 且报告没生成 | `reports/<run_id>/console.log`（重点看末尾有没有 `[SKIP] 进程内模式不可用`） |
| 服务起不来 | `reports/service.log`；循环会自动降级为进程内模式继续测，不必中断 |
| 报告没出现在 GitHub | 第一节准备步骤 1 的 push 凭据；`report.json` 里 `pushed` 是否为 false |
| 阶段④在 Windows 上仍报 `ready=false` | `env.json` 的 `missing` 字段：`autocad` / `pywin32` / `pypdf` 各自对应一条安装提示 |

报告目录里每个文件的作用见 `reports/README.md`。
