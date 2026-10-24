"""
v0.1.145：监理确认模板库（内置模板引擎扩展）

基于监理确认过的辊磨筛分车间表格实例，制作内置模板库（templates_builtin/）：
- 去数据化：把马诺诺实例中的项目常量/设备数据替换为 {{占位符}}
- 按设备类型分类：胶带输送机/平板闸门/振动筛/电动葫芦/渣浆泵/液下渣浆泵/微雾抑尘/通用

生成时数据填充优先级：
1. 项目常量（施工单位/项目经理/技术负责人/监理单位/单位工程/分部工程等）→ 项目配置
2. 设备数据（设备位号/规格型号/供货厂家/重量）→ 设备台账自动匹配（位号>名称）
3. 实测数据（实测偏差/检查结果）→ 现场记录/解析库预填，缺失列出待补
4. 验收标准（允许偏差等）→ 模板已按国标固化，不覆盖

实现：
- scan_builtin_templates(): 扫描 templates_builtin/ 注册到模板索引（doc_type=监理确认表）
- render_supervision_doc(): 按表类型+设备 自动匹配模板并填充生成
- list_by_category(): 按表类型分组返回可用模板
"""

import os
import re
import json
import datetime
import shutil
from typing import Optional, Dict, List

from . import config
from . import template_engine as _te

# 内置模板目录
BUILTIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates_builtin",
)

DOC_TYPE = "监理确认表"

# 表类型 ↔ 文件名关键词映射（模板按此归类）
CATEGORY_KEYWORDS = [
    ("设备报审表", ["报审"]),
    ("设备开箱检查记录", ["开箱"]),
    ("设备安装基础复测记录", ["基础复测"]),
    ("设备垫铁检查记录", ["垫铁"]),
    ("设备安装检查记录", ["安装检查"]),
    ("分项工程质量验收记录", ["分项"]),
    ("分部子分部质量评定表", ["分部"]),
    ("单机无负荷试运转记录", ["试运转", "单机"]),
    ("系统联动试运行记录", ["联动"]),
    ("设备重量确认单", ["重量确认"]),
]

# 内置模板的原始实例数据（从监理模板提取，作为占位符说明/默认）
BUILTIN_FIELD_DOC = {    "项目名称": "工程项目全称（自动取当前项目名）",
    "单位工程": "单位工程名，如：选矿厂",
    "分部工程": "分部工程名，如：工业设备安装",
    "车间": "所在车间，如：辊磨筛分车间",
    "系统名称": "联动试运行系统名，如：辊磨筛分系统设备",
    "施工单位": "施工总包单位（项目配置）",
    "项目经理": "项目经理姓名（项目配置）",
    "技术负责人": "技术负责人姓名（项目配置）",
    "质量负责人": "质量部门负责人（项目配置）",
    "监理单位": "监理单位全称（项目配置）",
    "建设单位": "建设单位（项目配置）",
    "标准编号": "验收标准，如：GB50231-2009（模板已按国标固化）",
    "设备名称": "设备名称（设备台账自动匹配）",
    "设备位号": "设备位号/图号（设备台账自动匹配）",
    "规格型号": "设备规格型号（设备台账自动匹配）",
    "供货厂家": "设备生产厂家（设备台账自动匹配）",
    "施工图号": "施工图纸编号（设备台账/图纸解析）",
    "数量": "设备数量",
    "单重": "设备单重（t）",
    "总重": "设备总重（t）",
    "重量依据": "重量依据来源（厂家图纸/清单）",
}


def _ensure_builtin_registered() -> int:
    """扫描 templates_builtin/ 并把未注册的 docx 注册进模板索引。
    返回本次新注册数量。幂等：已存在（同名同 doc_type）跳过。"""
    if not os.path.isdir(BUILTIN_DIR):
        return 0
    registered = 0
    index = _te._load_template_index()
    existing_names = {t.get("name") for t in index.get("templates", [])}
    for fn in sorted(os.listdir(BUILTIN_DIR)):
        if not (fn.endswith(".docx") or fn.endswith(".xlsx")):
            continue
        # 文件名 → 模板名（去 监理模板_ 前缀和 _设备类型 后缀）
        base = fn[:-5]  # 去掉 .docx/.xlsx
        tpl_name = base
        src_path = os.path.join(BUILTIN_DIR, fn)
        # 计算该模板的表类型
        category = _categorize(base)
        doc_type = f"{DOC_TYPE}|{category}"
        if tpl_name in existing_names:
            continue
        try:
            result = _te.upload_template(src_path, tpl_name, doc_type, f"监理确认模板：{category}")
            if result.get("ok"):
                registered += 1
                existing_names.add(tpl_name)
        except Exception:  # noqa: BLE001
            continue
    return registered


def _categorize(name: str) -> str:
    """根据模板名关键词归类表类型。"""
    for cat, kws in CATEGORY_KEYWORDS:
        if any(k in name for k in kws):
            return cat
    return "其他"


def list_by_category() -> Dict:
    """按表类型分组返回内置模板。"""
    _ensure_builtin_registered()
    index = _te._load_template_index()
    grouped = {}
    for t in index.get("templates", []):
        dt = t.get("doc_type", "")
        if not dt.startswith(DOC_TYPE):
            continue
        cat = dt.split("|", 1)[1] if "|" in dt else t.get("name", "")
        grouped.setdefault(cat, []).append({
            "id": t["id"],
            "name": t["name"],
            "placeholder_count": t.get("placeholder_count", 0),
            "use_count": t.get("use_count", 0),
        })
    return {
        "ok": True,
        "total": sum(len(v) for v in grouped.values()),
        "categories": grouped,
        "fields": BUILTIN_FIELD_DOC,
    }


def _load_project_config(project_id: str = None) -> Dict:
    """读取项目配置（施工单位/项目经理/监理单位等常量）。
    优先级：项目 meta 自定义字段 > 默认值。"""
    from . import project_manager as _pm
    cfg = {
        "项目名称": "",
        "单位工程": "",
        "分部工程": "工业设备安装",
        "车间": "",
        "系统名称": "",
        "施工单位": "",
        "项目经理": "",
        "技术负责人": "",
        "质量负责人": "",
        "监理单位": "",
        "建设单位": "",
        "标准编号": "《机械设备安装工程施工及验收通用规范》GB50231-2009",
    }
    current = _pm.get_current_project()
    if current:
        cfg["项目名称"] = current.get("name", "")
        cfg["建设单位"] = current.get("client", "")
        cfg["单位工程"] = current.get("unit_works", cfg["单位工程"])
        cfg["分部工程"] = current.get("sub_works", cfg["分部工程"])
        cfg["车间"] = current.get("default_workshop", cfg["车间"])
        cfg["施工单位"] = current.get("contractor", cfg["施工单位"])
        cfg["项目经理"] = current.get("project_manager", cfg["项目经理"])
        cfg["技术负责人"] = current.get("tech_leader", cfg["技术负责人"])
        cfg["质量负责人"] = current.get("quality_leader", cfg["质量负责人"])
        cfg["监理单位"] = current.get("supervisor", cfg["监理单位"])
    return cfg


def _get_equipment_data(equipment_name: str = "", tag: str = "",
                        project_id: str = None) -> Dict:
    """从设备台账匹配设备数据。优先级：位号精确 > 名称匹配。
    数据源：项目 index.json devices + equipment_merge.json merged。"""
    data = {
        "设备名称": equipment_name,
        "设备位号": tag,
        "规格型号": "",
        "供货厂家": "",
        "施工图号": "",
        "数量": "",
        "单重": "",
        "总重": "",
        "重量依据": "",
    }
    # 1) 项目 index.json devices（解析库主源）
    try:
        from . import project_manager as _pm
        data_dir = _pm.get_project_data_dir(project_id)
        idx_path = os.path.join(data_dir, "index.json")
        if os.path.isfile(idx_path):
            with open(idx_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
            devices = idx.get("devices", {})
            matched = None
            if tag:
                matched = devices.get(tag) or devices.get(str(tag).upper())
            if not matched and equipment_name:
                for t, d in devices.items():
                    if d.get("name") == equipment_name or equipment_name in str(d.get("name", "")):
                        matched = d
                        if not tag:
                            data["设备位号"] = t
                        break
            if matched:
                data["规格型号"] = matched.get("model", "") or matched.get("spec", "")
                data["供货厂家"] = matched.get("manufacturer", "")
                data["数量"] = matched.get("quantity", "")
                data["单重"] = matched.get("weight", "") or matched.get("single_weight", "")
                data["施工图号"] = matched.get("drawing_no", "")
                data["车间"] = matched.get("workshop", "")
    except Exception:  # noqa: BLE001
        pass

    # 2) equipment_merge.json 兜底
    try:
        from . import equipment_merge as _em
        merged = _em.get_merged()
        if merged:
            m = None
            norm_tag = _em._norm_tag(tag) if tag else ""
            if norm_tag:
                for d in merged:
                    if _em._norm_tag(d.get("canonical_tag", "")) == norm_tag:
                        m = d
                        break
            if not m and equipment_name:
                for d in merged:
                    if d.get("name") == equipment_name or equipment_name in str(d.get("name", "")):
                        m = d
                        break
            if m:
                if not data["规格型号"]:
                    data["规格型号"] = m.get("model", "")
                if not data["供货厂家"]:
                    data["供货厂家"] = m.get("manufacturer", "") or (m.get("fields") or {}).get("厂家", "")
                if not data["数量"]:
                    data["数量"] = (m.get("fields") or {}).get("数量", "")
                if not data["单重"]:
                    data["单重"] = (m.get("fields") or {}).get("重量", "") or (m.get("fields") or {}).get("单重", "")
                if not data["设备位号"]:
                    data["设备位号"] = m.get("canonical_tag", "")
                if not data["设备名称"]:
                    data["设备名称"] = m.get("name", "")
    except Exception:  # noqa: BLE001
        pass
    return data


def _get_equipment_list(project_id: str = None) -> List[Dict]:
    """获取当前项目设备列表（前端选设备用）。"""
    from . import project_manager as _pm
    devices = []
    try:
        data_dir = _pm.get_project_data_dir(project_id)
        idx_path = os.path.join(data_dir, "index.json")
        if os.path.isfile(idx_path):
            with open(idx_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
            for tag, d in (idx.get("devices") or {}).items():
                devices.append({
                    "tag": tag,
                    "name": d.get("name", ""),
                    "model": d.get("model", "") or d.get("spec", ""),
                    "workshop": d.get("workshop", ""),
                })
    except Exception:  # noqa: BLE001
        pass
    # 按车间分组
    from . import equipment_merge as _em
    try:
        merged = _em.get_merged()
        seen = {d["tag"] for d in devices}
        for m in merged:
            tag = m.get("canonical_tag", "")
            if tag in seen:
                continue
            devices.append({
                "tag": tag,
                "name": m.get("name", ""),
                "model": m.get("model", ""),
                "workshop": m.get("workshop", ""),
            })
    except Exception:  # noqa: BLE001
        pass
    return devices


def save_project_config(project_id: str = None, config: Dict = None) -> Dict:
    """保存项目配置（施工单位/项目经理/技术负责人/监理单位/单位工程等）。
    写入项目 meta 文件的自定义字段，供模板生成自动带出。"""
    if not config:
        return {"ok": False, "error": "未提供配置内容"}
    from . import project_manager as _pm
    current = _pm.get_current_project()
    pid = project_id or (current.get("id") if current else "")
    if not pid:
        return {"ok": False, "error": "无当前项目，请先新建或选择项目"}
    project = _pm.get_project(pid)
    if not project:
        return {"ok": False, "error": f"项目不存在：{pid}"}
    # 更新可配置字段
    field_map = {
        "施工单位": "contractor",
        "项目经理": "project_manager",
        "技术负责人": "tech_leader",
        "质量负责人": "quality_leader",
        "监理单位": "supervisor",
        "建设单位": "client",
        "单位工程": "unit_works",
        "分部工程": "sub_works",
        "车间": "default_workshop",
        "系统名称": "system_name",
    }
    changed = []
    for cn, key in field_map.items():
        if cn in config and config[cn] is not None:
            project[key] = str(config[cn]).strip()
            changed.append(cn)
    project["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta_path = _pm._get_project_meta_path(pid)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "project": project,
        "updated": changed,
        "message": f"已保存项目配置：{'、'.join(changed) if changed else '无变化'}",
    }


def _device_type_of(equipment: str) -> str:
    """从设备名称提取设备类型关键词（用于模板匹配）。"""
    if not equipment:
        return ""
    kws = ["胶带输送机", "平板闸门", "双层直线振动筛", "振动筛", "电动葫芦",
           "液下渣浆泵", "渣浆泵", "微雾抑尘", "抑尘系统", "胶带机"]
    for k in kws:
        if k in equipment:
            if k == "双层直线振动筛":
                return "振动筛"
            return k
    return ""


def _render_xlsx_template(template_path: str, fill: Dict,
                          output_path: str) -> Dict:
    """渲染 xlsx 模板：替换 {{占位符}}。重量确认单特殊：设备数据行按台账重填。"""
    import openpyxl
    wb = openpyxl.load_workbook(template_path)
    ws = wb.active

    # 占位符替换（所有单元格）
    filled = set()
    unfilled = set()
    pat = re.compile(r'\{\{([^}]+)\}\}')
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str) and "{{" in c.value:
                orig = c.value
                ms = list(pat.finditer(orig))
                replaced = orig
                for m in ms:
                    field = m.group(1).strip()
                    if field in fill and str(fill[field]):
                        replaced = replaced.replace(m.group(0), str(fill[field]))
                        filled.add(field)
                    else:
                        unfilled.add(field)
                if replaced != orig:
                    c.value = replaced

    # 重量确认单设备行自动填充：找到"设备名称"表头下方数据行
    # 用设备台账（fill 中按名称匹配的重量/型号）重填
    device_rows = []
    header_row_idx = None
    for ri, row in enumerate(ws.iter_rows(min_row=1, max_row=40), start=1):
        vals = [c.value for c in row]
        if vals and vals[1] == "设备名称" and "重量依据" in [str(v) for v in vals]:
            header_row_idx = ri
            continue
        if header_row_idx and ri > header_row_idx and vals and vals[1]:
            device_rows.append((ri, vals))

    # 设备台账数据（名称→重量/型号/数量）
    eq_map = {}
    try:
        from . import equipment_merge as _em
        merged = _em.get_merged()
        for m in merged:
            name = m.get("name", "")
            if not name:
                continue
            flds = m.get("fields") or {}
            eq_map[name] = {
                "model": m.get("model", "") or flds.get("型号", ""),
                "quantity": flds.get("数量", ""),
                "weight": flds.get("重量", "") or flds.get("单重", ""),
                "basis": flds.get("重量依据", "厂家随机清单"),
            }
    except Exception:  # noqa: BLE001
        pass

    filled_dev = 0
    for ri, vals in device_rows:
        name = str(vals[1] or "").strip()
        if name and name in eq_map:
            eq = eq_map[name]
            # C列 型号
            if eq.get("model") and (not vals[2] or str(vals[2]).strip() in ("", "-", "待填")):
                ws.cell(row=ri, column=3).value = eq["model"]
            # E列 数量
            if eq.get("quantity") and (not vals[4] or str(vals[4]).strip() in ("", "-", "待填")):
                ws.cell(row=ri, column=5).value = eq["quantity"]
            # F列 单重
            if eq.get("weight") and (not vals[5] or str(vals[5]).strip() in ("", "-", "待填")):
                ws.cell(row=ri, column=6).value = float(eq["weight"])
                # G列 总重 = 单重×数量
                qty = eq.get("quantity")
                if qty:
                    try:
                        ws.cell(row=ri, column=7).value = float(eq["weight"]) * float(qty)
                    except (TypeError, ValueError):
                        pass
            # H列 重量依据
            if (not vals[7] or str(vals[7]).strip() in ("", "-", "待填")):
                ws.cell(row=ri, column=8).value = eq.get("basis", "厂家随机清单")
            filled_dev += 1

    wb.save(output_path)
    return {
        "ok": True,
        "output_path": output_path,
        "output_file": os.path.basename(output_path),
        "filled_fields": sorted(filled) + (["设备重量数据"] if filled_dev else []),
        "unfilled_fields": sorted(unfilled),
    }


def render_supervision_doc(category: str = "", equipment: str = "",
                           tag: str = "", project_id: str = None,
                           extra_data: Dict = None) -> Dict:
    """
    按表类型 + 设备生成监理确认表。
    category: 表类型（设备开箱检查记录/设备安装检查记录/...）
    equipment: 设备名称
    tag: 设备位号（可选，优先）
    extra_data: 人工补充/覆盖字段
    """
    # 1. 注册内置模板
    _ensure_builtin_registered()

    # 2. 找该表类型下的模板（优先匹配设备类型的模板，其次通用）
    index = _te._load_template_index()
    cat_templates = []
    for t in index.get("templates", []):
        dt = t.get("doc_type", "")
        if dt.startswith(DOC_TYPE + "|") and dt.split("|", 1)[1] == category:
            cat_templates.append(t)

    if not cat_templates:
        # 没有该表类型的模板 → 提示可上传
        return {
            "ok": False,
            "error": f"未找到表类型「{category}」的模板",
            "available": [c for c, _ in CATEGORY_KEYWORDS],
        }

    # 3. 设备类型匹配：模板名末段设备类型 与 设备名提取的类型 精确匹配
    chosen = cat_templates[0]
    dev_type = _device_type_of(equipment)
    if dev_type:
        matched = []
        for t in cat_templates:
            tname = t.get("name", "")
            # 模板名末段（最后一个 _ 之后）是设备类型，精确匹配（避免"渣浆泵"误中"液下渣浆泵"）
            tail = tname.split("_")[-1] if "_" in tname else tname
            if tail == dev_type:
                matched.append(t)
        # 同类型多个模板时：优先不含"通用表"的（专用表 > 通用表）
        if matched:
            for t in matched:
                if "通用表" not in t.get("name", ""):
                    chosen = t
                    break
            else:
                chosen = matched[0]
        else:
            # 无精确匹配 → 通用模板优先
            for t in cat_templates:
                if "通用" in t.get("name", ""):
                    chosen = t
                    break
    elif equipment:
        # 无类型关键词：设备名包含在模板名中
        for t in cat_templates:
            if equipment in t.get("name", ""):
                chosen = t
                break

    # 4. 收集填充数据
    fill = {}
    # 项目常量
    proj = _load_project_config(project_id)
    fill.update(proj)
    # 设备数据（台账匹配）
    eq = _get_equipment_data(equipment, tag, project_id)
    fill.update(eq)
    # 国标验收标准默认值（模板已固化，这里补充说明性字段）
    fill["验收标准"] = "符合GB50231-2009及设计文件要求"
    # 人工补充覆盖
    if extra_data:
        fill.update(extra_data)

    # 5. 渲染
    # 找模板文件（按 file_name 定位模板库中的文件）
    try:
        tpl_file = chosen.get("file_name", "")
        tpl_path = os.path.join(_te.TEMPLATES_DIR, tpl_file) if tpl_file else ""
    except Exception:  # noqa: BLE001
        tpl_path = ""

    if tpl_path and tpl_path.endswith(".xlsx"):
        # xlsx 模板：生成到项目 exports 目录
        from . import project_manager as _pm
        data_dir = _pm.get_project_data_dir(project_id)
        exports_dir = os.path.join(data_dir, "exports")
        os.makedirs(exports_dir, exist_ok=True)
        out_name = f"{chosen['name']}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        out_path = os.path.join(exports_dir, out_name)
        return _render_xlsx_template(tpl_path, fill, out_path)

    return _te.render_template(
        template_id=chosen["id"],
        equipment=equipment,
        project_id=project_id,
        extra_data=fill,
    )


def generate_batch(category: str = "", project_id: str = None,
                   equipment_list: List[str] = None,
                   extra_data: Dict = None) -> Dict:
    """批量生成：对一批设备逐个生成同一表类型。"""
    if not equipment_list:
        return {"ok": False, "error": "未指定设备列表"}
    results = []
    ok_count = 0
    for eq_name in equipment_list:
        r = render_supervision_doc(
            category=category,
            equipment=eq_name,
            project_id=project_id,
            extra_data=extra_data,
        )
        results.append({
            "equipment": eq_name,
            "ok": r.get("ok", False),
            "output_file": r.get("output_file", ""),
            "output_path": r.get("output_path", ""),
            "unfilled_fields": r.get("unfilled_fields", []),
            "error": r.get("error", ""),
        })
        if r.get("ok"):
            ok_count += 1
    return {
        "ok": ok_count > 0,
        "total": len(results),
        "success": ok_count,
        "failed": len(results) - ok_count,
        "results": results,
    }
