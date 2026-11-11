"""
v0.1.112：自动更新模块

启动时检测GitHub最新版本，一键更新，保留数据目录。
支持两种更新方式：
1. Git仓库：直接 git pull
2. 非Git仓库：从GitHub下载最新zip，解压覆盖（保留数据目录）
"""

from . import atomic_io as _atomic_io
import os
import sys
import json
import time
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

# F-10（2026-10-26）：Windows 中文系统子进程输出是 GBK（netstat/taskkill/git 等），
# text=True 默认按 UTF-8 解码会 UnicodeDecodeError（0xbb）导致 apply 线程崩溃→半更新。
# 统一按平台编码、errors="replace" 兜底；pid/英文关键字（LISTENING）仍可正常解析。
_SUBPROC_ENCODING = "gbk" if sys.platform.startswith("win") else "utf-8"


def _subproc_kwargs(timeout=15):
    """跨平台子进程捕获参数：Windows 用 GBK 解码、非法字节替换不抛异常。"""
    return {"capture_output": True, "text": True,
            "encoding": _SUBPROC_ENCODING, "errors": "replace", "timeout": timeout}


# 备份目录
BACKUP_DIR = os.path.join(WORKSPACE_ROOT, "updates", "backups")

# 更新日志
UPDATE_LOG_FILE = os.path.join(WORKSPACE_ROOT, "updates", "update_log.json")

# v0.1.134：staging 暂存目录（P2 修复：运行中不直接覆盖，停服后原子替换）
STAGING_DIR = os.path.join(WORKSPACE_ROOT, "updates", "staging")
PENDING_FILE = os.path.join(WORKSPACE_ROOT, "updates", "pending_update.json")
APPLY_LOG = os.path.join(WORKSPACE_ROOT, "updates", "apply.log")


def _safe_copy(src: str, dst: str, retries: int = 3) -> str:
    """Windows 安全复制：目标存在先清只读位并删除，PermissionError（占用/只读）重试。
    成功返回 None，失败返回错误描述。"""
    last = None
    for i in range(retries):
        try:
            if os.path.exists(dst):
                try:
                    os.chmod(dst, 0o666)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    os.remove(dst)
                except Exception:  # noqa: BLE001
                    pass
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            return None
        except PermissionError as e:
            last = e
            time.sleep(0.4 * (i + 1))
        except OSError as e:
            last = e
            time.sleep(0.4 * (i + 1))
    return f"{dst}: {last}"


def _unique_staging_dir():
    """生成一个全新的、带时间戳的唯一 staging 目录名（含毫秒，避免同秒重复）。"""
    return os.path.join(
        os.path.dirname(STAGING_DIR),
        "staging_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:18],
    )


def _fresh_staging_dir() -> str:
    """获取一个保证**为空且可写**的 staging 目录。

    v0.1.160（2026-10-26 真机 500 修复）：旧实现 rmtree(ignore_errors=True) 后**不校验**
    残留是否清干净，makedirs(exist_ok)+探针可写就返回。Windows 上残留文件被占用/只读时
    rmtree 部分失败，于是新旧 61 个文件混杂，后续复制异常 → POST /api/update/perform 500。

    现在：默认目录清理后若仍有残留，立即改用带时间戳的唯一目录（与残留彻底隔离）；
    唯一目录是全新名，不含任何旧文件，保证写入干净。
    """
    base = STAGING_DIR
    for _ in range(4):
        if os.path.isdir(base):
            shutil.rmtree(base, ignore_errors=True)
        # rmtree 后校验：默认目录仍有残留（被占用/只读）→ 换唯一目录，绝不与残留混杂
        if os.path.isdir(base) and os.listdir(base):
            if base == STAGING_DIR:
                base = _unique_staging_dir()
                continue
            # 唯一目录都清不干净（极少见），再换一个新名
            base = _unique_staging_dir()
            continue
        try:
            os.makedirs(base, exist_ok=True)
            probe = os.path.join(base, ".probe")
            with open(probe, "w", encoding="utf-8") as _f:
                _f.write("ok")
            os.remove(probe)
            # 返回前再确认目录为空（只有刚删掉的 .probe，已移除）
            if not os.path.exists(base) or os.listdir(base):
                base = _unique_staging_dir()
                continue
            return base
        except Exception:  # noqa: BLE001
            base = _unique_staging_dir()
    return base


def _verify_staged_files(staging: str) -> Dict:
    """2026-10-25 整改：staging 完整性校验（防"装出起不来的版本"）。

    实测事故：main.py 升到 0.1.152 但 supervision_integration.py /
    supervision_templates.py 两个新模块没下载到位 → 启动即崩 ImportError。

    做法：静态解析 staging/app/main.py 内的相对导入
    （`from . import X` / `from .X import ...`），逐项确认 staging/app/X.py 存在；
    缺项判定更新失败，不进入替换。
    """
    import re as _re
    missing = []
    main_py = os.path.join(staging, "app", "main.py")
    if not os.path.isfile(main_py):
        return {"ok": False, "missing": ["app/main.py 缺失"]}
    try:
        with open(main_py, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return {"ok": False, "missing": ["读取 main.py 失败: %s" % e]}
    # from . import X（多行；用 [ \\t]* 避免 \\s 吞换行导致误匹配）
    for m in _re.finditer(r"from\s+\.\s+import\s+([A-Za-z0-9_]+(?:[ \t]*,[ \t]*[A-Za-z0-9_]+)*)", content):
        for name in m.group(1).split(","):
            name = name.strip()
            if not name:
                continue
            if not os.path.isfile(os.path.join(staging, "app", name + ".py")):
                missing.append("app/%s.py" % name)
    # from .X import ...（X 是模块名）
    for m in _re.finditer(r"from\s+\.([A-Za-z0-9_]+)\s+import\s", content):
        mod = m.group(1)
        if not os.path.isfile(os.path.join(staging, "app", mod + ".py")):
            missing.append("app/%s.py" % mod)
    # import X（顶层模块，staging 内应存在）
    for m in _re.finditer(r"^\s*import\s+([A-Za-z0-9_]+)", content, _re.MULTILINE):
        mod = m.group(1)
        if mod in ("os", "sys", "json", "re", "time", "datetime", "uuid", "hashlib",
                   "shutil", "subprocess", "threading", "math", "traceback", "ast",
                   "signal", "socket", "platform", "copy", "collections", "functools",
                   "itertools", "pathlib", "tempfile", "glob", "urllib", "zipfile",
                   "io", "base64", "random", "string", "typing", "asyncio", "stat",
                   "unicodedata", "html", "xml", "sqlite3", "numbers", "abc"):
            continue
        if os.path.isfile(os.path.join(staging, "app", mod + ".py")) or \
           os.path.isfile(os.path.join(staging, "parsers", mod + ".py")):
            continue
    # web 前端必须存在
    if not os.path.isfile(os.path.join(staging, "web", "index.html")):
        missing.append("web/index.html")
    # v0.1.160：tools/dwg_cleaner（清稿模块）关键文件必须齐全，否则半更新导致清稿功能异常
    for rel in ("core.py", "cad.py", "rules.py", "titleblock.py", "config.json"):
        p = os.path.join(staging, "tools", "dwg_cleaner", rel)
        if not os.path.isfile(p):
            missing.append("tools/dwg_cleaner/%s" % rel)
    if missing:
        return {"ok": False, "missing": sorted(set(missing))}
    return {"ok": True, "missing": []}

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
    """获取当前版本号。

    v0.1.206：这个函数此前恒返回 "0.0.0"，导致「检查更新」形同虚设。
    实测：/api/update/check 返回 current_version=0.0.0，而 /api/status
    同一时刻返回 version=0.1.205 —— 两个接口对同一件事给出不同答案。

    根因是两条取值路径都打空了：
      1) 读 config.VERSION —— config.py 里根本没有这个属性，
         真实定义叫 APP_VERSION；
      2) 回退到 main.py 里找 `version = "..."` —— main.py 里也没有这种
         写法（版本号统一放在 config.py）。
    两处都拿不到就落到最后的 "0.0.0"。

    修法：先读 config.APP_VERSION（兼容旧名 VERSION），
    再回退直接解析 config.py 源码里的 APP_VERSION = "..."。
    """
    try:
        from . import config
        for attr in ("APP_VERSION", "VERSION"):
            v = getattr(config, attr, None)
            if v:
                return str(v).strip()
    except Exception:  # noqa: BLE001
        pass

    # 回退：直接解析 config.py 源码（config 导入失败时的兜底）
    import re
    for rel in (("app", "config.py"), ("app", "main.py")):
        fp = os.path.join(WORKSPACE_ROOT, *rel)
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                content = f.read()
            for pat in (r'APP_VERSION\s*=\s*"([^"]+)"',
                        r'VERSION\s*=\s*"([^"]+)"'):
                match = re.search(pat, content)
                if match:
                    return match.group(1)
        except Exception:  # noqa: BLE001
            pass

    return "0.0.0"


def is_git_repo() -> bool:
    """是否走 Git 路线更新。

    v0.1.160（2026-10-26）：**部署机默认禁用 git 路线**。原因：
    1. 安装包是 zip 解压，WORKSPACE_ROOT 是 workbench 子目录，而 .git 在上一级（或不存在），
       本函数此前恒为 False（git 路线是死代码）；
    2. 即使存在 .git，也是浅克隆（.git/shallow）且本地工作树有改动，`git pull` 会报
       unrelated histories / local changes would be overwritten。
    因此页面更新统一走下载方式（staging 原子替换 + 完整性校验 + 失败回滚）。
    开发者确需走 git 时，设置环境变量 FANGONG_DEV_GIT=1 显式启用（失败仍会自动回退下载）。
    """
    if os.environ.get("FANGONG_DEV_GIT") != "1":
        return False
    git_dir = os.path.join(WORKSPACE_ROOT, ".git")
    return os.path.isdir(git_dir)


def get_latest_version_from_github() -> Dict:
    """
    从GitHub获取最新版本信息。
    优先使用raw文件方式（无API频率限制），失败时回退到API方式。
    """
    import re
    
    # 方式1：从raw.githubusercontent.com读取 config.py 中的版本号（无频率限制）
    # v0.1.206：原来这里读的是 workbench/app/main.py 里 `version = "..."`，
    # 而版本号实际定义在 app/config.py 的 APP_VERSION —— 永远匹配不到，
    # raw 方式必定落空、静默退回方式2。
    # v0.1.207：raw 会在网络抖动时返回 502。实测（2026-11-06 19:14，连续 6 次）：
    #   OK / 502 / OK / OK / OK / 502 / 502  —— 约一半失败。
    # 单发一次就退回方式2，导致「同一接口几秒内给出两个不同答案」。
    # 加两次重试（共 3 次机会，间隔 1s / 2s），把抖动挡在版本号之外。
    for attempt in range(3):
        try:
            raw_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/workbench/app/config.py"
            req = urllib.request.Request(raw_url)
            req.add_header("User-Agent", "FanGongAI-Updater")

            with urllib.request.urlopen(req, timeout=15) as response:
                content = response.read().decode("utf-8")

            # 从 config.py 中提取版本号
            version_match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', content)
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
        except Exception:  # noqa: BLE001
            if attempt < 2:
                time.sleep(1 if attempt == 0 else 2)
                continue
            # raw方式三次都失败，继续尝试API方式
            break
    
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
        
        # v0.1.207：不再用提交信息里的 `v(\d+\.\d+\.\d+)` 猜版本号 —— 这个
        # 假设是错的。实测（2026-11-06 19:12，本机 0.1.206 已推到 main）：
        #   第 1~3 次 /api/update/check → latest=0.1.205 source=api
        #   第 4~5 次 /api/update/check → latest=0.1.206 source=raw
        # 同一接口、同一件事，几秒内给出两个答案。原因是 0.1.206 的提交
        # 信息沿用了上一版文案 "feat(v0.1.205): ..."，正则就抓到 0.1.205。
        # 提交信息是给人看的散文，不是版本数据源。
        # 改为：版本号只认远端 config.py 里的 APP_VERSION（走 contents API
        # 取同一份原文）；取不到就明确报错，绝不拿猜的值冒充。
        latest_version = ""
        remote_err = ""
        try:
            c_url = (f"{GITHUB_API_URL}/contents/workbench/app/config.py"
                     f"?ref={GITHUB_BRANCH}")
            req2 = urllib.request.Request(c_url)
            req2.add_header("User-Agent", "FanGongAI-Updater")
            req2.add_header("Accept", "application/vnd.github.raw")
            with urllib.request.urlopen(req2, timeout=15) as r2:
                src = r2.read().decode("utf-8", "replace")
            m2 = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src)
            if m2:
                latest_version = m2.group(1)
        except Exception as e2:  # noqa: BLE001
            remote_err = str(e2)[:120]

        if not latest_version:
            return {
                "ok": False,
                "error": "无法读取远端版本号（config.py 未取到），不做猜测",
                "detail": remote_err,
                "latest_commit": commit_sha,
                "latest_commit_msg": commit_msg,
                "latest_commit_date": commit_date,
                "current_version": get_current_version(),
                "suggestion": "可直接访问 https://github.com/hufanrong/engineering-ai-assistant 下载最新版",
            }
        
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
            encoding=_SUBPROC_ENCODING,
            errors="replace",
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
            # v0.1.160：加入 tools（清稿模块 dwg_cleaner 等），否则页面更新永远不会更新 tools，
            # 清稿修复无法到达用户机器（tools 下无用户数据，可全量同步）。
            SYNC_DIRS = ["app", "parsers", "web", "docs", "cloud_server", "tools"]
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
            copy_errors = []

            # v0.1.134（P2 修复）：所有文件先复制到 staging 暂存目录，
            # 由独立 apply 进程在停服后原子替换，避免运行中覆盖 Permission denied
            # v0.1.142：默认目录清理失败（残留被占用/只读）时自动换唯一目录，并全部走 _safe_copy
            staging_dir = _fresh_staging_dir()

            # 1) 同步目录 → staging
            for dname in SYNC_DIRS:
                src_dir = os.path.join(workbench_root, dname)
                if not os.path.isdir(src_dir):
                    continue
                dst_dir = os.path.join(staging_dir, dname)
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
                        err = _safe_copy(src_file, dst_file)
                        if err:
                            copy_errors.append(err)
                        else:
                            copied_count += 1

            # 2) 同步根文件 → staging（含新增 install_optional.bat / open_or_start.bat）
            root_extra = ["install_optional.bat", "open_or_start.bat", "run_workbench.bat"]
            for fname in list(SYNC_FILES) + root_extra:
                src_file = os.path.join(workbench_root, fname)
                if os.path.isfile(src_file):
                    dst_file = os.path.join(staging_dir, fname)
                    err = _safe_copy(src_file, dst_file)
                    if err:
                        copy_errors.append(err)
                    else:
                        copied_count += 1

            if copy_errors:
                # 有文件无法写入（被占用/只读/杀毒锁定）→ 明确告知用户，不进入调度
                shutil.rmtree(staging_dir, ignore_errors=True)
                return {
                    "ok": False,
                    "method": "download",
                    "error": "暂存失败：以下文件无法写入（可能被其他程序占用或设为只读）：\n"
                             + "\n".join(copy_errors[:10])
                             + "\n\n请关闭杀毒软件/编辑器/OneDrive 同步后重试，或在 Windows 资源管理器中取消文件只读属性。",
                    "suggestion": "也可手动下载安装包覆盖更新（data 目录不受影响）。",
                }

            # v0.1.154：staging 完整性校验（防装出起不来的版本——2026-10-25 实测事故）
            verify = _verify_staged_files(staging_dir)
            if not verify.get("ok"):
                shutil.rmtree(staging_dir, ignore_errors=True)
                return {
                    "ok": False,
                    "method": "download",
                    "error": "下载包不完整，已取消更新（缺失文件：%s）。\n"
                             "请重试；若持续失败，请手动下载安装包更新。" % "、".join(verify.get("missing", [])),
                    "suggestion": "也可手动下载安装包覆盖更新（data 目录不受影响）。",
                }
            staging_dir = staging_dir  # noqa: PLW0127  （供下方返回引用）
            
            # 3) staging 内保护本地配置（config.py → config.local.py 机制）
            _preserve_local_config()
            
            # 清理临时文件
            shutil.rmtree(extract_dir, ignore_errors=True)
            
            return {
                "ok": True,
                "method": "download",
                "copied_files": copied_count,
                "staged": True,
                "staging": staging_dir,
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
                ["netstat", "-ano"], **_subproc_kwargs(15))
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
                ["lsof", "-ti", f":{port}"], **_subproc_kwargs(15))
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
        except Exception:
            try:
                result = subprocess.run(
                    ["fuser", f"{port}/tcp"], **_subproc_kwargs(15))
                for line in result.stdout.splitlines():
                    for tok in line.split():
                        if tok.isdigit():
                            pids.append(int(tok))
            except Exception:
                pass
    return list(set(pids))


# v0.1.233：**删掉了 _kill_process_tree()**。它用 taskkill /PID x /T（连整个
# 进程树一起杀），而重启 helper 就是服务进程拉起的子进程 —— helper 调它等于
# 自杀，这就是 D18「点了重启，工作台整台消失」的根因。现在杀进程统一用 helper
# 里的 kill_one()（不带 /T，只结束目标进程）。留着一个「看起来能用、实际会杀
# 死调用方」的公共函数，下一个人迟早会再踩一次。


_RESTART_SCRIPT = r'''# -*- coding: utf-8 -*-
# 繁工AI 重启 helper（v0.1.233）—— 由 auto_updater.restart_service() 生成并派发
#
# 这一版是按 WORKbuddy 真机缺陷 D18 重写的。v0.1.232 的 helper 有两个硬伤：
#   ① 杀旧进程用 taskkill /PID x /T（**连进程树**），而 helper 本身就是服务进程
#      拉起的子进程 —— 于是 helper 把自己也杀了，新服务永远起不来；
#   ② 杀完才拉新进程，且「新进程能不能起来」没人检查，服务死了也没人知道。
# 今天的顺序改成「先起后死」，而且这个「起」是真的起：
#   探活阶段：用**临时端口 + 临时数据目录**把新代码完整跑一遍（真启动、真绑定、
#             真响应 /api/status）。跑不通 → 直接退出，**旧服务一个字节都不动**。
#             单端口不可能两个进程同时 listen，所以这是同端口下能做到的最强保证：
#             宁可不重启，也不能宕机。
#   切换阶段：探活通过才结束旧进程，**taskkill 不带 /T**（只杀这一个进程）。
#   验收阶段：轮询 /api/status，要求 PID 真的换了、接口真的应答，才写成功。
#   全程写 updates/restart.log；结果写 updates/restart_result.json ——
#   服务死了也能读到，不依赖 HTTP。
import os, sys, json, time, shutil, socket, subprocess, datetime

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WS = {ws!r}
HOST = {host!r}
PORT = {port!r}
OLD_PIDS = {pids!r}
TAG = {tag!r}
RESULT = os.path.join(WS, "updates", "restart_result.json")
LOG = os.path.join(WS, "updates", "restart.log")

CANARY_TIMEOUT = 45      # 探活实例要多快应答（Windows 冷启动实测手动 start.py 约 8 秒）
FREE_TIMEOUT = 25        # 旧进程退出后端口要多久释放
UP_TIMEOUT = 60          # 正式实例要多久应答
RETRIES = 1              # 正式启动失败重试次数


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] [helper %s] %s\n" % (
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), TAG, msg))
    except Exception:
        pass


ERROR_LOG = os.path.join(WS, "updates", "restart_error.log")


def write_result(d):
    d = dict(d)
    d.setdefault("tag", TAG)
    d.setdefault("ts", time.time())
    d.setdefault("at", datetime.datetime.now().isoformat())
    d.setdefault("port", PORT)
    try:
        os.makedirs(os.path.dirname(RESULT), exist_ok=True)
        # v0.1.233：临时文件必须**唯一**。原来是固定的 restart_result.json.tmp，
        # 两个 helper 同时收尾（用户连点两次重启、或探活与正式实例先后写）会往
        # 同一个临时文件里各写一份 → os.replace 之后 result.json 成了两段 JSON
        # 拼接 → json.load 抛 Extra data。用 mkstemp 让「同进程多线程」和
        # 「多进程」两种并发都不会撞（只按 pid 命名挡不住线程）。
        import tempfile as _tf
        fd, tmp = _tf.mkstemp(prefix="restart_result.", suffix=".tmp",
                              dir=os.path.dirname(RESULT))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:  # noqa: BLE001
                    pass
            # v0.1.234（D22）：**os.replace 要重试**。
            # 真机实测：mkstemp 之后仍有 28~38/480 次（5.8%~7.9%）写失败，
            # 原因是 Windows 上目标文件正被别的进程读着（/api/update/restart/status
            # 轮询、另一个 helper 刚写完），replace 抛 WinError 32。
            # 这类冲突是**转瞬即逝**的，退避几百毫秒就过去了；直接把异常吞掉
            # 等于让「结果没落盘」变成常态。
            last_err = None
            for _k in range(5):
                try:
                    os.replace(tmp, RESULT)
                    last_err = None
                    break
                except OSError as _e:
                    last_err = _e
                    time.sleep(0.05 * (2 ** _k))  # 50/100/200/400/800 ms
            if last_err is not None:
                raise last_err
        except Exception:
            try:
                os.remove(tmp)
            except Exception:
                pass
            raise
    except Exception as e:
        # v0.1.234（D22）：失败**不再**往 restart.log 写「写结果失败」。
        # restart.log 是老板要求「失败要写清原因」的那份业务日志，
        # 480 次并发写往里掺几十行基础设施噪音，运维读日志会被误导。
        # 转记到独立的 restart_error.log，主日志只留业务结论。
        _write_error_log("写结果失败：%s" % e)
    return d


def _write_error_log(msg):
    """把「结果文件没落盘」这类基础设施故障写到独立日志，不污染 restart.log。"""
    try:
        os.makedirs(os.path.dirname(ERROR_LOG), exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] [helper %s] %s\n" % (
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), TAG, msg))
    except Exception:  # noqa: BLE001
        pass


def free_port_taken(port):
    """端口是否仍被监听：能 bind 上就是空的。"""
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((HOST, port))
        return False
    except OSError:
        return True
    finally:
        try:
            s.close()
        except Exception:
            pass


def pick_free_port():
    s = socket.socket()
    try:
        s.bind((HOST, 0))
        return s.getsockname()[1]
    except OSError:
        return 0
    finally:
        try:
            s.close()
        except Exception:
            pass


def pids_on_port(port):
    pids = []
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=20)
            txt = (out.stdout or b"").decode("gbk", "replace")
            for line in txt.splitlines():
                if (":" + str(port)) in line and "LISTENING" in line.upper():
                    tok = line.split()
                    if tok and tok[-1].isdigit() and tok[-1] != "0":
                        pids.append(int(tok[-1]))
        else:
            out = subprocess.run(["lsof", "-ti", ":" + str(port)], capture_output=True, timeout=20)
            for line in (out.stdout or b"").decode("utf-8", "replace").splitlines():
                if line.strip().isdigit():
                    pids.append(int(line.strip()))
    except Exception:
        pass
    return sorted(set(pids))


def pid_alive(pid):
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid],
                                 capture_output=True, timeout=15)
            return str(pid) in (out.stdout or b"").decode("gbk", "replace")
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def kill_one(pid):
    """只杀这一个进程。**绝不带 /T**：helper 是旧服务的子进程，/T 会把自己杀掉。"""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=20)
            return True
        try:
            os.kill(pid, 15)
        except Exception:
            return True
        for _ in range(10):
            if not pid_alive(pid):
                return True
            time.sleep(0.3)
        try:
            os.kill(pid, 9)
        except Exception:
            pass
        return True
    except Exception as e:
        log("结束 PID=%s 失败：%s" % (pid, e))
        return False


def http_status(port, timeout=2.0):
    """不带代理地取 /api/status。返回 (状态码, 字典)。"""
    import urllib.request
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open("http://127.0.0.1:%d/api/status" % port, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                d = json.loads(body)
            except Exception:
                d = {"_raw": body[:200]}
            return r.status, d
    except Exception as e:
        return 0, {"_err": str(e)[:160]}


def spawn(cmd, env, logpath):
    os.makedirs(os.path.dirname(logpath), exist_ok=True)
    lf = open(logpath, "a", encoding="utf-8")
    lf.write("\n--- spawn %s (%s) ---\n" % (
        " ".join(cmd), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    lf.flush()
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS} \
        if sys.platform.startswith("win") else {"start_new_session": True}
    return subprocess.Popen(cmd, cwd=WS, stdout=lf, stderr=lf, stdin=subprocess.DEVNULL,
                            env=env, close_fds=True, **kw)


def wait_http(port, timeout):
    """等到 /api/status 真的应答，返回 (ok, 耗时, 字典)。"""
    t0 = time.time()
    last = {}
    while time.time() - t0 < timeout:
        code, d = http_status(port)
        last = d
        if code == 200 and d.get("app") == "fangong-workbench":
            return True, round(time.time() - t0, 1), d
        time.sleep(0.5)
    return False, round(time.time() - t0, 1), last


def base_env(port, data_dir):
    env = dict(os.environ)
    env["FANGONG_NO_BROWSER"] = "1"
    env["FANGONG_PORT"] = str(port)
    env["FANGONG_DATA_DIR"] = data_dir
    env.pop("PYTHONPATH", None)
    return env


def main():
    t_start = time.time()
    log("helper 启动 argv=%s cwd=%s pid=%s" % (" ".join(sys.argv), os.getcwd(), os.getpid()))
    log("目标旧进程=%s 端口=%s tag=%s" % (OLD_PIDS, PORT, TAG))

    py = sys.executable or "python"
    start_py = os.path.join(WS, "start.py")
    cmd = [py, start_py] if os.path.isfile(start_py) else [py, os.path.join(WS, "app", "main.py")]
    if not os.path.isfile(start_py) and not os.path.isfile(os.path.join(WS, "app", "main.py")):
        log("找不到启动入口，放弃")
        write_result({"ok": False, "phase": "precheck",
                      "error": "缺少 start.py / app/main.py，无法重启"})
        return

    # ---------- 阶段 1：探活（**先起**，动了生产进程就回不去了） ----------
    probe = pick_free_port()
    if not probe:
        log("找不到空闲端口做探活，放弃（不动旧服务）")
        write_result({"ok": False, "phase": "canary",
                      "error": "找不到空闲端口做探活", "old_alive": [p for p in OLD_PIDS if pid_alive(p)]})
        return
    canary_data = os.path.join(WS, "updates", "_probe_data_%s" % TAG)
    try:
        shutil.rmtree(canary_data, ignore_errors=True)
        os.makedirs(canary_data, exist_ok=True)
    except Exception as e:
        log("建探活数据目录失败（不影响探活）：%s" % e)
    log("探活：端口=%s 数据目录=%s" % (probe, canary_data))
    canary = None
    try:
        canary = spawn(cmd, base_env(probe, canary_data),
                       os.path.join(WS, "updates", "restart_canary.log"))
        ok, sec, d = wait_http(probe, CANARY_TIMEOUT)
        log("探活结果=%s 耗时=%ss version=%s" % (ok, sec, d.get("version")))
        if not ok:
            log("探活失败：新代码起不来。**旧服务保持原样，本次不重启**")
            write_result({"ok": False, "phase": "canary",
                          "error": "新代码在探活端口 %d 上 %ds 内没能应答 /api/status，"
                                   "旧服务未被动过（工作台仍可用）。请查看 updates/restart_canary.log" % (probe, CANARY_TIMEOUT),
                          "canary_port": probe, "canary_log": os.path.join(WS, "updates", "restart_canary.log"),
                          "canary_last": d, "old_alive": [p for p in OLD_PIDS if pid_alive(p)],
                          "guarantee": "canary_verified_before_kill", "elapsed": round(time.time() - t_start, 1)})
            return
        canary_version = d.get("version")
    finally:
        if canary is not None:
            try:
                kill_one(canary.pid)
            except Exception:
                pass
        for p in pids_on_port(probe):
            kill_one(p)
        time.sleep(0.5)
        shutil.rmtree(canary_data, ignore_errors=True)

    # ---------- 阶段 2：结束旧进程（不带 /T） ----------
    killed = []
    for pid in OLD_PIDS:
        if kill_one(pid):
            killed.append(pid)
            log("已结束旧进程 PID=%s（未使用 /T，helper 自身不受影响）" % pid)
    freed = False
    for _ in range(FREE_TIMEOUT * 2):
        if not free_port_taken(PORT):
            freed = True
            break
        time.sleep(0.5)
    log("端口 %s 释放=%s 仍占用=%s" % (PORT, freed, pids_on_port(PORT)))
    if not freed:
        write_result({"ok": False, "phase": "kill",
                      "error": "旧进程已结束但 %ds 内端口 %d 仍未释放" % (FREE_TIMEOUT, PORT),
                      "killed": killed, "still_on_port": pids_on_port(PORT),
                      "canary_version": canary_version, "old_alive": [],
                      "guarantee": "canary_verified_before_kill",
                      "elapsed": round(time.time() - t_start, 1)})
        return

    # ---------- 阶段 3：正式拉起 + 验收 ----------
    real_log = os.path.join(WS, "updates", "restart.log")
    last = {}
    for attempt in range(RETRIES + 1):
        log("第 %d 次拉起正式实例（端口 %s）" % (attempt + 1, PORT))
        proc = spawn(cmd, base_env(PORT, ""), real_log)
        # FANGONG_DATA_DIR 置空 = 用真实 data 目录（config 里空串视为未设置）
        ok, sec, d = wait_http(PORT, UP_TIMEOUT)
        newp = [p for p in pids_on_port(PORT)]
        log("第 %d 次结果 ok=%s 耗时=%ss pid=%s version=%s" % (attempt + 1, ok, sec, newp, d.get("version")))
        if ok:
            write_result({"ok": True, "phase": "done", "killed": killed,
                          "old_pids": OLD_PIDS, "new_pids": newp,
                          "version": d.get("version"), "canary_version": canary_version,
                          "http_seconds": sec, "elapsed": round(time.time() - t_start, 1),
                          "guarantee": "canary_verified_before_kill"})
            log("重启成功：旧=%s 新=%s 版本=%s 总耗时=%ss"
                % (OLD_PIDS, newp, d.get("version"), round(time.time() - t_start, 1)))
            return
        last = d
        # 失败的那次先收尸，避免占着端口影响下一次
        for p in pids_on_port(PORT):
            kill_one(p)
        time.sleep(1)

    write_result({"ok": False, "phase": "start",
                  "error": "探活通过，但正式实例 %d 次都没能在 %ds 内应答 /api/status"
                           % (RETRIES + 1, UP_TIMEOUT),
                  "killed": killed, "old_pids": OLD_PIDS, "last_response": last,
                  "canary_version": canary_version,
                  "suggestion": "手动运行 run_workbench.bat；若 restart.log 里有 Errno 10048，"
                                "说明端口仍被别的程序占用",
                  "elapsed": round(time.time() - t_start, 1)})
    log("重启失败：正式实例没起来（旧进程已被结束，看 updates/restart.log）")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log("helper 异常：%s" % e)
        try:
            log(traceback.format_exc())
        except Exception:
            pass
        write_result({"ok": False, "phase": "helper_crash", "error": "helper 异常：%s" % e})
'''


def _restart_result_path() -> str:
    return os.path.join(WORKSPACE_ROOT, "updates", "restart_result.json")


def restart_status() -> Dict:
    """查上一次重启到底成没成。（v0.1.232 / v0.1.233 增 tag、耗时、阶段）

    这一条是「接口不许说谎」的兑现方式：restart 这个接口天生无法在自己
    返回的那一刻确认结果（它要杀的就是它自己）。于是把结果落到
    updates/restart_result.json，由独立进程写，这个接口只负责如实回报。

    D18 的另一半：**结果必须落在文件里**。v0.1.232 的提示让用户「用
    GET /api/update/restart/status 核对」，可那个接口活在被杀的进程里 ——
    服务死了就查不到，恰恰是最需要查的时候。现在这个接口只是**读文件**，
    而且真有路由（v0.1.232 只写了函数没挂路由，等于对外承诺了一个 404）。
    """
    p = _restart_result_path()
    try:
        if not os.path.isfile(p):
            return {"ok": False, "known": False,
                    "message": "还没有重启记录（或刚更新过还没重启）"}
        with open(p, encoding="utf-8") as f:
            raw = f.read()
        try:
            d = json.loads(raw)
        except Exception:
            # v0.1.233：文件被写坏时**如实说文件坏了**，不要抛异常让调用方
            # 整个 500，也不要猜一个「大概成功」的结论。
            return {"ok": False, "known": False, "corrupt": True,
                    "error": "restart_result.json 内容不合法（可能两次重启同时收尾）",
                    "raw_head": raw[:200]}
        if not isinstance(d, dict):
            return {"ok": False, "known": False, "corrupt": True,
                    "error": "restart_result.json 不是对象", "raw_head": str(d)[:200]}
        d["known"] = True
        # 服务在跑说明「当前这一代」是活着的，供前端区分「重启失败但旧服务还在」与「彻底没了」
        d["service_alive_now"] = True
        try:
            d["result_age_seconds"] = round(time.time() - float(d.get("ts") or 0), 1)
        except Exception:
            pass
        return d
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "known": False, "error": str(e)}


def _render_restart_script(port: int, pids: List[int], tag: str) -> str:
    """把 helper 模板渲染成可执行脚本源码（不落盘、不派生）。

    v0.1.233 拆出这一层是为了让测试能**只跑一个** helper：以前测试走
    _dispatch_restart_helper（它已经真派生了 helper），又自己再 run 一次脚本，
    于是两个 helper 并发收尾 —— 这正是本轮顺带抓到的那条真实缺陷
    （result.json 被两个进程拼成两段 JSON）。测试应当派生「自己那一份」。
    """
    host = "127.0.0.1"
    try:
        from . import config as _cfg  # noqa: F401
        host = getattr(_cfg, "HOST", host) or host
    except Exception:  # noqa: BLE001
        pass
    return (_RESTART_SCRIPT.replace("{ws!r}", repr(WORKSPACE_ROOT))
                          .replace("{host!r}", repr(host))
                          .replace("{port!r}", str(port))
                          .replace("{pids!r}", repr(sorted(pids)))
                          .replace("{tag!r}", repr(tag)))


def _helper_script_path() -> str:
    return os.path.join(WORKSPACE_ROOT, "updates", "restart_service.py")


def _dispatch_restart_helper(port: int, pids: List[int], tag: str) -> Dict:
    """把重启交给独立进程。返回 {ok, script} 或 {ok:False, error}。"""
    try:
        script_path = _helper_script_path()
        os.makedirs(os.path.dirname(script_path), exist_ok=True)
        if os.path.exists(script_path):
            try:
                os.remove(script_path)
            except Exception:  # noqa: BLE001
                pass
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(_render_restart_script(port, pids, tag))
        helper_log = os.path.join(WORKSPACE_ROOT, "updates", "restart_helper.log")
        os.makedirs(os.path.dirname(helper_log), exist_ok=True)
        with open(helper_log, "a", encoding="utf-8") as lf:
            lf.write(f"\n=== {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                     f"派发重启 helper tag={tag} 目标={sorted(pids)} 端口={port} ===\n")
            kw = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
                  if sys.platform.startswith("win") else {"start_new_session": True})
            subprocess.Popen([sys.executable or "python", script_path], cwd=WORKSPACE_ROOT,
                             stdout=lf, stderr=lf, stdin=subprocess.DEVNULL,
                             close_fds=True, **kw)
        return {"ok": True, "script": script_path}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"派发重启进程失败：{str(e)}"}


def restart_service(port: int = 8756) -> Dict:
    """
    【Bug2】重启工作台服务。v0.1.233 重写（D18）。

    历史：v0.1.231 谎报成功（只跳过自己，一个进程都没换）；v0.1.232 改成
    「分离 helper 先杀后起」，结果 helper 被自己的 taskkill /T 杀掉，**服务
    整台消失**。WORKbuddy 的结论是「做不到『先起后死』，就不要杀」。

    这一版的顺序：

      1. 探活（先起）：用临时端口 + 临时数据目录把新代码真正跑一遍，
         要求 /api/status 真应答。跑不通 → 直接回 ok:false，**旧服务不动**。
      2. 切换（后死）：taskkill 不带 /T，只结束服务这一个进程。
      3. 验收：轮询 /api/status，要求接口应答且端口上换了 PID，才回 ok:true。
      4. 落盘：结果写 updates/restart_result.json，服务死了也读得到；
         GET /api/update/restart/status 只是读这个文件。

    返回体里 `verified` 是关键词：true=当场确认过；false=已受理、结果待查。
    """
    tag = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    pids = _get_pid_by_port(port)
    self_pid = os.getpid()
    self_owned = self_pid in pids

    # 清掉上一次的结果，避免「新的这次还没跑完，前端读到旧的 ok:true」
    try:
        rp = _restart_result_path()
        if os.path.isfile(rp):
            os.remove(rp)
    except Exception:  # noqa: BLE001
        pass

    disp = _dispatch_restart_helper(port, pids, tag)
    if not disp.get("ok"):
        return {
            "ok": False, "verified": False, "state": "failed", "mode": "helper",
            "error": disp.get("error"),
            "killed_pids": [], "will_kill": sorted(pids), "port": port,
            "suggestion": "手动关闭旧窗口后，重新运行 run_workbench.bat",
        }

    if self_owned:
        # 占着端口的就是我自己：这一轮 HTTP 必须立刻返回，后面交给 helper
        return {
            "ok": True, "accepted": True, "verified": False, "state": "dispatched",
            "mode": "helper",
            "message": (f"已受理：约占端口的是当前进程本身（PID {self_pid}）。"
                        f"helper 先在旁路端口探活新代码，探活通过才会切换；"
                        f"探活失败则保持旧服务不变。"),
            "killed_pids": [], "will_kill": sorted(pids), "port": port,
            "check": "GET /api/update/restart/status（读文件，服务重启期间/之后都能查）",
            "tag": tag,
        }

    # 不是自己的 pid（从命令行/其它进程调用）：同样交给 helper，但本进程可以等结果，
    # 于是能当场给出 verified 的结论。**逻辑只有 helper 一份**，不另写一套。
    deadline = time.time() + 200
    while time.time() < deadline:
        d = restart_status()
        if d.get("known") and str(d.get("tag")) == tag and d.get("phase") in (
                "done", "failed", "canary", "start", "kill", "precheck", "helper_crash"):
            # canary/start/kill 是终态失败；done 是成功
            d = dict(d)
            d["verified"] = True
            d["mode"] = "helper"
            d.setdefault("state", "done" if d.get("ok") else "failed")
            return d
        time.sleep(0.5)

    return {
        "ok": False, "verified": False, "state": "timeout", "mode": "helper",
        "error": "等待重启结果超时（200 秒）", "port": port,
        "check": "GET /api/update/restart/status",
        "suggestion": "看 updates/restart.log 与 updates/restart_canary.log",
    }




# ============ v0.1.134：staging 自动替换（P2 修复）============

_APPLY_SCRIPT = r"""# -*- coding: utf-8 -*-
# 由繁工AI auto_updater 生成：停服 → 原子替换 → 回滚 → 重启
import os, sys, json, time, shutil, subprocess, datetime

# F-10（2026-10-26）：Windows 中文系统子进程输出 GBK，text=True 默认按 UTF-8 解会
# UnicodeDecodeError(0xbb) 导致 apply 线程崩溃→app 换了 tools 没换、服务不重启的半更新。
# ① 强制本子进程 stdout/stderr 为 UTF-8（写入 UTF-8 日志文件不崩）；
# ② subprocess 捕获一律按平台编码 + errors="replace"，pid/英文关键字仍可解析。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
ENC = "gbk" if sys.platform.startswith("win") else "utf-8"

WS = {ws!r}
PORT = {port!r}
PENDING = os.path.join(WS, "updates", "pending_update.json")
LOG = os.path.join(WS, "updates", "apply.log")
BACKUP_DIR = os.path.join(WS, "updates", "backups")

# v0.1.142：staging 目录从 pending_update.json 读取（可能为带时间戳的唯一目录），
# 旧版本 PENDING 无 staging 字段时回退默认目录
try:
    with open(PENDING, encoding="utf-8") as _f:
        _pending = json.load(_f)
    STAGING = _pending.get("staging") or os.path.join(WS, "updates", "staging")
except Exception:
    STAGING = os.path.join(WS, "updates", "staging")


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
            out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                                 encoding=ENC, errors="replace", timeout=15).stdout
            for line in out.splitlines():
                if (":" + str(port)) in line and "LISTENING" in line:
                    parts = line.split()
                    if parts and parts[-1].isdigit():
                        pids.append(int(parts[-1]))
        else:
            out = subprocess.run(["fuser", str(port) + "/tcp"], capture_output=True, text=True,
                                 encoding=ENC, errors="replace", timeout=10)
            for tok in (out.stdout or "").split():
                if tok.isdigit():
                    pids.append(int(tok))
    except Exception:
        pass
    return list(set(pids))


def kill_tree(pid):
    # v0.1.233：这个 apply 脚本本身是服务进程派生的子进程，原来用 /T（连进程树）
    # 杀服务 = 连自己一起杀，主进程一死脚本就断在替换文件之前，更新只做一半。
    # 与 restart helper 的 kill_one 保持同一策略：只结束目标进程。
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=15)
        else:
            subprocess.run(["kill", "-9", str(pid)], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def force_replace(src, dst, retries=4):
    # v0.1.142：Windows 替换文件——清只读位 + 重试（停服后句柄延迟释放/杀毒锁定）。
    # 注意：此模板为原始三引号字符串，函数内部禁止出现连续三个双引号。
    last = None
    for i in range(retries):
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst):
                try:
                    os.chmod(dst, 0o666)
                except Exception:
                    pass
                try:
                    os.remove(dst)
                except Exception:
                    pass
            os.replace(src, dst)
            return None
        except Exception as e:
            last = e
            time.sleep(0.5 * (i + 1))
    return last


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
            err = force_replace(src, dst)
            if err is None:
                replaced.append(dst)
            else:
                failed.append((dst, str(err)))
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


def schedule_staged_apply(staging: str = "") -> Dict:
    """把 staging 的更新交给独立进程执行：停服→替换→重启（当前进程继续返回响应）。
    v0.1.140：修复「调度更新失败：name 'config' is not defined」——本模块无模块级 config 导入，
    此前 schedule_staged_apply 直接引用 config.PORT 触发 NameError，导致在线更新永远无法执行。
    v0.1.142：支持传入唯一 staging 目录（staging_时间戳），PENDING 记录实际目录供 apply 读取。"""
    from . import config  # noqa: F401  （局部导入，避免模块级循环依赖）
    try:
        staging = staging or STAGING_DIR
        script_path = os.path.join(WORKSPACE_ROOT, "updates", "apply_update.py")
        if os.path.exists(script_path):
            try:
                os.chmod(script_path, 0o666)
            except Exception:  # noqa: BLE001
                pass
            try:
                os.remove(script_path)
            except Exception:  # noqa: BLE001
                pass
        with open(script_path, "w", encoding="utf-8") as f:
            # v0.1.140：不能用 .format()——模板内含 apply 脚本自身的 f-string/format 占位符
            # （{0}/{pid}/{e} 等）会被误解析，导致「Replacement index 0 out of range」。
            # 改为只定向替换两个模板变量，其余花括号原样保留。
            f.write(_APPLY_SCRIPT.replace("{ws!r}", repr(WORKSPACE_ROOT))
                                     .replace("{port!r}", str(config.PORT)))
        pending = {
            "staging": staging,
            "created": datetime.datetime.now().isoformat(),
        }
        _atomic_io.write_json(PENDING_FILE, pending, indent=None)
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
        # v0.1.142：传入实际 staging 目录（可能是带时间戳的唯一目录）
        sched = schedule_staged_apply(update_result.get("staging") or "")
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
            _atomic_io.write_json(UPDATE_LOG_FILE, logs, indent=2)
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
        _atomic_io.write_json(UPDATE_LOG_FILE, logs, indent=2)
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
                err = _safe_copy(src_file, dst_file)
                if not err:
                    restored_count += 1
        
        return {
            "ok": True,
            "restored_files": restored_count,
            "message": f"已从备份恢复 {restored_count} 个文件，请重启服务",
        }
    except Exception as e:
        return {"ok": False, "error": f"恢复失败：{str(e)}"}
