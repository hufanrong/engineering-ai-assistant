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
import re
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
                    status: str = "parsed", note: str = "",
                    doc_version: str = "", doc_date: str = "",
                    mtime: str = "") -> dict:
    """登记一个文件版本。同一文件名不同 SHA256 → 多版本；同 SHA256 更新元数据。
    v0.1.138：最新版判定优先级 = CAD 标题栏/命名版本号 > 标题栏/命名日期 > 文件修改时间 > 入库时间；
    不再以入库时间为准。关键维度相同才标记 conflict 待人工确认。
    返回 {action: added|updated|duplicate, is_latest, conflict}。"""
    fname = _norm_name(file_name)
    if not fname or not sha256:
        return {"action": "error", "is_latest": False, "conflict": False}
    dv = _parse_doc_version(doc_version)
    dd = _parse_doc_date(doc_date) or _parse_name_date(fname)
    mt = _parse_ts(mtime)
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
        existing["doc_version_raw"] = doc_version
        existing["doc_version_num"] = dv
        existing["doc_date"] = doc_date
        existing["doc_date_ts"] = dd
        existing["mtime"] = mtime
        existing["mtime_ts"] = mt
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
        "doc_version_raw": doc_version,
        "doc_version_num": dv,
        "doc_date": doc_date,
        "doc_date_ts": dd,
        "mtime": mtime,
        "mtime_ts": mt,
    }
    versions.append(entry)
    conflict = _recompute_latest(fname, m)
    _save(m)
    return {"action": "added", "is_latest": entry.get("is_latest", False), "conflict": conflict}


# ---------- v0.1.138：版本/日期解析辅助 ----------
_VER_R_RE = re.compile(r"[Rr]\s*(\d+)")
_VER_REV_RE = re.compile(r"[Rr][Ee][Vv]\.?\s*([A-Za-z0-9]+)")
_VER_V_RE = re.compile(r"(?:[Vv]|第|版本)[^\d]{0,2}(\d+(?:\.\d+)?)")
_DATE_RE = re.compile(r"(\d{4})[._/-](\d{1,2})[._/-](\d{1,2})")


def _parse_doc_version(raw) -> float:
    """CAD 标题栏/文件名版本号数值化：R0→0、Rev A→0、V1.2→1.2、无→None。"""
    s = str(raw or "").strip()
    if not s:
        return None
    m = _VER_R_RE.search(s)
    if m:
        return float(m.group(1))
    m = _VER_REV_RE.search(s)
    if m:
        g = m.group(1).strip()
        if g.isdigit():
            return float(g)
        if len(g) == 1 and g.isalpha():
            return float(ord(g.upper()) - ord("A"))
    m = _VER_V_RE.search(s)
    if m:
        return float(m.group(1))
    m = re.search(r"\d+(?:\.\d+)?", s)
    if m:
        return float(m.group(0))
    return None


def _parse_doc_date(raw) -> str:
    """标题栏日期多种格式 → 归一化 ISO；无法解析返回空。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    m = _DATE_RE.search(s)
    if m:
        try:
            return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except Exception:  # noqa: BLE001
            return ""
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?", s)
    if m:
        try:
            day = int(m.group(3) or 1)
            return datetime.datetime(int(m.group(1)), int(m.group(2)), day).isoformat()
        except Exception:  # noqa: BLE001
            return ""
    return ""


def _parse_name_date(name: str) -> str:
    """文件名中的日期（如 0101 锂辉石库工艺图（2025.06.05）-R0.dwg → 2025-06-05）。"""
    m = _DATE_RE.search(name or "")
    if m:
        try:
            return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except Exception:  # noqa: BLE001
            return ""
    return ""


def extract_doc_meta(structure, path=None):
    """从解析结果提取版本判定元数据：(doc_version, doc_date, mtime_iso)。
    CAD 标题栏版本/日期优先（title_block），文件修改时间兜底。"""
    dv = dd = ""
    if isinstance(structure, dict):
        tb = (structure.get("spatial") or {}).get("title_block") or {}
        dv = str(tb.get("版本", "") or tb.get("rev", "") or tb.get("version", "") or "").strip()
        dd = str(tb.get("日期", "") or "").strip()
    mt = ""
    if path and os.path.exists(path):
        try:
            mt = datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
        except Exception:  # noqa: BLE001
            pass
    return dv, dd, mt


def _parse_ts(v) -> float:
    """ISO 时间字符串 → 数值（用于排序），失败返回 0。"""
    if not v:
        return 0.0
    try:
        dt = datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def _version_sort_key(v: dict):
    """v0.1.138 排序键：版本号 → 文档日期 → 文件修改时间 → 入库时间。"""
    return (
        1 if v.get("doc_version_num") is not None else 0,
        v.get("doc_version_num") or -1.0,
        1 if v.get("doc_date_ts") else 0,
        v.get("doc_date_ts") or 0.0,
        v.get("mtime_ts") or 0.0,
        _parse_ts(v.get("ts")) or 0.0,
    )


def _recompute_latest(fname: str, m: dict) -> bool:
    """重新计算最新版。v0.1.138 优先级：CAD 标题栏/命名版本号 > 标题栏/命名日期 > 文件修改时间 > 入库时间。
    多个版本关键维度相同 → conflict 待人工确认。返回是否有冲突。"""
    versions = m.get(fname, [])
    if len(versions) <= 1:
        for v in versions:
            v["is_latest"] = True
        return False
    # 排序：最新在前
    ordered = sorted(versions, key=_version_sort_key, reverse=True)
    for v in versions:
        v["is_latest"] = False
    top = ordered[0]
    top["is_latest"] = True
    # 冲突判定：与第一名在所有判定维度上完全相同 → 无法自动分辨
    def _key_dim(v):
        return (v.get("doc_version_num"), v.get("doc_date_ts"), v.get("mtime_ts"))
    for v in ordered[1:]:
        if _key_dim(v) == _key_dim(top) and v.get("doc_version_num") is None:
            # 都没有版本号、日期、mtime 可分辨（只有入库时间不同）→ 人工确认
            top["note"] = (top.get("note", "") + "；时间维度无法区分，待人工确认最新版").strip("；")
            v["note"] = (v.get("note", "") + "；时间维度无法区分，待人工确认最新版").strip("；")
            return True
        if _key_dim(v) == _key_dim(top) and v.get("doc_version_num") is not None:
            # 版本号相同但内容不同（同一版本多个文件）→ 按日期/mtime 已排过，仍相同则人工确认
            if v.get("doc_date_ts") == top.get("doc_date_ts") and v.get("mtime_ts") == top.get("mtime_ts"):
                top["note"] = (top.get("note", "") + "；版本/日期相同，待人工确认最新版").strip("；")
                return True
    return False


def get_versions(file_name: str) -> list:
    """获取某文件的所有版本（按最新版在前）。"""
    fname = _norm_name(file_name)
    m = _load()
    versions = m.get(fname, [])
    # v0.1.138：修复排序方向（原 reverse=True 把最新版排到最后）
    return sorted(versions,
                  key=lambda v: (0 if v.get("is_latest") else 1,
                                 -(_parse_ts(v.get("ts")) or 0.0)))


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
