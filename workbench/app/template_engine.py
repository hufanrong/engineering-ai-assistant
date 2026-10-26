"""
v0.1.108：模板引擎

支持用户上传Word模板到平台，系统解析模板结构和占位符（{{字段名}}），
用项目数据库中的数据自动填充，生成最终文件。

占位符格式：{{字段名}}
支持的字段：设备名称、项目名称、车间、施工单位、日期、供货厂家、
           设备型号、设备规格、基础编号、隐蔽部位、验收日期 等。

表格占位：在表格单元格中使用 {{字段名}}，系统会自动填充。
重复行：在表格行中使用 {{#设备列表}}...{{/设备列表}} 标记，系统会
        根据设备数量自动复制行并填充。
"""

import os
import re
import json
import datetime
import shutil
from typing import Optional, Dict, List, Tuple

try:
    from docx import Document
    from docx.shared import Pt, Inches, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False


# 模板存储目录（平台级，所有项目共享模板库）
TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "templates"
)

# 模板元数据文件
TEMPLATE_INDEX_FILE = os.path.join(TEMPLATES_DIR, "template_index.json")


def _ensure_templates_dir():
    os.makedirs(TEMPLATES_DIR, exist_ok=True)


def _load_template_index() -> Dict:
    """加载模板索引。"""
    _ensure_templates_dir()
    if os.path.isfile(TEMPLATE_INDEX_FILE):
        try:
            with open(TEMPLATE_INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"templates": []}


def _save_template_index(index: Dict):
    """保存模板索引。"""
    _ensure_templates_dir()
    with open(TEMPLATE_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


# 支持的占位符字段定义
PLACEHOLDER_FIELDS = {
    "设备名称": {"description": "设备名称", "source": "equipment", "example": "球磨机"},
    "设备型号": {"description": "设备型号规格", "source": "equipment_detail", "example": "MQY3660"},
    "项目名称": {"description": "工程项目名称", "source": "project", "example": "XX矿山选厂项目"},
    "车间": {"description": "所在车间", "source": "equipment", "example": "磨矿车间"},
    "施工单位": {"description": "施工单位名称", "source": "manual", "example": "XX建设公司"},
    "建设单位": {"description": "建设单位名称", "source": "project", "example": "XX矿业公司"},
    "日期": {"description": "当前日期", "source": "auto", "example": "2026-09-07"},
    "验收日期": {"description": "验收日期", "source": "auto", "example": "2026-09-07"},
    "开箱日期": {"description": "开箱检验日期", "source": "auto", "example": "2026-09-07"},
    "安装日期": {"description": "设备安装日期", "source": "auto", "example": "2026-09-07"},
    "供货厂家": {"description": "设备供货厂家", "source": "equipment", "example": "XX重工"},
    "基础编号": {"description": "设备基础编号", "source": "manual", "example": "J-101"},
    "隐蔽部位": {"description": "隐蔽工程部位", "source": "manual", "example": "设备基础地脚螺栓"},
    "编制人": {"description": "文件编制人", "source": "manual", "example": "张工"},
    "审核人": {"description": "文件审核人", "source": "manual", "example": "李工"},
    "批准人": {"description": "文件批准人", "source": "manual", "example": "王总"},
    "设备位号": {"description": "设备位号/编号", "source": "equipment", "example": "P-101"},
    "安装位置": {"description": "设备安装位置", "source": "equipment", "example": "1号车间A区"},
    "标高": {"description": "设备安装标高", "source": "equipment", "example": "EL+5.500"},
    "重量": {"description": "设备重量", "source": "equipment_detail", "example": "85t"},
    "外形尺寸": {"description": "设备外形尺寸", "source": "equipment_detail", "example": "Φ3600×6000"},
    "电机功率": {"description": "电机功率", "source": "equipment_detail", "example": "400kW"},
    "电压": {"description": "电机电压", "source": "equipment_detail", "example": "10kV"},
    "转速": {"description": "设备转速", "source": "equipment_detail", "example": "17.5r/min"},
}


def list_templates(doc_type: str = None) -> Dict:
    """
    获取模板列表。
    
    Args:
        doc_type: 按文件类型筛选，为None时返回全部
    
    Returns:
        模板列表
    """
    index = _load_template_index()
    templates = index.get("templates", [])
    
    if doc_type:
        templates = [t for t in templates if t.get("doc_type") == doc_type]
    
    return {
        "ok": True,
        "total": len(templates),
        "templates": templates,
    }


def upload_template(file_path: str, template_name: str = "",
                    doc_type: str = "", description: str = "") -> Dict:
    """
    上传并注册模板。
    
    Args:
        file_path: 模板文件路径（Word .docx）
        template_name: 模板名称
        doc_type: 关联的文件类型（安全交底/技术交底/施工方案等）
        description: 模板描述
    
    Returns:
        上传结果，包含解析出的占位符列表
    """
    if not HAS_DOCX:
        return {"ok": False, "error": "python-docx 未安装，无法解析Word模板"}
    
    if not os.path.isfile(file_path):
        return {"ok": False, "error": f"文件不存在：{file_path}"}
    
    if not (file_path.endswith(".docx") or file_path.endswith(".xlsx")):
        return {"ok": False, "error": "仅支持 .docx / .xlsx 格式模板"}
    
    _ensure_templates_dir()
    
    # 生成模板ID（毫秒级+pid+序号，避免同一秒注册多个模板时 ID 冲突）
    template_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3] + "_" + str(os.getpid())
    index0 = _load_template_index()
    existing_ids = {t.get("id") for t in index0.get("templates", [])}
    seq = 0
    base_id = template_id
    while template_id in existing_ids:
        seq += 1
        template_id = base_id + f"_{seq}"
    
    # 拷贝模板到模板库
    ext = os.path.splitext(file_path)[1]
    stored_name = f"{template_id}{ext}"
    stored_path = os.path.join(TEMPLATES_DIR, stored_name)
    shutil.copy2(file_path, stored_path)
    
    # 解析模板
    parse_result = parse_template(stored_path)
    
    # 确定模板名称
    if not template_name:
        template_name = os.path.splitext(os.path.basename(file_path))[0]
    
    # 注册到索引
    index = _load_template_index()
    template_info = {
        "id": template_id,
        "name": template_name,
        "doc_type": doc_type,
        "description": description,
        "file_name": stored_name,
        "file_path": stored_path,
        "file_size": os.path.getsize(stored_path),
        "placeholders": parse_result.get("placeholders", []),
        "placeholder_count": parse_result.get("placeholder_count", 0),
        "has_tables": parse_result.get("has_tables", False),
        "table_count": parse_result.get("table_count", 0),
        "paragraph_count": parse_result.get("paragraph_count", 0),
        "uploaded_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "use_count": 0,
    }
    index["templates"].append(template_info)
    _save_template_index(index)
    
    return {
        "ok": True,
        "template": template_info,
        "message": f"模板「{template_name}」上传成功，解析到{template_info['placeholder_count']}个占位符",
    }


def parse_template(file_path: str) -> Dict:
    """
    解析Word模板，提取占位符和结构。
    
    Args:
        file_path: 模板文件路径
    
    Returns:
        解析结果
    """
    if not (HAS_DOCX or file_path.endswith(".xlsx")):
        return {"ok": False, "error": "python-docx 未安装"}
    
    placeholders = set()
    placeholder_pattern = re.compile(r'\{\{([^}]+)\}\}')
    paragraph_count = 0
    table_count = 0
    repeat_sections = set()
    
    if file_path.endswith(".xlsx"):
        # Excel 模板：扫描所有单元格占位符
        try:
            import openpyxl
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "openpyxl 未安装，无法解析xlsx模板"}
        wb = openpyxl.load_workbook(file_path)
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str) and "{{" in str(cell.value):
                        matches = placeholder_pattern.findall(str(cell.value))
                        for m in matches:
                            placeholders.add(m.strip())
        return {
            "ok": True,
            "placeholders": sorted(list(placeholders)),
            "placeholder_count": len(placeholders),
            "has_tables": True,
            "table_count": len(wb.worksheets),
            "paragraph_count": 0,
            "repeat_sections": [],
            "supported_fields": list(PLACEHOLDER_FIELDS.keys()),
        }
    
    try:
        doc = Document(file_path)
    except Exception as e:
        return {"ok": False, "error": f"解析模板失败：{str(e)}"}
    
    # 解析段落
    for para in doc.paragraphs:
        paragraph_count += 1
        matches = placeholder_pattern.findall(para.text)
        for m in matches:
            placeholders.add(m.strip())
    
    # 解析表格
    table_count = len(doc.tables)
    has_tables = table_count > 0
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                matches = placeholder_pattern.findall(cell.text)
                for m in matches:
                    placeholders.add(m.strip())
    
    # 检查重复行标记
    repeat_pattern = re.compile(r'\{\{#([^}]+)\}\}')
    for para in doc.paragraphs:
        matches = repeat_pattern.findall(para.text)
        for m in matches:
            repeat_sections.add(m.strip())
    
    return {
        "ok": True,
        "placeholders": sorted(list(placeholders)),
        "placeholder_count": len(placeholders),
        "has_tables": has_tables,
        "table_count": table_count,
        "paragraph_count": paragraph_count,
        "repeat_sections": list(repeat_sections),
        "supported_fields": list(PLACEHOLDER_FIELDS.keys()),
    }


def _get_project_data(project_id: str = None) -> Dict:
    """从项目数据库获取填充数据。"""
    from . import project_manager as _pm
    
    data = {
        "项目名称": "",
        "建设单位": "",
        "设备名称": "",
        "设备型号": "",
        "车间": "",
        "供货厂家": "",
        "设备位号": "",
        "安装位置": "",
        "标高": "",
    }
    
    # 当前项目信息
    current = _pm.get_current_project()
    if current:
        data["项目名称"] = current.get("name", "")
        data["建设单位"] = current.get("client", "")
    
    # 从项目 index.json 读取设备数据
    data_dir = _pm.get_project_data_dir(project_id)
    index_path = os.path.join(data_dir, "index.json")
    if os.path.isfile(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
            devices = idx.get("devices", {})
            if devices:
                # 取第一个设备作为默认
                first_tag = list(devices.keys())[0]
                dev = devices[first_tag]
                data["设备名称"] = dev.get("name", "")
                data["设备位号"] = first_tag
                data["车间"] = dev.get("workshop", "")
                data["供货厂家"] = dev.get("manufacturer", "")
                data["安装位置"] = dev.get("location", "")
                data["标高"] = dev.get("elevation", "")
        except Exception:
            pass
    
    # 自动填充日期
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    data["日期"] = today
    data["验收日期"] = today
    data["开箱日期"] = today
    data["安装日期"] = today
    
    return data


def _get_equipment_detail_data(equipment_name: str) -> Dict:
    """从设备详细知识库获取设备参数。"""
    data = {
        "设备型号": "",
        "重量": "",
        "外形尺寸": "",
        "电机功率": "",
        "电压": "",
        "转速": "",
    }
    
    try:
        from . import mining_equipment_detail as _med
        result = _med.get_equipment_detail(equipment_name)
        if result.get("ok"):
            detail = result.get("detail", {})
            models = detail.get("typical_models", [])
            if models:
                data["设备型号"] = models[0].get("model", "")
            params = detail.get("key_parameters", [])
            for p in params:
                pname = p.get("parameter", "")
                pvalue = p.get("value", "")
                if "功率" in pname:
                    data["电机功率"] = pvalue
                elif "电压" in pname:
                    data["电压"] = pvalue
                elif "转速" in pname or "速度" in pname:
                    data["转速"] = pvalue
                elif "重量" in pname:
                    data["重量"] = pvalue
                elif "尺寸" in pname or "规格" in pname:
                    data["外形尺寸"] = pvalue
    except Exception:
        pass
    
    return data


def render_template(template_id: str, equipment: str = "",
                    project_id: str = None, extra_data: Dict = None,
                    output_path: str = None) -> Dict:
    """
    用项目数据填充模板，生成最终文件。
    
    Args:
        template_id: 模板ID
        equipment: 设备名称（用于从知识库获取设备参数）
        project_id: 项目ID，为None时使用当前项目
        extra_data: 额外填充数据（人工补充的字段）
        output_path: 输出文件路径，为None时自动生成
    
    Returns:
        生成结果，包含输出文件路径和未填充的占位符列表
    """
    if not HAS_DOCX:
        return {"ok": False, "error": "python-docx 未安装"}
    
    # 查找模板
    index = _load_template_index()
    template_info = None
    for t in index.get("templates", []):
        if t["id"] == template_id:
            template_info = t
            break
    
    if not template_info:
        return {"ok": False, "error": f"模板不存在：{template_id}"}
    
    template_path = template_info["file_path"]
    if not os.path.isfile(template_path):
        return {"ok": False, "error": f"模板文件丢失：{template_path}"}
    
    # 收集填充数据
    fill_data = {}
    
    # 1. 从项目数据库获取
    project_data = _get_project_data(project_id)
    fill_data.update(project_data)
    
    # 2. 从设备详细知识库获取
    if equipment:
        fill_data["设备名称"] = equipment
        eq_data = _get_equipment_detail_data(equipment)
        fill_data.update(eq_data)
    
    # 3. 额外数据（人工补充）覆盖
    if extra_data:
        fill_data.update(extra_data)
    
    # 打开模板并填充
    try:
        doc = Document(template_path)
    except Exception as e:
        return {"ok": False, "error": f"打开模板失败：{str(e)}"}
    
    placeholder_pattern = re.compile(r'\{\{([^}]+)\}\}')
    filled_fields = set()
    unfilled_fields = set()

    def _fill_para_cross_run(para, pat, data, filled, unfilled):
        """v0.1.129：段落级跨 run 兜底替换。
        Word 常把 {{字段}} 拆到多个 run（如 '{{' / '设备名称' / '}}'），单 run 替换会漏。
        若段落拼接文本含占位符：把替换结果写到第一个非空 run，其余 run 清空，保留原格式。"""
        joined = "".join(r.text for r in para.runs)
        if "{{" not in joined or "}}" not in joined:
            return
        ms = list(pat.finditer(joined))
        if not ms:
            return
        replaced = joined
        for m in ms:
            field = m.group(1).strip()
            if field in data and data[field]:
                replaced = replaced.replace(m.group(0), str(data[field]))
                filled.add(field)
            else:
                unfilled.add(field)
        if replaced == joined:
            return
        # 写回：首 run 承载全文，其余清空
        first = None
        for r in para.runs:
            if first is None:
                first = r
            else:
                r.text = ""
        if first is not None:
            first.text = replaced

    # 填充段落
    for para in doc.paragraphs:
        for run in para.runs:
            text = run.text
            matches = placeholder_pattern.findall(text)
            for m in matches:
                field = m.strip()
                if field in fill_data and fill_data[field]:
                    text = text.replace("{{" + m + "}}", str(fill_data[field]))
                    filled_fields.add(field)
                else:
                    unfilled_fields.add(field)
            run.text = text
        _fill_para_cross_run(para, placeholder_pattern, fill_data, filled_fields, unfilled_fields)
    
    # 填充表格
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for run in para.runs:
                        text = run.text
                        matches = placeholder_pattern.findall(text)
                        for m in matches:
                            field = m.strip()
                            if field in fill_data and fill_data[field]:
                                text = text.replace("{{" + m + "}}", str(fill_data[field]))
                                filled_fields.add(field)
                            else:
                                unfilled_fields.add(field)
                        run.text = text
                    _fill_para_cross_run(para, placeholder_pattern, fill_data, filled_fields, unfilled_fields)
    
    # 生成输出路径
    if not output_path:
        from . import project_manager as _pm
        exports_dir = _pm.get_project_exports_dir(project_id)
        os.makedirs(exports_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[^\w\u4e00-\u9fa5]', '_', template_info["name"])
        output_path = os.path.join(exports_dir, f"{safe_name}_{timestamp}.docx")
    
    # 保存
    try:
        _apply_national_style(doc)  # v0.1.164：国标样式规整（字体/页边距/表格边框）
        doc.save(output_path)
    except Exception as e:
        return {"ok": False, "error": f"保存文件失败：{str(e)}"}
    
    # 更新使用次数
    for t in index.get("templates", []):
        if t["id"] == template_id:
            t["use_count"] = t.get("use_count", 0) + 1
            t["last_used_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            break
    _save_template_index(index)
    
    return {
        "ok": True,
        "template_name": template_info["name"],
        "output_path": output_path,
        "output_file": os.path.basename(output_path),
        "filled_fields": sorted(list(filled_fields)),
        "filled_count": len(filled_fields),
        "unfilled_fields": sorted(list(unfilled_fields)),
        "unfilled_count": len(unfilled_fields),
        "has_unfilled": len(unfilled_fields) > 0,
        "message": f"文件已生成：{os.path.basename(output_path)}" + 
                   (f"，有{len(unfilled_fields)}个占位符未填充（数据缺失），请手动补充" if unfilled_fields else "，所有占位符已填充"),
    }


def delete_template(template_id: str) -> Dict:
    """删除模板。"""
    index = _load_template_index()
    templates = index.get("templates", [])
    
    found = None
    for i, t in enumerate(templates):
        if t["id"] == template_id:
            found = t
            del templates[i]
            break
    
    if not found:
        return {"ok": False, "error": f"模板不存在：{template_id}"}
    
    # 删除文件
    file_path = found.get("file_path", "")
    if file_path and os.path.isfile(file_path):
        os.remove(file_path)
    
    index["templates"] = templates
    _save_template_index(index)
    
    return {
        "ok": True,
        "message": f"模板「{found['name']}」已删除",
    }


def get_supported_fields() -> Dict:
    """获取支持的占位符字段列表。"""
    fields = []
    for name, info in PLACEHOLDER_FIELDS.items():
        fields.append({
            "field": name,
            "description": info["description"],
            "source": info["source"],
            "example": info["example"],
        })
    return {
        "ok": True,
        "total": len(fields),
        "fields": fields,
    }


def generate_from_template_by_type(doc_type: str, equipment: str = "",
                                    project_id: str = None,
                                    extra_data: Dict = None) -> Dict:
    """
    根据文件类型自动选择模板并生成文件。
    
    Args:
        doc_type: 文件类型（安全交底/技术交底/施工方案等）
        equipment: 设备名称
        project_id: 项目ID
        extra_data: 额外数据
    
    Returns:
        生成结果
    """
    # 查找该类型的模板
    result = list_templates(doc_type)
    templates = result.get("templates", [])
    
    if not templates:
        return {
            "ok": False,
            "error": f"未找到「{doc_type}」类型的模板，请先上传模板",
            "suggestion": f"在模板管理区上传一个Word模板，并将类型设为「{doc_type}」",
        }
    
    # 使用第一个匹配的模板（使用次数最多的优先）
    templates.sort(key=lambda x: x.get("use_count", 0), reverse=True)
    template = templates[0]
    
    return render_template(
        template_id=template["id"],
        equipment=equipment,
        project_id=project_id,
        extra_data=extra_data,
    )


# ================= v0.1.164：模板网页预览 + 国标样式 =================

# 预览页样式（国家文件标准版式：黑体标题、宋体正文、实线表格、A4 页宽模拟）
TEMPLATE_PREVIEW_CSS = """<style>
.tpl-preview{font-family:'SimSun','宋体',serif;color:#000;max-width:165mm;margin:0 auto;background:#fff;padding:30px 26px 34px;line-height:1.5;font-size:12pt}
.tpl-preview h3{font-family:'SimHei','黑体',sans-serif;font-size:16pt;font-weight:700;text-align:center;margin:10px 0 6px}
.tpl-preview p{margin:3px 0;font-size:12pt}
.tpl-preview p.c{text-align:center}
.tpl-preview table{border-collapse:collapse;width:100%;margin:8px 0;font-size:10.5pt}
.tpl-preview th,.tpl-preview td{border:1px solid #000;padding:3px 6px;vertical-align:middle;word-break:break-all}
.tpl-preview th{font-family:'SimHei','黑体',sans-serif;font-weight:700;text-align:center;background:#f5f5f5}
.tpl-preview .ph{color:#C0392B;background:#FFF3C4;font-weight:700;border-bottom:1px dashed #C0392B;padding:0 2px}
.tpl-preview .empty{color:#999;text-align:center}
</style>
<div class="tpl-preview">
"""


def preview_template_html(tpl_id: str) -> Dict:
    """v0.1.164：网页版模板预览——把模板 docx 渲染为符合国家文件标准的 HTML。

    按文档顺序解析段落与表格，占位符 {{字段}} 高亮标注，标题黑体、
    正文宋体、表格实线边框，A4 页宽模拟（GB/T 9704 版式）。
    支持模板库（data/templates 注册模板）与 templates_builtin 内置模板。
    """
    if not HAS_DOCX:
        return {"ok": False, "error": "python-docx 未安装，无法预览模板"}
    index = _load_template_index()
    info = None
    for t in index.get("templates", []):
        if t.get("id") == tpl_id or t.get("name") == tpl_id:
            info = t
            break
    if not info:
        return {"ok": False, "error": "模板不存在，请刷新列表后重试"}
    path = info.get("file_path") or ""
    if not path or not os.path.isfile(path):
        alt = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "templates_builtin",
            (info.get("name") or "") + ".docx")
        if os.path.isfile(alt):
            path = alt
    if not path or not os.path.isfile(path):
        return {"ok": False, "error": "模板文件丢失，无法预览"}
    if not path.lower().endswith(".docx"):
        return {"ok": False, "error": "该模板为 %s 格式，网页预览仅支持 docx" % os.path.splitext(path)[1]}

    from docx.text.paragraph import Paragraph
    from docx.table import Table
    from docx.oxml.ns import qn

    def _esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _ph(s):
        def rep(m):
            return '<span class="ph">{{%s}}</span>' % _esc(m.group(1))
        return re.sub(r"\{\{([^}]+)\}\}", rep, _esc(s))

    def _para_html(p):
        txt = "".join(r.text for r in p.runs)
        if not txt.strip():
            return ""
        align = p.alignment
        is_title = len(txt.strip()) <= 40 and (align == 1 or any(r.bold for r in p.runs if r.text.strip()))
        if is_title:
            return "<h3>%s</h3>" % _ph(txt.strip())
        return '<p%s>%s</p>' % (" class='c'" if align == 1 else "", _ph(txt.strip()))

    def _table_html(tbl):
        rows = list(tbl.rows)
        if not rows:
            return "<table></table>"
        parts = ["<table>"]
        seen_prev = set()
        for row in rows:
            parts.append("<tr>")
            seen = set()
            for cell in row.cells:
                if id(cell._tc) in seen:
                    continue
                seen.add(id(cell._tc))
                txts = []
                for p in cell.paragraphs:
                    t = "".join(r.text for r in p.runs).strip()
                    if t:
                        txts.append(t)
                ctxt = " ".join(txts)
                tag = "th" if row is rows[0] else "td"
                parts.append("<%s>%s</%s>" % (tag, _ph(ctxt or "&nbsp;"), tag))
            parts.append("</tr>")
        parts.append("</table>")
        return "".join(parts)

    try:
        doc = Document(path)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "打开模板失败：%s" % str(e)}

    parts = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            parts.append(_para_html(Paragraph(child, doc)))
        elif child.tag == qn("w:tbl"):
            parts.append(_table_html(Table(child, doc)))

    body = "\n".join(parts) or "<p class='empty'>（空模板，无内容可预览）</p>"
    fields = sorted(set(m.group(1).strip() for m in re.finditer(r"\{\{([^}]+)\}\}", body)))
    return {
        "ok": True,
        "name": info.get("name", ""),
        "doc_type": info.get("doc_type", ""),
        "placeholder_count": len(fields),
        "fields": fields,
        "html": TEMPLATE_PREVIEW_CSS + body + "</div>",
    }


def _apply_national_style(doc) -> None:
    """v0.1.164：国标样式规整（仅作用于生成副本，不修改源模板）。

    按 GB/T 9704-2012《党政机关公文格式》及工程资料通用版式：
    页边距 上3.7cm/下3.5cm/左2.8cm/右2.6cm；标题黑体16pt居中、
    正文宋体12pt；表格实线边框、表头行加粗居中、表内文字五号(10.5pt)。
    """
    try:
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        from docx.enum.text import WD_ALIGN_PARAGRAPH as _ALIGN

        for section in doc.sections:
            section.top_margin = Cm(3.7)
            section.bottom_margin = Cm(3.5)
            section.left_margin = Cm(2.8)
            section.right_margin = Cm(2.6)

        def _set_font(run, ea, size, bold=None):
            try:
                run.font.name = ea
                run.font.size = Pt(size)
                if bold is not None:
                    run.font.bold = bold
                rPr = run._element.get_or_add_rPr()
                rFonts = rPr.get_or_add_rFonts()
                rFonts.set(qn("w:eastAsia"), ea)
            except Exception:  # noqa: BLE001
                pass

        for para in doc.paragraphs:
            txt = "".join(r.text for r in para.runs).strip()
            if not txt:
                continue
            is_title = len(txt) <= 30 and any(r.bold for r in para.runs if r.text.strip())
            for r in para.runs:
                _set_font(r, "黑体" if is_title else "宋体", 16 if is_title else 12, None)
            if is_title:
                para.alignment = _ALIGN.CENTER

        for table in doc.tables:
            tbl = table._tbl
            tblPr = tbl.tblPr
            borders = tblPr.find(qn("w:tblBorders"))
            if borders is None:
                borders = OxmlElement("w:tblBorders")
                tblPr.append(borders)
            for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                el = borders.find(qn("w:" + edge))
                if el is None:
                    el = OxmlElement("w:" + edge)
                    borders.append(el)
                el.set(qn("w:val"), "single")
                el.set(qn("w:sz"), "4")
                el.set(qn("w:color"), "000000")
            for ri, row in enumerate(table.rows):
                for cell in row.cells:
                    for p in cell.paragraphs:
                        for r in p.runs:
                            _set_font(r, "宋体", 10.5, True if ri == 0 else None)
                        if ri == 0:
                            p.alignment = _ALIGN.CENTER
    except Exception:  # noqa: BLE001
        pass
