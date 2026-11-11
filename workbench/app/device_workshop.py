# 繁工AI 本地解析工作台 - 设备级车间归属（v0.1.29）
# 目的：设备箱单/台账跨车间（同一厂家混合装箱）时，按台账行"车间"列或位号前缀
#       把每台设备分到具体车间；人工指定最高优先，持久化到 data/device_workshop.json。
#
# 与 v0.1.27 workshop_assign（文件级车间）的区别：
#   - workshop_assign：一个文件归到哪个车间（CAD标题栏/文件名/正文）
#   - device_workshop：一台设备（位号）归到哪个车间（台账行/位号前缀/人工）
#   跨车间箱单文件本身归"未归车间"，但其中每台设备有明确车间归属。

from . import atomic_io as _atomic_io
import os
import json
import re
import datetime

from . import config

# v0.1.167：登记表改为按项目定位 —— 原来是全局 data/device_workshop.json，
# 换项目后上一项目的设备车间登记仍然生效并覆盖新项目同名位号（如 T-301 被
# 上一项目推成 3号车间，而本项目台账明确写的是配电室），属于跨项目串味。
def _store_path(data_dir=None) -> str:
    """登记表落点：显式 data_dir > 隔离目录 > 当前项目 > config.DATA_DIR。

    v0.1.238：加上前两级。没有它们时，凡是「传 data_dir 重建关系图谱」的场景
    （离线脚本、临时目录重解析、隔离测试）都会把登记写进当前项目/全局目录 ——
    与 workshop_assign._dir_for 同一条教训（EE/FF：参数有，但没接力）。
    """
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "device_workshop.json")
    if _ISOLATED_DIR:
        os.makedirs(_ISOLATED_DIR, exist_ok=True)
        return os.path.join(_ISOLATED_DIR, "device_workshop.json")
    try:
        from . import project_manager as _pm
        return os.path.join(_pm.get_project_data_dir(), "device_workshop.json")
    except Exception:  # noqa: BLE001
        return os.path.join(config.DATA_DIR, "device_workshop.json")


_STORE_PATH = os.path.join(config.DATA_DIR, "device_workshop.json")  # 兼容旧引用（读写请走 _store_path()）

# 位号前缀→车间的可配置映射（如 P-1xx→1号车间）；默认空，由人工/台账积累
_TAG_PREFIX_MAP = {}

# v0.1.238：与 workshop_assign._ISOLATED_DIR 同一条教训 —— 隔离必须放在
# **目录解析函数内部**，不能靠调用方「临时改全局再 finally 还原」，
# 因为中间任何一次内部调用都会把它重置回去。
_ISOLATED_DIR = None


def _load(data_dir=None) -> dict:
    p = _store_path(data_dir)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save(m: dict, data_dir=None):
    p = _store_path(data_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    _atomic_io.write_json(p, m, indent=2)


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
    仅当位号格式为 字母-数字 且数字≥3位时推断，否则返回空。

    v0.1.238：**只保留函数本身用于兼容，调用处已默认不再用它**。
    实测（2026-11-12）台账只有「粗碎站 / 磨浮车间」两个真车间时，
    这个函数把 P-301 推成「3号车间」、C-401 推成「4号车间」，
    而同一台设备在 graph["devices"] 里是「1号车间」、在 layout 里是「3号车间」
    —— 既造出了用户明令禁止的假车间名，又是「同一件事两个答案」。
    """
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
                  confidence: float = 0.5, file_sha: str = "", force: bool = False,
                  data_dir=None) -> bool:
    """登记设备→车间。人工登记(source=manual)不被自动覆盖；force=True 才覆盖。
    返回是否写入（True=写入，False=已有更高优先登记被跳过）。

    v0.1.238：**在出口加台账白名单**（用户 2026-11-11「不要在生成其他乱七八糟的
    车间名字」）。实测本条路径原本完全不经过闸门：
      · rebind 台账只有「粗碎站/磨浮车间」两个真车间；
      · 正文正则把「1号车间」当提示、位号前缀把 P-301 推成 3 号车间、
        C-401 推成 4 号车间，全部写进 device_workshop.json；
      · 同一台设备在 graph["devices"] 里叫「1号车间」、在 layout 里叫「3号车间」。
    闸门只拦自动来源：人工登记（source=manual）是用户显式点头，永远放行；
    台账为空时退回旧逻辑（不能因为没台账就把一切判空）。
    """
    if not tag or not workshop:
        return False
    tag = tag.strip()
    workshop = _norm_workshop(workshop)
    if source != "manual":
        try:
            from . import workshop_assign as _wa
            # 台账非空 = 台账是唯一权威清单；台账为空 = 不裁剪（旧逻辑）
            if _wa.ledger_workshop_names(data_dir) and not _wa.is_workshop_allowed(workshop, data_dir):
                return False
        except Exception:  # noqa: BLE001
            pass
    m = _load(data_dir)
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
    _save(m, data_dir)
    return True


def manual_assign(tag: str, workshop: str, data_dir=None) -> bool:
    """人工指定设备车间（最高优先，覆盖任何自动登记）。"""
    return assign_device(tag, workshop, source="manual", confidence=1.0, force=True,
                         data_dir=data_dir)


def get_workshop(tag: str, data_dir=None) -> str:
    """获取设备登记车间（人工优先）。无登记返回空字符串。"""
    m = _load(data_dir)
    rec = m.get(tag.strip())
    return rec["workshop"] if rec else ""


def get_record(tag: str, data_dir=None) -> dict:
    """获取设备登记完整记录。"""
    return _load(data_dir).get(tag.strip(), {})


def list_devices(data_dir=None) -> list:
    """列出所有设备车间登记，按车间分组排序。"""
    m = _load(data_dir)
    items = [{"tag": k, **v} for k, v in m.items()]
    items.sort(key=lambda x: (x.get("workshop", ""), x["tag"]))
    return items


def list_by_workshop(data_dir=None) -> dict:
    """按车间分组：{车间: [设备记录], 未归车间: [设备记录]}。"""
    groups = {}
    for rec in list_devices(data_dir):
        ws = rec.get("workshop") or "未归车间"
        groups.setdefault(ws, []).append(rec)
    return groups


def rebuild_from_excel(docs: dict, data_dir=None) -> int:
    """从已解析台账重建设备→车间登记（台账行「车间」列优先，位号前缀兜底）。

    docs 形状：{sha: {file_name, workshop, equipments? ...}}。
    v0.1.177：**接受两种入参**——带 equipments 的（build_relations 产物），
    以及**裸解析缓存**（rebuild 接口从 parsed_cache 直接读的那些）。
    实测事故：接口把缓存文件原样塞进来，缓存里没有 "equipments" 键，
    `d.get("equipments", [])` 恒为空 → 195 行台账、车间列齐全，
    device_workshop 却是 0，按车间预填 devices=0、整卷取不到设备。
    现在没有 equipments 时用 relations 的抽取器现场还原，形状问题由本模块自己兜住。
    """
    try:
        from . import relations as _rel
        _extract = _rel._equipment_from_cache
    except Exception:  # noqa: BLE001
        _extract = None

    n = 0
    for sha, d in (docs or {}).items():
        if not isinstance(d, dict):
            continue
        eqs = d.get("equipments")
        if eqs is None and _extract is not None:
            try:
                eqs = _extract(d)
            except Exception:  # noqa: BLE001
                eqs = []
        for e in (eqs or []):
            if not isinstance(e, dict) or e.get("where") != "excel_row":
                continue
            tag = (e.get("tag") or "").strip()
            hint = e.get("workshop_hint") or ""
            if not tag or not hint:
                continue
            if assign_device(tag, hint, source="excel_row", confidence=0.8, file_sha=sha,
                             data_dir=data_dir):
                n += 1
    # 位号推断补充（仅对未登记的设备）
    for sha, d in (docs or {}).items():
        if not isinstance(d, dict):
            continue
        eqs = d.get("equipments")
        if eqs is None and _extract is not None:
            try:
                eqs = _extract(d)
            except Exception:  # noqa: BLE001
                eqs = []
        for e in (eqs or []):
            if not isinstance(e, dict):
                continue
            tag = (e.get("tag") or "").strip()
            if not tag or get_workshop(tag, data_dir):
                continue
            inferred = infer_workshop_from_tag(tag)
            if inferred:
                if assign_device(tag, inferred, source="tag_infer", confidence=0.4, file_sha=sha,
                                 data_dir=data_dir):
                    n += 1
    return n


def stats(data_dir=None) -> dict:
    """统计：总设备数、各车间设备数、人工/自动来源分布。"""
    items = list_devices(data_dir)
    by_ws = {}
    by_src = {}
    for it in items:
        ws = it.get("workshop", "未归车间")
        by_ws[ws] = by_ws.get(ws, 0) + 1
        src = it.get("source", "unknown")
        by_src[src] = by_src.get(src, 0) + 1
    return {"total": len(items), "by_workshop": by_ws, "by_source": by_src}
