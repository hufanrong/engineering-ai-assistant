# 繁工AI 本地解析工作台 - 存储位置管理（v0.1.124）
# 解析资源储存位置设置管理：查看/设置/迁移/恢复默认。
# 配置持久化到 data/storage_config.json，config.py 加载时优先读取。
import os
import shutil
import json
import time

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(_BASE_DIR, "data", "storage_config.json")

# 默认路径（与 config.py 默认一致）
DEFAULT_DATA_ROOT = os.path.join(_BASE_DIR, "data")
DEFAULT_PLATFORM_ROOT = os.path.join(_BASE_DIR, "platform_data")


def _load_config() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def get_data_root() -> str:
    cfg = _load_config()
    return cfg.get("data_root") or DEFAULT_DATA_ROOT


def get_platform_root() -> str:
    cfg = _load_config()
    return cfg.get("platform_root") or DEFAULT_PLATFORM_ROOT


def _save_config(cfg: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _dir_size(path: str) -> int:
    """计算目录大小（字节）。"""
    total = 0
    try:
        for root, dirs, files in os.walk(path):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _dir_file_count(path: str) -> int:
    count = 0
    try:
        for root, dirs, files in os.walk(path):
            count += len(files)
    except OSError:
        pass
    return count


def _fmt_size(n: int) -> str:
    if n >= 1 << 30:
        return f"{n / (1 << 30):.2f} GB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} MB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.0f} KB"
    return f"{n} B"


def get_locations() -> dict:
    """获取所有存储位置信息。"""
    data_root = get_data_root()
    platform_root = get_platform_root()
    projects_root = os.path.join(data_root, "projects")

    def _info(path: str, label: str) -> dict:
        exists = os.path.exists(path)
        return {
            "label": label,
            "path": path,
            "exists": exists,
            "size": _dir_size(path) if exists else 0,
            "size_text": _fmt_size(_dir_size(path)) if exists else "—",
            "file_count": _dir_file_count(path) if exists else 0,
        }

    locations = [
        _info(data_root, "项目数据根目录（解析库/台账/关系图谱/生成文件）"),
        _info(projects_root, "项目独立数据（每个项目一个子目录）"),
        _info(platform_root, "平台级规范库（国标/通用规范）"),
    ]

    # 磁盘可用空间（取数据根目录所在盘）
    disk_free = 0
    try:
        disk_free = shutil.disk_usage(data_root if os.path.exists(data_root) else _BASE_DIR).free
    except OSError:
        pass

    return {
        "ok": True,
        "data_root": data_root,
        "platform_root": platform_root,
        "default_data_root": DEFAULT_DATA_ROOT,
        "default_platform_root": DEFAULT_PLATFORM_ROOT,
        "is_custom": data_root != DEFAULT_DATA_ROOT or platform_root != DEFAULT_PLATFORM_ROOT,
        "disk_free": disk_free,
        "disk_free_text": _fmt_size(disk_free),
        "locations": locations,
    }


def _safe_move(src: str, dst: str) -> dict:
    """迁移目录内容：src 存在则移动到 dst（目录级移动）。"""
    if not os.path.exists(src):
        return {"ok": True, "moved": False, "message": "源目录不存在，无需迁移"}
    try:
        os.makedirs(dst, exist_ok=True)
        # 逐项移动，避免目录嵌套问题
        moved = 0
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            if os.path.exists(d):
                # 目标已存在同名项：合并（文件跳过，目录递归移动）
                if os.path.isdir(s) and os.path.isdir(d):
                    for sub in os.listdir(s):
                        ss = os.path.join(s, sub)
                        dd = os.path.join(d, sub)
                        if os.path.exists(dd):
                            if os.path.isdir(ss) and os.path.isdir(dd):
                                shutil.copytree(ss, dd, dirs_exist_ok=True)
                                shutil.rmtree(ss, ignore_errors=True)
                            else:
                                continue
                        else:
                            shutil.move(ss, dd)
                            moved += 1
                    continue
                continue
            shutil.move(s, d)
            moved += 1
        return {"ok": True, "moved": True, "message": f"已迁移 {moved} 项到新位置"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def set_locations(data_root: str = None, platform_root: str = None) -> dict:
    """设置存储位置（支持迁移）。"""
    cfg = _load_config()
    old_data = cfg.get("data_root") or DEFAULT_DATA_ROOT
    old_platform = cfg.get("platform_root") or DEFAULT_PLATFORM_ROOT

    new_data = data_root.strip() if data_root and data_root.strip() else old_data
    new_platform = platform_root.strip() if platform_root and platform_root.strip() else old_platform

    # 校验：不能指向自身内部
    if os.path.abspath(new_data) == os.path.abspath(_BASE_DIR):
        return {"ok": False, "error": "数据根目录不能设置为工作台安装目录本身"}
    if os.path.abspath(new_platform) == os.path.abspath(_BASE_DIR):
        return {"ok": False, "error": "平台库目录不能设置为工作台安装目录本身"}

    results = []
    # 迁移数据根目录
    if os.path.abspath(new_data) != os.path.abspath(old_data):
        results.append(_safe_move(old_data, new_data))
    # 迁移平台库
    if os.path.abspath(new_platform) != os.path.abspath(old_platform):
        results.append(_safe_move(old_platform, new_platform))

    for r in results:
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error", "迁移失败")}

    cfg["data_root"] = new_data
    cfg["platform_root"] = new_platform
    if not _save_config(cfg):
        return {"ok": False, "error": "配置保存失败，请检查磁盘权限"}

    return {
        "ok": True,
        "data_root": new_data,
        "platform_root": new_platform,
        "message": "存储位置已更新（重启服务后完全生效，路径引用已自动切换）",
        "migrations": [r.get("message", "") for r in results],
    }


def reset_locations() -> dict:
    """恢复默认存储位置（数据迁移回安装目录）。"""
    return set_locations(DEFAULT_DATA_ROOT, DEFAULT_PLATFORM_ROOT)
