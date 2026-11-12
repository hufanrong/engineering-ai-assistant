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

from . import atomic_io as _atomic_io
import os
import json
import threading
import re
import datetime
import unicodedata
from . import config
from . import project_scope as _scope

_MERGE_NAME = "equipment_merge.json"


def _merge_file() -> str:
    """v0.1.199：设备合并/别名确认结果随项目隔离（原来写死全局 data/，
    且常量首次赋值后不再复算，切项目仍写旧路径）。"""
    return _scope.path(_MERGE_NAME)


def _load() -> dict:
    data, _src = _scope.load_with_migration(_MERGE_NAME)
    if isinstance(data, dict) and data:
        return data
    return {"merged": {}, "pending": [], "confirmed_alias": {}, "rejected_alias": {}}


def _save(m: dict):
    _atomic_io.write_json(_merge_file(), m, indent=1)


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
                    # v0.1.180：**单位必须一路带到合并条目**。
                    # 实测事故（紫金选矿厂真实台账 248 行）：尾矿库 4 行全是
                    # 「复合土工膜 1.5mm」「HDPE管 DN200」「长丝无纺土工布 400g」，
                    # 单位 m2 / 米 —— 它们是材料不是设备；原来这里把单位丢了，
                    # 下游无从判别，照样按设备逐台出「设备安装检查记录」。
                    "unit": str(row.get("单位") or "").strip() if isinstance(row, dict) else "",
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


# ---------------- 设备身份键（v0.1.241） ----------------
# 用户决策（2026-11-12 13:20，interaction 7707149546354150699）：
#   「位号为空时，设备主键按什么定？」
#   → 「车间+设备名称作主键，同名多行再按型号区分，仍冲突则进人工确认」
#
# 但**这个主键只能当「身份」，不能当「实例」**。实测真实项目 322fef90（228 台）：
#     车间+名称        → 178 台（少 50）
#     车间+名称+型号   → 202 台（少 26）
# 被并掉的行数量列各不相同，是不同实例，不是重复行：
#     渣浆泵 6 行 数量 2/4/2/2/2/2 ；一级高效脱介筛 4 行 3/6/3/3
# 竣工资料按台出表，少一台就少一整套确认表。v0.1.179 正是为此把
# 「源文件+行号」塞进 canonical_tag 的，不能退回去。
#
# 所以分两层：
#   identity_key(canonical_tag 之外的**并列字段**)
#       = 「车间|名称|型号」—— 用来认出「这两处资料说的是同一台设备」。
#         不含源文件、不含行号：同一台设备出现在两份台账里，身份相同。
#         型号为空时两者会落到同一个身份上，这正是用户要的「同名多行再按
#         型号区分」；型号也相同且确实是不同实例时，由 canonical_tag 区分，
#         需要人工确认哪几行是同一台（进 pending，不擅自合并）。
#   canonical_tag（实例键，维持 v0.1.179 现状）
#       = 一台一行，起诉到源文件与行号，保证不丢设备。
#
# 一句话：**身份用来建立联系，实例用来出表计数。**
def identity_key(name: str = "", workshop: str = "", model: str = "") -> str:
    """设备身份键 = 车间|名称|型号（规范化后）。

    规范化必要的：实测台账里同一型号写成「8/6E-AH」和「8/6e-ah」、车间名里
    混入全角空格的情况都存在，不收敛就会把同一台设备裂成两个身份。

    v0.1.242：**名称是身份的必要条件，空名一律返回空身份**。
    实测真实项目 322fef90 有 13 行名称列为空（台账合并单元格/换行造成的），
    其中 3 行的型号也为空 —— 按「车间||型号」拼键会让同车间两台都空名空型号
    的设备落到同一个身份上，等于凭空断言「这两台是同一台」。身份键的作用是
    认出「同一台设备」，没有名字就认不出任何设备，只能返回空、交给人工补名。
    空身份不会被 find_by_identity 匹配（那里显式挡掉）。
    """
    def _n(s):
        s = unicodedata.normalize("NFKC", str(s or ""))
        s = s.replace("\u3000", " ")
        return " ".join(s.split()).strip()

    _name = _n(name)
    if not _name:
        return ""
    return "|".join([
        _n(workshop),
        _name,
        _n(model).upper(),
    ])


def identity_conflicts(data_dir: str) -> list:
    """型号为空且同车间同名称多实例 → 无法按型号区分，交人工确认。

    用户决策原文：「车间+设备名称作主键，同名多行再按型号区分，**仍冲突则进
    人工确认**」。这里就是「仍冲突」那一半：型号列整列为空时，同名多行既分不开
    也合不掉 —— 擅自合并会丢设备（实测渣浆泵 6 行数量 2/4/2/2/2/2，是一批
    2 台装的泵组，不是同一台），强行拆开又会把同一台设备当两台。

    只**登记**不处置：返回冲突清单供 human_confirm 呈现，实例一条不动。
    """
    idx_path = os.path.join(_index_dir(data_dir), "index.json")
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

    groups = {}
    for tag, d in devs.items():
        if not isinstance(d, dict):
            continue
        k = d.get("identity_key") or identity_key(
            d.get("name", ""), d.get("workshop", ""), d.get("model", ""))
        if not k:
            continue                      # 空名：没有身份，单独进「名称缺失」
        groups.setdefault(k, []).append((tag, d))

    out = []
    for k, rows in groups.items():
        if len(rows) < 2:
            continue
        _ws, _name, _model = (k.split("|") + ["", "", ""])[:3]
        if _model:
            continue                      # 型号能区分 → 不算冲突
        # v0.1.242：数量的「合计」必须按单位分组，不能混着加。
        # 实测这 14 组里有一组是「水源取水 / 螺旋焊接钢管」，数量列 705901.5 与
        # 526149，单位是 kg —— 那是材料不是台数。把 kg 和台加在一起得到 1232163，
        # 是个看着像数字、实际没有任何意义的合计（数错比不数更危险）。
        by_unit = {}
        for _, d in rows:
            u = str(d.get("unit", "") or "").strip() or "（未填单位）"
            by_unit[u] = by_unit.get(u, 0) + _to_float(d.get("quantity"))
        unit_sums = {u: _fmt_num(v) for u, v in sorted(by_unit.items())}
        out.append({
            "type": "身份冲突（型号为空）",
            "identity_key": k,
            "workshop": _ws,
            "name": _name,
            "tags": [t for t, _ in rows],
            # 单位一致时才给单一合计；不一致就给分单位小计，绝不跨单位相加
            "total_qty": (list(unit_sums.values())[0] if len(unit_sums) == 1 else None),
            "unit": (list(unit_sums)[0] if len(unit_sums) == 1 else None),
            "qty_by_unit": unit_sums,
            "evidence": sorted({d.get("source_file", "") for _, d in rows if d.get("source_file")}),
            "note": "同车间同名称、型号列为空，无法按型号区分；请确认这些行是同一台设备（应合并）还是不同设备（应补型号）",
        })
    return out


def devices_missing_name(data_dir: str) -> list:
    """名称为空的设备实例（台账里没取到设备名）—— 无法建身份，交人工补名。

    v0.1.242 命名说明：不叫 nameless_devices —— supervision_integration.py 已有
    同名函数（意思是「出不了竣工表、要回台账补名」）。同一名字两个用途，
    下游按名字引用必然出错，这正是本项目反复踩的「同一件事两个答案」。
    """
    idx_path = os.path.join(_index_dir(data_dir), "index.json")
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
    for tag, d in devs.items():
        if not isinstance(d, dict):
            continue
        if not str(d.get("name", "")).strip():
            out.append({
                "type": "设备名称缺失",
                "tag": tag,
                "workshop": d.get("workshop", ""),
                "model": d.get("model", ""),
                "quantity": d.get("quantity", ""),
                "source_file": d.get("source_file", ""),
                "note": "台账该行名称为空（多为合并单元格/换行），无法建立设备身份，请补设备名",
            })
    return out


def _to_float(v) -> float:
    """数量列转数字。取不到就 0（台账里常见空值/「—」）。"""
    try:
        return float(str(v).strip().replace(",", ""))
    except Exception:  # noqa: BLE001
        return 0.0


def _fmt_num(v: float):
    """数字回显：整数不带 .0，小数保留原精度。"""
    if abs(v - round(v)) < 1e-9:
        return int(round(v))
    return round(v, 4)


def _index_dir(data_dir=None) -> str:
    """解析「index.json 所在目录」—— 显式 data_dir > 当前项目目录 > 全局 data。

    v0.1.242 修：原来三处直接写 `data_dir or config.DATA_DIR`，不传 data_dir 就
    落到全局 data/，而真实项目的数据在 data/projects/<pid>/ —— 于是「按身份反查
    设备」在正常调用下永远查不到，返回空却被当成「没有这台设备」。这就是本项目
    反复出现的 EE/FF 类问题：参数一路传给函数，内部某一处又换成别的目录。
    这里收敛成唯一入口，谁要读 index.json 都从这里拿路径。
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


def find_by_identity(data_dir: str, name: str = "", workshop: str = "",
                     model: str = "") -> list:
    """按身份键反查设备实例（可跨源文件）。

    返回该身份的**全部实例**（1..n 条），每条带 canonical_tag / source_file。
    这是「文件夹名→设备」「图纸挂到设备」这类联系能力的唯一查询入口：
    没有它，同一台设备在不同文件里的资料就永远挂不到一起。
    """
    key = identity_key(name, workshop, model)
    if not key:
        # v0.1.242：空身份（名称缺失）不做任何匹配。否则传空名会把所有空名行
        # 当成「同一台设备」一起返回 —— 凭空断言比查不到更糟。
        return []
    idx_path = os.path.join(_index_dir(data_dir), "index.json")
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
    for tag, d in devs.items():
        if not isinstance(d, dict):
            continue
        k = d.get("identity_key") or identity_key(
            d.get("name", ""), d.get("workshop", ""), d.get("model", ""))
        if k == key:
            row = dict(d)
            row["canonical_tag"] = tag
            out.append(row)
    return out


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
                # v0.1.241：身份键与实例键并列落库。身份用来跨文件认出同一台设备，
                # 实例键保证一台一行不丢设备（见 identity_key() 处的长注释）。
                "identity_key": identity_key(eq.get("name", ""),
                                             eq.get("workshop", ""),
                                             eq.get("model", "")),
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
                # v0.1.180：单位随设备条目走（台/套=设备，m2/米/kg=材料）
                "unit": eq.get("unit", "") or (eq.get("fields", {}) or {}).get("单位", ""),
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
                # v0.1.241：实例仍是独立一台（_dup_ / _vN），但身份与主实例相同 ——
                # 这样按身份反查能把它们一起拿回来，交给人工确认是否同一台。
                "identity_key": identity_key(eq.get("name", ""),
                                             eq.get("workshop", ""),
                                             eq.get("model", "")),
                "name": eq.get("name", ""),
                "model": eq.get("model", ""),
                "spec": eq.get("spec", ""),
                "workshop": eq.get("workshop", ""),
                # v0.1.180：单位随设备条目走（台/套=设备，m2/米/kg=材料）
                "unit": eq.get("unit", "") or (eq.get("fields", {}) or {}).get("单位", ""),
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
                # v0.1.241：实例仍是独立一台（_dup_ / _vN），但身份与主实例相同 ——
                # 这样按身份反查能把它们一起拿回来，交给人工确认是否同一台。
                "identity_key": identity_key(eq.get("name", ""),
                                             eq.get("workshop", ""),
                                             eq.get("model", "")),
                "name": eq.get("name", ""),
                "model": eq.get("model", ""),
                "spec": eq.get("spec", ""),
                "workshop": eq.get("workshop", ""),
                # v0.1.180：单位随设备条目走（台/套=设备，m2/米/kg=材料）
                "unit": eq.get("unit", "") or (eq.get("fields", {}) or {}).get("单位", ""),
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

# v0.1.180：**索引写盘必须串行**。
# 整卷按车间并发出卷（19 个车间 3 路并发），每个线程进来都会调一次
# sync_devices_to_index，而原来 tmp 文件名固定是 index.json.tmp ——
# 19 个线程抢同一个临时文件，写一半被别的线程覆盖，
# 结果部分车间的设备在跑的过程中"消失"（实测：尾矿库材料跳过从 2 项掉到 0）。
_SYNC_LOCK = threading.RLock()


def _serialized(fn):
    """把整个「读索引 → 解析缓存 → 合并 → 回写」包进同一把进程内锁。

    用装饰器而不是改缩进：这个函数 60 多行、分支很多，手工整体缩进
    极易引入缩进错误（已实战踩到一次 IndentationError）。
    """
    def wrapper(*a, **kw):
        with _SYNC_LOCK:
            return fn(*a, **kw)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


@_serialized
def sync_devices_to_index(data_dir: str) -> dict:
    """把当前项目解析出的设备台账行写进 index.json 的 devices 字段。
    返回 {"devices": n, "with_workshop": n, "sources": [...]}；无数据时 devices=0 且不覆盖原值以外的键。
    """
    data_dir = _index_dir(data_dir)
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
            # v0.1.241：身份键必须落进索引。只放在 merge 的临时结果里，
            # 下游（find_by_identity / 资料归属 / 大模型检索）读不到，
            # 等于「算了一遍又丢掉」——本项目反复出现的「同一件事两个答案」。
            "identity_key": d.get("identity_key") or identity_key(
                d.get("name", ""), d.get("workshop", ""), d.get("model", "")),
            "quantity": d.get("quantity", ""),
            "weight": d.get("weight", ""),
            # v0.1.180：单位写进索引 —— 整卷要知道哪些车间是"材料"（m2/米/kg）而非设备
            "unit": d.get("unit", ""),
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

    # v0.1.199：改用统一的 atomic_io.write_json。
    # 原来这里手写 mkstemp + os.replace，但没有 finally 清理临时文件 ——
    # 进程在 open→dump→replace 之间被杀（合并在真实台账上要跑几十秒，
    # 用户很容易以为卡死就关掉），临时文件就永久留在项目目录里。
    # 实测现场：data/projects/e75e857c/ 下积了 3 个 index.*.tmp，
    # 每个 127304 B、各存一份完整的 228 台设备索引（11-02 的三个时间点），
    # 白占 380 KB，而且把 228 台设备的数据在用户目录里重复了三份。
    _atomic_io.write_json(idx_path, idx, indent=1)
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
