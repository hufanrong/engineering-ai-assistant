# 繁工AI 本地解析工作台 - 车间资料自动划分（v0.1.27）
# 优先级：manual(人工) > cad_title(CAD标题栏/图名,设计院) > filename(文件名) > content(正文关键词)
# 平票/无法确认 → 待人工，不报错；人工修正后重建图谱即生效。
import datetime
import json
import os
import re

from . import config

_ASSIGN_FILE = None


def _ensure():
    global _ASSIGN_FILE
    if _ASSIGN_FILE is None:
        _ASSIGN_FILE = os.path.join(config.DATA_DIR, "workshop_assign.json")
        os.makedirs(config.DATA_DIR, exist_ok=True)


def _load() -> dict:
    _ensure()
    if os.path.exists(_ASSIGN_FILE):
        try:
            with open(_ASSIGN_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save(m: dict):
    _ensure()
    with open(_ASSIGN_FILE, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


_WORKSHOP_RE = re.compile(r"(\d{1,2}|[一二三四五六七八九十]+)\s*号?\s*车间")
_CN = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
       "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}


def _norm(raw: str):
    m = _WORKSHOP_RE.search(raw or "")
    if not m:
        return None
    n = _CN.get(m.group(1), m.group(1))
    return f"{n}号车间"


def _from_text(text: str, limit=5):
    """正文关键词提取车间（取前 N 个去重）。"""
    out = []
    for m in _WORKSHOP_RE.finditer(text or ""):
        n = _CN.get(m.group(1), m.group(1))
        w = f"{n}号车间"
        if w not in out:
            out.append(w)
        if len(out) >= limit:
            break
    return out


def detect_workshop(file_name: str = "", text: str = "", structure: dict = None) -> dict:
    """按优先级识别车间 → {workshop, source, confidence, candidates}。
    无法唯一确认 → workshop=None，candidates 列出候选（供人工）。"""
    structure = structure or {}
    # 1) CAD 标题栏图名（设计院）
    cad_title = ""
    sp = structure.get("spatial") or {}
    tb = sp.get("title_block") or {}
    if tb.get("图名"):
        cad_title = tb["图名"]
    if cad_title:
        w = _norm(cad_title)
        if w:
            return {"workshop": w, "source": "cad_title", "confidence": 0.9, "candidates": [w]}
    # 2) 文件名
    if file_name:
        w = _norm(file_name)
        if w:
            return {"workshop": w, "source": "filename", "confidence": 0.75, "candidates": [w]}
    # 3) 正文关键词
    cands = _from_text(text or "", limit=3)
    if len(cands) == 1:
        return {"workshop": cands[0], "source": "content", "confidence": 0.55, "candidates": cands}
    if len(cands) > 1:
        # 多车间（如台账/清单跨车间）→ 不强行归单车间，列候选
        return {"workshop": None, "source": "content_multi", "confidence": 0.3, "candidates": cands}
    return {"workshop": None, "source": "none", "confidence": 0.0, "candidates": []}


def assign_workshop(sha: str, file_name: str = "", text: str = "", structure: dict = None,
                    force: bool = False) -> dict:
    """解析后自动归车间；已有人工登记不覆盖（force=True 才覆盖）。"""
    m = _load()
    existing = m.get(sha)
    if existing and existing.get("source") == "manual" and not force:
        return existing
    info = detect_workshop(file_name, text, structure)
    rec = {
        "sha256": sha,
        "file_name": file_name,
        "workshop": info["workshop"],
        "source": info["source"],
        "confidence": info["confidence"],
        "candidates": info["candidates"],
        "ts": datetime.datetime.now().isoformat(),
    }
    m[sha] = rec
    _save(m)
    return rec


def manual_assign(sha: str, workshop: str, file_name: str = "") -> dict:
    m = _load()
    rec = m.get(sha, {})
    rec.update({
        "sha256": sha, "file_name": file_name or rec.get("file_name", ""),
        "workshop": workshop, "source": "manual", "confidence": 1.0,
        "candidates": [workshop], "ts": datetime.datetime.now().isoformat(),
    })
    m[sha] = rec
    _save(m)
    return rec


def batch_assign(shas: list, workshop: str) -> int:
    m = _load()
    n = 0
    for sha in shas:
        rec = m.get(sha, {})
        rec.update({"sha256": sha, "workshop": workshop, "source": "manual",
                    "confidence": 1.0, "candidates": [workshop],
                    "ts": datetime.datetime.now().isoformat()})
        m[sha] = rec
        n += 1
    _save(m)
    return n


def re_auto_unassigned() -> int:
    """对未归车间的文件重新自动识别（基于 parsed_cache）。"""
    from . import scanner
    idx = scanner._load_index()
    n = 0
    for sha, info in idx.items():
        m = _load()
        if m.get(sha, {}).get("workshop"):
            continue
        cache = scanner._load_cache(sha) if hasattr(scanner, "_load_cache") else None
        if not cache:
            continue
        rec = assign_workshop(sha, cache.get("file_name", ""), cache.get("text", ""),
                               cache.get("structure") or {})
        if rec.get("workshop"):
            n += 1
    return n


def list_by_workshop() -> dict:
    """{workshop: [rec], "未归车间": [rec]}"""
    m = _load()
    out = {}
    for sha, rec in m.items():
        w = rec.get("workshop") or "未归车间"
        out.setdefault(w, []).append(rec)
    for w in out:
        out[w].sort(key=lambda r: r.get("ts", ""), reverse=True)
    return out


def get_workshop(sha: str) -> str:
    """relations 用：取登记车间（人工优先），无则 None。"""
    m = _load()
    rec = m.get(sha)
    return (rec or {}).get("workshop")
