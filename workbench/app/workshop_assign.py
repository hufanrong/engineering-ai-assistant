# 繁工AI 本地解析工作台 - 车间资料自动划分（v0.1.27）
# 优先级：manual(人工) > cad_title(CAD标题栏/图名,设计院) > filename(文件名) > content(正文关键词)
# 平票/无法确认 → 待人工，不报错；人工修正后重建图谱即生效。
import datetime
import json
import os
import re

from . import config

_LEGACY_FILE = None      # 全局旧文件路径（迁移用）
_MIGRATED = False


def _assign_file() -> str:
    """v0.1.138：车间归属按项目隔离——写入当前项目数据目录，
    未选择项目时回退全局目录（兼容单项目/迁移期）。"""
    try:
        from . import project_manager as _pm
        cur = _pm.get_current_project()
        if cur:
            pdir = _pm.get_project_data_dir(cur["id"])
            os.makedirs(pdir, exist_ok=True)
            return os.path.join(pdir, "workshop_assign.json")
    except Exception:  # noqa: BLE001
        pass
    os.makedirs(config.DATA_DIR, exist_ok=True)
    return os.path.join(config.DATA_DIR, "workshop_assign.json")


def _legacy_file() -> str:
    global _LEGACY_FILE
    if _LEGACY_FILE is None:
        _LEGACY_FILE = os.path.join(config.DATA_DIR, "workshop_assign.json")
    return _LEGACY_FILE


def _migrate_legacy():
    """一次性迁移：旧全局 workshop_assign.json 按 sha 匹配各项目 index，
    把记录迁入对应项目目录；匹配不到的留在全局备份。"""
    global _MIGRATED
    if _MIGRATED:
        return
    _MIGRATED = True
    legacy = _legacy_file()
    if not os.path.exists(legacy):
        return
    try:
        with open(legacy, encoding="utf-8") as f:
            legacy_map = json.load(f)
        if not isinstance(legacy_map, dict) or not legacy_map:
            return
        from . import project_manager as _pm
        moved = 0
        for proj in _pm.list_projects():
            pdir = _pm.get_project_data_dir(proj["id"])
            idx_path = os.path.join(pdir, "index.json")
            if not os.path.exists(idx_path):
                continue
            with open(idx_path, encoding="utf-8") as f:
                idx = json.load(f)
            target = {}
            tpath = os.path.join(pdir, "workshop_assign.json")
            if os.path.exists(tpath):
                with open(tpath, encoding="utf-8") as f:
                    target = json.load(f)
            for sha, rec in legacy_map.items():
                if sha in idx and sha not in target:
                    target[sha] = rec
                    moved += 1
            if target:
                with open(tpath, "w", encoding="utf-8") as f:
                    json.dump(target, f, ensure_ascii=False, indent=1)
        # 迁移后全局文件改名备份（保留可追溯）
        if moved > 0 or True:
            os.rename(legacy, legacy + ".migrated_bak")
    except Exception:  # noqa: BLE001
        pass


def _load() -> dict:
    _migrate_legacy()
    f = _assign_file()
    if os.path.exists(f):
        try:
            with open(f, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save(m: dict):
    f = _assign_file()
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(m, fh, ensure_ascii=False, indent=1)


# v0.1.139：车间识别同时支持编号车间（2号车间/二号车间）与命名车间（磨浮车间/焙烧车间），
# 命名车间直接从资料文本提取，不再漏识别（以项目资料为准，不能确认时留人工）
_WORKSHOP_RE = re.compile(
    r"(?P<num>\d{1,2}|[一二三四五六七八九十]+)\s*号?\s*车间"
    r"|(?P<name>[\u4e00-\u9fa5]{2,8})车间"
)
_CN = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
       "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
# v0.1.139：命名车间干扰前缀清洗（如「今日磨浮车间」→ 磨浮车间）
_BAD_PREFIX = ("今日", "本次", "当天", "现在", "现场", "项目", "整个", "全部",
               "有关", "相关", "各个", "以及", "本", "该", "在", "和", "与",
               "及", "对", "将", "已", "正在", "进行", "使用", "安装")


def _clean_name(name: str):
    """去掉命名车间前的干扰前缀，返回核心车间名（<2 字返回 None）。"""
    for b in _BAD_PREFIX:
        if name.startswith(b):
            name = name[len(b):]
            break
    if len(name) < 2:
        return None
    return name


def _norm(raw: str):
    """文件名/标题识别车间：编号车间归一化（2号车间），命名车间保留原名（磨浮车间）。"""
    m = _WORKSHOP_RE.search(raw or "")
    if not m:
        return None
    if m.group("num"):
        n = _CN.get(m.group("num"), m.group("num"))
        return f"{n}号车间"
    name = _clean_name(m.group("name"))
    if not name or "车间" in name or "车" in name:
        return None
    return f"{name}车间"


def _from_text(text: str, limit=5):
    """正文关键词提取车间（取前 N 个去重）。"""
    out = []
    for m in _WORKSHOP_RE.finditer(text or ""):
        if m.group("num"):
            n = _CN.get(m.group("num"), m.group("num"))
            w = f"{n}号车间"
        else:
            name = _clean_name(m.group("name"))
            if not name or "车间" in name or "车" in name:
                continue
            w = f"{name}车间"
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
