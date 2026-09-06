# 繁工AI 本地解析工作台 - 设计院编号与厂家编号自动映射（v0.1.31）
# 目的：同一设备在设计院图纸（位号 P-101）和厂家资料（设备编号 EQ-2024-001 / 合同号）
#       中编号不同，自动识别映射关系，以设计院位号为主键合并；不能确认时留人工确认。
#
# 口径（用户锁定）：
#   - 以设计院为准（CAD 图纸块属性中的"位号"为主键）
#   - 能够实现相同归类，而不是报错
#   - 不能确认时，留存为人工确认
#
# 存储：
#   data/tag_alias.json          已确认映射 {primary: {aliases:[...], source, confidence, ts}}
#   data/tag_alias_pending.json  待人工确认 [{primary, alias, source, confidence, evidence, ts}]

import os
import json
import re
import datetime

from . import config

_ALIAS_FILE = os.path.join(config.DATA_DIR, "tag_alias.json")
_PENDING_FILE = os.path.join(config.DATA_DIR, "tag_alias_pending.json")

# 厂家编号字段名（CAD 块属性 / Excel 表头）
_MANUFACTURER_KEYS = ["厂家编号", "厂家位号", "设备编号", "合同号", "订货号", "出厂编号",
                       "资产编号", "物料编码", "厂家图号", "制造商编号", "供应商编号"]
# 设计院位号字段名
_DESIGN_KEYS = ["位号", "设备位号", "设计院位号", "设计位号", "TAG", "tag"]

# 厂家编号格式（比设计院位号更宽松：字母+数字，可能含日期/流水号）
_MANU_RE = re.compile(r"^[A-Za-z]{1,6}[-_]?\d{2,10}(?:[-_]\d{1,6})?$")


def _load(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return default
    return default


def _save(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _norm_tag(tag: str) -> str:
    return (tag or "").strip().upper().replace(" ", "")


def is_design_tag(tag: str) -> bool:
    """判断是否为设计院位号格式（P-101、V-201 等，严格匹配 _TAG_RE）。"""
    if not tag:
        return False
    return bool(re.fullmatch(r"[A-Z]{1,3}-\d{1,6}(?:[/-][A-Z]{0,3}\d{0,4})?", _norm_tag(tag)))


def is_manufacturer_tag(tag: str) -> bool:
    """判断是否为厂家编号格式。特征：含4位年份段（如2024）、多段数字（EQ-2024-001）、
    或无连字符的长编号（PO12345）。设计院位号（P-101、V-201A）排除。"""
    if not tag:
        return False
    t = _norm_tag(tag)
    if is_design_tag(t) and not re.search(r"\d{4}", t):
        # 严格设计院格式且无4位年份段 → 不是厂家编号
        return False
    # 厂家特征：4位年份段 或 2+段数字 或 无连字符长编号
    if re.search(r"\d{4}", t):
        return True
    parts = re.split(r"[-_]", t)
    digit_parts = [p for p in parts if p and p.isdigit()]
    if len(digit_parts) >= 2:
        return True
    if "-" not in t and "_" not in t and re.fullmatch(r"[A-Z]{1,4}\d{4,10}", t):
        return True
    return bool(_MANU_RE.fullmatch(t)) and not is_design_tag(t)


def detect_from_cad_block(attrs: dict) -> dict:
    """从 CAD 块属性中识别设计院位号↔厂家编号映射。
    attrs: {属性名: 值}，如 {"位号": "P-101", "厂家编号": "EQ-2024-001"}
    返回 {"primary": "P-101", "alias": "EQ-2024-001"} 或 {}。"""
    if not attrs:
        return {}
    primary = ""
    alias = ""
    for k, v in attrs.items():
        k_clean = str(k or "").strip()
        v_clean = str(v or "").strip()
        if not v_clean:
            continue
        if k_clean in _DESIGN_KEYS and not primary and is_design_tag(v_clean):
            primary = _norm_tag(v_clean)
        elif k_clean in _MANUFACTURER_KEYS and not alias:
            alias = v_clean.strip()
    if primary and alias and _norm_tag(alias) != primary:
        return {"primary": primary, "alias": alias}
    return {}


def detect_from_excel_row(row: dict, header: list = None) -> dict:
    """从 Excel 台账行中识别映射。row 为 dict {表头: 值} 或 list（配合 header）。"""
    if not row:
        return {}
    if isinstance(row, dict):
        items = row.items()
    else:
        if not header:
            return {}
        items = [(header[i], row[i]) for i in range(min(len(header), len(row)))]
    primary = ""
    alias = ""
    for k, v in items:
        k_clean = str(k or "").strip()
        v_clean = str(v or "").strip()
        if not v_clean:
            continue
        if k_clean in _DESIGN_KEYS and not primary and is_design_tag(v_clean):
            primary = _norm_tag(v_clean)
        elif k_clean in _MANUFACTURER_KEYS and not alias:
            alias = v_clean.strip()
    if primary and alias and _norm_tag(alias) != primary:
        return {"primary": primary, "alias": alias}
    return {}


def add_alias(primary: str, alias: str, source: str = "auto",
              confidence: float = 0.5, evidence: str = "") -> bool:
    """登记映射。高置信（≥0.7）直接确认；低置信进待人工确认。
    返回 True=已确认写入，False=进待确认或重复。"""
    primary = _norm_tag(primary)
    alias = (alias or "").strip()
    if not primary or not alias or _norm_tag(alias) == primary:
        return False
    confirmed = _load(_ALIAS_FILE, {})
    # 已存在则跳过
    if primary in confirmed and alias in confirmed[primary].get("aliases", []):
        return False
    # 检查 alias 是否已属于其他 primary
    for p, info in confirmed.items():
        if alias in info.get("aliases", []):
            return False  # 已映射到其他设备，不重复
    if confidence >= 0.7:
        info = confirmed.setdefault(primary, {"aliases": [], "source": source,
                                                "confidence": confidence, "ts": ""})
        if alias not in info["aliases"]:
            info["aliases"].append(alias)
        info["source"] = source
        info["confidence"] = max(info.get("confidence", 0), confidence)
        info["ts"] = datetime.datetime.now().isoformat()
        _save(_ALIAS_FILE, confirmed)
        return True
    else:
        # 低置信 → 待人工确认
        pending = _load(_PENDING_FILE, [])
        if not any(p["primary"] == primary and p["alias"] == alias for p in pending):
            pending.append({"primary": primary, "alias": alias, "source": source,
                            "confidence": confidence, "evidence": evidence,
                            "ts": datetime.datetime.now().isoformat()})
            _save(_PENDING_FILE, pending)
        return False


def confirm(primary: str, alias: str) -> bool:
    """人工确认映射：从待确认移到已确认。"""
    primary = _norm_tag(primary)
    pending = _load(_PENDING_FILE, [])
    pending = [p for p in pending if not (p["primary"] == primary and p["alias"] == alias)]
    _save(_PENDING_FILE, pending)
    confirmed = _load(_ALIAS_FILE, {})
    info = confirmed.setdefault(primary, {"aliases": [], "source": "manual",
                                            "confidence": 1.0, "ts": ""})
    if alias not in info["aliases"]:
        info["aliases"].append(alias)
    info["source"] = "manual"
    info["confidence"] = 1.0
    info["ts"] = datetime.datetime.now().isoformat()
    _save(_ALIAS_FILE, confirmed)
    return True


def reject(primary: str, alias: str) -> bool:
    """人工拒绝映射：从待确认移除，不再自动建议。"""
    primary = _norm_tag(primary)
    pending = _load(_PENDING_FILE, [])
    pending = [p for p in pending if not (p["primary"] == primary and p["alias"] == alias)]
    _save(_PENDING_FILE, pending)
    return True


def get_primary(tag: str) -> str:
    """解析别名→主位号。如果 tag 本身是主位号或无映射，返回原 tag。"""
    t = _norm_tag(tag)
    confirmed = _load(_ALIAS_FILE, {})
    if t in confirmed:
        return t  # 本身就是主位号
    for primary, info in confirmed.items():
        if t in [_norm_tag(a) for a in info.get("aliases", [])]:
            return primary
    return tag


def list_confirmed() -> list:
    confirmed = _load(_ALIAS_FILE, {})
    return [{"primary": k, **v} for k, v in confirmed.items()]


def list_pending() -> list:
    return _load(_PENDING_FILE, [])


def stats() -> dict:
    confirmed = list_confirmed()
    pending = list_pending()
    total_aliases = sum(len(c.get("aliases", [])) for c in confirmed)
    return {"confirmed_primary": len(confirmed), "total_aliases": total_aliases,
            "pending": len(pending)}
