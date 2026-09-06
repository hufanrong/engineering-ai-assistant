# 繁工AI 本地解析工作台 - 多图纸联动关联引擎（v0.1.13）
# 输入：data/index.json（已解析文件登记）+ data/parsed_cache/*.json（含 structure 空间结构）
# 输出：data/relations.json（关联图谱）+ 向量库追加"空间摘要"（让 AI 按车间/坐标/设备问答）
#
# 关联维度：
#   0) 图纸网络（drawings）：图号/图名/车间/覆盖设备/图纸间互引（共享设备+全场图+同套图号）
#   1) 图纸/文档 → 车间归属（文件名 + 标题栏图名 + 正文"X号车间"）
#   2) 图纸类型分类（全场布置图 / 车间布置图 / 台账 / 文本资料）
#   3) 全场布置图内车间区域坐标（图块/文本定位）
#   4) 设备位号跨图纸/台账关联（CAD 块属性 ↔ 台账行 ↔ 文本实体）
#   5) 无法确认的冲突 → human_confirm 人工确认队列

import os
import re
import json
import datetime

from . import config

RELATIONS_FILE = None
_WORKSHOP_RE = re.compile(r"(\d{1,2}|[一二三四五六七八九十]+)\s*号?\s*车间")
_TAG_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,3}-\d{1,6}(?:[/-][A-Z]{0,3}\d{0,4})?)(?![A-Za-z0-9])")

# 图纸类型关键词（按文件名+图名判断）
TOTAL_KEYS = ["总图", "总平面", "平面布置", "布置总", "全场", "全厂", "总体", "厂区", "总布置"]
WORKSHOP_MAP_KEYS = ["布置图", "平面图", "设备布置", "基础图", "安装图", "流程图", "管道图", "配管", "电气布置"]
TABLE_KEYS = ["台账", "清单", "记录", "箱单", "货单", "采购", "到货"]
PLAN_KEYS = ["施工计划", "进度", "project", "计划"]


def _ensure():
    global RELATIONS_FILE
    if RELATIONS_FILE is None:
        RELATIONS_FILE = os.path.join(config.DATA_DIR, "relations.json")
        os.makedirs(config.DATA_DIR, exist_ok=True)


CONFIRM_FILE = None  # v0.1.23 人工确认持久化


def _ensure_confirm():
    global CONFIRM_FILE
    if CONFIRM_FILE is None:
        CONFIRM_FILE = os.path.join(config.DATA_DIR, "confirmed_relations.json")
        os.makedirs(config.DATA_DIR, exist_ok=True)


def _load_confirmed() -> dict:
    """人工确认记录：tag -> {workshop, note, ts}（v0.1.23）"""
    _ensure_confirm()
    if os.path.exists(CONFIRM_FILE):
        try:
            with open(CONFIRM_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_confirmed(m: dict):
    _ensure_confirm()
    with open(CONFIRM_FILE, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


def confirm_candidate(tag: str, workshop: str, note: str = "") -> dict:
    """人工确认候选设备归属车间（v0.1.23）：写入持久化并重建图谱。"""
    m = _load_confirmed()
    m[tag.strip()] = {"workshop": workshop.strip(), "note": note or "",
                      "ts": datetime.datetime.now().isoformat()}
    _save_confirmed(m)
    build_relations(force=True)
    return m[tag.strip()]


def _load_index():
    idx_file = os.path.join(config.DATA_DIR, "index.json")
    if os.path.exists(idx_file):
        try:
            with open(idx_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _load_cache(sha256: str):
    p = os.path.join(config.DATA_DIR, "parsed_cache", f"{sha256}.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return None
    return None


# ---------------- 车间名归一 ----------------
def _norm_workshop(raw: str) -> str:
    """把 '1车间' / '二号车间' / '2号车间' 统一为 '1号车间'。"""
    m = _WORKSHOP_RE.search(raw or "")
    if not m:
        return None
    num = m.group(1)
    cn = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
          "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
    n = cn.get(num, num)
    return f"{n}号车间"


def _extract_workshops_from_text(text: str) -> list:
    out = []
    for m in re.finditer(r"(?:[\u4e00-\u9fa5A-Za-z0-9]{0,8}?)(\d{1,2}|[一二三四五六七八九十]+)\s*号?\s*车间", text or ""):
        w = _norm_workshop(m.group(0))
        if w and w not in out:
            out.append(w)
    return out


# ---------------- 图纸类型分类 ----------------
def _classify(name: str, title_block: dict, text: str = "") -> str:
    hay = f"{name} {title_block.get('图名', '')} {title_block.get('图号', '')}".lower()
    if any(k in hay for k in TOTAL_KEYS):
        return "全场布置图"
    w = _norm_workshop(hay)
    if w and any(k in hay for k in WORKSHOP_MAP_KEYS):
        return "车间图纸"
    if any(k in hay for k in TABLE_KEYS):
        return "台账/清单"
    if any(k in hay for k in PLAN_KEYS):
        return "计划"
    return "资料"


# ---------------- 设备位号提取（按文件类型） ----------------
def _equipment_from_cache(cache: dict) -> list:
    """从解析缓存里抽取 {tag, where, workshop_hint} 集合。"""
    out = []
    if not cache:
        return out
    parser = cache.get("parser", "")
    text = cache.get("text", "") or ""
    structure = cache.get("structure") or {}
    fname = cache.get("file_name", "")

    if parser == "cad":
        sp = structure.get("spatial") or {}
        title_no = (sp.get("title_block") or {}).get("图号", "") or ""
        for b in sp.get("blocks", [])[:2000]:
            attrs = {a.get("tag", ""): a.get("value", "") for a in b.get("attrs", [])}
            tag = attrs.get("位号") or attrs.get("设备位号") or attrs.get("TAG")
            if tag:
                out.append({"tag": tag, "where": "cad_block", "x": b.get("x"), "y": b.get("y"),
                            "block": b.get("block")})
        # 图纸文本中的位号（标注/说明）；排除标题栏图号避免把图号当设备
        for m in _TAG_RE.finditer(text):
            if m.group(1) == title_no:
                continue
            out.append({"tag": m.group(1), "where": "cad_text"})
    elif parser in ("text", "ocr"):
        # 文本/OCR（现场照片铭牌识别）中的位号
        for m in _TAG_RE.finditer(text):
            out.append({"tag": m.group(1), "where": "ocr" if parser == "ocr" else "text"})
    elif parser == "excel":
        ws = _norm_workshop(fname) or None
        for sheet in structure.get("sheets", [])[:10]:
            header = [str(h or "").strip() for h in sheet.get("header", [])]
            for row in sheet.get("rows", [])[:5000]:
                if isinstance(row, dict):
                    # parse_excel 输出 dict 行 {表头: 值}
                    tag = str(row.get("位号") or row.get("设备位号") or row.get("设备编号") or row.get("编号") or "").strip()
                    ws_hint = str(row.get("车间") or row.get("所属车间") or row.get("区域") or row.get("装置") or "").strip()
                else:
                    vals = [str(v or "").strip() for v in row]
                    tag = ""
                    for i, h in enumerate(header):
                        if h in ("位号", "设备位号", "设备编号", "编号", "tag", "TAG") and i < len(vals):
                            tag = vals[i]
                            break
                    ws_hint = ""
                    for i, h in enumerate(header):
                        if h in ("车间", "所属车间", "区域", "装置") and i < len(vals):
                            ws_hint = vals[i]
                            break
                if not tag or not _TAG_RE.fullmatch(tag):
                    continue
                row_ws = _norm_workshop(ws_hint) or ws
                out.append({"tag": tag, "where": "excel_row", "workshop_hint": row_ws})
    else:
        for m in _TAG_RE.finditer(text):
            out.append({"tag": m.group(1), "where": "text"})
    return out


def _parse_scale(title_block: dict) -> int:
    """标题栏比例 → 分母：'1:100' → 100；'1:20' → 20；缺省 1（坐标单位即毫米）。"""
    raw = (title_block or {}).get("比例", "") or ""
    m = re.search(r"1\s*[:：]\s*(\d+)", raw)
    if m:
        try:
            return int(m.group(1))
        except ValueError:  # noqa: BLE001
            return 1
    return 1


# ---------------- 设备间距（同图两两距离） ----------------
def _compute_distances(devices: list, docs: dict) -> list:
    """同一张图纸内的设备两两距离。
    口径：DXF 模型空间坐标按真实毫米计（工程 CAD 惯例），实际米 = 坐标差 / 1000；
    标题栏比例（如 1:100）为打印比例，仅作展示不参与换算。
    仅统计同图共坐标系；不同图纸坐标系不同，暂不跨图算距。"""
    out = []
    per_file = {}
    for d in devices:
        for p in d.get("cad_positions", []):
            per_file.setdefault(p["file"], []).append((d["tag"], p["x"], p["y"]))
    for fname, items in per_file.items():
        if len(items) < 2:
            continue
        # 该文件的比例（车间图标题栏，仅展示）
        sha = None
        for k, v in docs.items():
            if v["file_name"] == fname:
                sha = k
                break
        scale = _parse_scale(docs[sha]["title_block"]) if sha and sha in docs else 1
        ws = docs[sha]["workshop"] if sha and sha in docs else None
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                t1, x1, y1 = items[i]
                t2, x2, y2 = items[j]
                mm = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                out.append({
                    "workshop": ws, "file": fname, "from": t1, "to": t2,
                    "mm": round(mm, 1),
                    "meters": round(mm / 1000.0, 2),
                    "scale": scale,
                })
    out.sort(key=lambda r: (r["workshop"] or "", r["file"], r["from"], r["to"]))
    return out[:2000]


# ---------------- 主构建 ----------------
def build_relations(force: bool = False) -> dict:
    _ensure()
    idx = _load_index()
    docs = {}   # sha -> {file_name, parser, workshop, doc_type, tags, title_block, frame}
    for sha, info in idx.items():
        cache = _load_cache(sha)
        if not cache or cache.get("status") not in ("parsed", "partial"):
            continue
        fname = cache.get("file_name", "")
        tb = (cache.get("structure") or {}).get("spatial", {}).get("title_block", {}) if cache.get("parser") == "cad" else {}
        text = cache.get("text", "") or ""

        # 车间归属：文件名 > 标题栏图名 > 正文。
        # 注意：台账/清单正文含多车间行，文档级不做正文车间推断（每行用车间列，行级归组更准）
        ws = _norm_workshop(fname) or _norm_workshop(tb.get("图名", ""))
        if not ws:
            doc_type_pre = _classify(fname, tb, text)
            if doc_type_pre != "台账/清单":
                cands = _extract_workshops_from_text(text)
                ws = cands[0] if cands else None

        doc_type = _classify(fname, tb, text)
        eqs = _equipment_from_cache(cache)
        sp = (cache.get("structure") or {}).get("spatial") or {}
        docs[sha] = {
            "file_name": fname, "parser": cache.get("parser"),
            "workshop": ws, "doc_type": doc_type,
            "tags": list(dict.fromkeys(e["tag"] for e in eqs)),
            "equipments": eqs,
            "title_block": tb,
            "frame": sp.get("frame"),
            "dimensions": sp.get("dimensions"),
            "structure": cache.get("structure") or {},
        }

    # ---- 全场布置图：车间区域坐标 ----
    site_docs = [d for d in docs.values() if d["doc_type"] == "全场布置图"]
    workshop_zones = {}   # 车间名 -> [x, y] 代表点
    for d in site_docs:
        cache = _load_cache_by_name(d["file_name"], idx)
        if not cache:
            continue
        struct = cache.get("structure") or {}
        sp = struct.get("spatial") or {}
        # text_labels 在 structure 顶层（parse_cad 输出），兼容 spatial 内
        labels = struct.get("text_labels") or sp.get("text_labels") or []
        for lb in labels[:1000]:
            w = _norm_workshop(lb.get("text", ""))
            if w and w not in workshop_zones:
                workshop_zones[w] = {"x": lb.get("x"), "y": lb.get("y"), "from": d["file_name"]}
        for b in sp.get("blocks", [])[:1000]:
            w = _norm_workshop(b.get("block", ""))
            if w and w not in workshop_zones:
                workshop_zones[w] = {"x": b.get("x"), "y": b.get("y"), "from": d["file_name"]}

    # ---- 设备汇总：位号 -> 出现的图纸/台账 + 车间 + 坐标 ----
    device_map = {}   # tag -> {...}
    human_confirm = []   # 跨车间/冲突待确认
    for sha, d in docs.items():
        for e in d["equipments"]:
            tag = e["tag"]
            dev = device_map.setdefault(tag, {
                "tag": tag,
                "in_files": [],        # [{file, workshop, where, x, y}]
                "workshops": [],       # 去重车间列表
                "sources": {"cad": 0, "excel": 0, "text": 0, "ocr": 0},
            })
            src_key = {"cad_block": "cad", "cad_text": "text", "excel_row": "excel", "text": "text", "ocr": "ocr"}.get(e["where"], "text")
            dev["sources"][src_key] = dev["sources"].get(src_key, 0) + 1
            entry = {
                "file": d["file_name"], "workshop": d["workshop"],
                "where": e["where"], "x": e.get("x"), "y": e.get("y"),
                "workshop_hint": e.get("workshop_hint"),
            }
            if not any(f["file"] == entry["file"] and f["where"] == entry["where"] for f in dev["in_files"]):
                dev["in_files"].append(entry)
            for w in [d["workshop"], e.get("workshop_hint")]:
                if w and w not in dev["workshops"]:
                    dev["workshops"].append(w)

    # 冲突/待确认：跨车间出现 或 图纸无车间归属但含设备
    for tag, dev in device_map.items():
        ws_set = [w for w in dev["workshops"] if w]
        if len(set(ws_set)) > 1:
            human_confirm.append({"type": "跨车间冲突", "tag": tag, "workshops": list(set(ws_set)),
                                  "files": [f["file"] for f in dev["in_files"]]})
        elif not ws_set:
            human_confirm.append({"type": "车间未确认", "tag": tag,
                                  "files": [f["file"] for f in dev["in_files"]]})

    # ---- v0.1.23：OCR/文本铭牌候选设备（未出现在图纸与台账，可能为新到货/待入台账）----
    plate_by_tag = {}
    for _sha, d in docs.items():
        _pl = (d.get("structure") or {}).get("plate") or {}
        for _t in _pl.get("tags", []):
            plate_by_tag.setdefault(_t, []).append({
                "params": _pl.get("params", [])[:6],
                "manufacturers": _pl.get("manufacturers", []),
                "workshops": _pl.get("workshops", []),
                "file": d["file_name"],
            })
    confirmed_map = _load_confirmed()
    _seen_conflict = set()
    for c in human_confirm:
        _seen_conflict.add(c["tag"])
    for tag, dev in sorted(device_map.items()):
        if tag in confirmed_map or tag in _seen_conflict:
            continue
        if dev["sources"]["cad"] or dev["sources"]["excel"]:
            continue
        if not (dev["sources"]["ocr"] or dev["sources"]["text"]):
            continue
        _pl = plate_by_tag.get(tag, [])
        human_confirm.append({
            "type": "铭牌未在台账（候选设备）", "tag": tag,
            "evidence": [f["file"] for f in dev["in_files"]][:8],
            "plate": _pl[0] if _pl else {},
            "workshop_hint": [f.get("workshop_hint") for f in dev["in_files"] if f.get("workshop_hint")][:3],
        })

    # ---- 图纸网络（v0.1.13）：图号/图名/车间/覆盖设备/图纸间互引 ----
    drawings = []
    site_docs_names = [d["file_name"] for d in site_docs]
    for sha, d in docs.items():
        if d["parser"] != "cad":
            continue
        tb = d["title_block"] or {}
        # 带坐标的设备（CAD 块/标注）
        dev_in_dwg = [{"tag": e["tag"], "x": e.get("x"), "y": e.get("y")}
                      for e in d["equipments"] if e.get("x") is not None]
        drawings.append({
            "file": d["file_name"], "no": tb.get("图号", "") or "",
            "name": tb.get("图名", "") or "", "scale": tb.get("比例", "") or "",
            "workshop": d["workshop"], "doc_type": d["doc_type"],
            "tags": d["tags"], "device_count": len(set(e["tag"] for e in d["equipments"])),
            "devices": dev_in_dwg[:300],
            "frame": d["frame"], "dimensions": d["dimensions"],
            "is_site": d["doc_type"] == "全场布置图",
        })
    # 图纸互引：① 共享设备 ② 全场图↔车间图 ③ 同套图号前缀（如 A-101/A-102 同属 A 套）
    for dwg in drawings:
        rels = []
        for other in drawings:
            if other is dwg:
                continue
            shared = sorted(set(dwg["tags"]) & set(other["tags"]))
            reason = []
            if shared:
                reason.append(f"共享设备{len(shared)}台")
            if dwg["is_site"] and not other["is_site"]:
                reason.append("全场图涵盖车间图")
            if not dwg["is_site"] and other["is_site"]:
                reason.append("车间图归属全场图")
            same_series = (dwg["no"] and other["no"]
                           and dwg["no"].split("-")[0] == other["no"].split("-")[0])
            if same_series and dwg["no"] != other["no"]:
                reason.append("同套图号")
            if reason:
                rels.append({"to": other["file"], "to_no": other["no"],
                             "shared_devices": shared[:50], "reasons": reason})
        dwg["relations"] = rels
        dwg["cross_drawing_devices"] = sorted(set(dwg["tags"]) & {
            t for other in drawings if other is not dwg for t in other["tags"]})

    # ---- 设备-车间映射（layout，v0.1.13）：以设计院图纸（cad）车间为准，台账行车间次之 ----
    layout = []
    for tag, dev in sorted(device_map.items()):
        # 车间证据按来源分级：cad 图纸（设计院）> excel 行（台账）> 文本/OCR
        ws_votes = {}
        for f in dev["in_files"]:
            src_w = f.get("workshop")
            hint_w = f.get("workshop_hint")
            weight = 2 if f["where"] in ("cad_block", "cad_text") else 1
            for w in [src_w, hint_w]:
                if not w:
                    continue
                ws_votes.setdefault(w, 0)
                ws_votes[w] += weight
        if ws_votes:
            top = max(ws_votes.values())
            winners = sorted(w for w, v in ws_votes.items() if v == top)
            main_ws = winners[0] if len(winners) == 1 else None  # 平票→人工确认
        else:
            main_ws = None
        layout.append({"tag": tag, "workshop": main_ws,
                       "votes": [{"workshop": w, "weight": v} for w, v in sorted(ws_votes.items(), key=lambda x: -x[1])],
                       "files": len(dev["in_files"]),
                       "confirmed": main_ws is not None and len(ws_votes) == 1,
                       "cross_drawings": len({f["file"] for f in dev["in_files"] if f["where"].startswith("cad")})})
    # 平票冲突补充进 human_confirm
    for row in layout:
        if row["workshop"] is None and len(row["votes"]) > 1:
            human_confirm.append({"type": "跨车间冲突(平票)", "tag": row["tag"],
                                  "workshops": [v["workshop"] for v in row["votes"]],
                                  "files": [f["file"] for f in device_map[row["tag"]]["in_files"]]})

    # v0.1.23：人工确认结果覆盖/挂载到 layout（设计院图纸为准，人工仲裁兜底）
    for tag, c in confirmed_map.items():
        row = next((r for r in layout if r["tag"] == tag), None)
        if row:
            row["workshop"] = c["workshop"]; row["confirmed"] = True
            row["confirmed_note"] = c.get("note", "")
            row["votes"] = row["votes"] or [{"workshop": c["workshop"], "weight": 0, "manual": True}]
        else:
            layout.append({"tag": tag, "workshop": c["workshop"], "votes": [],
                           "files": 0, "confirmed": True, "confirmed_note": c.get("note", ""),
                           "cross_drawings": 0})

    # ---- 车间聚合 ----
    workshops = {}
    for d in docs.values():
        w = d["workshop"]
        if not w:
            continue
        ws = workshops.setdefault(w, {"workshop": w, "zone": workshop_zones.get(w), "docs": [], "tags": set()})
        ws["docs"].append({"file": d["file_name"], "doc_type": d["doc_type"], "parser": d["parser"]})
        ws["tags"].update(d["tags"])
    for w in workshops:
        workshops[w]["tags"] = sorted(workshops[w]["tags"])
        workshops[w]["doc_count"] = len(workshops[w]["docs"])
        workshops[w]["device_count"] = len(workshops[w]["tags"])

    devices_out = [{"tag": t, "workshops": list(set(d["workshops"])), "files": [f["file"] for f in d["in_files"]],
                    "sources": d["sources"],
                    "cad_positions": [{"x": f["x"], "y": f["y"], "file": f["file"]} for f in d["in_files"] if f["x"] is not None]}
                   for t, d in sorted(device_map.items())]
    distances = _compute_distances(devices_out, docs)
    graph = {
        "workshops": list(workshops.values()),
        "drawings": drawings,
        "layout": layout,
        "devices": devices_out,
        "distances": distances,
        "unassigned_docs": [{"file": d["file_name"], "doc_type": d["doc_type"]} for d in docs.values() if not d["workshop"]],
        "human_confirm": human_confirm[:500],
        "stats": {
            "docs": len(docs),
            "workshops": len(workshops),
            "devices": len(device_map),
            "distances": len(distances),
            "relations": sum(len(w["docs"]) for w in workshops.values()) + sum(len(d["in_files"]) for d in device_map.values()),
            "unassigned_docs": len([1 for d in docs.values() if not d["workshop"]]),
            "human_confirm": len(human_confirm),
            "built_at": datetime.datetime.now().isoformat(),
        },
    }
    _save(graph)
    _append_spatial_summary(graph, docs, idx)
    return graph


def _load_cache_by_name(fname: str, idx: dict):
    for k, v in idx.items():
        if v.get("file_name") == fname:
            return _load_cache(k)
    return None


def _save(graph: dict):
    with open(RELATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=1)


def _append_spatial_summary(graph: dict, docs: dict, idx: dict):
    """把空间摘要追加为检索块（parser=relation_meta），让 AI 能按车间/坐标/设备定位。
    摘要如：『1号车间 布置图 A-101：设备 P-101 离心泵 坐标(5000,3000)』"""
    from .vector_store import VectorStore
    store = VectorStore()
    # 车间级摘要
    summaries = []
    for w in graph["workshops"]:
        devs = [d for d in graph["devices"] if w["workshop"] in d["workshops"]][:200]
        zone = f"全场图位置 ({w['zone']['x']},{w['zone']['y']})" if w.get("zone") else "位置待确认"
        lines = [f"车间：{w['workshop']}（全场图{zone}）"]
        lines += [f"设备 {d['tag']}：见 {len(d['files'])} 份资料" for d in devs[:50]]
        summaries.append("\n".join(lines))
    # 设备级摘要
    for d in graph["devices"]:
        for p in d.get("cad_positions", [])[:3]:
            summaries.append(f"设备 {d['tag']} 位于 {p['file']} 坐标({p['x']},{p['y']})，车间：{'/'.join(d['workshops']) or '待确认'}")
    # 设备间距摘要（让 AI 回答"某设备距离某设备多远"）
    for r in graph.get("distances", [])[:500]:
        summaries.append(f"设备 {r['from']} 距设备 {r['to']} 约 {r['meters']} 米（{r['file']}，比例1:{r['scale']}，车间：{r['workshop'] or '待确认'}）")
    # 入库（带车间元数据）
    for i, s in enumerate(summaries):
        if not s.strip():
            continue
        import hashlib
        fake = type("R", (), {})()
        fake.text = s
        fake.sha256 = "rel-" + hashlib.sha256(s.encode()).hexdigest()[:32]
        fake.file_name = f"[空间关联{i}]"
        fake.ext = ".rel"
        fake.parser = "relation_meta"
        fake.file_path = ""
        try:
            store.index_file(fake)
        except Exception:  # noqa: BLE001（向量化失败不影响图谱）
            pass


def load_relations() -> dict:
    _ensure()
    if os.path.exists(RELATIONS_FILE):
        try:
            with open(RELATIONS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {"stats": {}, "workshops": [], "devices": [], "human_confirm": []}
    return {"stats": {}, "workshops": [], "devices": [], "human_confirm": []}
