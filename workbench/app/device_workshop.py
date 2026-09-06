# 繁工AI 本地解析工作台 - 设备级车间归属（v0.1.29）
# 目的：设备箱单/台账跨车间（同一厂家混合装箱）时，按台账行"车间"列或位号前缀
#       把每台设备分到具体车间；人工指定最高优先，持久化到 data/device_workshop.json。
#
# 与 v0.1.27 workshop_assign（文件级车间）的区别：
#   - workshop_assign：一个文件归到哪个车间（CAD标题栏/文件名/正文）
#   - device_workshop：一台设备（位号）归到哪个车间（台账行/位号前缀/人工）
#   跨车间箱单文件本身归"未归车间"，但其中每台设备有明确车间归属。

import os
import json
import re
import datetime

from . import config

_STORE_PATH = os.path.join(config.DATA_DIR, "device_workshop.json")

# 位号前缀→车间的可配置映射（如 P-1xx→1号车间）；默认空，由人工/台账积累
_TAG_PREFIX_MAP = {}


def _load() -> dict:
    if os.path.exists(_STORE_PATH):
        try:
            with open(_STORE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save(m: dict):
    os.makedirs(os.path.dirname(_STORE_PATH), exist_ok=True)
    with open(_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def _norm_workshop(name: str) -> str:
    """'1车间' / '1#车间' / '一号车间' / '1号车间' → '1号车间'。"""
    if not name:
        return ""
    s = str(name).strip()
    cn = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
          "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
    for k, v in cn.items():
        s = s.replace(k + "号", v + "号").replace(k, v)
    m = re.match(r"^(\d+)\s*[#号]?\s*(车间|装置|区域|工区)?$", s)
    if m:
        return f"{m.group(1)}号车间"
    # 已含"车间"但数字在中间
    m2 = re.search(r"(\d+)\s*号?\s*车间", s)
    if m2:
        return f"{m2.group(1)}号车间"
    return s


def infer_workshop_from_tag(tag: str) -> str:
    """从位号推断车间：P-101→1号车间（百位数字段），P-2101→2号车间。
    仅当位号格式为 字母-数字 且数字≥3位时推断，否则返回空。"""
    if not tag:
        return ""
    m = re.match(r"^[A-Za-z]+-?(\d{3,})$", tag.strip())
    if m:
        num = m.group(1)
        # 取百位（3位取第1位，4位取前2位中第1位）
        if len(num) == 3:
            return f"{num[0]}号车间"
        if len(num) == 4:
            return f"{num[0]}号车间"
    return ""


def assign_device(tag: str, workshop: str, source: str = "auto",
                  confidence: float = 0.5, file_sha: str = "", force: bool = False) -> bool:
    """登记设备→车间。人工登记(source=manual)不被自动覆盖；force=True 才覆盖。
    返回是否写入（True=写入，False=已有更高优先登记被跳过）。"""
    if not tag or not workshop:
        return False
    tag = tag.strip()
    workshop = _norm_workshop(workshop)
    m = _load()
    existing = m.get(tag)
    # 人工登记最高优先，不被自动覆盖
    if existing and existing.get("source") == "manual" and not force:
        return False
    # 同来源不覆盖（避免重复写入）
    if existing and existing.get("source") == source and existing.get("workshop") == workshop and not force:
        return False
    m[tag] = {
        "workshop": workshop,
        "source": source,           # manual / excel_row / tag_infer / cad / filename
        "confidence": round(float(confidence), 2),
        "file_sha": file_sha or "",
        "ts": datetime.datetime.now().isoformat(),
    }
    _save(m)
    return True


def manual_assign(tag: str, workshop: str) -> bool:
    """人工指定设备车间（最高优先，覆盖任何自动登记）。"""
    return assign_device(tag, workshop, source="manual", confidence=1.0, force=True)


def get_workshop(tag: str) -> str:
    """获取设备登记车间（人工优先）。无登记返回空字符串。"""
    m = _load()
    rec = m.get(tag.strip())
    return rec["workshop"] if rec else ""


def get_record(tag: str) -> dict:
    """获取设备登记完整记录。"""
    return _load().get(tag.strip(), {})


def list_devices() -> list:
    """列出所有设备车间登记，按车间分组排序。"""
    m = _load()
    items = [{"tag": k, **v} for k, v in m.items()]
    items.sort(key=lambda x: (x.get("workshop", ""), x["tag"]))
    return items


def list_by_workshop() -> dict:
    """按车间分组：{车间: [设备记录], 未归车间: [设备记录]}。"""
    groups = {}
    for rec in list_devices():
        ws = rec.get("workshop") or "未归车间"
        groups.setdefault(ws, []).append(rec)
    return groups


def rebuild_from_excel(docs: dict) -> int:
    """从 relations 的 docs 中提取 excel_row 设备的 workshop_hint，批量登记。
    docs: {sha: {file_name, equipments:[{tag, where, workshop_hint}], ...}}
    返回新登记数量。"""
    n = 0
    for sha, d in docs.items():
        for e in d.get("equipments", []):
            if e.get("where") != "excel_row":
                continue
            tag = e.get("tag", "").strip()
            hint = e.get("workshop_hint", "")
            if not tag or not hint:
                continue
            if assign_device(tag, hint, source="excel_row", confidence=0.8, file_sha=sha):
                n += 1
    # 位号推断补充（仅对未登记的设备）
    for sha, d in docs.items():
        for e in d.get("equipments", []):
            tag = e.get("tag", "").strip()
            if not tag or get_workshop(tag):
                continue
            inferred = infer_workshop_from_tag(tag)
            if inferred:
                if assign_device(tag, inferred, source="tag_infer", confidence=0.4, file_sha=sha):
                    n += 1
    return n


def stats() -> dict:
    """统计：总设备数、各车间设备数、人工/自动来源分布。"""
    items = list_devices()
    by_ws = {}
    by_src = {}
    for it in items:
        ws = it.get("workshop", "未归车间")
        by_ws[ws] = by_ws.get(ws, 0) + 1
        src = it.get("source", "unknown")
        by_src[src] = by_src.get(src, 0) + 1
    return {"total": len(items), "by_workshop": by_ws, "by_source": by_src}
