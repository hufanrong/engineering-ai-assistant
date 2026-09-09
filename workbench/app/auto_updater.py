"""
v0.1.112：自动更新模块

启动时检测GitHub最新版本，一键更新，保留数据目录。
支持两种更新方式：
1. Git仓库：直接 git pull
2. 非Git仓库：从GitHub下载最新zip，解压覆盖（保留数据目录）
"""

import os
import sys
import json
import zipfile
import shutil
import datetime
import subprocess
import urllib.request
import urllib.error
from typing import Optional, Dict, List


# GitHub 仓库信息
GITHUB_OWNER = "hufanrong"
GITHUB_REPO = "engineering-ai-assistant"
GITHUB_BRANCH = "main"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_ZIP_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip"

# 工作台根目录（app/ 的上一级）
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 备份目录
BACKUP_DIR = os.path.join(WORKSPACE_ROOT, "updates", "backups")

# 更新日志
UPDATE_LOG_FILE = os.path.join(WORKSPACE_ROOT, "updates", "update_log.json")

# v0.1.134：staging 暂存目录（P2 修复：运行中不直接覆盖，停服后原子替换）
STAGING_DIR = os.path.join(WORKSPACE_ROOT, "updates", "staging")
PENDING_FILE = os.path.join(WORKSPACE_ROOT, "updates", "pending_update.json")
APPLY_LOG = os.path.join(WORKSPACE_ROOT, "updates", "apply.log")

# 需要保留的数据目录（更新时不覆盖）
PRESERVE_DIRS = [
    "data",
    "platform_data",
    "cloud_server/cloud_data",
    "venv",
    "updates",
    "test_data",
]

# 需要保留的文件
PRESERVE_FILES = [
    ".git",
    ".gitignore",
]


def _ensure_dirs():
    """确保目录存在。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(UPDATE_LOG_FILE), exist_ok=True)


def get_current_version() -> str:
    """获取当前版本号。"""
    try:
        from . import config
        if hasattr(config, 'VERSION'):
            return config.VERSION
    except Exception:
        pass
    
    # 从 main.py 中读取
    main_py = os.path.join(WORKSPACE_ROOT, "app", "main.py")
    if os.path.isfile(main_py):
        try:
            with open(main_py, "r", encoding="utf-8") as f:
                content = f.read()
            import re
            match = re.search(r'version\s*=\s*"([^"]+)"', content)
            if match:
                return match.group(1)
        except Exception:
            pass
    
    return "0.0.0"


def is_git_repo() -> bool:
    """检查是否是Git仓库。"""
    git_dir = os.path.join(WORKSPACE_ROOT, ".git")
    return os.path.isdir(git_dir)


def get_latest_version_from_github() -> Dict:
    """
    从GitHub获取最新版本信息。
    优先使用raw文件方式（无API频率限制），失败时回退到API方式。
    """
    import re
    
    # 方式1：从raw.githubusercontent.com读取main.py中的版本号（无频率限制）
    try:
        raw_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/workbench/app/main.py"
        req = urllib.request.Request(raw_url)
        req.add_header("User-Agent", "FanGongAI-Updater")
        
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read().decode("utf-8")
        
        # 从main.py中提取版本号
        version_match = re.search(r'version\s*=\s*"([^"]+)"', content)
        if version_match:
            latest_version = version_match.group(1)
            current = get_current_version()
            return {
                "ok": True,
                "latest_version": latest_version,
                "latest_commit": "",
                "latest_commit_msg": f"v{latest_version}",
                "latest_commit_date": "",
                "current_version": current,
                "has_update": _compare_versions(latest_version, current) > 0,
                "source": "raw",
            }
    except Exception as e:
        # raw方式失败，继续尝试API方式
        pass
    
    # 方式2：使用GitHub API（有频率限制）
    try:
        commits_url = f"{GITHUB_API_URL}/commits/{GITHUB_BRANCH}"
        req = urllib.request.Request(commits_url)
        req.add_header("User-Agent", "FanGongAI-Updater")
        req.add_header("Accept", "application/vnd.github.v3+json")
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        commit_sha = data.get("sha", "")[:7]
        commit_msg = data.get("commit", {}).get("message", "")
        commit_date = data.get("commit", {}).get("committer", {}).get("date", "")
        
        version_match = re.search(r'v(\d+\.\d+\.\d+)', commit_msg)
        latest_version = version_match.group(1) if version_match else "0.0.0"
        
        return {
            "ok": True,
            "latest_version": latest_version,
            "latest_commit": commit_sha,
            "latest_commit_msg": commit_msg,
            "latest_commit_date": commit_date,
            "current_version": get_current_version(),
            "has_update": _compare_versions(latest_version, get_current_version()) > 0,
            "source": "api",
        }
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return {
                "ok": False,
                "error": "GitHub API访问频率超限，请稍后重试或手动下载更新",
                "suggestion": "可直接访问 https://github.com/hufanrong/engineering-ai-assistant 下载最新版",
            }
        return {
            "ok": False,
            "error": f"网络错误：HTTP {e.code}",
            "suggestion": "请检查网络连接",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"获取版本信息失败：{str(e)}",
            "suggestion": "请检查网络连接，或手动下载更新",
        }


def _compare_versions(v1: str, v2: str) -> int:
    """比较版本号，v1>v2返回1，v1<v2返回-1，相等返回0。"""
    try:
        parts1 = [int(x) for x in v1.split(".")]
        parts2 = [int(x) for x in v2.split(".")]
        for i in range(max(len(parts1), len(parts2))):
            p1 = parts1[i] if i < len(parts1) else 0
            p2 = parts2[i] if i < len(parts2) else 0
            if p1 > p2:
                return 1
            if p1 < p2:
                return -1
        return 0
    except Exception:
        return 0


def backup_current_version() -> Dict:
    """备份当前版本。"""
    _ensure_dirs()
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    version = get_current_version()
    backup_name = f"fanGong_v{version}_{timestamp}"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    
    try:
        # 复制整个工作目录（排除数据目录）
        shutil.copytree(
            WORKSPACE_ROOT,
            backup_path,
            ignore=shutil.ignore_patterns(
                "data", "platform_data", "cloud_server/cloud_data",
                "venv", "__pycache__", "*.pyc", "test_data",
                ".git", "updates"
            )
        )
        
        return {
            "ok": True,
            "backup_path": backup_path,
            "backup_name": backup_name,
            "message": f"当前版本已备份到：{backup_name}",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"备份失败：{str(e)}",
        }


def update_via_git() -> Dict:
    """通过Git pull更新。"""
    try:
        result = subprocess.run(
            ["git", "pull", "origin", GITHUB_BRANCH],
            cwd=WORKSPACE_ROOT,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            return {
                "ok": True,
                "method": "git",
                "output": result.stdout,
                "message": "Git pull 成功，代码已更新",
            }
        else:
            return {
                "ok": False,
                "method": "git",
                "error": result.stderr or result.stdout,
                "message": "Git pull 失败，将尝试下载方式更新",
            }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "method": "git",
            "error": "Git pull 超时",
        }
    except Exception as e:
        return {
            "ok": False,
            "method": "git",
            "error": str(e),
        }


def update_via_download() -> Dict:
    """通过下载GitHub zip更新（v0.1.127：只同步 workbench/ 子目录，保护本地配置）。"""
    import tempfile
    
    try:
        # 下载zip
        print(f"正在从GitHub下载最新版本...")
        req = urllib.request.Request(GITHUB_ZIP_URL)
        req.add_header("User-Agent", "FanGongAI-Updater")
        
        with urllib.request.urlopen(req, timeout=120) as response:
            zip_data = response.read()
        
        # 保存到临时文件
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(zip_data)
            zip_path = tmp.name
        
        try:
            # 解压到临时目录
            extract_dir = tempfile.mkdtemp()
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
            
            # GitHub zip 解压后有一层目录 engineering-ai-assistant-main/
            repo_root = os.path.join(extract_dir, f"{GITHUB_REPO}-{GITHUB_BRANCH}")
            if not os.path.isdir(repo_root):
                # 尝试找第一个子目录
                dirs = [d for d in os.listdir(extract_dir) if os.path.isdir(os.path.join(extract_dir, d))]
                if dirs:
                    repo_root = os.path.join(extract_dir, dirs[0])
                else:
                    repo_root = extract_dir
            
            # 【Bug1 修复】定位 workbench/ 子目录作为更新源（仓库根目录含 client/server/mobile 等无关项目）
            workbench_root = os.path.join(repo_root, "workbench")
            if not os.path.isdir(workbench_root):
                # 兼容旧结构：仓库根目录即 workbench
                workbench_root = repo_root
            if not os.path.isdir(workbench_root):
                return {"ok": False, "method": "download", "error": "下载包中未找到 workbench 子目录"}
            
            # 只同步程序文件白名单（不复制数据/环境/无关文件）
            # 同步目录（相对 workbench_root）：app、parsers、web、docs、cloud_server（不含cloud_data）
            SYNC_DIRS = ["app", "parsers", "web", "docs", "cloud_server"]
            # 同步文件（相对 workbench_root）
            SYNC_FILES = [
                "start.py", "run_workbench.bat", "README.md", "requirements.txt",
                "requirements-ocr.txt", ".gitignore", "config.local.py.example",
                "install_optional.bat", "open_or_start.bat",
            ]
            # 保护：本地用户数据/配置，更新时跳过
            LOCAL_PRESERVE = [
                "data", "platform_data", "venv", "updates", "test_data",
                "__pycache__", ".git", ".pytest_cache",
            ]
            
            copied_count = 0
            
            # v0.1.134（P2 修复）：所有文件先复制到 staging 暂存目录，
            # 由独立 apply 进程在停服后原子替换，避免运行中覆盖 Permission denied
            if os.path.isdir(STAGING_DIR):
                shutil.rmtree(STAGING_DIR, ignore_errors=True)
            os.makedirs(STAGING_DIR, exist_ok=True)
            
            # 1) 同步目录 → staging
            for dname in SYNC_DIRS:
                src_dir = os.path.join(workbench_root, dname)
                if not os.path.isdir(src_dir):
                    continue
                dst_dir = os.path.join(STAGING_DIR, dname)
                os.makedirs(dst_dir, exist_ok=True)
                for root, dirs, files in os.walk(src_dir):
                    rel_path = os.path.relpath(root, src_dir)
                    skip = False
                    for p in LOCAL_PRESERVE:
                        if rel_path == p or rel_path.startswith(p + os.sep):
                            skip = True
                            break
                    if rel_path.startswith("cloud_data"):
                        skip = True
                    if skip:
                        continue
                    target_dir = os.path.join(dst_dir, rel_path) if rel_path != "." else dst_dir
                    if rel_path != ".":
                        os.makedirs(target_dir, exist_ok=True)
                    for f in files:
                        if f.endswith(".pyc"):
                            continue
                        src_file = os.path.join(root, f)
                        dst_file = os.path.join(target_dir, f)
                        shutil.copy2(src_file, dst_file)
                        copied_count += 1
            
            # 2) 同步根文件 → staging（含新增 install_optional.bat / open_or_start.bat）
            root_extra = ["install_optional.bat", "open_or_start.bat", "run_workbench.bat"]
            for fname in list(SYNC_FILES) + root_extra:
                src_file = os.path.join(workbench_root, fname)
                if os.path.isfile(src_file):
                    dst_file = os.path.join(STAGING_DIR, fname)
                    shutil.copy2(src_file, dst_file)
                    copied_count += 1
            
            # 3) staging 内保护本地配置（config.py → config.local.py 机制）
            _preserve_local_config()
            
            # 清理临时文件
            shutil.rmtree(extract_dir, ignore_errors=True)
            
            return {
                "ok": True,
                "method": "download",
                "copied_files": copied_count,
                "staged": True,
                "message": f"已下载并暂存 {copied_count} 个程序文件，将自动停服替换并重启",
            }
        finally:
            if os.path.exists(zip_path):
                os.remove(zip_path)
    
    except Exception as e:
        return {
            "ok": False,
            "method": "download",
            "error": str(e),
        }


def _preserve_local_config():
    """【Bug3 修复】保护本地 config.py 修改：
    更新前若本地 config.py 与仓库版本不同，先备份为 config.local.py（加载时覆盖生效）。
    更新后再比较，保留用户修改。"""
    try:
        import re as _re
        workbench_cfg = os.path.join(WORKSPACE_ROOT, "app", "config.py")
        local_cfg = os.path.join(WORKSPACE_ROOT, "app", "config.local.py")
        
        # 已存在 config.local.py（用户之前就有本地配置）→ 保留不动
        if os.path.exists(local_cfg):
            return
        
        # 本地 config.py 中查找用户可能的修改点（HOST 等）
        if os.path.exists(workbench_cfg):
            with open(workbench_cfg, "r", encoding="utf-8") as f:
                content = f.read()
            # 检测是否被用户改过（HOST 非 127.0.0.1、PORT 非 8756 等）
            host_match = _re.search(r'HOST\s*=\s*"([^"]+)"', content)
            modified = host_match and host_match.group(1) != "127.0.0.1"
            if not modified:
                port_match = _re.search(r'PORT\s*=\s*(\d+)', content)
                modified = port_match and port_match.group(1) != "8756"
            
            if modified:
                # 备份为 config.local.py，程序加载时覆盖
                shutil.copy2(workbench_cfg, local_cfg)
                print("检测到本地 config.py 修改，已保留为 config.local.py")
    except Exception:
        pass


def _get_pid_by_port(port: int) -> List[int]:
    """【Bug2】查找占用指定端口的进程PID列表（Windows/Linux兼容）。"""
    pids = []
    if sys.platform.startswith("win"):
        try:
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=15)
            for line in result.stdout.splitlines():
                if f":{port}" in line and ("LISTENING" in line or "LISTEN" in line):
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        if pid.isdigit() and pid != "0":
                            pids.append(int(pid))
        except Exception:
            pass
    else:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=15)
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
        except Exception:
            try:
                result = subprocess.run(
                    ["fuser", f"{port}/tcp"], capture_output=True, text=True, timeout=15)
                for line in result.stdout.splitlines():
                    for tok in line.split():
                        if tok.isdigit():
                            pids.append(int(tok))
            except Exception:
                pass
    return list(set(pids))


def _kill_process_tree(pid: int) -> bool:
    """【Bug2】结束进程及其子进程树（Windows taskkill /T /F，Linux kill 进程组）。"""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, text=True, timeout=15)
        else:
            try:
                os.killpg(os.getpgid(pid), 15)  # SIGTERM
            except Exception:
                os.kill(pid, 15)
            # 等待退出
            for _ in range(10):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.3)
                except OSError:
                    return True
            try:
                os.kill(pid, 9)  # SIGKILL
            except Exception:
                pass
        return True
    except Exception:
        return False


def restart_service(port: int = 8756) -> Dict:
    """
    【Bug2】重启工作台服务：结束占用端口的旧进程 → 重新启动新进程。
    返回 {ok, message, error, port_pid}
    """
    import time as _time
    
    # 1. 查找占用端口的进程
    pids = _get_pid_by_port(port)
    killed = []
    for pid in pids:
        # 跳过自身（如果检测到自己）
        if pid == os.getpid():
            continue
        if _kill_process_tree(pid):
            killed.append(pid)
    
    # 2. 等待端口释放
    for _ in range(10):
        remaining = _get_pid_by_port(port)
        remaining = [p for p in remaining if p != os.getpid()]
        if not remaining:
            break
        _time.sleep(0.5)
    
    # 3. 重新启动服务（后台）
    try:
        python = sys.executable or "python"
        main_py = os.path.join(WORKSPACE_ROOT, "app", "main.py")
        start_py = os.path.join(WORKSPACE_ROOT, "start.py")
        
        # 优先用 start.py（如果有），否则直接跑 main.py
        if os.path.isfile(start_py):
            cmd = [python, start_py]
        else:
            cmd = [python, main_py]
        
        # 启动新进程（不阻塞，日志输出到 updates/restart.log）
        log_path = os.path.join(WORKSPACE_ROOT, "updates", "restart.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as logf:
            logf.write(f"\n=== {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 重启服务 ===\n")
            if sys.platform.startswith("win"):
                subprocess.Popen(
                    cmd, cwd=WORKSPACE_ROOT,
                    stdout=logf, stderr=logf,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                    close_fds=True)
            else:
                subprocess.Popen(
                    cmd, cwd=WORKSPACE_ROOT,
                    stdout=logf, stderr=logf,
                    start_new_session=True, close_fds=True)
        
        return {
            "ok": True,
            "message": f"服务已重新启动（端口 {port}），新进程已后台运行",
            "killed_pids": killed,
            "port": port,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"重启失败：{str(e)}",
            "killed_pids": killed,
            "suggestion": "请手动关闭旧窗口后，重新运行 run_workbench.bat",
        }


# ============ v0.1.134：staging 自动替换（P2 修复）============

_APPLY_SCRIPT = r"""# -*- coding: utf-8 -*-
# 由繁工AI auto_updater 生成：停服 → 原子替换 → 回滚 → 重启
import os, sys, json, time, shutil, subprocess, datetime

WS = {ws!r}
PORT = {port!r}
STAGING = os.path.join(WS, "updates", "staging")
PENDING = os.path.join(WS, "updates", "pending_update.json")
LOG = os.path.join(WS, "updates", "apply.log")
BACKUP_DIR = os.path.join(WS, "updates", "backups")


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[{0}] {1}\n".format(
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def pid_by_port(port):
    pids = []
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=15).stdout
            for line in out.splitlines():
                if (":" + str(port)) in line and "LISTENING" in line:
                    parts = line.split()
                    if parts and parts[-1].isdigit():
                        pids.append(int(parts[-1]))
        else:
            out = subprocess.run(["fuser", str(port) + "/tcp"], capture_output=True, text=True, timeout=10)
            for tok in (out.stdout or "").split():
                if tok.isdigit():
                    pids.append(int(tok))
    except Exception:
        pass
    return list(set(pids))


def kill_tree(pid):
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=15)
        else:
            subprocess.run(["kill", "-9", str(pid)], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def main():
    log("apply 开始，等待主进程响应返回…")
    time.sleep(2)
    if not os.path.isdir(STAGING):
        log("staging 不存在，跳过")
        return
    # 1. 停服
    for pid in pid_by_port(PORT):
        if pid == os.getpid():
            continue
        log(f"结束旧进程 PID={pid}")
        kill_tree(pid)
    time.sleep(1.5)
    # 2. 原子替换
    replaced, failed = [], []
    for root, _dirs, files in os.walk(STAGING):
        rel = os.path.relpath(root, STAGING)
        for f in files:
            src = os.path.join(root, f)
            dst = os.path.join(WS, rel, f) if rel != "." else os.path.join(WS, f)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.exists(dst):
                    os.remove(dst)  # 先释放旧句柄
                os.replace(src, dst)
                replaced.append(dst)
            except Exception as e:
                failed.append((dst, str(e)))
    log(f"替换完成：成功 {len(replaced)}，失败 {len(failed)}")
    # 3. 失败回滚：从最近备份恢复失败文件
    if failed:
        if os.path.isdir(BACKUP_DIR):
            baks = sorted([d for d in os.listdir(BACKUP_DIR) if os.path.isdir(os.path.join(BACKUP_DIR, d))], reverse=True)
            if baks:
                bak_root = os.path.join(BACKUP_DIR, baks[0])
                for dst, err in failed:
                    rel = os.path.relpath(dst, WS)
                    src_bak = os.path.join(bak_root, rel)
                    try:
                        if os.path.isfile(src_bak):
                            os.makedirs(os.path.dirname(dst), exist_ok=True)
                            os.replace(src_bak, dst)
                            log(f"已回滚 {rel}")
                    except Exception as e2:
                        log(f"回滚失败 {rel}: {e2}")
    # 4. 清理
    try:
        shutil.rmtree(STAGING, ignore_errors=True)
    except Exception:
        pass
    for p in (PENDING,):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
    # 5. 重启服务
    time.sleep(0.5)
    try:
        python = sys.executable or "python"
        start_py = os.path.join(WS, "start.py")
        cmd = [python, start_py] if os.path.isfile(start_py) else [python, os.path.join(WS, "app", "main.py")]
        log_path = os.path.join(WS, "updates", "restart.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(f"\n=== {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 更新后自动重启 ===\n")
            if sys.platform.startswith("win"):
                subprocess.Popen(cmd, cwd=WS, stdout=lf, stderr=lf,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                                 close_fds=True)
            else:
                subprocess.Popen(cmd, cwd=WS, stdout=lf, stderr=lf, start_new_session=True, close_fds=True)
        log("服务已重启")
    except Exception as e:
        log(f"重启失败: {e}")


if __name__ == "__main__":
    main()
"""


def schedule_staged_apply() -> Dict:
    """把 staging 的更新交给独立进程执行：停服→替换→重启（当前进程继续返回响应）。
    v0.1.140：修复「调度更新失败：name 'config' is not defined」——本模块无模块级 config 导入，
    此前 schedule_staged_apply 直接引用 config.PORT 触发 NameError，导致在线更新永远无法执行。"""
    from . import config  # noqa: F401  （局部导入，避免模块级循环依赖）
    try:
        script_path = os.path.join(WORKSPACE_ROOT, "updates", "apply_update.py")
        with open(script_path, "w", encoding="utf-8") as f:
            # v0.1.140：不能用 .format()——模板内含 apply 脚本自身的 f-string/format 占位符
            # （{0}/{pid}/{e} 等）会被误解析，导致「Replacement index 0 out of range」。
            # 改为只定向替换两个模板变量，其余花括号原样保留。
            f.write(_APPLY_SCRIPT.replace("{ws!r}", repr(WORKSPACE_ROOT))
                                     .replace("{port!r}", str(config.PORT)))
        pending = {
            "staging": STAGING_DIR,
            "created": datetime.datetime.now().isoformat(),
        }
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False)
        # 分离进程执行（主进程立即返回）
        log_path = os.path.join(WORKSPACE_ROOT, "updates", "apply.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(f"\n=== {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 调度 apply ===\n")
            if sys.platform.startswith("win"):
                subprocess.Popen([sys.executable, script_path], cwd=WORKSPACE_ROOT,
                                 stdout=lf, stderr=lf,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                                 close_fds=True)
            else:
                subprocess.Popen([sys.executable, script_path], cwd=WORKSPACE_ROOT,
                                 stdout=lf, stderr=lf, start_new_session=True, close_fds=True)
        return {"ok": True, "message": "更新已暂存，正在自动停服替换并重启（约10秒），页面将自动恢复"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"调度更新失败：{e}"}


def perform_update(backup: bool = True, force: bool = False) -> Dict:
    """
    执行更新。
    
    Args:
        backup: 是否先备份当前版本
        force: 是否强制更新（即使没有新版本）
    
    Returns:
        更新结果
    """
    _ensure_dirs()
    
    # 1. 检查更新
    version_info = get_latest_version_from_github()
    if not version_info.get("ok"):
        return version_info
    
    if not version_info.get("has_update") and not force:
        return {
            "ok": True,
            "skipped": True,
            "message": f"当前已是最新版本（v{version_info['current_version']}）",
            "current_version": version_info["current_version"],
            "latest_version": version_info["latest_version"],
        }
    
    # 2. 备份当前版本
    backup_result = None
    if backup:
        backup_result = backup_current_version()
        if not backup_result.get("ok"):
            return {
                "ok": False,
                "error": f"备份失败，已取消更新：{backup_result.get('error')}",
            }
    
    # 3. 执行更新
    update_result = None
    
    if is_git_repo():
        # 优先用git pull
        update_result = update_via_git()
        if not update_result.get("ok"):
            # git失败，尝试下载方式
            update_result = update_via_download()
    else:
        # 非git仓库，用下载方式
        update_result = update_via_download()
    
    if not update_result.get("ok"):
        return {
            "ok": False,
            "error": f"更新失败：{update_result.get('error')}",
            "backup": backup_result,
            "suggestion": "更新失败，当前版本未受影响。可尝试手动下载更新包。",
        }
    
    # v0.1.134（P2）：下载方式为 staging 暂存 → 调度独立进程停服替换并自动重启
    if update_result.get("staged"):
        sched = schedule_staged_apply()
        if not sched.get("ok"):
            return {
                "ok": False,
                "error": sched.get("error"),
                "backup": backup_result,
                "suggestion": "暂存成功但调度失败：请手动关闭服务后，将 updates/staging/ 内文件覆盖到工作台目录，再重启。",
            }
        log_entry = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "from_version": version_info["current_version"],
            "to_version": version_info["latest_version"],
            "method": "download(staged)",
            "backup_path": backup_result.get("backup_path", "") if backup_result else "",
            "result": "success",
        }
        try:
            logs = []
            if os.path.isfile(UPDATE_LOG_FILE):
                with open(UPDATE_LOG_FILE, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            logs.insert(0, log_entry)
            logs = logs[:50]
            with open(UPDATE_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True,
            "message": sched.get("message"),
            "from_version": version_info["current_version"],
            "to_version": version_info["latest_version"],
            "method": "download(staged)",
            "backup": backup_result,
            "need_restart": True,
            "auto_restarting": True,
            "restart_hint": "更新文件已就绪，正在自动停服替换并重启（约10秒）。页面若断开请稍等后刷新。",
        }
    
    # 4. 记录更新日志
    log_entry = {
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "from_version": version_info["current_version"],
        "to_version": version_info["latest_version"],
        "method": update_result.get("method", "unknown"),
        "backup_path": backup_result.get("backup_path", "") if backup_result else "",
        "result": "success",
    }
    
    try:
        logs = []
        if os.path.isfile(UPDATE_LOG_FILE):
            with open(UPDATE_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        logs.insert(0, log_entry)
        logs = logs[:50]  # 只保留最近50条
        with open(UPDATE_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    
    return {
        "ok": True,
        "message": update_result.get("message", "更新成功"),
        "from_version": version_info["current_version"],
        "to_version": version_info["latest_version"],
        "method": update_result.get("method", "unknown"),
        "backup": backup_result,
        "need_restart": True,
        "restart_hint": "更新完成！请重启工作台服务以加载新版本（关闭后重新运行 run_workbench.bat）。",
    }


def get_update_log() -> Dict:
    """获取更新日志。"""
    try:
        if os.path.isfile(UPDATE_LOG_FILE):
            with open(UPDATE_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
            return {"ok": True, "logs": logs, "total": len(logs)}
    except Exception:
        pass
    return {"ok": True, "logs": [], "total": 0}


def get_backup_list() -> Dict:
    """获取备份列表。"""
    _ensure_dirs()
    backups = []
    if os.path.isdir(BACKUP_DIR):
        for name in os.listdir(BACKUP_DIR):
            path = os.path.join(BACKUP_DIR, name)
            if os.path.isdir(path):
                backups.append({
                    "name": name,
                    "path": path,
                    "created_at": datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S"),
                    "size": _get_dir_size(path),
                })
    backups.sort(key=lambda x: x["created_at"], reverse=True)
    return {"ok": True, "backups": backups, "total": len(backups)}


def _get_dir_size(path: str) -> int:
    """获取目录大小（字节）。"""
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass
    return total


def restore_backup(backup_name: str) -> Dict:
    """从备份恢复。"""
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    if not os.path.isdir(backup_path):
        return {"ok": False, "error": f"备份不存在：{backup_name}"}
    
    try:
        # 复制备份文件回工作目录（保留数据目录）
        restored_count = 0
        for root, dirs, files in os.walk(backup_path):
            rel_path = os.path.relpath(root, backup_path)
            target_dir = os.path.join(WORKSPACE_ROOT, rel_path)
            if rel_path != ".":
                os.makedirs(target_dir, exist_ok=True)
            for f in files:
                src_file = os.path.join(root, f)
                dst_file = os.path.join(target_dir, f)
                shutil.copy2(src_file, dst_file)
                restored_count += 1
        
        return {
            "ok": True,
            "restored_files": restored_count,
            "message": f"已从备份恢复 {restored_count} 个文件，请重启服务",
        }
    except Exception as e:
        return {"ok": False, "error": f"恢复失败：{str(e)}"}
