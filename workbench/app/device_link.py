# 繁工AI 本地解析工作台 - 文件 → 设备身份关联（v0.1.248 / D36）
#
# 用户原始需求（2026-11-12）：
#   「当输入文件夹时,如果文件夹以车间命名,或者设备命名时：该文件夹内资料极有可能
#     全部和该设备或车间有关系,可以归在一起,或者建立联系」
#
# v0.1.248 之前的状态：
#   · 文件夹名 → 车间：已实现（workshop_assign.detect_workshop 的 file_path 通道，
#     置信度 0.85，目录段优先于文件名）。
#   · 文件夹名 → 设备：**只有查询入口、没有接线**。equipment_merge.find_by_identity()
#     能按身份键反查设备，但扫描路径、上传路径都不调用它 —— 于是「某台设备的资料
#     单独放在一个以设备命名的文件夹里」这件事，平台永远建立不了联系。
#     「只有入口没有接线」是本项目吃过大亏的一类假完成（见 D18：接口存在≠接口能用、
#     后端有能力但前端没入口）。
#
# 本模块负责：
#   1. 从项目设备台账（index.json 的 devices）读出设备身份集合；
#   2. 用**目录段**（优先）或**文件名**去匹配台账里的设备名 / 位号；
#   3. 唯一命中 → 自动建立「文件 ↔ 设备身份」联系；
#      多身份命中 → **不自动关联**，进待人工确认
#      （对齐用户决策「同名多行再按型号区分，仍冲突则进人工确认」）；
#   4. 落盘到 <项目目录>/device_links.json。
#
# **绝不建车间**：本模块不产生任何车间名。车间由 workshop_assign 负责，且用户
# 2026-11-11 明确要求「所有新建立的车间必须交由人工审批」。设备名不是车间名。
#
# 平台通则（与 app/workshop_assign.py 顶部四条一致，照抄照用）：
#   ① 任何落盘点必须跟随 data_dir，禁止「参数收到了但没接力」；
#   ② 落点解析收敛到单一函数，不允许同一个概念两套解析；
#   ③ 读路径不得依赖写操作留下的全局状态；
#   ④ 禁止「临时改全局再 finally 还原」式传参。

from . import atomic_io as _atomic_io
from . import config
import datetime
import json
import os
import re
import threading
import unicodedata

_LINK_FILE = "device_links.json"
_LOCK = threading.RLock()

# 置信度与车间通道对齐：目录段 0.85（用户按设备分文件夹是最强信号），
# 文件名 0.75（次之）。两处口径必须一致，否则又是一条「同一件事两个答案」。
_CONF_DIR = 0.85
_CONF_FILENAME = 0.75


# ---------------------------------------------------------------- 落点解析
def _data_dir(data_dir=None) -> str:
    """落点解析：显式 data_dir > 当前项目目录 > config.DATA_DIR。

    单一入口，全模块只此一处解析目录 —— 通则②。
    """
    if data_dir:
        return data_dir
    try:
        from . import project_manager as _pm
        cur = _pm.get_current_project()
        if cur:
            pdir = _pm.get_project_data_dir(cur["id"])
            if pdir:
                return pdir
    except Exception:  # noqa: BLE001
        pass
    return config.DATA_DIR


def _links_path(data_dir=None) -> str:
    return os.path.join(_data_dir(data_dir), _LINK_FILE)


def _tomb_blocked(data_dir) -> bool:
    """落点是否已被删除（项目墓碑命中）。永不抛异常。

    v0.1.247（D35）：项目删掉后被后台写盘「复活」。本模块是写盘方之一，
    必须先问墓碑。
    """
    try:
        return bool(data_dir) and _tombstone().is_deleted(data_dir)
    except Exception:  # noqa: BLE001
        return False


def _tombstone():
    from . import tombstone as _t
    return _t


def _load(data_dir=None) -> dict:
    p = _links_path(data_dir)
    if not os.path.isfile(p):
        return {"links": {}, "pending": {}, "rejected": {}}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:  # noqa: BLE001
        return {"links": {}, "pending": {}, "rejected": {}}
    if not isinstance(d, dict):
        return {"links": {}, "pending": {}, "rejected": {}}
    for k in ("links", "pending", "rejected"):
        if not isinstance(d.get(k), dict):
            d[k] = {}
    return d


def _save(store: dict, data_dir=None) -> bool:
    """落盘。落点被墓碑挡住时**不写、不建目录**（D35）。"""
    p = _links_path(data_dir)
    d = os.path.dirname(p)
    if _tomb_blocked(d):
        return False
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    _atomic_io.write_json(p, store, indent=2)
    return True


# ---------------------------------------------------------------- 文本规范化
def _norm(s) -> str:
    """NFKC + 全角空格归一 + 空白折叠。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = s.replace("\u3000", " ")
    return " ".join(s.split()).strip()


def _k(s) -> str:
    """比对键：去掉所有分隔符与空白，转小写。

    「P-301」与「p301」、「1号 泵」与「1号泵」要能对上，否则同一台设备会因为
    目录命名习惯不同而认不出来（这正是「同一件事两个答案」的另一种形态）。
    """
    s = _norm(s)
    return re.sub(r"[\s\-_/\\.()（）\[\]{}#＃、,，:：|]+", "", s).lower()


# ---------------------------------------------------------------- 台账读取
def ledger_devices(data_dir=None) -> list:
    """读本项目设备台账（index.json 的 devices）→ 设备身份集合。

    返回 [{tag, name, model, workshop, identity_key}]。
    **名称为空的行不参与匹配** —— 与 equipment_merge.identity_key() 一致：
    没有名字就认不出任何设备，空名匹配会凭空断言「这些是同一台」。
    """
    from . import equipment_merge as _em
    ddir = _data_dir(data_dir)
    idx_path = os.path.join(ddir, "index.json")
    if not os.path.isfile(idx_path):
        return []
    try:
        with open(idx_path, encoding="utf-8") as f:
            idx = json.load(f)
    except Exception:  # noqa: BLE001
        return []
    devs = idx.get("devices") or {}
    if not isinstance(devs, dict):
        return []
    out = []
    for tag, rec in devs.items():
        if not isinstance(rec, dict):
            continue
        name = _norm(rec.get("name"))
        if not name:
            continue
        model = _norm(rec.get("model"))
        workshop = _norm(rec.get("workshop"))
        ikey = rec.get("identity_key") or _em.identity_key(name, workshop, model)
        if not ikey:
            continue
        out.append({
            "tag": str(tag),
            "name": name,
            "model": model,
            "workshop": workshop,
            "identity_key": ikey,
            "is_synthetic": str(tag).startswith("_no_tag_"),
        })
    return out


# ---------------------------------------------------------------- 匹配
def _match_score(sig_key: str, dev: dict):
    """信号与一台设备的匹配分。0 = 不匹配。

    满分 30 = 规范化后完全相等；20 = 包含（名字/位号 ≥3 字符）。
    2 字符的名字只允许完全相等（"泵""机"这类词包含匹配会大量误命中）。
    """
    if not sig_key:
        return 0
    best = 0
    name_key = _k(dev.get("name"))
    if name_key:
        if sig_key == name_key:
            best = max(best, 30)
        elif len(name_key) >= 3 and name_key in sig_key:
            best = max(best, 20)
    tag = str(dev.get("tag") or "")
    if tag and not dev.get("is_synthetic"):
        tag_key = _k(tag)
        if tag_key:
            if sig_key == tag_key:
                best = max(best, 30)
            elif len(tag_key) >= 3 and tag_key in sig_key:
                best = max(best, 20)
    return best


def _best_candidates(sig_key: str, devices: list) -> list:
    """取最高分的那一批设备（并列都保留 —— 并列正是要人工确认的情形）。"""
    scored = []
    for d in devices:
        sc = _match_score(sig_key, d)
        if sc:
            scored.append((sc, d))
    if not scored:
        return []
    top = max(s for s, _ in scored)
    return [d for s, d in scored if s == top]


def _path_segments(file_path: str) -> list:
    """把路径拆成目录段（不含文件名），深到浅。"""
    segs = [s.strip() for s in re.split(r"[\\/]+", file_path or "")]
    segs = [s for s in segs
            if s and s not in (".", "..") and not re.match(r"^[A-Za-z]:$", s)]
    if segs and re.search(r"\.[A-Za-z0-9]{1,5}$", segs[-1]):
        segs = segs[:-1]
    return segs


def _signals(file_name: str, file_path: str) -> list:
    """信号序列：目录段（深→浅，最多 4 段）→ 文件名（去扩展名）。

    顺序即优先级：**目录段优先于文件名**，与 workshop_assign 的通道顺序一致。
    """
    out = []
    segs = _path_segments(file_path)
    for seg in reversed(segs[-4:]):
        if seg:
            out.append(("dir", seg))
    if file_name:
        stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", str(file_name))
        if stem:
            out.append(("filename", stem))
    return out


def _workshop_context(file_name: str, file_path: str, data_dir=None) -> list:
    """路径/文件名里出现的**台账或已确认车间名**，用来给多身份命中消歧。

    例：`粗碎站/金属探测器/xx.pdf` —— 名字命中多个车间里的同名设备时，
    路径里的车间能把它收敛到一个。这不新建车间，只是读取既有事实。
    """
    try:
        from . import workshop_assign as _wa
        names = set(_wa.ledger_workshop_names(data_dir) or set())
        for r in _wa.list_registry(data_dir) or []:
            if isinstance(r, dict) and r.get("name"):
                names.add(r["name"])
    except Exception:  # noqa: BLE001
        names = set()
    hay = f"{file_path or ''} {file_name or ''}"
    return [w for w in names if w and w in hay]


def match_file(file_name: str = "", file_path: str = "", data_dir=None) -> dict:
    """把一个文件（按路径/文件名）匹配到台账里的设备身份。

    返回：
      {"matched": bool, "ambiguous": bool, "identity_key": str, "devices": [...],
       "candidates": [...], "source": "dir"|"filename", "confidence": float}
    """
    devices = ledger_devices(data_dir)
    if not devices:
        return {"matched": False, "reason": "no_ledger"}
    ctx = _workshop_context(file_name, file_path, data_dir)
    for source, text in _signals(file_name, file_path):
        sig = _k(text)
        if not sig:
            continue
        cands = _best_candidates(sig, devices)
        if not cands:
            continue
        groups = {}
        for d in cands:
            groups.setdefault(d["identity_key"], []).append(d)
        conf = _CONF_DIR if source == "dir" else _CONF_FILENAME
        if len(groups) == 1:
            key = next(iter(groups))
            return {"matched": True, "ambiguous": False, "identity_key": key,
                    "devices": groups[key], "source": source, "confidence": conf,
                    "workshop_context": ctx}
        # 多身份命中 → 尝试用路径里的车间消歧
        if ctx:
            narrowed = {k: v for k, v in groups.items()
                        if any((r.get("workshop") or "") in ctx for r in v)}
            if len(narrowed) == 1:
                key = next(iter(narrowed))
                return {"matched": True, "ambiguous": False, "identity_key": key,
                        "devices": narrowed[key], "source": source, "confidence": conf,
                        "workshop_context": ctx}
        # 仍分不清 → 进人工确认，不自动关联
        return {
            "matched": True, "ambiguous": True, "source": source, "confidence": conf,
            "workshop_context": ctx,
            "candidates": [{
                "identity_key": k,
                "name": (v[0].get("name") or ""),
                "model": (v[0].get("model") or ""),
                "workshop": (v[0].get("workshop") or ""),
                "tags": [r.get("tag") for r in v],
            } for k, v in sorted(groups.items())],
        }
    return {"matched": False, "reason": "no_match"}


# ---------------------------------------------------------------- 写入
def link_file(sha256: str, file_name: str = "", file_path: str = "",
              data_dir=None, force: bool = False) -> dict:
    """为一个文件建立（或不建立）「文件 ↔ 设备身份」联系。

    · 人工确认过的联系不被自动改写（与 workshop_assign 的 manual 优先一致）；
    · 多身份命中 → 落 pending（待人工确认），**不落 links**；
    · 未命中 → 不写 links，并清掉该文件此前的 pending（台账或路径变了）。
    """
    if not sha256:
        return {"sha256": "", "skipped": "no_sha"}
    ddir = _data_dir(data_dir)
    if _tomb_blocked(ddir):
        return {"sha256": sha256, "skipped": "project_deleted"}
    with _LOCK:
        store = _load(data_dir)
        links = store["links"]
        pending = store["pending"]
        rejected = store["rejected"]
        exist = links.get(sha256)
        if exist and exist.get("confirmed") and not force:
            return exist
        if sha256 in rejected and not force:
            return {"sha256": sha256, "linked": False, "reason": "rejected"}
        m = match_file(file_name, file_path, data_dir)
        if not m.get("matched"):
            changed = pending.pop(sha256, None) is not None
            if changed:
                _save(store, data_dir)
            return {"sha256": sha256, "linked": False,
                    "reason": m.get("reason", "no_match")}
        if m.get("ambiguous"):
            rec = {
                "sha256": sha256,
                "file_name": file_name,
                "file_path": file_path,
                "candidates": m.get("candidates") or [],
                "source": m.get("source"),
                "confidence": m.get("confidence"),
                "ts": datetime.datetime.now().isoformat(),
            }
            pending[sha256] = rec
            links.pop(sha256, None)
            _save(store, data_dir)
            out = dict(rec)
            out["linked"] = False
            out["ambiguous"] = True
            return out
        devs = m.get("devices") or []
        rec = {
            "sha256": sha256,
            "file_name": file_name,
            "file_path": file_path,
            "identity_key": m.get("identity_key"),
            "tags": [d.get("tag") for d in devs if d.get("tag")],
            "name": devs[0].get("name") if devs else "",
            "model": devs[0].get("model") if devs else "",
            "workshop": devs[0].get("workshop") if devs else "",
            "source": m.get("source"),
            "confidence": m.get("confidence"),
            "confirmed": False,
            "ts": datetime.datetime.now().isoformat(),
        }
        links[sha256] = rec
        pending.pop(sha256, None)
        _save(store, data_dir)
        out = dict(rec)
        out["linked"] = True
        return out


def confirm_link(sha256: str, identity_key: str = "", data_dir=None) -> dict:
    """人工确认某个待定联系（多身份命中时由人裁定）。"""
    if not sha256:
        return {"ok": False, "msg": "缺少 sha256"}
    with _LOCK:
        store = _load(data_dir)
        pending = store["pending"]
        rec = pending.get(sha256)
        if not rec:
            return {"ok": False, "msg": "没有待确认的联系", "sha256": sha256}
        cands = rec.get("candidates") or []
        chosen = None
        for c in cands:
            if identity_key and c.get("identity_key") == identity_key:
                chosen = c
                break
        if chosen is None and len(cands) == 1:
            chosen = cands[0]
        if chosen is None:
            return {"ok": False, "msg": "请指定 identity_key", "candidates": cands}
        new = {
            "sha256": sha256,
            "file_name": rec.get("file_name"),
            "file_path": rec.get("file_path"),
            "identity_key": chosen.get("identity_key"),
            "tags": list(chosen.get("tags") or []),
            "name": chosen.get("name") or "",
            "model": chosen.get("model") or "",
            "workshop": chosen.get("workshop") or "",
            "source": rec.get("source"),
            "confidence": rec.get("confidence"),
            "confirmed": True,
            "ts": datetime.datetime.now().isoformat(),
        }
        store["links"][sha256] = new
        pending.pop(sha256, None)
        _save(store, data_dir)
        return {"ok": True, "link": new}


def reject_link(sha256: str, reason: str = "", data_dir=None) -> dict:
    """人工否决某个联系：不再自动建立。"""
    if not sha256:
        return {"ok": False, "msg": "缺少 sha256"}
    with _LOCK:
        store = _load(data_dir)
        store["pending"].pop(sha256, None)
        store["links"].pop(sha256, None)
        store["rejected"][sha256] = {
            "reason": reason or "",
            "ts": datetime.datetime.now().isoformat(),
        }
        _save(store, data_dir)
        return {"ok": True, "sha256": sha256}


# ---------------------------------------------------------------- 查询
def list_links(data_dir=None) -> list:
    store = _load(data_dir)
    return sorted(store["links"].values(),
                  key=lambda r: (r.get("ts") or ""), reverse=True)


def list_pending(data_dir=None) -> list:
    store = _load(data_dir)
    return sorted(store["pending"].values(),
                  key=lambda r: (r.get("ts") or ""), reverse=True)


def links_for_device(tag: str, data_dir=None) -> list:
    """某台设备（实例位号）关联到的资料。"""
    if not tag:
        return []
    out = []
    for r in list_links(data_dir):
        if tag in (r.get("tags") or []):
            out.append(r)
    return out


def device_file_map(data_dir=None) -> dict:
    """{设备位号: [资料文件名]} —— 供关系图谱把「文件夹名关联的资料」挂到设备上。"""
    out = {}
    for r in list_links(data_dir):
        fn = r.get("file_name") or ""
        if not fn:
            continue
        for t in (r.get("tags") or []):
            out.setdefault(t, [])
            if fn not in out[t]:
                out[t].append(fn)
    return out


def stats(data_dir=None) -> dict:
    store = _load(data_dir)
    links = store["links"]
    return {
        "links": len(links),
        "pending": len(store["pending"]),
        "rejected": len(store["rejected"]),
        "confirmed": sum(1 for r in links.values() if r.get("confirmed")),
        "by_source": {
            src: sum(1 for r in links.values() if r.get("source") == src)
            for src in ("dir", "filename")
        },
        "devices_linked": len({t for r in links.values() for t in (r.get("tags") or [])}),
    }
