# 繁工AI 本地解析工作台 - 深度解析引擎
# 设计：按文件类型分派解析器；每个解析器输出统一结构 ParseResult；
# 可选依赖（OCR/CAD）缺失时优雅降级，不影响主链路。
# 优先级（v3.6 口径）：Project → 表格台账 → 图片OCR → CAD图纸

import os
import re
import json
import hashlib
import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

from app import config


# ============ 统一结果结构 ============
@dataclass
class ParseResult:
    file_path: str                 # 原始路径
    file_name: str                 # 文件名
    file_size: int                 # 字节
    sha256: str                    # 文件哈希（去重/云端合并用）
    ext: str                       # 扩展名
    parser: str                    # 解析器名
    status: str = "parsed"         # parsed / partial / skipped / failed
    error: Optional[str] = None    # 失败原因
    text: str = ""                 # 提取的全文（用于向量化）
    structure: dict = field(default_factory=dict)   # 结构化结果（表头/行/任务树/标题栏等）
    entities: list = field(default_factory=list)    # 浅层实体（设备位号等）
    chunks: list = field(default_factory=list)      # 分块（由向量化步骤填充）
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


# ============ 实体浅提取（位号/编号） ============
_TAG_RE = re.compile(config.EQUIPMENT_TAG_RE)


def extract_entities(text: str, limit: int = 200) -> list:
    """从文本中提取疑似设备位号（浅层，后续由云端图谱归并）。"""
    seen, out = set(), []
    for m in _TAG_RE.finditer(text or ""):
        tag = m.group(1)
        if tag not in seen:
            seen.add(tag)
            out.append({"type": "equipment", "tag": tag})
        if len(out) >= limit:
            break
    return out


# ============ 解析器注册表（优先级：Project → 表格台账 → 图片OCR → CAD → PDF/Word/Text） ============
def _pick_parser(ext: str):
    if ext in config.EXT_PROJECT and config.PARSE_PROJECT:
        return parse_project
    if ext in config.EXT_EXCEL and config.PARSE_EXCEL:
        return parse_excel
    if ext in config.EXT_IMAGE and config.PARSE_IMAGE:
        return parse_image
    if ext in config.EXT_CAD and config.PARSE_CAD:
        return parse_cad
    if ext in config.EXT_PDF and config.PARSE_PDF:
        return parse_pdf
    if ext in config.EXT_WORD and config.PARSE_WORD:
        return parse_word
    if ext in config.EXT_TEXT and config.PARSE_TEXT:
        return parse_text
    return None


def parse_file(path: str) -> ParseResult:
    """按扩展名分派解析。无法解析的类型返回 skipped。"""
    ext = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)
    size = os.path.getsize(path)
    res = ParseResult(
        file_path=path, file_name=name, file_size=size,
        sha256=sha256_of_file(path), ext=ext, parser="none",
    )
    parser = _pick_parser(ext)
    if parser is None:
        res.status = "skipped"
        res.parser = "unsupported"
        res.error = "该类型当前未启用解析（可在 config.py 开启或安装可选依赖）"
        return res
    try:
        parser(res)
        if not res.text and not res.structure:
            res.status = "partial"
        res.entities = extract_entities(res.text)
    except ImportError as e:
        res.status = "skipped"
        res.error = f"缺少依赖：{e}。请按 README 安装可选依赖后重启"
    except Exception as e:  # noqa: BLE001
        res.status = "failed"
        res.error = f"{type(e).__name__}: {e}"
    return res


# ============ PDF（文本 + 表格；pdfplumber 缺失时降级为纯文本） ============
def parse_pdf(res: ParseResult):
    from pypdf import PdfReader
    res.parser = "pdf"
    reader = PdfReader(res.file_path)
    parts = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
        if t.strip():
            parts.append(f"【第{i+1}页】\n{t}")
    res.text = "\n\n".join(parts)
    tables = _extract_pdf_tables(res.file_path)
    if tables:
        for ti, tb in enumerate(tables):
            parts.append(f"【PDF表格{ti+1}】\n" + "\n".join(" | ".join(row) for row in tb))
        res.text = "\n\n".join(parts)
    res.structure = {
        "page_count": len(reader.pages),
        "text_chars": len(res.text),
        "tables": tables[:50],
    }
    if not res.text:
        res.status = "partial"
        res.error = "PDF 无可提取文本层（可能是扫描件，建议启用 OCR）"


def _extract_pdf_tables(path: str) -> list:
    """用 pdfplumber 提取跨页表格（可选依赖；缺失/失败时返回空，不影响主流程）。
    先按画线识别；无边框表格（常见于导出的 PDF）再用文本策略兜底。"""
    try:
        import pdfplumber
    except ImportError:
        return []

    def _run(table_settings=None):
        out = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for tb in page.extract_tables(table_settings=table_settings):
                    rows = [[(c or "").replace("\n", " ").strip() for c in row] for row in tb]
                    if any(any(c for c in row) for row in rows):
                        out.append(rows)
        return out

    try:
        out = _run()
        if out:
            return out
        # 无画线表格 → 按文本对齐策略识别
        return _run({"vertical_strategy": "text", "horizontal_strategy": "text"})
    except Exception:  # noqa: BLE001
        return []


# ============ Word ============
def parse_word(res: ParseResult):
    import docx
    res.parser = "word"
    doc = docx.Document(res.file_path)
    parts = []
    for p in doc.paragraphs:
        if p.text.strip():
            parts.append(p.text)
    tables = []
    for ti, tb in enumerate(doc.tables):
        rows = []
        for row in tb.rows:
            rows.append([c.text.strip() for c in row.cells])
        tables.append({"sheet": f"表格{ti+1}", "rows": rows})
        for row in rows:
            parts.append(" | ".join(row))
    res.text = "\n".join(parts)
    res.structure = {"paragraphs": len(doc.paragraphs), "tables": tables}


# ============ Excel（台账结构化，v3.6 核心） ============
def _normalize_header(cells):
    """表头归一：合并单元格/多行表头 → 取首个非空作为列名；同名列自动加序号去重。"""
    out = []
    seen = {}
    for c in cells:
        v = (c or "").strip()
        name = v if v else f"列{len(out)+1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out


def parse_excel(res: ParseResult):
    import openpyxl
    res.parser = "excel"
    wb = openpyxl.load_workbook(res.file_path, read_only=True, data_only=True)
    sheets = []
    text_parts = []
    for ws in wb.worksheets:
        rows_iter = ws.iter_rows(values_only=True)
        all_rows = [list(r) for r in rows_iter if any(v is not None and str(v).strip() for v in r)]
        if not all_rows:
            continue
        header = _normalize_header([str(v) if v is not None else "" for v in all_rows[0]])
        data_rows = []
        for r in all_rows[1:]:
            row = {}
            for i, v in enumerate(r):
                if i < len(header) and v is not None:
                    row[header[i]] = str(v).strip()
            if row:
                data_rows.append(row)
        sheets.append({
            "sheet": ws.title,
            "header": header,
            "row_count": len(data_rows),
            "rows": data_rows[:500],          # 前端展示上限
        })
        text_parts.append(f"【工作表：{ws.title}】")
        text_parts.append(" | ".join(header))
        for row in data_rows[:1000]:
            text_parts.append(" | ".join(f"{k}={v}" for k, v in row.items()))
    wb.close()
    res.text = "\n".join(text_parts)
    res.structure = {"sheets": sheets, "total_rows": sum(s["row_count"] for s in sheets)}


# ============ 文本 ============
def parse_text(res: ParseResult):
    res.parser = "text"
    with open(res.file_path, "r", encoding="utf-8", errors="ignore") as f:
        res.text = f.read()
    res.structure = {"chars": len(res.text)}


# ============ 图片 OCR（可选，需 PaddleOCR） ============
_ocr_engine = None


def _get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        from paddleocr import PaddleOCR
        _ocr_engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    return _ocr_engine


def parse_image(res: ParseResult):
    res.parser = "ocr"
    ocr = _get_ocr()
    result = ocr.ocr(res.file_path, cls=True)
    lines = []
    blocks = []
    for page in result or []:
        for item in page or []:
            box, (text, conf) = item
            lines.append(text)
            blocks.append({"text": text, "conf": round(float(conf), 3), "box": box})
    res.text = "\n".join(lines)
    res.structure = {"blocks": blocks, "line_count": len(lines)}


# ============ CAD（可选，需 ezdxf；DWG 需 ODA 转 DXF） ============
def parse_cad(res: ParseResult):
    import ezdxf
    res.parser = "cad"
    path = res.file_path
    if path.lower().endswith(".dwg"):
        # 尝试调用 ODA File Converter（用户在 PATH 或指定目录安装）
        converted = _dwg_to_dxf(path)
        if not converted:
            res.status = "failed"
            res.error = "DWG 需先安装 ODA File Converter 并配置转换（见 README），或先用 AutoCAD 另存为 DXF"
            return
        path = converted
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    texts = []
    tags = []
    labels = []      # 文本+坐标（为空间结构库打底）
    for e in msp:
        t = e.dxftype()
        if t == "TEXT":
            texts.append(e.dxf.text)
            labels.append({"text": e.dxf.text, "x": round(e.dxf.insert.x, 2), "y": round(e.dxf.insert.y, 2)})
        elif t == "MTEXT":
            texts.append(e.plain_text())
            labels.append({"text": e.plain_text(), "x": round(e.dxf.insert.x, 2), "y": round(e.dxf.insert.y, 2)})
        elif t == "INSERT":
            tags.append({"block": e.dxf.name, "x": round(e.dxf.insert.x, 2), "y": round(e.dxf.insert.y, 2)})
    # 图框/标题栏粗识别：取右下角区域（常见标题栏位置）的文本作为图纸标题候选
    if labels:
        labels.sort(key=lambda p: (p["x"], -p["y"]))
    res.text = "\n".join(texts)
    res.structure = {
        "text_labels": labels[:500],
        "block_inserts": tags[:500],
        "version": doc.dxfversion,
        "entity_counts": {dt: sum(1 for _ in msp.query(dt)) for dt in ("TEXT", "MTEXT", "INSERT", "LINE")},
    }
    res.entities = extract_entities("\n".join(texts))


def _dwg_to_dxf(dwg_path: str) -> Optional[str]:
    """调用 ODA File Converter 命令行将 DWG 转 DXF；失败返回 None。"""
    import subprocess
    oda = os.environ.get("ODA_CONVERTER", r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe")
    if not os.path.exists(oda):
        return None
    src_dir = os.path.dirname(dwg_path)
    out_dir = os.path.join(src_dir, "_dxf_converted")
    os.makedirs(out_dir, exist_ok=True)
    # ODAFileConverter 输入目录 输出目录 输出版本 输出类型 递归 审计
    cmd = [oda, src_dir, out_dir, "ACAD2018", "DXF", "0", "1"]
    try:
        subprocess.run(cmd, timeout=180, check=True, capture_output=True)
        base = os.path.splitext(os.path.basename(dwg_path))[0] + ".dxf"
        cand = os.path.join(out_dir, base)
        return cand if os.path.exists(cand) else None
    except Exception:  # noqa: BLE001
        return None


# ============ Project 计划（.xml，纯 Python；.mpp 需先另存为 XML） ============
def _project_link_uid(task_elem, ns) -> str:
    """取 PredecessorLink 下的 PredecessorUID 子元素（前置任务编号）。"""
    link = task_elem.find("p:PredecessorLink", ns)
    if link is None:
        return ""
    uids = [e.text or "" for e in link.findall("p:PredecessorUID", ns) if e.text]
    return ",".join(uids)


def parse_project(res: ParseResult):
    import xml.etree.ElementTree as ET
    res.parser = "project"
    tree = ET.parse(res.file_path)
    root = tree.getroot()
    ns = {"p": "http://schemas.microsoft.com/project"}

    # 任务：名称 / WBS / 开始完成 / 工期 / 前置任务 / 里程碑
    tasks = []
    for t in root.findall(".//p:Task", ns):
        def g(tag):
            e = t.find(f"p:{tag}", ns)
            return (e.text or "").strip() if e is not None and e.text else ""
        task = {
            "id": g("UID"),
            "name": g("Name"),
            "wbs": g("WBS"),
            "start": g("Start"),
            "finish": g("Finish"),
            "duration": g("Duration"),
            "predecessors": g("PredecessorLink") or g("Predecessors")
                or _project_link_uid(t, ns),
            "milestone": g("Milestone"),
        }
        if task["name"]:
            tasks.append(task)

    text_parts = []
    for t in tasks:
        line = " | ".join(f"{k}={v}" for k, v in t.items() if v)
        text_parts.append(line)
    res.text = "\n".join(text_parts)
    res.structure = {"tasks": tasks, "task_count": len(tasks)}
    if not tasks:
        res.status = "partial"
        res.error = "未解析到任务，确认文件是 MS Project 导出的 XML（文件头含 <Project>）"
