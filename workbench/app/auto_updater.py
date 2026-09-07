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
    通过最新commit信息解析版本号。
    """
    try:
        # 获取最新commit
        commits_url = f"{GITHUB_API_URL}/commits/{GITHUB_BRANCH}"
        req = urllib.request.Request(commits_url)
        req.add_header("User-Agent", "FanGongAI-Updater")
        req.add_header("Accept", "application/vnd.github.v3+json")
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        commit_sha = data.get("sha", "")[:7]
        commit_msg = data.get("commit", {}).get("message", "")
        commit_date = data.get("commit", {}).get("committer", {}).get("date", "")
        
        # 从commit信息中解析版本号
        import re
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
        }
    except urllib.error.URLError as e:
        return {
            "ok": False,
            "error": f"网络连接失败：{str(e)}",
            "suggestion": "请检查网络连接，或手动下载更新",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"获取版本信息失败：{str(e)}",
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
    """通过下载GitHub zip更新。"""
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
            extracted_root = os.path.join(extract_dir, f"{GITHUB_REPO}-{GITHUB_BRANCH}")
            if not os.path.isdir(extracted_root):
                # 尝试找第一个子目录
                dirs = [d for d in os.listdir(extract_dir) if os.path.isdir(os.path.join(extract_dir, d))]
                if dirs:
                    extracted_root = os.path.join(extract_dir, dirs[0])
                else:
                    extracted_root = extract_dir
            
            # 复制文件到工作目录（保留数据目录）
            copied_count = 0
            for root, dirs, files in os.walk(extracted_root):
                rel_path = os.path.relpath(root, extracted_root)
                
                # 跳过需要保留的目录
                skip = False
                for preserve in PRESERVE_DIRS:
                    if rel_path.startswith(preserve) or rel_path == preserve:
                        skip = True
                        break
                if skip:
                    continue
                
                # 创建目录
                target_dir = os.path.join(WORKSPACE_ROOT, rel_path)
                if rel_path != ".":
                    os.makedirs(target_dir, exist_ok=True)
                
                # 复制文件
                for f in files:
                    if f in PRESERVE_FILES:
                        continue
                    src_file = os.path.join(root, f)
                    dst_file = os.path.join(target_dir, f)
                    shutil.copy2(src_file, dst_file)
                    copied_count += 1
            
            # 清理临时文件
            shutil.rmtree(extract_dir, ignore_errors=True)
            
            return {
                "ok": True,
                "method": "download",
                "copied_files": copied_count,
                "message": f"下载更新成功，已更新 {copied_count} 个文件",
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
