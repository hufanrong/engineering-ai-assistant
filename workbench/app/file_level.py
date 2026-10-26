# -*- coding: utf-8 -*-
"""繁工AI 本地解析工作台 - 文件三级归属（v0.1.157）

在「文件→车间」(workshop_assign) 与「设备→车间」(device_workshop) 之上，
新增「文件→归属层级」维度，与资料类型、实体引用正交：

  L0 平台规范库（跨项目，只读引用，由 platform_store 管理）
  L1 项目级（不属于任何车间）：综合台账 / 采购合同 / 物流到货 / 全场图纸 / 综合管理
  L2 车间级（parent=车间名）：车间图纸 / 方案交底 / 验收资料 / 施工记录 / 其他
  L3 设备级（parent=设备位号）：开箱 / 基础 / 安装 / 试运转 / 厂家资料 等
  PENDING 待确认（层级无法判定，人工挂级）

设计要点：
- 与 workshop_assign 解耦：本模块只决定「层级」，车间仍以 workshop_assign 为准；
- 文件主归属唯一，但内容可拆下级实体（混合装箱箱单整体 L1，设备行各自 L3，
  由 device_workshop 负责，已在既有流程中）；
- 人工登记(source=manual) 不被自动覆盖；
- 存储按项目隔离（与 workshop_assign 一致）。
"""
import datetime
import json
import os
import re

from . import config

# 层级常量
L1 = "L1"   # 项目级
L2 = "L2"   # 车间级
L3 = "L3"   # 设备级
PENDING = "PENDING"

# L1 五子类（顺序即展示顺序）
L1_CATEGORIES = ["综合台账", "采购合同", "物流到货", "全场图纸", "综合管理"]

# L2 车间级资料子类
L2_CATEGORIES = ["车间图纸", "方案交底", "验收资料", "施工记录", "其他"]

# 设备位号：带连字符（P-101 / M-205 / AG-101）；无连字符单字母串（X398 图号）
# 仅在 device_workshop 已登记时才采信，避免误判图号
_TAG_RE = re.compile(r"(?<![A-Za-z0-9\-])([A-Za-z]{1,3}\-\d{2,4}[A-Za-z]?)(?![0-9])")

# ---------- L1 项目级识别词（category → 关键词） ----------
L1_KEYWORDS = {
    "综合台账": ["设备总台账", "设备台账", "设备清单", "设备一览", "设备清册", "设备总表",
               "材料台账", "材料清单", "清册", "汇总表", "总台账", "台账", "一览表",
               "设备明细表", "工程量清单", "总表"],
    "采购合同": ["合同", "采购", "采购订单", "订单", "招投标", "招标", "投标", "中标",
               "技术协议", "订货", "供货合同", "协议"],
    "物流到货": ["物流", "运输", "货运", "发货", "到货", "签收", "货损", "索赔",
               "装箱单", "箱单", "包装单", "提单", "发运", "交货", "快递", "运单"],
    "全场图纸": ["总平面", "总平面布置", "总图", "全场", "全厂", "总体布置", "厂区",
               "位置图", "总布置", "总平面布置图"],
    "综合管理": ["施工组织设计", "施工组织", "总进度", "总计划", "总体进度", "总控计划",
               "会议纪要", "会议记录", "例会", "纪要", "往来", "函件", "工作联系单",
               "联系单", "月报", "周报", "周报", "群文件", "项目管理", "管理制度"],
}

# ---------- L3 设备级资料识别词（subtype → 关键词） ----------
L3_KEYWORDS = {
    "开箱记录": ["开箱检验", "开箱记录", "开箱"],
    "基础验收": ["基础验收", "基础复测", "基础检查", "设备基础"],
    "安装记录": ["安装检查", "安装记录", "找平找正", "找平", "找正", "垫铁", "就位",
               "设备安装"],
    "试运转": ["单机试运转", "单机无负荷", "无负荷试运转", "联动试运转", "系统联动",
             "试运行", "试车", "试运转", "单机"],
    "厂家资料": ["合格证", "说明书", "质保书", "铭牌", "设备报验", "出厂检验",
               "出厂合格证", "质量证明", "检验报告"],
}

# ---------- L2 车间级资料子类识别词 ----------
L2_KEYWORDS = {
    "车间图纸": ["布置图", "安装图", "基础图", "工艺图", "管道图", "电气图", "仪表图",
               "施工图", "平面图", "剖面图", "系统图", "原理图", ".dwg", ".dxf", "图纸"],
    "方案交底": ["施工方案", "吊装方案", "技术交底", "安全交底", "方案", "交底",
               "专项方案", "作业指导书"],
    "验收资料": ["验收", "分部", "分项", "隐蔽", "检验批", "报验单", "验收记录"],
    "施工记录": ["施工日志", "日志", "施工记录", "施工日记", "日报"],
}

# L1 强信号（即使文件带车间名也归项目级；用于跨车间汇总文件）
def _l1_hit(hay):
    """返回命中的 L1 类别，无命中返回 None。"""
    for cat in L1_CATEGORIES:
        for k in L1_KEYWORDS[cat]:
            if k in hay:
                return cat
    return None


def _l3_hit(hay):
    """返回命中的 L3 资料子类，无命中返回 None。"""
    best, best_len = None, 0
    for sub, kws in L3_KEYWORDS.items():
        for k in kws:
            if k in hay and len(k) > best_len:
                best, best_len = sub, len(k)
    return best


def _l2_hit(hay):
    """返回命中的 L2 资料子类，无命中返回 '其他'。"""
    best, best_len = "其他", 0
    for sub, kws in L2_KEYWORDS.items():
        for k in kws:
            kk = k.lower()
            if kk in hay.lower() and len(k) > best_len:
                best, best_len = sub, len(k)
    return best


def _extract_tags(text, known_tags):
    """抽取设备位号：已登记位号优先，其次带连字符通用位号。"""
    tags = []
    seen = set()
    for t in (known_tags or []):
        t = (t or "").strip()
        if t and t in text and t not in seen:
            seen.add(t)
            tags.append(t)
    for m in _TAG_RE.finditer(text):
        t = m.group(1)
        if t not in seen:
            seen.add(t)
            tags.append(t)
    return tags


def _level_file() -> str:
    """层级登记表路径（按项目隔离；未选项目回退全局，兼容迁移期）。"""
    try:
        from . import project_manager as _pm
        cur = _pm.get_current_project()
        if cur:
            pdir = _pm.get_project_data_dir(cur["id"])
            os.makedirs(pdir, exist_ok=True)
            return os.path.join(pdir, "file_level.json")
    except Exception:  # noqa: BLE001
        pass
    os.makedirs(config.DATA_DIR, exist_ok=True)
    return os.path.join(config.DATA_DIR, "file_level.json")


def _load() -> dict:
    p = _level_file()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save(m: dict):
    p = _level_file()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def detect_level(file_name: str = "", file_type: str = "", workshop: str = "",
                 text: str = "", structure: dict = None, known_tags: list = None,
                 workshop_hint: str = "") -> dict:
    """自动判定文件归属层级。

    返回 {level, category, parent, source, confidence, tags}。
    优先级：L3 设备资料（含位号） > L1 项目级强信号 > L2 车间级 > PENDING。
    """
    structure = structure or {}
    name = (file_name or "").strip()
    sp = structure.get("spatial") or {}
    tb = sp.get("title_block") or {}
    tb_name = tb.get("图名", "") or ""
    hay = f"{name} {tb_name} {(text or '')[:1500]}"

    tags = _extract_tags(f"{name} {tb_name} {(text or '')[:3000]}", known_tags)

    # 1) L3 设备级资料（开箱/基础/安装/试运转/厂家资料）
    l3_sub = _l3_hit(hay)
    if l3_sub:
        parent = tags[0] if tags else ""
        ws = workshop or workshop_hint
        if not ws and tags:
            try:
                from . import device_workshop as _dw
                ws = _dw.get_workshop(tags[0]) or ""
            except Exception:  # noqa: BLE001
                ws = ""
        return {"level": L3, "category": l3_sub, "parent": parent, "workshop": ws,
                "tags": tags, "source": "auto", "confidence": 0.85 if tags else 0.6}

    # 2) L1 项目级强信号（总台账/物流/合同/全场图纸/综合管理；即使含车间名也归项目级）
    l1_cat = _l1_hit(hay)
    if l1_cat:
        # 箱单/台账若只涉及单一车间且无跨车间特征，仍可能是车间级；
        # 但「总/全场/全厂/汇总/装箱」与多车间候选一律 L1
        cross = any(k in hay for k in
                    ["总", "全场", "全厂", "汇总", "装箱", "一览", "清册", "全厂", "项目"])
        if cross or not workshop:
            return {"level": L1, "category": l1_cat, "parent": "", "workshop": "",
                    "tags": [], "source": "auto", "confidence": 0.8 if cross else 0.62}
        # 单车间且无跨车间词 → 落到 L2（如「粗碎车间设备清单」）
        return {"level": L2, "category": _l2_hit(hay), "parent": workshop,
                "workshop": workshop, "tags": [], "source": "auto", "confidence": 0.6}

    # 3) L2 车间级（有明确车间）
    if workshop:
        return {"level": L2, "category": _l2_hit(hay), "parent": workshop,
                "workshop": workshop, "tags": [], "source": "auto", "confidence": 0.7}

    # 4) 无法判定 → 待确认
    return {"level": PENDING, "category": "", "parent": "", "workshop": "",
            "tags": [], "source": "none", "confidence": 0.0}


def assign_level(sha: str, file_name: str = "", file_type: str = "", workshop: str = "",
                 text: str = "", structure: dict = None, known_tags: list = None,
                 workshop_hint: str = "", force: bool = False) -> dict:
    """自动归级并落盘；人工登记不覆盖（force=True 才覆盖）。"""
    m = _load()
    existing = m.get(sha)
    if existing and existing.get("source") == "manual" and not force:
        return existing
    info = detect_level(file_name, file_type, workshop, text, structure,
                        known_tags, workshop_hint)
    rec = {
        "sha256": sha,
        "file_name": file_name,
        "level": info["level"],
        "category": info["category"],
        "parent": info["parent"],
        "workshop": info.get("workshop", ""),
        "tags": info.get("tags", []),
        "source": info["source"],
        "confidence": info["confidence"],
        "ts": datetime.datetime.now().isoformat(),
    }
    m[sha] = rec
    _save(m)
    return rec


def manual_assign_level(sha: str, level: str, category: str = "",
                        parent: str = "", file_name: str = "") -> dict:
    """人工指定层级（最高优先）。"""
    m = _load()
    rec = m.get(sha, {})
    rec.update({
        "sha256": sha, "file_name": file_name or rec.get("file_name", ""),
        "level": level, "category": category, "parent": parent,
        "source": "manual", "confidence": 1.0,
        "ts": datetime.datetime.now().isoformat(),
    })
    m[sha] = rec
    _save(m)
    return rec


def get_level(sha: str) -> dict:
    return _load().get(sha, {})


def re_auto(limit: int = 2000) -> int:
    """重新判定 PENDING 及低置信度文件（人工登记跳过）。返回新归级数量。

    需要外部补全 workshop/device 信息，故实际重算在 build_tree 调用处做；
    这里仅返回当前仍待确认数量（供 API 提示）。
    """
    m = _load()
    return len([r for r in m.values() if r.get("level") == PENDING])


def build_tree(items, workshop_map=None, device_tags=None, persist_missing=True):
    """把索引文件列表组装为三级归属树。

    参数：
      items: _frontend_index_items() 列表（含 id/sha256/file_name/file_type/text/structure）
      workshop_map: {sha: workshop}（workshop_assign 登记结果）
      device_tags: 已登记设备位号列表（device_workshop）
      persist_missing: 未登记层级的文件是否自动判定并落盘
    返回：
      {L1:{category:[file...]}, L2:{workshop:{files:[...], devices:{tag:[file...]}}},
       PENDING:[file...], counts:{...}}
    """
    workshop_map = workshop_map or {}
    device_tags = device_tags or []
    level_map = _load()
    changed = False

    tree = {
        "L1": {c: [] for c in L1_CATEGORIES},
        "L2": {},
        "PENDING": [],
    }

    def _file_brief(info, sha):
        return {
            "id": sha or info.get("file_name"),
            "sha256": sha,
            "file_name": info.get("file_name") or info.get("name") or "",
            "file_type": info.get("file_type") or "",
            "status": info.get("status") or "parsed",
            "upload_time": info.get("ts") or info.get("upload_time") or "",
        }

    for info in items:
        sha = info.get("id") or info.get("sha256") or ""
        fname = info.get("file_name") or info.get("name") or ""
        ftype = info.get("file_type") or ""
        ws = workshop_map.get(sha) or info.get("workshop") or ""
        brief = _file_brief(info, sha)

        rec = level_map.get(sha)
        if not rec or (rec.get("source") != "manual"):
            # 取解析缓存里的正文/结构（若索引里没带）
            text = info.get("text") or ""
            structure = info.get("structure") or {}
            if not text or not structure:
                structure, text = _cache_text_structure(sha)
            info_rec = detect_level(fname, ftype, ws, text, structure, device_tags)
            rec = {
                "sha256": sha, "file_name": fname,
                "level": info_rec["level"], "category": info_rec["category"],
                "parent": info_rec["parent"], "workshop": info_rec.get("workshop", ""),
                "tags": info_rec.get("tags", []),
                "source": info_rec["source"], "confidence": info_rec["confidence"],
                "ts": datetime.datetime.now().isoformat(),
            }
            if persist_missing:
                level_map[sha] = rec
                changed = True
        # 人工记录的 parent 若为空，用车间补全展示
        level = rec.get("level") or PENDING
        cat = rec.get("category") or ""
        parent = rec.get("parent") or ""
        rec_ws = rec.get("workshop") or ws

        node = dict(brief)
        node.update({"level": level, "category": cat, "parent": parent})

        if level == L1:
            c = cat if cat in L1_CATEGORIES else "综合管理"
            tree["L1"].setdefault(c, []).append(node)
        elif level == L3:
            ws_key = rec_ws or "未定位车间"
            tag = parent or "未定位设备"
            ws_node = tree["L2"].setdefault(ws_key, {"files": [], "devices": {}})
            ws_node["devices"].setdefault(tag, []).append(node)
        elif level == L2:
            ws_key = parent or rec_ws or "未定位车间"
            ws_node = tree["L2"].setdefault(ws_key, {"files": [], "devices": {}})
            ws_node["files"].append(node)
        else:
            tree["PENDING"].append(node)

    if changed:
        _save(level_map)  # 批量现算后统一写盘一次

    counts = {
        "L1": sum(len(v) for v in tree["L1"].values()),
        "L2": sum(len(n["files"]) + sum(len(x) for x in n["devices"].values())
                  for n in tree["L2"].values()),
        "L2_workshops": len(tree["L2"]),
        "L3": sum(sum(len(x) for x in n["devices"].values())
                  for n in tree["L2"].values()),
        "PENDING": len(tree["PENDING"]),
    }
    tree["counts"] = counts
    return tree


def _cache_text_structure(sha):
    """从解析缓存读正文/结构（供自动归级）。失败返回 ({},'')。"""
    try:
        from . import relations as _rel
        from . import project_manager as _pm
        cur = _pm.get_current_project()
        ddir = _pm.get_project_data_dir(cur["id"]) if cur else None
        cache = _rel._load_cache(sha, data_dir=ddir)
        if not cache:
            return {}, ""
        return cache.get("structure") or {}, cache.get("text") or ""
    except Exception:  # noqa: BLE001
        return {}, ""
