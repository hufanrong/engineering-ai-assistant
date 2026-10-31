"""
v0.1.45：设备台账多版本合并去重

功能：
1. 从所有解析文件中提取设备清单（Excel台账行、CAD图块、OCR铭牌）
2. 同一设备跨版本识别（位号精确匹配 > 名称关键词匹配 > 规格型号匹配）
3. 多版本合并（最新版本为准，字段取并集，冲突留人工确认）
4. 相同设备不同名称/编号的辨认划分
5. 合并结果持久化 + 人工确认界面

设计原则：
- 位号（TAG）是设备唯一标识的首选，设计院编号为准
- 名称不同但位号相同 → 同一设备，取最新版名称
- 位号不同但名称+规格高度相似 → 候选同一设备，留人工确认
- 多版本字段冲突（如重量不同）→ 留人工确认，默认取最新版
"""

import os
import json
import re
import datetime
from . import config

MERGE_FILE = None


def _ensure():
    global MERGE_FILE
    if MERGE_FILE is None:
        MERGE_FILE = os.path.join(config.DATA_DIR, "equipment_merge.json")


def _load() -> dict:
    _ensure()
    if os.path.exists(MERGE_FILE):
        try:
            with open(MERGE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {"merged": {}, "pending": [], "confirmed_alias": {}, "rejected_alias": {}}


def _save(m: dict):
    _ensure()
    with open(MERGE_FILE, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


# ---------------- 设备提取 ----------------

def extract_equipment_from_cache(cache: dict, skipped: list = None) -> list:
    """从单个解析缓存中提取设备列表。
    返回 [{tag, name, model, spec, workshop, source_file, source_type, version_ts, fields}]

    v0.1.179：传入 skipped 列表时，**每一行没进设备库的台账行都记账**（行号+原因），
    不再静默丢弃。竣工资料按设备逐台出表，少一台就少一整套确认表，
    用户必须能看到"这一行为什么没算设备"，而不是自己去数。
    """
    out = []
    if not cache:
        return out
    parser = cache.get("parser", "")
    fname = cache.get("file_name", "")
    ts = cache.get("parsed_at", "") or cache.get("ts", "")
    structure = cache.get("structure") or {}
    text = cache.get("text", "") or ""

    if parser == "excel":
        # Excel台账：每行一个设备
        for sheet in structure.get("sheets", [])[:10]:
            header = [str(h or "").strip() for h in sheet.get("header", [])]
            for _row_i, row in enumerate(sheet.get("rows", [])[:5000]):
                if isinstance(row, dict):
                    tag = str(row.get("位号") or row.get("设备位号") or row.get("设备编号") or row.get("编号") or "").strip()
                    name = str(row.get("设备名称") or row.get("名称") or row.get("品名") or "").strip()
                    model = str(row.get("型号") or row.get("规格型号") or row.get("规格") or "").strip()
                    ws = str(row.get("车间") or row.get("所属车间") or row.get("区域") or "").strip()
                    weight = str(row.get("重量") or row.get("设备重量") or "").strip()
                    spec = str(row.get("规格参数") or row.get("规格参数及技术性能")
                               or row.get("规格及技术性能") or row.get("技术性能") or "").strip()
                    # v0.1.167：补采「数量」—— 原来只取重量，台账里的数量列整列丢失，
                    # 设备库/竣工资料的数量恒为空
                    qty = str(row.get("数量") or row.get("台数") or "").strip()
                else:
                    vals = [str(v or "").strip() for v in row]
                    tag = name = model = ws = weight = qty = spec = ""
                    for i, h in enumerate(header):
                        if i >= len(vals):
                            break
                        if h in ("位号", "设备位号", "设备编号", "编号", "tag", "TAG"):
                            tag = vals[i]
                        elif h in ("设备名称", "名称", "品名"):
                            name = vals[i]
                        elif h in ("型号", "规格型号", "规格"):
                            model = vals[i]
                        elif h in ("车间", "所属车间", "区域", "装置"):
                            ws = vals[i]
                        elif h in ("重量", "设备重量"):
                            weight = vals[i]
                        elif h in ("数量", "台数"):
                            qty = vals[i]
                        # v0.1.179：采「规格参数」—— 真实台账里同一车间同名设备的唯一区分依据
                        # 就是规格（渣浆泵 8/6E-AH、50/40B-AH…），型号列常常整列为空。
                        elif h in ("规格参数", "规格参数及技术性能", "规格及技术性能",
                                   "技术性能", "规格型号", "规格参数/性能"):
                            spec = vals[i]
                # v0.1.179：**有型号或有规格的行也要保留**。
                # 实测事故：用户真实台账（选矿厂 248 行）里有 33 行「设备名称」是空的，
                # 只填了型号（G6-51-10D-55kw、LS250、V11-8…）或规格。
                # 原来这里 `not tag and not name` 直接 continue，把这 33 台设备整行丢掉，
                # 竣工资料按设备逐台出表，等于凭空少了 33 台。
                if not tag and not name and not model and not spec:
                    # 空行 / 续行（只有厂家或只有数量）：不算设备，但要留下证据
                    if skipped is not None:
                        skipped.append({
                            "source_file": fname, "row_index": _row_i,
                            "workshop": ws, "unit": str(row.get("单位") or "").strip()
                            if isinstance(row, dict) else "",
                            "quantity": qty, "vendor": str(row.get("厂家") or "").strip()
                            if isinstance(row, dict) else "",
                            "reason": ("台账空行（无名称/型号/规格）" if not qty
                                       else "只有数量、无名称/型号/规格"),
                        })
                    continue
                fields = {}
                if weight:
                    fields["重量"] = weight
                if qty:
                    fields["数量"] = qty
                out.append({
                    "tag": tag, "name": name, "model": model, "spec": spec,
                    "quantity": qty, "weight": weight,
                    "workshop": ws, "source_file": fname,
                    "source_type": "excel", "version_ts": ts,
                    "row_index": _row_i,
                    "fields": fields,
                })
    elif parser == "cad":
        # CAD图块：有位号属性的设备
        sp = structure.get("spatial") or {}
        for b in sp.get("blocks", [])[:2000]:
            attrs = {a.get("tag", ""): a.get("value", "") for a in b.get("attrs", [])}
            tag = attrs.get("位号") or attrs.get("设备位号") or attrs.get("TAG") or ""
            name = attrs.get("设备名称") or attrs.get("名称") or ""
            model = attrs.get("型号") or attrs.get("规格") or ""
            if tag or name:
                out.append({
                    "tag": tag, "name": name, "model": model,
                    "workshop": "", "source_file": fname,
                    "source_type": "cad", "version_ts": ts,
                    "fields": {"x": b.get("x"), "y": b.get("y"), "block": b.get("block")},
                })
    elif parser in ("ocr", "text"):
        # OCR铭牌/文本：提取位号和名称
        tag_match = re.search(r"[A-Z]{1,4}-?\d{2,4}[A-Z]?", text)
        tag = tag_match.group(0) if tag_match else ""
        # 简单名称提取（从铭牌文本中）
        name = ""
        for kw in ["离心泵", "压缩机", "换热器", "塔", "容器", "反应器", "电机", "泵", "风机"]:
            if kw in text:
                name = kw
                break
        if tag or name:
            out.append({
                "tag": tag, "name": name, "model": "",
                "workshop": "", "source_file": fname,
                "source_type": parser, "version_ts": ts,
                "fields": {},
            })
    return out


def extract_all_equipment(docs: dict, skipped: list = None) -> list:
    """从所有解析文档中提取设备清单。

    v0.1.179：skipped 透传到 extract_equipment_from_cache，逐行记账未计为设备的台账行。
    """
    all_eq = []
    for sha, d in docs.items():
        cache = d.get("_cache") or {}
        if not cache:
            continue
        eqs = extract_equipment_from_cache(cache, skipped=skipped)
        for e in eqs:
            e["sha"] = sha
            all_eq.append(e)
    return all_eq


# ---------------- 设备匹配 ----------------

# ---------------- 位号分层（v0.1.179） ----------------
# 真实台账（如紫金矿业选矿厂设备台账 248 行）往往**没有「位号」列**。
# 这类设备没有设计院编号，合并时必须给一个内部身份键，否则同名设备会互相当成同一台；
# 但这个内部键**绝不能印到给监理的确认表里**——「设备位号」栏应当是空的（人工填写），
# 而不是 _no_tag_xxx 这种字符串。所以内部键与对外位号必须分两层：
#   canonical_tag   = 内部身份键（可以是占位键）
#   display_tag()   = 对外位号（占位键一律返回空）
PLACEHOLDER_TAG_PREFIX = "_no_tag_"


def is_placeholder_tag(tag) -> bool:
    """是否是"台账里没有位号"而生成的内部占位键。"""
    return str(tag or "").strip().startswith(PLACEHOLDER_TAG_PREFIX)


def display_tag(tag) -> str:
    """对外（监理表格/设备清单）显示的位号。占位键一律返回空，由人工补填。"""
    t = str(tag or "").strip()
    if not t or is_placeholder_tag(t):
        return ""
    # _dup_ / _vN 后缀是合并过程产生的内部区分，同样不能外露
    t = re.sub(r"_dup_\d+$", "", t)
    t = re.sub(r"_v\d+$", "", t)
    return t


def _norm_tag(tag: str) -> str:
    """规范化位号：去空格、统一大写、去连接符差异。"""
    if not tag:
        return ""
    t = tag.strip().upper().replace(" ", "").replace("_", "-")
    return t


def _name_similarity(name1: str, name2: str) -> float:
    """名称相似度：关键词重叠率。"""
    if not name1 or not name2:
        return 0.0
    # 提取关键词（2字以上）
    def keywords(s):
        kws = set()
        for kw in ["离心泵", "齿轮泵", "柱塞泵", "螺杆泵", "隔膜泵", "泵",
                    "离心压缩机", "螺杆压缩机", "往复压缩机", "压缩机", "风机",
                    "管壳式换热器", "板式换热器", "空冷器", "换热器", "冷凝器", "再沸器",
                    "精馏塔", "吸收塔", "塔", "储罐", "容器", "反应器", "反应釜",
                    "电动机", "电机", "减速机", "搅拌器", "阀门", "管道"]:
            if kw in s:
                kws.add(kw)
        return kws
    k1 = keywords(name1)
    k2 = keywords(name2)
    if not k1 or not k2:
        return 0.0
    intersection = k1 & k2
    union = k1 | k2
    return len(intersection) / len(union) if union else 0.0


def match_equipment(eq1: dict, eq2: dict) -> dict:
    """判断两个设备是否为同一设备。
    返回 {match: bool, confidence: float, reason: str, match_type: str}
    match_type: exact_tag / tag_alias / name_model / possible / no
    """
    tag1 = _norm_tag(eq1.get("tag", ""))
    tag2 = _norm_tag(eq2.get("tag", ""))
    name1 = eq1.get("name", "") or ""
    name2 = eq2.get("name", "") or ""
    model1 = eq1.get("model", "") or ""
    model2 = eq2.get("model", "") or ""

    # 1) 位号精确匹配
    if tag1 and tag2 and tag1 == tag2:
        return {"match": True, "confidence": 0.95, "reason": f"位号相同: {tag1}", "match_type": "exact_tag"}

    # 2) 位号别名匹配（设计院编号 vs 厂家编号）
    if tag1 and tag2:
        try:
            from . import tag_alias
            if tag_alias.is_alias(tag1, tag2):
                return {"match": True, "confidence": 0.85, "reason": f"位号别名: {tag1} ↔ {tag2}", "match_type": "tag_alias"}
        except Exception:  # noqa: BLE001
            pass

    # 3) 名称+型号高度相似
    name_sim = _name_similarity(name1, name2)
    model_match = (model1 and model2 and model1.strip().upper() == model2.strip().upper())
    if name_sim >= 0.6 and model_match:
        return {"match": True, "confidence": 0.75,
                "reason": f"名称相似({name_sim:.0%})+型号相同: {name1}≈{name2}, {model1}",
                "match_type": "name_model"}

    # 4) 名称高度相似但型号不同/缺失 → 候选（留人工确认）
    if name_sim >= 0.8 and (not model1 or not model2):
        return {"match": True, "confidence": 0.5,
                "reason": f"名称高度相似({name_sim:.0%})但型号缺失: {name1}≈{name2}",
                "match_type": "possible"}

    return {"match": False, "confidence": 0.0, "reason": "不匹配", "match_type": "no"}


# ---------------- 合并逻辑 ----------------

def merge_equipment_list(equipment_list: list) -> dict:
    """合并设备列表，去重。
    返回 {merged: [{canonical_tag, name, model, workshop, versions, fields, conflicts}],
          pending: [{eq1, eq2, match_result}]}
    """
    merged = {}  # canonical_tag -> merged device
    pending = []  # 待人工确认的匹配对

    # 按版本时间排序（最新在后）
    sorted_eq = sorted(equipment_list, key=lambda e: e.get("version_ts", "") or "")

    for eq in sorted_eq:
        tag = _norm_tag(eq.get("tag", ""))
        if not tag:
            # v0.1.179：**无位号设备必须做到"一台一行、互不合并"**。
            # 旧写法只取「名称+源文件」，实测后果（紫金选矿厂真实台账 248 行）：
            # 同一车间同名设备全被合成一台 —— 渣浆泵 6 行（不同规格 8/6E-AH、50/40B-AH、
            # 200/150E-AH、100/80D-AH）、液下渣浆泵 20 行、电动单梁起重机 11 行……
            # 合并后只剩 173 台，**凭空少了 75 台（30.2%）**，竣工资料按设备逐台出表，
            # 等于每少一台就少一整套确认表。
            # 现在把「名称+车间+型号+规格+源文件+行号」全放进键里：
            # 内容相同的两行不会被误当成两台不同设备（同表同源），
            # 内容不同的行也绝不会被挤成一台。宁可多出来让人去重，也不能悄悄少设备。
            tag = (f"{PLACEHOLDER_TAG_PREFIX}"
                   f"{eq.get('name', '')}|{eq.get('workshop', '')}|{eq.get('model', '')}"
                   f"|{eq.get('spec', '')}|{eq.get('source_file', '')}"
                   f"|{eq.get('row_index', '')}")
            # 内部键统一大写去空格会破坏 | 分隔的中文内容，所以这里不再走 _norm_tag
            tag = tag.strip()

        if tag not in merged:
            # 新设备
            merged[tag] = {
                "canonical_tag": tag,
                "name": eq.get("name", ""),
                "model": eq.get("model", ""),
                # v0.1.179：规格提到顶层 —— 无位号台账里型号列常常整列为空，
                # 能区分同名设备的只有规格（渣浆泵 8/6E-AH / 50/40B-AH），
                # 只留在 fields 里下游读不到，确认表的「规格型号」栏就会空着。
                "spec": eq.get("spec", "") or (eq.get("fields", {}) or {}).get("规格参数", ""),
                "row_index": eq.get("row_index", ""),
                # v0.1.167：数量/重量提到顶层 —— 下游 /api/supervision-templates/equipment
                # 与 docgen 读的是顶层字段，只放在 fields 里读不到
                "quantity": eq.get("quantity", "") or (eq.get("fields", {}) or {}).get("数量", ""),
                "weight": eq.get("weight", "") or (eq.get("fields", {}) or {}).get("重量", ""),
                "workshop": eq.get("workshop", ""),
                "versions": [eq],
                "fields": dict(eq.get("fields", {})),
                "conflicts": [],
                "source_count": 1,
            }
            continue

        existing = merged[tag]
        match_result = match_equipment(existing["versions"][-1], eq)

        if match_result["match"] and match_result["confidence"] >= 0.7:
            # 确认同一设备 → 合并
            existing["versions"].append(eq)
            existing["source_count"] += 1
            # 名称：最新版非空则覆盖
            if eq.get("name"):
                existing["name"] = eq["name"]
            if eq.get("model"):
                existing["model"] = eq["model"]
            if eq.get("spec") and not existing.get("spec"):
                existing["spec"] = eq["spec"]
            if eq.get("workshop"):
                existing["workshop"] = eq["workshop"]
            # v0.1.167：数量/重量同样合并（首个非空即采用，后续非空覆盖）
            for _f in ("quantity", "weight"):
                _v = eq.get(_f or "", "") or (eq.get("fields", {}) or {}).get(
                    "数量" if _f == "quantity" else "重量", "")
                if _v:
                    existing[_f] = _v
            # 字段合并：冲突记录
            for k, v in eq.get("fields", {}).items():
                if k in existing["fields"] and existing["fields"][k] != v:
                    existing["conflicts"].append({
                        "field": k,
                        "old_value": existing["fields"][k],
                        "new_value": v,
                        "source_file": eq.get("source_file", ""),
                    })
                    existing["fields"][k] = v  # 默认取最新版
                else:
                    existing["fields"][k] = v
        elif match_result["match"] and 0.4 <= match_result["confidence"] < 0.7:
            # 候选匹配 → 留人工确认
            pending.append({
                "existing_tag": tag,
                "existing_name": existing["name"],
                "new_eq": eq,
                "match_result": match_result,
                "status": "pending",
            })
            # 先作为独立设备加入（不合并），等人工确认
            new_tag = f"{tag}_dup_{len([p for p in pending if p['existing_tag'] == tag])}"
            merged[new_tag] = {
                "canonical_tag": new_tag,
                "name": eq.get("name", ""),
                "model": eq.get("model", ""),
                "spec": eq.get("spec", ""),
                "workshop": eq.get("workshop", ""),
                "versions": [eq],
                "fields": dict(eq.get("fields", {})),
                "conflicts": [],
                "source_count": 1,
                "_pending_merge_with": tag,
            }
        else:
            # 不匹配 → 独立设备
            new_tag = f"{tag}_v{existing['source_count']}"
            merged[new_tag] = {
                "canonical_tag": new_tag,
                "name": eq.get("name", ""),
                "model": eq.get("model", ""),
                "spec": eq.get("spec", ""),
                "workshop": eq.get("workshop", ""),
                "versions": [eq],
                "fields": dict(eq.get("fields", {})),
                "conflicts": [],
                "source_count": 1,
            }

    return {"merged": list(merged.values()), "pending": pending}


# ---------------- 持久化与人工确认 ----------------

def run_merge(docs: dict) -> dict:
    """执行全量设备合并，保存结果。"""
    skipped_rows = []
    all_eq = extract_all_equipment(docs, skipped=skipped_rows)
    result = merge_equipment_list(all_eq)
    m = _load()
    m["merged"] = {d["canonical_tag"]: d for d in result["merged"]}
    # v0.1.179：跳过行落盘，用户点开设备库就能看到"这一行为什么没算设备"
    m["skipped_rows"] = skipped_rows
    # 保留已确认的别名，新pending追加
    existing_pending_tags = {(p["existing_tag"], p["new_eq"].get("source_file", "")) for p in m.get("pending", [])}
    for p in result["pending"]:
        key = (p["existing_tag"], p["new_eq"].get("source_file", ""))
        if key not in existing_pending_tags:
            m["pending"].append(p)
    _save(m)
    return {
        "total_equipment": len(all_eq),
        "merged_count": len(result["merged"]),
        "pending_count": len(m["pending"]),
        "duplicate_removed": len(all_eq) - len(result["merged"]),
        "skipped_rows": len(skipped_rows),
        "skipped_samples": skipped_rows[:10],
    }


def get_merged() -> list:
    """获取合并后的设备列表。"""
    m = _load()
    return list(m.get("merged", {}).values())


# ---------------- 设备写入项目索引（v0.1.172） ----------------
# 背景：supervision_templates._get_workshop_devices 读的是项目 index.json 的 "devices"，
# 但全库检索下来这个字段从来没有赋值处（INDEX_RESERVED_KEYS 保留了键，却没人写），
# 于是「监理确认表按车间出设备行」永远拿不到设备，产出只剩表头。
# 这里补齐写入链路：解析缓存里的台账行 → 合并 → 写 index.json["devices"]（按位号做键）。

def sync_devices_to_index(data_dir: str) -> dict:
    """把当前项目解析出的设备台账行写进 index.json 的 devices 字段。
    返回 {"devices": n, "with_workshop": n, "sources": [...]}；无数据时 devices=0 且不覆盖原值以外的键。
    """
    data_dir = data_dir or config.DATA_DIR
    idx_path = os.path.join(data_dir, "index.json")
    cache_dir = os.path.join(data_dir, "parsed_cache")
    if not os.path.isfile(idx_path):
        return {"devices": 0, "with_workshop": 0, "sources": [], "error": "index.json 不存在"}
    try:
        with open(idx_path, encoding="utf-8") as f:
            idx = json.load(f)
    except Exception as e:  # noqa: BLE001
        return {"devices": 0, "with_workshop": 0, "sources": [], "error": f"index.json 读取失败：{e}"}

    docs = {}
    for sha, info in idx.items():
        if sha in ("files", "devices", "workshops", "version", "updated_at", "relations"):
            continue
        if not isinstance(info, dict):
            continue
        cf = os.path.join(cache_dir, f"{sha}.json")
        if not os.path.isfile(cf):
            continue
        try:
            with open(cf, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        docs[sha] = {"_cache": cache, "file_name": info.get("file_name", "")}

    skipped_rows = []
    equipment = extract_all_equipment(docs, skipped=skipped_rows)
    if not equipment:
        # 不写空值到磁盘：保留上一次的有效结果，避免「一次扫描没解析到台账」把已有设备清空
        return {"devices": 0, "with_workshop": 0, "sources": [],
                "note": "本次未从解析缓存提取到设备行，保留索引里已有的 devices"}

    merged = merge_equipment_list(equipment)["merged"]
    devices = {}
    for d in merged:
        tag = (d.get("canonical_tag") or "").strip()
        if not tag:
            continue
        devices[tag] = {
            "name": d.get("name", ""),
            "model": d.get("model", ""),
            "quantity": d.get("quantity", ""),
            "weight": d.get("weight", ""),
            "workshop": d.get("workshop", ""),
            "manufacturer": (d.get("fields") or {}).get("厂家", "") or (d.get("fields") or {}).get("生产厂家", ""),
            "drawing_no": (d.get("fields") or {}).get("图号", ""),
            "source_file": ((d.get("versions") or [{}])[-1] or {}).get("source_file", ""),
            "source_count": d.get("source_count", 1),
        }
    idx["devices"] = devices
    # v0.1.179：跳过行写进索引，设备库页面能直接看到「哪些台账行没算成设备、为什么」
    idx["ledger_skipped_rows"] = skipped_rows[:200]
    idx["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 车间键顺手补齐（同一份索引里两个键都是"给人看的分组视图"）
    ws_map = {}
    for tag, d in devices.items():
        ws = (d.get("workshop") or "").strip()
        if not ws:
            continue
        ws_map.setdefault(ws, []).append(tag)
    if ws_map:
        idx["workshops"] = {k: {"devices": v} for k, v in sorted(ws_map.items())}

    tmp = idx_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    os.replace(tmp, idx_path)
    sources = sorted({d.get("source_file", "") for d in merged if d.get("source_file")})
    return {"devices": len(devices),
            "with_workshop": sum(1 for d in devices.values() if d.get("workshop")),
            "sources": sources[:10],
            "workshops": sorted(ws_map),
            "skipped_rows": len(skipped_rows)}


def get_pending() -> list:
    """获取待人工确认的匹配对。"""
    m = _load()
    return [p for p in m.get("pending", []) if p.get("status") == "pending"]


def confirm_merge(pending_index: int, action: str, canonical_tag: str = "") -> dict:
    """人工确认/拒绝待合并项。
    action: confirm（合并到existing）/ reject（保持独立）/ merge_as_new（合并为新设备）
    """
    m = _load()
    pending = m.get("pending", [])
    if pending_index < 0 or pending_index >= len(pending):
        return {"ok": False, "error": "索引超出范围"}
    p = pending[pending_index]
    if p.get("status") != "pending":
        return {"ok": False, "error": "该项已处理"}

    existing_tag = p["existing_tag"]
    new_eq = p["new_eq"]

    if action == "confirm":
        # 合并到现有设备
        if existing_tag in m["merged"]:
            existing = m["merged"][existing_tag]
            existing["versions"].append(new_eq)
            existing["source_count"] += 1
            if new_eq.get("name"):
                existing["name"] = new_eq["name"]
            if new_eq.get("model"):
                existing["model"] = new_eq["model"]
            # 移除临时独立设备
            for k, v in list(m["merged"].items()):
                if v.get("_pending_merge_with") == existing_tag and v["name"] == new_eq.get("name"):
                    del m["merged"][k]
                    break
        p["status"] = "confirmed"
    elif action == "reject":
        # 保持独立，移除_pending_merge_with标记
        for k, v in m["merged"].items():
            if v.get("_pending_merge_with") == existing_tag:
                v.pop("_pending_merge_with", None)
                break
        p["status"] = "rejected"
    elif action == "merge_as_new":
        # 合并为新设备（用指定的canonical_tag）
        if not canonical_tag:
            return {"ok": False, "error": "需要指定新位号"}
        new_merged = {
            "canonical_tag": canonical_tag,
            "name": new_eq.get("name", ""),
            "model": new_eq.get("model", ""),
            "workshop": new_eq.get("workshop", ""),
            "versions": [new_eq],
            "fields": dict(new_eq.get("fields", {})),
            "conflicts": [],
            "source_count": 1,
        }
        m["merged"][canonical_tag] = new_merged
        # 移除临时设备
        for k, v in list(m["merged"].items()):
            if v.get("_pending_merge_with") == existing_tag:
                del m["merged"][k]
                break
        p["status"] = "merged_as_new"

    _save(m)
    return {"ok": True, "action": action, "pending_index": pending_index}


def resolve_conflict(canonical_tag: str, field: str, choose: str) -> dict:
    """解决字段冲突（choose: old/new）。"""
    m = _load()
    if canonical_tag not in m["merged"]:
        return {"ok": False, "error": "设备不存在"}
    dev = m["merged"][canonical_tag]
    for i, c in enumerate(dev.get("conflicts", [])):
        if c["field"] == field:
            if choose == "old":
                dev["fields"][field] = c["old_value"]
            else:
                dev["fields"][field] = c["new_value"]
            dev["conflicts"].pop(i)
            break
    _save(m)
    return {"ok": True, "canonical_tag": canonical_tag, "field": field, "chosen": choose}


def stats() -> dict:
    """合并统计。"""
    m = _load()
    merged = list(m.get("merged", {}).values())
    pending = [p for p in m.get("pending", []) if p.get("status") == "pending"]
    conflicts = sum(len(d.get("conflicts", [])) for d in merged)
    multi_version = sum(1 for d in merged if d.get("source_count", 0) > 1)
    return {
        "total_merged": len(merged),
        "pending_confirm": len(pending),
        "field_conflicts": conflicts,
        "multi_version_devices": multi_version,
        "duplicate_removed": sum(d.get("source_count", 1) - 1 for d in merged),
    }
