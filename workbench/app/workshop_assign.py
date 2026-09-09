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


# v0.1.141：空间单元识别增强——不只识别「N号车间」，还覆盖命名车间（磨浮车间）
# 与工程常见功能单元（锂辉石库/原料库/焙烧炉/配电室/泵站/堆场/选矿厂等），
# 文件名支持分段解析（0101-锂辉石库-防雷接地.dwg → 锂辉石库），
# 一切以项目资料为准：唯一命中即归，多候选/无法确认留人工。
# v0.1.141：name 用非贪婪最短匹配（原料库入库→原料库而非原料库入库），
# 允许 1 字核心名（泵站/堆场/料场）但限白名单，防「在现场」类误报
_WORKSHOP_RE = re.compile(
    r"(?P<num>\d{1,2}|[一二三四五六七八九十]+)\s*号?\s*车间"
    r"|(?P<name>[\u4e00-\u9fa5]{1,8}?)(?:车间|厂房|库房|配电室|化验室|控制室|变电站|配电站|泵站|堆场|料场|库|室|间|仓|房|站|场|区|厂)"
)
_ONE_CHAR_OK = ("泵", "堆", "料", "站", "库", "场", "室", "厂", "区", "仓", "房", "矿", "渣", "储")
_CN = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
       "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
# v0.1.139：命名车间干扰前缀清洗（如「今日磨浮车间」→ 磨浮车间）
_BAD_PREFIX = ("今日", "本次", "当天", "现在", "现场", "项目", "整个", "全部",
               "有关", "相关", "各个", "以及", "本", "该", "在", "和", "与",
               "及", "对", "将", "已", "正在", "进行", "使用", "安装")
# v0.1.141：明显非空间单元的组合黑名单（name+单元词 整体命中则跳过）
_BAD_FULL = ("数据库", "资料库", "文件库", "图纸库", "软件库", "程序库", "素材库", "样本库",
             "工具库", "资源库", "文档库", "代码库", "知识库", "模板库", "产品库", "模型库",
             "对象库", "数据库", "素材库",
             "办公室", "会议室", "休息室", "更衣室", "值班室", "档案室", "阅览室", "会客室",
             "活动室", "教室", "储藏室", "杂物室", "盥洗室", "卫生间", "茶水间",
             "网站", "工作站", "火车站", "汽车站", "地铁站", "高铁站",
             "地区", "区域", "小区", "郊区", "城区", "学区", "园区", "街道",
             "工厂", "厂家", "厂商", "现场", "操场", "市场", "广场", "机场", "战场",
             "会场", "考场", "商场", "运动场")
# 文件名分段时跳过的常见图纸类型词（不含空间单元信息）
_SKIP_SEG = ("图纸", "施工图", "平面图", "立面图", "剖面图", "系统图", "原理图", "布置图",
             "详图", "目录", "说明", "清单", "台账", "记录", "方案", "交底", "日志",
             "报告", "通知", "计划", "设计", "安装", "竣工", "防雷", "接地", "配线",
             "动力", "照明", "给排水", "暖通", "消防", "网络", "弱电", "强电")


def _clean_name(name: str):
    """去掉命名单元前的干扰前缀，返回核心名（1 字名保留，白名单在 _norm/_from_text 判断）。"""
    if not name:
        return None
    for b in _BAD_PREFIX:
        if name.startswith(b):
            name = name[len(b):]
            break
    return name


def _norm(raw: str):
    """识别空间单元：编号车间归一化（2号车间）；命名单元保留原名（磨浮车间/锂辉石库/配电室/泵站）。"""
    m = _WORKSHOP_RE.search(raw or "")
    if not m:
        return None
    if m.group("num"):
        n = _CN.get(m.group("num"), m.group("num"))
        return f"{n}号车间"
    raw_name = m.group("name")
    name = _clean_name(raw_name)
    if not name or "车间" in name or "车" in name:
        return None
    if len(name) == 1 and name not in _ONE_CHAR_OK:
        return None
    # 后缀用「原始 name 长度」切片（清洗前后长度不同会错位）
    suffix = m.group(0)[len(raw_name):]
    full = f"{name}{suffix}"
    # v0.1.141：黑名单改子串判断（项目资料数据库说明 含「数据库」→ 拒绝）
    if any(b in full for b in _BAD_FULL):
        return None
    return full


def _norm_filename(file_name: str):
    """文件名识别：先整名试，再按 -_（）空格 分段试（0101-锂辉石库-防雷接地.dwg → 锂辉石库）。"""
    w = _norm(file_name or "")
    if w:
        return w
    if not file_name:
        return None
    for seg in re.split(r"[-_（）()\[\]\s、，,./]+", file_name):
        seg = seg.strip()
        if len(seg) < 2:
            continue
        if seg.isdigit():
            continue
        if re.match(r"^\d{6,8}$", seg):
            continue
        if seg in _SKIP_SEG:
            continue
        w = _norm(seg)
        if w:
            return w
    return None


def _from_text(text: str, limit=5):
    """正文关键词提取空间单元（取前 N 个去重）。"""
    out = []
    for m in _WORKSHOP_RE.finditer(text or ""):
        if m.group("num"):
            n = _CN.get(m.group("num"), m.group("num"))
            w = f"{n}号车间"
        else:
            raw_name = m.group("name")
            name = _clean_name(raw_name)
            if not name or "车间" in name or "车" in name:
                continue
            if len(name) == 1 and name not in _ONE_CHAR_OK:
                continue
            suffix = m.group(0)[len(raw_name):]
            full = f"{name}{suffix}"
            if any(b in full for b in _BAD_FULL):
                continue
            w = full
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
    # 2) 文件名（v0.1.141：分段解析，识别 0101-锂辉石库-xxx.dwg → 锂辉石库）
    if file_name:
        w = _norm_filename(file_name)
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
