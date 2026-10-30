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
            alive = False
            try:
                if platform.system() == "Windows":
                    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                         capture_output=True, text=True, timeout=30).stdout
                    alive = str(pid) in out
                else:
                    os.kill(pid, 0)
                    alive = True
            except Exception:  # noqa: BLE001
                alive = False
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


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    return line


def run(cmd, cwd=None, timeout=300, check=False, env=None):
    """跑命令，返回 (rc, stdout, stderr)。

    env 传入时会与当前环境合并后交给子进程 —— 依赖路径这类「父进程能 import、
    子进程读不到」的差异必须显式传过去，否则子进程照样报缺包。
    """
    full_env = None
    if env:
        full_env = dict(os.environ)
        full_env.update(env)
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
    """
    py = sys.executable
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    child_env = dict(os.environ)
    child_env["FANGONG_NO_BROWSER"] = "1"
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
    """
    py = sys.executable
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
    try:
        from importlib.metadata import version as _v
    except Exception:  # noqa: BLE001
        _v = None
    for pkg in ("fastapi", "python-docx", "openpyxl", "ezdxf", "pywinauto"):
        try:
            env.setdefault("packages", {})[pkg] = _v(pkg) if _v else "?"
        except Exception:  # noqa: BLE001
            env.setdefault("packages", {})[pkg] = "未安装"
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
        """
        write_report_files(status, summary, error)
        if push and not getattr(args, "no_push", False):
            # 提交信息里带状态，方便远端一眼看出这一轮过没过
            pushed, psteps = commit_and_push(run_id, out_dir, status, summary or {},
                                             err_msg=error)
            rec["steps"].extend(psteps)
            rec["pushed"] = pushed
            # 提交后再写一次，保证 report.json 里也含回传结果
            write_report_files(status, summary, error)
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
        inproc = True
        rec["steps"].append({"step": "进程内自测", "rc": 0,
                             "out": "服务不在线，用 FastAPI TestClient 跑真实路由"})

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

    # 环境
    with open(os.path.join(out_dir, "env.json"), "w", encoding="utf-8") as f:
        json.dump(collect_env(), f, ensure_ascii=False, indent=2)

    # ---- 4. 回传（写盘、提交、记账都在 finish 里按正确顺序做完）
    status = "passed" if (rc == 0 and summary.get("failed", 1) == 0) else "failed"
    if not report:
        status = "error"
    rec["steps"].append({"step": "判定", "rc": 0,
                         "out": f"status={status} rc={rc}"})

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
