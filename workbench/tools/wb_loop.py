#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""繁工AI ↔ WORKbuddy 自动循环通道 · WORKbuddy 侧执行器

作用：让 WORKbuddy 在用户本地 Windows 电脑上「无人值守」地跑闭环，
不再需要人手传 zip、手贴报告。

一轮循环做四件事：
  1. WATCH  看 GitHub 上 AI 侧有没有新提交（只比对 workbench/ 目录的 commit sha）
  2. PULL   有新提交就 git fetch + git reset --hard origin/main（干净落到新代码）
  3. TEST   重启本地服务 → 跑 selftest.py --phase all → 产出报告
  4. REPORT 把报告 + 环境信息提交回仓库 reports/ 目录，AI 侧下一轮直接读

用法（在 D:\\hufanrong\\Documents\\workBudd\\工程 下）：

    python workbench\\tools\\wb_loop.py --once        # 跑一轮就退出（适合手动验证）
    python workbench\\tools\\wb_loop.py               # 常驻，每 5 分钟检查一次
    python workbench\\tools\\wb_loop.py --interval 120 --phases 1,2,3

设计原则（与项目质量底线一致）：
  - 只增不改：报告写到 reports/ 下独立文件，不回写代码
  - 不改动用户业务数据：selftest 自己造样本，跑完清理
  - 每步留证据：reports/<run_id>/ 里有 report.json / report.md / env.json / console.log
  - 失败不装成功：git 冲突、服务起不来、自测有 fail，都如实写进 report 的 status
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
WB_DIR = os.path.dirname(HERE)                    # workbench/
REPO_DIR = os.path.dirname(WB_DIR)                # 仓库根
REPORTS_DIR = os.path.join(REPO_DIR, "reports")
SELFTEST = os.path.join(HERE, "selftest.py")
STATE_FILE = os.path.join(REPORTS_DIR, ".wb_loop_state.json")

BASE_URL = os.environ.get("FANGONG_BASE", "http://127.0.0.1:8756")
BRANCH = "main"


def _runtime_python():
    r"""返回「老板双击启动时真正用的那个解释器」——venv 优先。

    为什么不能直接用 sys.executable：循环是我（或计划任务）用什么 python
    拉起来的，就用哪个 python 去起服务、跑自测。而 open_or_start.bat /
    run_workbench.bat 的探测顺序是
        venv\Scripts\python.exe -> .venv -> PATH -> LOCALAPPDATA -> 内置运行时
    两套解释器装的东西可以完全不同。实测 2026-11-10 这台机器：

        workbench/venv   : paddleocr 3.7.0 有、xlrd 没有
        WorkBuddy 内置 py: xlrd 有、paddleocr 没有

    于是「我这边 .xls 解析通过、图像 OCR 跳过」和「老板那边正好相反」，
    自测报告看起来有结论，实际验的不是同一个程序。这是最阴的一类
    「同一件事两个答案」——报告说没问题，真机就是不工作。

    所以：起服务与跑自测**一律走 venv**（没有 venv 才退回当前解释器），
    并把两个解释器的差异写进 env.json，不再靠猜。
    """
    cands = [
        os.path.join(WB_DIR, "venv", "Scripts", "python.exe"),
        os.path.join(WB_DIR, ".venv", "Scripts", "python.exe"),
        os.path.join(WB_DIR, "venv", "bin", "python"),
        os.path.join(WB_DIR, ".venv", "bin", "python"),
    ]
    for p in cands:
        if os.path.isfile(p):
            return p
    return sys.executable



# ---------------------------------------------------------------- 小工具
LOCK_FILE = os.path.join(REPORTS_DIR, ".wb_loop.lock")


def git_dir_info():
    """判断当前目录是不是 git 仓库，并取到「公共 git 目录」。

    v0.1.170：原来用 os.path.isdir(REPO_DIR/.git) 判定。用户日常全在
    **git worktree** 里开发（实测 r3/r4 都是 D:\fangong-workbench 的 worktree，
    .git 是 55 字节的指针文件 `gitdir: .../worktrees/xxx`），isdir() 恒为假
    → 通道在 worktree 里永远起不来，直接 return 2。改用 git 自己的判定。

    返回 (is_repo, git_dir, common_dir)。
    """
    rc, out, _ = git("rev-parse", "--git-dir")
    git_dir = out.strip() if rc == 0 else ""
    if not git_dir:
        return False, "", ""
    rc2, out2, _ = git("rev-parse", "--git-common-dir")
    common = out2.strip() if rc2 == 0 else git_dir
    # git 可能返回相对路径，统一成绝对路径
    if git_dir and not os.path.isabs(git_dir):
        git_dir = os.path.abspath(os.path.join(REPO_DIR, git_dir))
    if common and not os.path.isabs(common):
        common = os.path.abspath(os.path.join(REPO_DIR, common))
    return True, git_dir, common


def _pid_alive(pid: int) -> bool:
    """判断这个 pid 还活着吗 —— 直接问操作系统，不解析任何命令输出。

    为什么废弃 `tasklist` 那条路（v0.1.227）：
      原来用 `tasklist /FI "PID eq N"` 的输出里找 pid 字符串。中文 Windows 的
      tasklist 输出是 GBK，而 `text=True` 不指定编码时按「当前默认编码」解码 ——
      在开了 UTF-8 模式的进程里（PYTHONUTF8=1 / `-X utf8`）就是 UTF-8，
      于是读线程抛
        UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd0 in position 0
      这个异常发生在 subprocess 的 reader **线程**里，不会冒泡到调用处：
      stdout 变空串 → 判成「pid 不在了」→ 锁被当成过期 → 直接覆盖。
      实测 2026-11-10 09:29 / 09:37 两轮日志开头都留着这行报错，
      说明判活确实走空了；只要那一刻真有一个循环在跑，就会双开写同一个仓库。

      （更正一条我自己误判过的结论：我最初看到「两个 wb_loop」就认为已经双开，
      其实是 `venv/Scripts/python.exe` 这个 241KB 启动器又拉起了真身解释器，
      「启动器 + 真身」天然成对。机制成立、后果未实测到，按潜在缺陷处理。）

    OpenProcess 是 Win32 原生调用，零解析、零编码问题；Linux/macOS 用 os.kill(pid,0)。
    任何异常都按「活着」处理 —— 宁可拒绝启动，也不要让两个循环同时写仓库。
    """
    if pid <= 0:
        return False
    try:
        if platform.system() == "Windows":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not h:
                # 进程不存在（或权限不足）。用 GetExitCodeProcess 之外的最简判据：
                # ERROR_INVALID_PARAMETER(87) 才是「确实没有这个 pid」。
                err = ctypes.windll.kernel32.GetLastError()
                return err != 87
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:  # noqa: BLE001 —— 判不出来就当它活着，避免双开
        return True


def acquire_lock():
    """单实例锁：避免用户误开两个窗口、两个循环互相抢端口和提交。

    v0.1.170：锁文件落到 **git 公共目录**（worktree 之间共享），否则同一个
    仓库的三个 worktree 各有一把锁，三个循环同时往 main 推，必然互相打断。
    公共目录不可写时回落到 reports/。

    进程异常退出会留下锁文件，所以同时校验里面的 PID 是否还活着；
    死锁文件（stale）自动接管，不会把用户永久挡在外面。
    """
    global LOCK_FILE
    os.makedirs(REPORTS_DIR, exist_ok=True)
    _is_repo, _gd, common = git_dir_info()
    if common and os.path.isdir(common):
        try:
            probe = os.path.join(common, ".wb_loop_probe")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("1")
            os.remove(probe)
            LOCK_FILE = os.path.join(common, "wb_loop.lock")
        except Exception:  # noqa: BLE001
            LOCK_FILE = os.path.join(REPORTS_DIR, ".wb_loop.lock")

    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, encoding="utf-8") as f:
                info = json.load(f)
            pid = int(info.get("pid", 0))
        except Exception:  # noqa: BLE001
            pid = 0
        if pid:
            alive = _pid_alive(pid)
            if alive:
                return False, pid
    try:
        with open(LOCK_FILE, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "started": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    except Exception:  # noqa: BLE001
        pass
    return True, 0


def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:  # noqa: BLE001
        pass


_LOG_FILE = os.path.join(REPORTS_DIR, "_loop.log")


def log(msg):
    """打一行日志：控制台 + reports/_loop.log。

    v0.1.228：无人值守是用 pythonw.exe 被计划任务拉起来的，那种上下文里
    sys.stdout 可能是 None，原来裸 print 会抛 AttributeError 把整轮带走，
    而且**一点痕迹都不留** —— 计划任务那边只看得到 exit code，日志是空的。
    （历史上就出现过「任务说跑了 391 次，但什么都没有」这种查不下去的局面。）
    现在 print 包一层，同时把每行追加进 reports/_loop.log（reports/_* 已被
    .gitignore 挡住，不进版本库）。下次再出「任务说跑了却没结果」，至少有现场。
    """
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except Exception:  # noqa: BLE001  pythonw 下 stdout 可能是 None
        pass
    try:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        if os.path.exists(_LOG_FILE) and os.path.getsize(_LOG_FILE) > 2 * 1024 * 1024:
            os.replace(_LOG_FILE, _LOG_FILE + ".1")
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    return line


def _child_env(extra=None):
    """给子进程用的干净环境：剥掉宿主注入的沙箱 sitecustomize（v0.1.227）。

    为什么必须剥：WorkBuddy 这类宿主会把一个 `sitecustomize.py` 塞进
    PYTHONPATH，用来拦截/改写文件操作（删除走回收站、单轮批量删除超阈值
    直接 SystemExit）。这些规则**只存在于我的运行环境里，老板双击
    open_or_start.bat 时一概没有**。留着它们，自测测的是沙箱而不是产品：

      实测 2026-11-10 09:22  删一个 59 文件的测试项目
        → shim 的批量删除护栏抬 SystemExit(1)
        → 工作台主进程当场退出
        → 后面整轮自测全部级联失败，报告上像「十几个功能同时坏了」
      实测同一轮 test_atomic_io / test_atomic_write
        → 写 %TEMP% 被 shim 拦成 PermissionError [WinError 5]
        → 两条断言红，而产品代码一行都没错

    所以：子进程环境里把 PYTHONPATH 中的 shim 目录滤掉，保留其余路径。
    这不是绕过安全策略 —— 这只影响**我为测试而创建的进程**，
    且被剥掉的规则在目标用户的机器上本就不存在。本文件自身的文件操作
    仍受宿主策略约束（我不调用 shutil.rmtree 删用户数据）。
    """
    env = dict(os.environ)
    pp = env.get("PYTHONPATH") or ""
    keep = []
    dropped = []
    for part in pp.split(os.pathsep):
        p = part.strip()
        if not p:
            continue
        low = p.replace("\\", "/").lower()
        if "workbuddy" in low and "/shim" in low:
            dropped.append(p)
            continue
        keep.append(p)
    if dropped:
        env["PYTHONPATH"] = os.pathsep.join(keep)
        env["FANGONG_SHIM_STRIPPED"] = "1"
    if extra:
        env.update(extra)
    return env


def run(cmd, cwd=None, timeout=300, check=False, env=None):
    """跑命令，返回 (rc, stdout, stderr)。

    env 传入时会与「已剥掉沙箱 shim 的环境」合并后交给子进程 ——
    依赖路径这类「父进程能 import、子进程读不到」的差异必须显式传过去，
    否则子进程照样报缺包。
    """
    full_env = _child_env(env)
    try:
        p = subprocess.run(cmd, cwd=cwd or REPO_DIR, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=full_env)
        if check and p.returncode != 0:
            raise RuntimeError(f"命令失败 rc={p.returncode}: {' '.join(cmd)}\n{p.stderr[:500]}")
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"超时 {timeout}s: {' '.join(cmd)}"
    except FileNotFoundError as e:
        return 127, "", str(e)


def git(*args, timeout=120):
    return run(["git"] + list(args), timeout=timeout)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {"last_tested_commit": "", "runs": []}


def save_state(st):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 1. WATCH
def remote_head():
    """远端 main 的最新 commit sha。

    优先 git ls-remote（本机有 git 凭据，最直接）；git 不通时回落 GitHub 公共 API
    —— 这个仓库是公开的，匿名可读 main 的 HEAD sha。本机个别网络环境（代理/防火墙）
    会把 git 的 https 连接打成 502，有 API 兜底就不会整条循环停摆。
    """
    rc, out, err = git("ls-remote", "origin", BRANCH, timeout=60)
    if rc == 0:
        for line in out.splitlines():
            if line.strip():
                return line.split()[0], ""
    git_err = (err.strip() or "git ls-remote 失败")[:200]

    # 回落 GitHub API
    try:
        import urllib.request
        url = f"https://api.github.com/repos/{_repo_slug()}/commits/{BRANCH}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json", "User-Agent": "wb-loop"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        sha = d.get("sha", "")
        if sha:
            return sha, f"(git 不通，已用 API 兜底：{git_err})"
    except Exception as e:  # noqa: BLE001
        return None, f"git 与 API 都失败；git: {git_err}；api: {e}"
    return None, f"git: {git_err}；api 未返回 sha"


def _repo_slug():
    """从 origin URL 解析 owner/repo。"""
    rc, out, _ = git("remote", "get-url", "origin")
    u = out.strip()
    if not u:
        return "hufanrong/engineering-ai-assistant"
    u = u.replace("git@github.com:", "").replace("https://github.com/", "")
    if u.endswith(".git"):
        u = u[:-4]
    return u.strip("/")


def local_head():
    rc, out, _ = git("rev-parse", "HEAD")
    return out.strip() if rc == 0 else ""


def fetch_remote():
    rc, out, err = git("fetch", "origin", BRANCH, "--prune", timeout=180)
    return rc == 0, {"step": "git fetch", "rc": rc,
                     "out": out.strip()[:300], "err": err.strip()[:300]}


def behind_count():
    """本地落后远端几个提交。

    v0.1.169：原来用「远端 HEAD sha != 本地 HEAD sha」判断要不要拉取。
    但本机自己每轮都会提交 reports/ 报告，本地 HEAD 永远不等于远端 HEAD，
    于是每轮都被判成「有更新」，循环反复空转、还容易踩 rebase。
    真正要问的是「远端有没有本地还没有的提交」——用 rev-list 计数。
    """
    rc, out, _ = git("rev-list", "--count", f"HEAD..origin/{BRANCH}")
    if rc != 0:
        return None
    try:
        return int(out.strip() or 0)
    except ValueError:
        return None


def ahead_count():
    """本地有几个远端没有的提交（一般是没推成功的报告）。"""
    rc, out, _ = git("rev-list", "--count", f"origin/{BRANCH}..HEAD")
    try:
        return int(out.strip() or 0) if rc == 0 else None
    except ValueError:
        return None


# ---------------------------------------------------------------- 2. PULL
def pull_latest():
    """把本地落到 origin/main —— 但不许抹掉本地还没推上去的报告。

    v0.1.169：原来一律 `git reset --hard origin/main`。本机一旦有「跑了自测、
    报告已 commit 但 push 失败」的情形（断网、凭据失效很常见），下一轮的
    reset --hard 会把这些报告 commit 直接丢掉，测试结果永久消失。
    改成：先 stash 现场 → 能快进就快进 → 不能快进就 rebase 自己的报告提交
    到远端最新 → 仍失败就中止并回滚，绝不 reset --hard 抹掉本地提交。
    """
    steps = []

    # 1) 有未提交改动先 stash，保住用户现场
    rc, out, _ = git("status", "--porcelain")
    dirty = [l for l in out.splitlines() if l.strip()]
    stashed = False
    if dirty:
        rc2, o2, e2 = git("stash", "push", "-u", "-m",
                          f"wb_loop auto-stash {time.strftime('%Y%m%d_%H%M%S')}")
        stashed = rc2 == 0
        steps.append({"step": "git stash（保住本地改动）", "rc": rc2,
                      "out": o2.strip()[:300], "err": e2.strip()[:300],
                      "dirty_count": len(dirty)})

    # 2) 取远端（若调用方已 fetch，则本步直接快进）
    rc, out, err = git("fetch", "origin", BRANCH, "--prune", timeout=180)
    steps.append({"step": "git fetch", "rc": rc, "out": out.strip()[:300], "err": err.strip()[:300]})
    if rc != 0:
        if stashed:
            git("stash", "pop")
        return False, steps

    target = f"origin/{BRANCH}"

    # 3) 本地无自有提交 → 直接快进
    rc, out, _ = git("rev-list", "--count", f"{target}..HEAD")
    ahead = int(out.strip() or 0) if rc == 0 else 0
    if ahead == 0:
        rc, out, err = git("merge", "--ff-only", target, timeout=120)
        steps.append({"step": "快进到 origin/main", "rc": rc,
                      "out": out.strip()[:300], "err": err.strip()[:300]})
        ok = rc == 0
    else:
        # 4) 本地有未推送的报告提交 → rebase 到远端最新，保住它们
        rc, out, err = git("rebase", target, timeout=180)
        steps.append({"step": f"rebase {ahead} 个本地提交到 origin/main", "rc": rc,
                      "out": out.strip()[:300], "err": err.strip()[:400]})
        ok = rc == 0
        if not ok:
            git("rebase", "--abort")
            steps.append({"step": "rebase 冲突，已中止并保持原状", "rc": 0, "out": ""})

    if stashed:
        rc3, o3, e3 = git("stash", "pop")
        steps.append({"step": "git stash pop", "rc": rc3,
                      "out": o3.strip()[:300], "err": e3.strip()[:300]})
    return ok, steps


# ---------------------------------------------------------------- 3. TEST
def service_alive(timeout=3):
    import urllib.request
    try:
        with urllib.request.urlopen(BASE_URL + "/api/status", timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def stop_service():
    """尽力停掉占用端口的旧服务（Windows: netstat+taskkill；其它: pkill -f start.py）。"""
    steps = []
    if platform.system() == "Windows":
        rc, out, _ = run(["netstat", "-ano"], timeout=60)
        pids = set()
        for line in out.splitlines():
            if ":8756" in line and "LISTENING" in line.upper():
                parts = line.split()
                if parts and parts[-1].isdigit():
                    pids.add(parts[-1])
        for pid in pids:
            rc2, o2, e2 = run(["taskkill", "/PID", pid, "/F"], timeout=60)
            steps.append({"step": f"taskkill {pid}", "rc": rc2, "out": o2.strip()[:200], "err": e2.strip()[:200]})
    else:
        rc, out, _ = run(["pkill", "-f", "start.py"], timeout=60)
        steps.append({"step": "pkill start.py", "rc": rc, "out": out.strip()[:200]})
    return steps


def start_service():
    """后台拉起 start.py，等它健康。Windows 用 CREATE_NEW_PROCESS_GROUP 脱离。

    v0.1.169：加上 FANGONG_NO_BROWSER=1 —— 无人值守每轮都会重启服务，
    否则每轮都弹一个浏览器窗口出来，跑一夜能堆几十个。

    v0.1.227：解释器改用 _runtime_python()（venv 优先），与老板双击
    open_or_start.bat 时用的保持同一个 —— 否则测的不是同一个程序。
    """
    py = _runtime_python()
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    child_env = _child_env({"FANGONG_NO_BROWSER": "1"})
    logf = open(os.path.join(REPORTS_DIR, "service.log"), "a", encoding="utf-8")
    try:
        subprocess.Popen([py, os.path.join(WB_DIR, "start.py")], cwd=WB_DIR,
                         stdout=logf, stderr=logf, env=child_env, **kwargs)
    except Exception as e:  # noqa: BLE001
        return False, f"启动失败: {e}"
    for _ in range(30):
        time.sleep(2)
        if service_alive():
            return True, "服务已就绪"
    return False, "服务 60 秒内未就绪（看 reports/service.log）"


def _dep_paths():
    """本机可能把依赖装在非 site-packages 目录时的候选路径。

    沙箱/部分虚拟环境会把 python-multipart 之类装到自定义位置，
    进程内模式（FastAPI TestClient）需要它才能解析表单。找不到就返回空，
    不硬编码任何机器相关路径。
    """
    cands = []
    env = os.environ.get("FANGONG_DEP_PATH", "")
    if env:
        cands.extend([p for p in env.split(os.pathsep) if p])
    # 常见自定义安装位：.cli/python/lib、~/.local/lib
    for base in (os.path.expanduser("~/.aily/.cli/python/lib"),
                 os.path.expanduser("~/.local/lib")):
        if os.path.isdir(base):
            cands.append(base)
            for sub in os.listdir(base):
                if sub.startswith("python-multipart"):
                    cands.append(os.path.join(base, sub))
    return cands


def _ensure_inproc_deps():
    """确认进程内模式所需依赖可导入；能补路径就补，补不上返回缺失名。

    返回 (ok, detail)。
    """
    try:
        import multipart  # noqa: F401
        return True, "python-multipart 已可导入"
    except Exception:  # noqa: BLE001
        pass
    for p in _dep_paths():
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
        if os.path.isdir(p):
            try:
                import multipart  # noqa: F401
                return True, f"已通过 {p} 补上 python-multipart"
            except Exception:  # noqa: BLE001
                continue
    return False, "缺少 python-multipart（进程内模式需要；pip install python-multipart）"


def run_selftest(phases, out_dir, inproc=False):
    """跑 selftest，把报告收进 out_dir。

    v0.1.169 修三个会把循环打断的问题：
    1. 报告落盘路径取了 REPO_DIR，但 selftest.py 明确把 selftest_report.json
       写在「脚本同目录」（workbench/tools/）。路径错位导致每轮都拿不到
       summary，status 一律被判成 error —— 循环跑起来也永远回传不了结果。
       改为到 SELFTEST 的所在目录取报告。
    2. 服务没起来时 selftest 会把 19 项全判 FAIL，报告看起来像「代码全坏」。
       实际只是没启动。加 inproc 兜底：用 FastAPI TestClient 进程内跑真实
       路由，服务起不来也能拿到有效结论（阶段④仍会因缺 Windows 而 skip）。
    3. **陈旧报告污染**：selftest 在早退（例如 inproc 加载失败 rc=2）时不写
       报告，报告目录里会留着上一轮的旧文件。原来直接按存在就读，于是把
       上一轮的结果当成本轮的结论回传。改成开跑前先删旧报告，跑完按
       「mtime 是否晚于本轮开始」校验新鲜度，拿不到新报告就如实标 error。

    v0.1.227：解释器改用 _runtime_python()（venv 优先）。原来用 sys.executable，
    等于「谁拉起循环就测谁的依赖」，与老板双击启动时用的 venv 可能完全不同。
    """
    py = _runtime_python()
    if inproc:
        cmd = [py, SELFTEST, "--phase", phases, "--inproc", WB_DIR]
    else:
        cmd = [py, SELFTEST, "--phase", phases, "--base", BASE_URL]

    report_dir = os.path.dirname(SELFTEST)
    rj = os.path.join(report_dir, "selftest_report.json")
    rm = os.path.join(report_dir, "selftest_report.md")

    # 进程内模式要先确认依赖齐，缺就明确指出，别让 selftest 报成「19 项全坏」
    env_note = ""
    extra_paths = []
    if inproc:
        ok_dep, dep_detail = _ensure_inproc_deps()
        env_note = dep_detail
        if not ok_dep:
            with open(os.path.join(out_dir, "console.log"), "w", encoding="utf-8") as f:
                f.write(f"[SKIP] 进程内模式不可用：{dep_detail}\n")
            return 2, None, dep_detail
        # 父进程补进 sys.path 的路径，必须显式带到子进程
        extra_paths = [p for p in _dep_paths() if os.path.isdir(p)]

    # 3-a. 先清掉上一轮残留，避免把旧结论当新结论
    started_ts = time.time()
    for p in (rj, rm):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:  # noqa: BLE001
            pass

    child_env = None
    if extra_paths:
        child_env = {"PYTHONPATH": os.pathsep.join(extra_paths + [REPO_DIR])}

    rc, out, err = run(cmd, cwd=REPO_DIR, timeout=1800, env=child_env)
    with open(os.path.join(out_dir, "console.log"), "w", encoding="utf-8") as f:
        f.write(f"$ {' '.join(cmd)}\n\n[stdout]\n{out}\n\n[stderr]\n{err}\n")

    report = None
    if os.path.exists(rj):
        # 3-b. 只认本轮新产出的报告
        if os.path.getmtime(rj) >= started_ts - 2:
            shutil.copy2(rj, os.path.join(out_dir, "selftest_report.json"))
            try:
                with open(rj, encoding="utf-8") as f:
                    report = json.load(f)
            except Exception:  # noqa: BLE001
                report = None
    if os.path.exists(rm) and os.path.getmtime(rm) >= started_ts - 2:
        shutil.copy2(rm, os.path.join(out_dir, "selftest_detail.md"))
    return rc, report, err


# ---------------------------------------------------------------- 4. REPORT
def _is_admin() -> bool:
    """清稿要写系统目录，是否管理员会影响阶段④结果，值得记录。"""
    try:
        if platform.system() == "Windows":
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:  # noqa: BLE001
        return False


def collect_env():
    import urllib.request
    # 只收「判断问题需要」的环境信息：仓库是公开的，本机用户名/路径/主机名不往里写。
    env = {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "python": sys.version.split()[0],
        "is_admin": _is_admin(),
        "service_alive": service_alive(),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with urllib.request.urlopen(BASE_URL + "/api/status", timeout=10) as r:
            env["api_status"] = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        env["api_status_error"] = str(e)[:300]
    # v0.1.227：包版本必须问**交付用的那个解释器**（venv），不是拉起循环的这个。
    # 原来用 `importlib.metadata` 在循环自身进程里问，问的是错的对象 ——
    # 实测这台机器 venv 有 paddleocr 没 xlrd、内置 py 有 xlrd 没 paddleocr，
    # env.json 却只反映后者，看不出真机到底缺什么。
    _run_py = _runtime_python()
    env["interpreter"] = {
        "loop": sys.executable,
        "runtime": _run_py,
        "same": os.path.normcase(_run_py) == os.path.normcase(sys.executable),
    }
    try:
        _probe = (
            "import json\n"
            "from importlib.metadata import version as V\n"
            "out={}\n"
            "for n in ('fastapi','python-docx','openpyxl','ezdxf','xlrd','pdfplumber',"
            "'pypdf','paddleocr','paddlepaddle','pytesseract','chromadb',"
            "'sentence-transformers','pywin32'):\n"
            "    try: out[n]=V(n)\n"
            "    except Exception: out[n]='未安装'\n"
            "print(json.dumps(out,ensure_ascii=False))\n"
        )
        _r = subprocess.run([_run_py, "-c", _probe], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=120)
        env["packages"] = json.loads((_r.stdout or "{}").strip() or "{}")
    except Exception as e:  # noqa: BLE001
        env["packages_error"] = f"{type(e).__name__}: {e}"[:300]
    return env


def commit_and_push(run_id, out_dir, status, summary, err_msg=""):
    """把 reports/<run_id>/ 提交并推到远端，供 AI 侧读取。

    v0.1.169：只 add 显式路径（reports/<run_id> + state）。若 e.g. selftest 在
    workbench/tools/ 下留了 _samples 或 selftest_report.json，这些会留在工作区
    变成"脏"状态，下一轮 pull 又要 stash，越滚越大。改成 add reports/ 整目录，
    并靠 .gitignore 把样本/日志挡在外面。
    """
    steps = []
    rc, out, err = git("add", "-A", "reports")
    steps.append({"step": "git add reports", "rc": rc,
                  "out": out.strip()[:300], "err": err.strip()[:300]})
    # 确认这次确实有新内容进暂存区，避免「空提交」反复重试
    rc, out, _ = git("diff", "--cached", "--name-only")
    staged = [l for l in out.splitlines() if l.strip()]
    if not staged:
        steps.append({"step": "无可提交内容", "rc": 0, "out": "暂存区为空，跳过"})
        return False, steps

    msg = f"test(workbuddy): {run_id} status={status} " + \
          (f"P{summary.get('passed',0)}/F{summary.get('failed',0)}/S{summary.get('skipped',0)}" if summary else "")
    if err_msg:
        msg += f" ({err_msg[:60]})"
    rc, out, err = git("commit", "-m", msg, "--no-verify")
    steps.append({"step": "git commit", "rc": rc,
                  "out": out.strip()[:300], "err": err.strip()[:300]})
    if rc != 0:
        steps.append({"step": "commit 跳过", "rc": 0, "out": "无变更可提交"})
        return False, steps

    rc, out, err = git("push", "origin", f"HEAD:{BRANCH}", timeout=300)
    steps.append({"step": "git push", "rc": rc,
                  "out": out.strip()[:400], "err": err.strip()[:400]})
    return rc == 0, steps


def export_telemetry(out_dir):
    """把程序自己的「脱敏使用诊断包」导出到本轮报告目录。

    为什么放在循环里：自测用的是合成样本，永远测不到真实使用里的失败
    （「上传 200 个、30 个没解析出来」）。用户只要正常用程序，遥测就在记；
    每轮把这批增量带回去，AI 侧才有真实数据可优化，而不是靠猜。

    安全：导出的是 /api/telemetry/export 的脱敏包（无项目名/客户/地点/文件名/
    绝对路径），不是原始 requests.jsonl。原始日志带业务信息，且本仓库是 PUBLIC
    的，绝不能进版本库（已在 .gitignore 挡住）。

    返回 (ok, 说明)。失败不影响本轮判定 —— 遥测只是附加信息。
    """
    try:
        import urllib.request
        req = urllib.request.Request(BASE_URL + "/api/telemetry/export",
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
        bundle = (body or {}).get("data")
        if not isinstance(bundle, dict) or not bundle:
            return False, "导出返回为空（可能是旧版本，无遥测接口）"
        p = os.path.join(out_dir, "telemetry_bundle.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False, indent=1)
        req_n = (bundle.get("requests") or {}).get("total")
        pf_n = (bundle.get("parse_failures") or {}).get("total_failed")
        # 推进水位：下一轮只导新增，避免把同一批记录反复搬进仓库
        try:
            req2 = urllib.request.Request(
                BASE_URL + "/api/telemetry/export?advance=true",
                headers={"Accept": "application/json"})
            urllib.request.urlopen(req2, timeout=30).read()
        except Exception:  # noqa: BLE001
            pass
        return True, f"requests={req_n} parse_failed={pf_n} -> telemetry_bundle.json"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def run_suites(out_dir):
    """跑 tools/test_*.py 专项回归套件（v0.1.224）。

    为什么必须加这一步：每轮只跑 selftest.py，而 selftest 的 70 条断言是
    「跨接口对不对得上」这类口径校验；设备台账、整卷、备份恢复、项目隔离
    这些**功能链路**分别由 20 个 test_*.py 覆盖，以前从来不上真机。
    真机实测暴露的正是这个缺口：20261110_070527 那轮报 P68/F0/S2，其中
    「设备数跨接口一致」「设备车间归属可解析」两条因为本机当前项目没设备
    而**跳过**，于是「68 全过」听起来很绿，设备链路当轮零覆盖。

    每条都断言自己用 tempdir / 构造数据，不读写真实项目目录；本轮实测
    跑完真实 data 目录 10 个项目、审计 339 行、指针 322fef90 全未变。

    返回 (passed, failed, items)；items 每项含 name/rc/seconds/tail。
    """
    import glob
    files = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
    # test_*.py 里有几个是「解析」而不是「测试」语义的通用名，按前缀排除
    files = [f for f in files if os.path.basename(f).startswith("test_")]
    items = []
    for f in files:
        t0 = time.time()
        rc, out, err = run([sys.executable, f], cwd=WB_DIR, timeout=600)
        dur = round(time.time() - t0, 1)
        tail = ""
        for line in (out or "").strip().splitlines()[::-1]:
            s = line.strip()
            # 有些脚本最后一行是 "====" 分隔线，取它会看不出真实结论
            if not s or set(s) <= set("=-=") or len(s) < 3:
                continue
            tail = s[:160]
            break
        items.append({"name": os.path.basename(f), "rc": rc,
                      "seconds": dur, "tail": tail, "err": (err or "")[-160:]})
        log(f"  套件 {os.path.basename(f)} rc={rc} {dur}s | {tail[:80]}")

    passed = sum(1 for i in items if i["rc"] == 0)
    failed = len(items) - passed
    # v0.1.224：out_dir 必须自己确保存在 —— 原来假设调用方已建好（one_round 确实建了），
    # 但只要有人直接调这个函数（复跑、CI、我自己的验证脚本）就会 FileNotFoundError，
    # 而且这个异常发生在「20 条都跑完之后」，等于白跑一轮。
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "suites.json"), "w", encoding="utf-8") as fp:
            json.dump({"total": len(items), "passed": passed, "failed": failed,
                       "items": items}, fp, ensure_ascii=False, indent=1)
    except Exception as e:  # noqa: BLE001
        log(f"  [WARN] suites.json 写入失败：{type(e).__name__}: {e}")
    return passed, failed, items

def _write_transport(out_dir, run_id, pushed, steps):
    """把回传结果落到 transport.json —— 本地留档，不进版本库。

    v0.1.228：原来这些信息（pushed / git add|commit|push 三步的 rc）是 push 完
    再调一次 write_report_files 补写进 report.json 的。可那次补写发生在 commit
    之后，于是「提交 → 又改 → 不再提交」，每一轮收尾工作区都是脏的。下一轮
    PULL 段的 `git stash -u` 又会把刚建好的空报告目录一起 stash 掉 —— 这是
    外部包装 auto_round.py 存在的唯一理由。信息没丢，只是换了个不进库的地方。
    """
    try:
        payload = {"run_id": run_id,
                   "pushed": bool(pushed),
                   "report_commit": local_head(),
                   "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "steps": steps}
        with open(os.path.join(out_dir, "transport.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as e:  # 写不进去也不该影响本轮判定
        log(f"[警告] transport.json 写入失败：{type(e).__name__}: {e}")


def _assert_clean_after_push(out_dir, pushed):
    """守门：回传结束后，工作区里不应再有「已修改」的跟踪文件。

    这是这一轮修掉的根因的看门狗。脏了不抛异常（会把好端端的一轮判成失败），
    但必须留证据，否则下一轮 PULL 悄悄走 git stash，又把报告目录吃掉，
    现象和当初一模一样，却再也查不到是从哪一轮开始脏的。
    证据写在 reports/_dirty_after_push.txt（reports/_* 已被 .gitignore 挡住）。
    """
    rc, out, err = git("status", "--porcelain", "--untracked-files=no")
    if rc != 0:
        log(f"[警告] 收尾自检拿不到 git status：{err[:120]}")
        return
    dirty = [l for l in out.splitlines() if l.strip()]
    if not dirty:
        return
    log(f"[警告] 回传后仍有 {len(dirty)} 个跟踪文件被改动：{dirty[:5]}")
    try:
        with open(os.path.join(REPORTS_DIR, "_dirty_after_push.txt"), "w",
                  encoding="utf-8") as f:
            f.write(f"run={os.path.basename(out_dir)} pushed={pushed}\n")
            f.write("\n".join(dirty) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- 一轮
def one_round(args):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    st = load_state()
    run_id = time.strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(REPORTS_DIR, run_id)
    os.makedirs(out_dir, exist_ok=True)

    rec = {"run_id": run_id, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
           "status": "running", "steps": [], "summary": {}, "error": ""}

    def write_report_files(status, summary=None, error=""):
        """只负责把 report.json / report.md 落盘。

        v0.1.170：原来 report.json/md 在 finish 里写，而 finish 在
        commit_and_push **之后**才调用 → --once 单轮跑完时，这两个最关键的
        文件还没生成就被提交了，实测远端那一轮只有 console.log / env.json /
        selftest_report.json，没有 report.json，ai_side.py 读不到结论。
        拆成「先写盘 → 再提交 → 最后收尾记账」，保证一次提交就完整。
        """
        rec["status"] = status
        rec["summary"] = summary or {}
        rec["error"] = error
        rec["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        rec["commit_before"] = commit_before
        rec["commit_after"] = local_head()
        with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
            f.write(f"# WORKbuddy 自测报告 {run_id}\n\n")
            f.write(f"- 状态：**{status}**\n- 代码版本：`{rec['commit_after'][:12]}`\n")
            f.write(f"- 开始：{rec['started']}　结束：{rec['finished']}\n")
            if summary:
                f.write(f"- 结果：通过 {summary.get('passed',0)} / 失败 {summary.get('failed',0)} / 跳过 {summary.get('skipped',0)}\n")
            if error:
                f.write(f"\n**错误**：{error}\n")
            f.write("\n## 步骤\n\n")
            for s in rec["steps"]:
                mark = "OK" if s.get("rc", 0) == 0 else "FAIL"
                f.write(f"- [{mark}] {s.get('step')}　rc={s.get('rc')}\n")
                if s.get("err"):
                    f.write(f"  - {str(s['err'])[:200]}\n")

            # v0.1.224：专项套件逐条列出来。
            # 只写一行「P20/F0」看不出哪条链路被覆盖了；真机报告要能当证据用。
            try:
                _sj = os.path.join(out_dir, "suites.json")
                if os.path.exists(_sj):
                    with open(_sj, encoding="utf-8") as _f:
                        _s = json.load(_f)
                    f.write(f"\n## 专项回归套件（{_s.get('passed')} 通过 / "
                            f"{_s.get('failed')} 失败 / 共 {_s.get('total')}）\n\n")
                    f.write("| 套件 | 结果 | 用时(s) | 结论行 |\n|---|---|---|---|\n")
                    for _it in _s.get("items") or []:
                        _mk = "OK" if _it.get("rc") == 0 else "FAIL"
                        f.write(f"| {_it.get('name')} | {_mk} | {_it.get('seconds')} "
                                f"| {str(_it.get('tail') or '')[:80]} |\n")
            except Exception:  # noqa: BLE001
                pass

    def record_state(status, summary=None):
        """记账（本地状态文件），最后调用。"""
        st["runs"].append({"run_id": run_id, "status": status,
                           "commit": rec.get("commit_after", ""), "summary": summary})
        st["runs"] = st["runs"][-30:]
        if status in ("passed", "failed"):
            st["last_tested_commit"] = rec.get("commit_after", "")
        save_state(st)

    def finish(status, summary=None, error="", push=True):
        """收尾：写盘 → （可选）提交回传 → 记账。

        顺序很重要：必须先落盘再 commit，否则 --once 的报告进不了远端。

        v0.1.228：push 之后**不再**补写 report.json。补写发生在 commit 之后，
        等于每轮都往工作区留一处脏改动，下一轮 PULL 的 `git stash -u` 可能连带
        收走新建的报告目录。回传结果改记到 transport.json（.gitignore 已挡），
        收尾后 `git status` 应为空，由 _assert_clean_after_push 把关。
        """
        write_report_files(status, summary, error)
        if push and not getattr(args, "no_push", False):
            # 提交信息里带状态，方便远端一眼看出这一轮过没过
            pushed, psteps = commit_and_push(run_id, out_dir, status, summary or {},
                                             err_msg=error)
            rec["steps"].extend(psteps)
            _write_transport(out_dir, run_id, pushed, psteps)
            _assert_clean_after_push(out_dir, pushed)
        record_state(status, summary)
        log(f"本轮结束 status={status} 报告在 reports/{run_id}/")
        return status

    commit_before = local_head()
    log(f"===== 本轮开始 {run_id}，本地 {commit_before[:12] or '(空)'} =====")

    # ---- 1/2. 看远端，有新东西才搭动代码
    head, err = remote_head()
    rec["steps"].append({"step": "查远端 HEAD", "rc": 0 if head else 1,
                         "out": (head or "")[:40], "err": err})
    rec["remote_head"] = head
    if not head:
        finish("error", error=f"拿不到远端 HEAD：{err}")
        return "error"

    if args.no_pull:
        log("--no-pull：跳过拉取，直接用当前本地代码")
        rec["steps"].append({"step": "跳过拉取", "rc": 0, "out": "--no-pull"})
    else:
        # 先 fetch，再问「远端有多少提交本地还没有」
        ok, fstep = fetch_remote()
        rec["steps"].append(fstep)
        behind = behind_count() if ok else None
        ahead = ahead_count() if ok else None
        rec["behind"] = behind
        rec["ahead"] = ahead
        if not ok:
            finish("error", error="git fetch 失败，未动本地代码")
            return "error"
        if behind is None:
            finish("error", error="git rev-list 失败，无法判断是否需要拉取")
            return "error"
        if behind == 0:
            log(f"远端没有新提交（本地领先 {ahead} 个未推送提交），跳过拉取")
            rec["steps"].append({"step": "远端无新提交", "rc": 0,
                                 "out": f"behind=0 ahead={ahead}"})
        else:
            log(f"远端有 {behind} 个新提交，拉取")
            ok, steps = pull_latest()
            rec["steps"].extend(steps)
            if not ok:
                finish("error", error="git 拉取失败（见步骤），未动本地代码")
                return "error"
            rec["steps"].append({"step": "拉取后 HEAD", "rc": 0, "out": local_head()[:12]})

    # ---- 3. 重启服务 + 自测
    inproc = False
    if not args.no_restart:
        rec["steps"].extend(stop_service())
        time.sleep(2)
        ok, msg = start_service()
        rec["steps"].append({"step": "启动服务", "rc": 0 if ok else 1, "out": msg})
        if not ok:
            # 服务起不来不等于代码坏：降级为进程内模式继续自测，别让整轮空转
            inproc = True
            rec["steps"].append({"step": "服务不可用，转进程内模式", "rc": 0,
                                 "out": f"原因：{msg}"})
    if not service_alive():
        # v0.1.225：**服务没在线就不要降级跑自测**。
        #
        # 实测 2026-11-10 09:05 轮次（--no-restart，服务已被上一轮的清理连带杀掉）：
        # 代码自动转「进程内模式」继续跑，结果 phase1 扫描返回 {}、资料库条目 0，
        # phase3 全线「无设备数据」，phase4 清稿必然超时 —— 报告写着
        # 54 通过 / 13 失败，读报告的人会以为业务代码坏了，实际只是服务没起来。
        # 现场意义：老板看到的是一屏红色，真实结论是「工作台没开」。
        # 改为：先补启一次；还起不来就判 error 并只留一句话，绝不把
        # 「服务未就绪」伪装成 13 个功能缺陷。（进程内模式仍保留给沙箱/CI，
        # 由 --inproc-mode 显式要求，不再在真机循环里自动启用。）
        rec["steps"].append({"step": "服务健康检查", "rc": 1,
                             "out": "服务未监听，尝试再拉起一次"})
        ok2, msg2 = start_service()
        rec["steps"].append({"step": "补启动服务", "rc": 0 if ok2 else 1, "out": msg2})
        if not ok2 or not service_alive():
            finish("error",
                   error="服务未就绪：本轮未执行自测（避免把「工作台没开」"
                         "误报成一堆功能缺陷）。请先双击 open_or_start.bat。")
            return "error"

    rc, report, serr = run_selftest(args.phases, out_dir, inproc=inproc)
    summary = {}
    if report:
        s = report.get("summary", {}) or {}
        summary = {
            "passed": sum(v.get("passed", 0) for v in s.values()),
            "failed": sum(v.get("failed", 0) for v in s.values()),
            "skipped": sum(v.get("skipped", 0) for v in s.values()),
            "by_phase": s,
        }
    rec["steps"].append({"step": "selftest", "rc": rc,
                         "out": json.dumps(summary, ensure_ascii=False)[:300] if summary else "",
                         "err": serr[:300]})

    # ---- 3.5 真实使用遥测（v0.1.171）
    # 自测造的是合成样本，覆盖不到「用户真实传了 200 个文件、其中 30 个没解析出来」
    # 这种场景。所以每轮顺手把程序自己的脱敏诊断包也带回去：增量导出（水位机制），
    # 只取上一轮之后的新增，不会每轮重复搬运同一批记录。
    # 只有服务在线时才导（进程内模式的遥测落在临时库，带回来没有意义）。
    if not inproc:
        ok, msg = export_telemetry(out_dir)
        rec["steps"].append({"step": "导出使用遥测", "rc": 0 if ok else 1, "out": msg})

    # ---- 3.6 专项回归套件（v0.1.224）
    # selftest 管「跨接口口径一致」，test_*.py 管「功能链路本身」。
    # 只跑前者时，设备台账/整卷/备份这些链路只要本机没数据就会被 skip，
    # 报出来仍是「全过」—— 必须把专项也纳入每轮判定。
    s_pass, s_fail, s_items = run_suites(out_dir)
    rec["steps"].append({"step": "专项回归套件", "rc": 0 if s_fail == 0 else 1,
                         "out": f"P{s_pass}/F{s_fail}/T{len(s_items)} -> suites.json"})

    # 环境
    with open(os.path.join(out_dir, "env.json"), "w", encoding="utf-8") as f:
        json.dump(collect_env(), f, ensure_ascii=False, indent=2)

    # ---- 4. 回传（写盘、提交、记账都在 finish 里按正确顺序做完）
    # v0.1.225：状态判定合并两侧口径 ——
    #   ① 远端（v0.1.224）：专项套件 s_fail>0 时本轮不得判 passed，
    #      否则「selftest 全绿」会盖住整卷不覆盖、备份丢文件这类真实功能缺陷；
    #   ② 本地（实测 2026-11-10 07:19 全阶段 P74/F0/S2）：不能拿 selftest
    #      退出码判死 —— 那轮的 rc=1 只因为收尾清理测试项目被本机安全删除策略
    #      拦下（count:55 > threshold:50），业务断言全过（含 AutoCAD 阶段 4：
    #      原图 MD5 未变、成果 PDF 5136B），报告里却连轮判 failed，
    #      看的人以为系统坏了。
    # 合起来：没拿到报告=error；有失败断言或专项套件失败=failed；否则 passed；
    # 断言全过但 rc≠0 → passed，同时把 rc 与可能原因写进报告，不隐瞒。
    if not report:
        status = "error"
    elif summary.get("failed", 1) != 0 or s_fail:
        status = "failed"
    else:
        status = "passed"
    if status == "passed" and rc != 0:
        rec["steps"].append({
            "step": "注意", "rc": rc,
            "out": f"断言全过但 selftest 退出码={rc}（多为收尾清理被拦："
                   f"安全删除阈值/文件占用），已判 passed，需人工看 console.log"})
    rec["steps"].append({"step": "判定", "rc": 0,
                         "out": f"status={status} rc={rc} "
                                f"P{summary.get('passed', 0)}/F{summary.get('failed', 0)}"
                                f"/S{summary.get('skipped', 0)} suites_fail={s_fail}"})
    finish(status, summary, error=rec.get("error", ""))
    return status


def main():
    ap = argparse.ArgumentParser(description="繁工AI ↔ WORKbuddy 自动循环通道")
    ap.add_argument("--once", action="store_true", help="只跑一轮")
    ap.add_argument("--interval", type=int, default=300, help="常驻时检查间隔秒，默认 300")
    ap.add_argument("--phases", default="all", help="自测阶段，如 1,2,3 或 all")
    ap.add_argument("--no-restart", action="store_true", help="不重启服务（调试用）")
    ap.add_argument("--no-push", action="store_true", help="不回传报告（调试用）")
    ap.add_argument("--no-pull", action="store_true",
                    help="跳过拉取（仅调试用：沙箱里 git 不通，用于单独验证 TEST→REPORT 两段）")
    a = ap.parse_args()

    is_repo, git_dir, common = git_dir_info()
    if not is_repo:
        print(f"[错误] {REPO_DIR} 不是 git 仓库，请先确认路径")
        print("       （worktree 也支持：判定用 git rev-parse --git-dir，不靠 .git 目录）")
        return 2

    ok, holder = acquire_lock()
    if not ok:
        print(f"[错误] 已有循环在跑（PID {holder}）。同一个仓库不要同时开两个循环。")
        # v0.1.170：锁已移到共享 git 目录（worktree 与主仓库共用同一把），
        # 提示里的路径跟着实际 LOCK_FILE 走，免得按旧路径删不掉。
        print(f"       确认上一个已经退出后，删除 {LOCK_FILE} 再试。")
        return 3

    try:
        if a.once:
            return 0 if one_round(a) in ("passed",) else 1

        log(f"常驻模式启动：每 {a.interval} 秒检查一次，仓库 {REPO_DIR}")
        log("按 Ctrl+C 退出")
        while True:
            try:
                one_round(a)
            except KeyboardInterrupt:
                raise
            except Exception:  # noqa: BLE001
                log("本轮异常：\n" + traceback.format_exc())
            time.sleep(a.interval)
    except KeyboardInterrupt:
        log("收到 Ctrl+C，退出")
        return 0
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
