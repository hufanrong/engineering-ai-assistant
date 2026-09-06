# 繁工AI 本地解析工作台 - 文件版本管理与冲突合并（v0.1.32）
# 目的：多电脑并库时，同一文件名不同内容（多版本）自动建立版本对照表，
#       按时间戳以最新版为准；无法判断时留人工确认。重复文件（同 SHA256）自动去重。
#
# 口径（用户锁定）：
#   - 资料可能有很多重复，自动去重
#   - 多个版本以最新版为准
#   - 冲突时人工确认
#
# 存储：data/version_map.json
#   {file_name: [{sha256, status, ts, source_node, size, is_latest, note}]}

import os
import json
import datetime

from . import config

_VERSION_FILE = os.path.join(config.DATA_DIR, "version_map.json")


def _load() -> dict:
    if os.path.exists(_VERSION_FILE):
        try:
            with open(_VERSION_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save(m: dict):
    os.makedirs(os.path.dirname(_VERSION_FILE), exist_ok=True)
    with open(_VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def _norm_name(name: str) -> str:
    return os.path.basename(name or "").strip()


def record_version(file_name: str, sha256: str, ts: str = "",
                    source_node: str = "", size: int = 0,
                    status: str = "parsed", note: str = "") -> dict:
    """登记一个文件版本。同一文件名不同 SHA256 → 多版本；同 SHA256 更新元数据。
    自动按 ts 判断最新版；ts 缺失或相同 → 标记 conflict 待人工确认。
    返回 {action: added|updated|duplicate, is_latest, conflict}。"""
    fname = _norm_name(file_name)
    if not fname or not sha256:
        return {"action": "error", "is_latest": False, "conflict": False}
    m = _load()
    versions = m.setdefault(fname, [])
    existing = next((v for v in versions if v["sha256"] == sha256), None)
    if existing:
        # 同 SHA256 = 同一文件，更新元数据
        if ts:
            existing["ts"] = ts
        if source_node:
            existing["source_node"] = source_node
        if size:
            existing["size"] = size
        existing["status"] = status
        if note:
            existing["note"] = note
        _save(m)
        _recompute_latest(fname, m)
        return {"action": "updated", "is_latest": existing.get("is_latest", False), "conflict": False}

    # 新版本
    entry = {
        "sha256": sha256,
        "status": status,
        "ts": ts or datetime.datetime.now().isoformat(),
        "source_node": source_node or config.NODE_NAME,
        "size": size,
        "is_latest": False,
        "note": note,
    }
    versions.append(entry)
    conflict = _recompute_latest(fname, m)
    _save(m)
    return {"action": "added", "is_latest": entry.get("is_latest", False), "conflict": conflict}


def _recompute_latest(fname: str, m: dict) -> bool:
    """重新计算最新版。按 ts 降序，ts 相同或缺失 → conflict。返回是否有冲突。"""
    versions = m.get(fname, [])
    if len(versions) <= 1:
        for v in versions:
            v["is_latest"] = True
        return False
    # 按 ts 排序（有 ts 的优先）
    with_ts = [v for v in versions if v.get("ts")]
    without_ts = [v for v in versions if not v.get("ts")]
    if not with_ts:
        # 全部无 ts → 冲突，第一个暂标 latest
        for v in versions:
            v["is_latest"] = False
        versions[0]["is_latest"] = True
        versions[0]["note"] = (versions[0].get("note", "") + "；无时间戳，待人工确认最新版").strip("；")
        return True
    with_ts.sort(key=lambda v: v["ts"], reverse=True)
    latest_ts = with_ts[0]["ts"]
    # 检查是否有多个版本 ts 相同
    same_ts = [v for v in with_ts if v["ts"] == latest_ts]
    conflict = len(same_ts) > 1
    for v in versions:
        v["is_latest"] = False
    if conflict:
        same_ts[0]["is_latest"] = True
        same_ts[0]["note"] = (same_ts[0].get("note", "") + "；时间戳相同，待人工确认最新版").strip("；")
    else:
        with_ts[0]["is_latest"] = True
    return conflict


def get_versions(file_name: str) -> list:
    """获取某文件的所有版本（按最新版在前）。"""
    fname = _norm_name(file_name)
    m = _load()
    versions = m.get(fname, [])
    return sorted(versions, key=lambda v: (not v.get("is_latest", False), v.get("ts", "")), reverse=True)


def list_multi_version() -> list:
    """列出所有有多版本的文件（含版本数和最新版）。"""
    m = _load()
    out = []
    for fname, versions in m.items():
        if len(versions) > 1:
            latest = next((v for v in versions if v.get("is_latest")), versions[0])
            out.append({
                "file_name": fname,
                "version_count": len(versions),
                "latest_sha256": latest["sha256"],
                "latest_ts": latest.get("ts", ""),
                "latest_source": latest.get("source_node", ""),
                "conflict": any("待人工确认" in v.get("note", "") for v in versions),
                "versions": sorted(versions, key=lambda v: not v.get("is_latest", False)),
            })
    out.sort(key=lambda x: x["file_name"])
    return out


def list_conflicts() -> list:
    """列出待人工确认的版本冲突。"""
    return [item for item in list_multi_version() if item["conflict"]]


def set_latest(file_name: str, sha256: str) -> bool:
    """人工指定某版本为最新版（清除冲突标记）。"""
    fname = _norm_name(file_name)
    m = _load()
    versions = m.get(fname, [])
    target = next((v for v in versions if v["sha256"] == sha256), None)
    if not target:
        return False
    for v in versions:
        v["is_latest"] = False
        if "待人工确认" in v.get("note", ""):
            v["note"] = v["note"].replace("；待人工确认最新版", "").replace("待人工确认最新版", "").strip("；")
    target["is_latest"] = True
    target["note"] = (target.get("note", "") + "；人工指定最新版").strip("；")
    _save(m)
    return True


def get_latest_sha(file_name: str) -> str:
    """获取某文件最新版的 SHA256。"""
    versions = get_versions(file_name)
    if not versions:
        return ""
    latest = next((v for v in versions if v.get("is_latest")), versions[0])
    return latest["sha256"]


def stats() -> dict:
    m = _load()
    total_files = len(m)
    multi = sum(1 for v in m.values() if len(v) > 1)
    total_versions = sum(len(v) for v in m.values())
    conflicts = len(list_conflicts())
    return {"total_files": total_files, "total_versions": total_versions,
            "multi_version_files": multi, "conflicts": conflicts}
