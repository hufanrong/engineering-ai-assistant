# 繁工AI 本地解析工作台 - 深度解析引擎
# 设计：按文件类型分派解析器；每个解析器输出统一结构 ParseResult；
# 可选依赖（OCR/CAD）缺失时优雅降级，不影响主链路。
# 优先级（v3.6 口径）：Project → 表格台账 → 图片OCR → CAD图纸

import os
import re
import time
import json
import hashlib
import datetime
from dataclasses import dataclass, field, asdict
from html.parser import HTMLParser   # v0.1.224：解析「假 .xls」（内容为 HTML 表格）
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


_PARAM_RE = re.compile(
    r"(?:流量|扬程|功率|电压|电流|转速|重量|介质|温度|压力|频率|防爆等级|防护等级|绝缘等级|出厂编号|出厂日期|重量|容积|材质)"
    r"\s*[:：]?\s*[0-9A-Za-z./×xX·\-~～%℃m³kgKVWkWh]*")
_MFR_RE = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,20}?(?:有限公司|股份公司|制造厂|机械厂|实业公司|集团)")


def extract_entities(text: str, limit: int = 200) -> list:
    """从文本中提取实体：设备位号 / 铭牌参数 / 厂家 / 车间。
    浅层提取，后续由云端图谱归并去重。"""
    seen, out = set(), []
    for m in _TAG_RE.finditer(text or ""):
        tag = m.group(1)
        if tag not in seen:
            seen.add(tag)
            out.append({"type": "equipment", "tag": tag})
        if len(out) >= limit:
            break
    if len(out) < limit:
        for m in _PARAM_RE.finditer(text or ""):
            kv = m.group(0).strip()
            key = kv.split("：")[0].split(":")[0].strip()
            if kv not in seen:
                seen.add(kv)
                out.append({"type": "parameter", "name": key, "value": kv})
            if len(out) >= limit:
                break
    if len(out) < limit:
        for m in _MFR_RE.finditer(text or ""):
            v = m.group(0)
            if v not in seen:
                seen.add(v)
                out.append({"type": "manufacturer", "name": v})
            if len(out) >= limit:
                break
    if len(out) < limit:
        for m in re.finditer(r"\d+\s*号\s*车间", text or ""):
            v = m.group(0)
            if v not in seen:
                seen.add(v)
                out.append({"type": "workshop", "name": v})
            if len(out) >= limit:
                break
    return out


# ============ 解析器注册表（优先级：Project → 表格台账 → 图片OCR → CAD → PDF/Word/Text） ============
def _effective(switch: bool, dep: str) -> bool:
    """有效开关：自动探测开启且依赖已装 → 直接启用（全套部署免配置）；
    否则按 config 里的开关。"""
    if config.AUTO_DETECT_OPTIONAL and config.OPTIONAL_READY.get(dep, False):
        return True
    return switch


def _pick_parser(ext: str):
    if ext in config.EXT_PROJECT and config.PARSE_PROJECT:
        return parse_project
    # v0.1.224：.xls（Excel 97-2003）必须走 xlrd，openpyxl 读不了老格式；
    # 判定放在 EXT_EXCEL 之前，否则会落到 openpyxl 分支直接抛异常。
    if ext == ".xls" and config.PARSE_EXCEL:
        return parse_xls
    if ext in config.EXT_EXCEL and config.PARSE_EXCEL:
        return parse_excel
    if ext == ".csv" and config.PARSE_EXCEL:
        # v0.1.167：CSV 台账按表格结构化解析（原归 EXT_TEXT 只出纯文本，设备台账全丢）
        return parse_csv
    if ext in config.EXT_IMAGE and _effective(config.PARSE_IMAGE, "ocr"):
        return parse_image
    if ext in config.EXT_CAD and _effective(config.PARSE_CAD, "cad"):
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
        if ext in (".rar", ".zip", ".7z", ".tar", ".gz"):
            # 现场真实场景：用户把一批 CAD 图纸压成 rar/zip 直接上传，期望
            # 「传上去就能查」。当前不自动解压，但必须说清原因并给出下一步，
            # 否则用户看到的是一个「跳过了」的文件，不知道该怎么办。
            res.error = ("压缩包当前不自动解压：请先在电脑上解压，"
                         "再把里面的 pdf/dwg/xlsx 上传（解压后微信/QQ 传来的 "
                         "dwg 也能按车间自动归类）")
        else:
            res.error = "该类型当前未启用解析（可在 config.py 开启或安装可选依赖）"
        return res
    try:
        parser(res)
        # v0.1.224：解析器自己已经判了 failed 的，不能被这里改回 partial。
        #
        # 实测（2026-11-10 马诺诺真实资料 60 个文件）：本机没装 ODA File Converter，
        # 25 个 DWG 全部走 parse_cad 的「找不到转换器」分支，明确设了
        # status="failed" + error="未找到 ODA File Converter…"；可下一行
        # 「没有 text/structure 就记 partial」无条件把它覆盖成 partial ——
        # 界面上 25 张图显示「部分解析」，用户根本看不出是**缺依赖**，
        # 只会以为图纸内容提取不全。failed 与 partial 是两件事：
        # 前者要装东西/换格式，后者是文件里确实没那么多字。
        if res.status == "parsed" and not res.text and not res.structure:
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
        # v0.1.224：没有文本层不等于没救 —— 先试 OCR，再决定报什么状态。
        #
        # 实测（2026-11-10 马诺诺真实资料）：30 份 PDF 里 16 份是厂家出的
        # 「图形 PDF」（CAD 直接打印，文字被转成曲线，没有文本层），
        # 原文一律 partial + text="" —— 资料库里搜不到，用户以为没传上去。
        # 本机已装 PaddleOCR，所以这里直接兜底识别前几页；
        # 识别出字就按 parsed 入库，识别不出才保留原来的 partial + 提示。
        ocr_text, ocr_note = ("", "")
        try:
            if getattr(config, "PDF_OCR_FALLBACK", False):
                ocr_text, ocr_note = _ocr_pdf_text(res.file_path)
        except Exception as e:  # noqa: BLE001
            ocr_note = f"OCR 失败：{type(e).__name__}: {e}"
        if ocr_text.strip():
            res.text = ocr_text
            st = res.structure if isinstance(res.structure, dict) else {}
            st["ocr_fallback"] = ocr_note or "ok"
            st["text_chars"] = len(res.text)
            res.structure = st
            res.error = None
        else:
            res.status = "partial"
            res.error = ("PDF 无可提取文本层（图形 PDF/扫描件）；"
                         f"已尝试 OCR 未取得文字{'（' + ocr_note + '）' if ocr_note else ''}。"
                         "建议改用原始 dwg 或另存为带文字的 PDF")


def _ocr_pdf_text(path: str, max_pages: int = 3, dpi: int = 150,
                  budget_s: float = 120.0) -> tuple:
    """把 PDF 前几页渲染成图片再 OCR，返回 (文本, 说明)。

    限量而非全量：一张 A1 图纸 150dpi 约 2500x1700，PaddleOCR 单页 3~8 秒。
    16 份 PDF × 全部页数会把一次扫描拖到几十分钟，现场等不起；
    取前 3 页足够拿到图号、设备名称、主要标注 —— 检索要的是「这份图讲什么」。

    失败即熔断：本机实测（2026-11-10）PaddleOCR 3.x 在这台机器上 predict 直接抛
        NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support
        [pir::ArrayAttribute<pir::DoubleAttribute>] (onednn_instruction.cc:118)
    这是 PaddlePaddle 的 oneDNN 后端问题（设 FLAGS_use_mkldnn=0 也不解决），
    与 PDF 本身无关。一次熔断后本进程内不再重试 —— 否则每份图形 PDF 都要
    白等 2~3 秒，一次扫描 16 份就是 40 秒纯浪费，还会让人以为是「文件坏了」。
    """
    global _OCR_PDF_DISABLED
    if _OCR_PDF_DISABLED:
        return "", _OCR_PDF_DISABLED
    # v0.1.227：先看 Tesseract 能不能用（本机唯一稳定可用的引擎），
    # 能用就完全不走 PaddleOCR —— 否则每份图形 PDF 都要先等 Paddle 崩一次。
    _tess = (_find_external_tools().get("tesseract") or "")
    ocr = None
    try:
        import tempfile
        import pymupdf as fitz

        if _tess:
            pass
        else:
            ocr = _get_ocr()
    except Exception as e:  # noqa: BLE001
        _OCR_PDF_DISABLED = f"OCR 引擎不可用：{type(e).__name__}: {e}"
        return "", _OCR_PDF_DISABLED
    t0 = time.time()
    lines = []
    used = 0
    with tempfile.TemporaryDirectory(prefix="fg_ocr_") as td:
        doc = fitz.open(path)
        try:
            n = min(max_pages, doc.page_count if hasattr(doc, "page_count") else len(doc))
            for i in range(n):
                if time.time() - t0 > budget_s:
                    break
                pix = doc[i].get_pixmap(dpi=dpi)
                img = os.path.join(td, f"p{i}.png")
                pix.save(img)
                used += 1
                if _tess:
                    txt_i, _why = _ocr_png_with_tesseract(img)
                    if txt_i:
                        lines.extend([ln.strip() for ln in txt_i.splitlines() if ln.strip()])
                        continue
                    # Tesseract 这张没出字：不熔断，可能只是这一页空白
                    continue
                try:
                    result = ocr.ocr(img, cls=True)
                    for page in result or []:
                        for item in page or []:
                            try:
                                txt = item[1][0]
                            except Exception:  # noqa: BLE001
                                continue
                            if txt and txt.strip():
                                lines.append(txt.strip())
                except Exception:  # noqa: BLE001 —— PaddleOCR 3.x 走 predict
                    try:
                        out = ocr.predict(img)
                        for blk in out or []:
                            texts = blk.get("rec_texts") if isinstance(blk, dict) else None
                            for txt in texts or []:
                                if txt and str(txt).strip():
                                    lines.append(str(txt).strip())
                    except Exception as e2:  # noqa: BLE001
                        # 引擎级故障（见 docstring 里的 oneDNN 报错）→ 熔断，
                        # 本进程后面所有 PDF 直接返回原因，不再逐个白等。
                        _OCR_PDF_DISABLED = f"OCR 引擎故障已熔断：{type(e2).__name__}: {str(e2)[:120]}"
                        break
        finally:
            try:
                doc.close()
            except Exception:  # noqa: BLE001
                pass
    _eng_name = "tesseract" if _tess else "paddleocr"
    note = (f"{_eng_name} OCR 前 {used} 页，{len(lines)} 行，{time.time() - t0:.1f}s"
            if not _OCR_PDF_DISABLED else _OCR_PDF_DISABLED)
    return "\n".join(lines), note


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
    """表头归一：合并单元格/多行表头 → 取首个非空作为列名；同名列自动加序号去重。
    v0.1.167：剥离 UTF-8 BOM 与零宽字符 —— BOM 前缀会让首列名变成 "\ufeff位号"，
    与下游关键词表（位号/名称/规格…）对不上，导致 CSV/xlsx 台账首列（位号）整列丢失。"""
    out = []
    seen = {}
    for c in cells:
        v = (c or "").strip().lstrip("\ufeff").strip()
        v = v.replace("\u200b", "").replace("\u3000", " ").strip()
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
            "rows": data_rows[:500],          # 前端展示上限（数据全量保留在row_count）
        })
        text_parts.append(f"【工作表：{ws.title}】")
        text_parts.append(" | ".join(header))
        # v0.1.129：文本全量入向量库（原仅前1000行），长台账后段不再丢失
        for row in data_rows:
            text_parts.append(" | ".join(f"{k}={v}" for k, v in row.items()))
    wb.close()
    res.text = "\n".join(text_parts)
    res.structure = {"sheets": sheets, "total_rows": sum(s["row_count"] for s in sheets)}


# ============ XLS（老版 Excel 97-2003，v0.1.224 新增） ============
def parse_xls(res: ParseResult):
    """老版 .xls（Excel 97-2003）结构化解析，输出与 parse_excel 完全同构。

    为什么必须补：现场真实资料里大量箱单、设备表还是 .xls，而 config 原来只认
    .xlsx/.xlsm —— 用户上传后一律被判 unsupported、状态「跳过」，台账内容一个字
    都进不了库。实测 2026-11-10 项目 0c9a4b2d（马诺诺）真实资料：
        熟料粉末斗提机.xls / 江西华欣拉链机箱单.xls / 滁州安瑞链板称箱单.xls
    这 3 个文件上传后 status=skipped，用户在原话里问「我连工作台都看不到，
    怎么上传资料」—— 传了查不到，等于没传。

    两条真实分支（现场两种都遇到过，缺一条就有一批文件解析不出来）：
      ① 真 BIFF 格式 → xlrd；
      ② 后缀是 .xls、内容其实是 HTML 表格 —— 国内 ERP/电商/物流系统
         「导出 Excel」出来的就是这种东西（文件头是 `<html xmlns:o=...>`）。
         实测上面 3 个 .xls 全部是这种，xlrd 直接抛
         `Expected BOF record; found b'<html xm'`。

    structure 与 parse_excel 同构（sheets/header/rows/row_count/total_rows），
    且 parser 标 "excel"，使 equipment_merge 按 parser=="excel" 取台账行的
    下游逻辑对 .xls 一样生效（与 v0.1.167 处理 .csv 的做法一致）。
    """
    res.parser = "excel"
    if _looks_like_html(res.file_path):
        _parse_html_table(res)
        return
    try:
        import xlrd
        wb = xlrd.open_workbook(res.file_path)
    except Exception as e:  # noqa: BLE001
        # xlrd 认不出来，但内容可能是 HTML/XML 表格（见上②）；仍不行就把原始
        # 异常抛上去，让上层记 failed 并保留错误原因，不做静默降级。
        if _looks_like_html(res.file_path):
            _parse_html_table(res)
            return
        raise
    sheets = []
    text_parts = []
    for si in range(wb.nsheets):
        ws = wb.sheet_by_index(si)
        all_rows = []
        for r in range(ws.nrows):
            vals = [_xls_cell_text(ws.cell_value(r, c)) for c in range(ws.ncols)]
            if any(v.strip() for v in vals):
                all_rows.append(vals)
        if not all_rows:
            continue
        header = _normalize_header(all_rows[0])
        data_rows = []
        for r in all_rows[1:]:
            row = {}
            for i, v in enumerate(r):
                if i < len(header) and v.strip():
                    row[header[i]] = v.strip()
            if row:
                data_rows.append(row)
        sheets.append({
            "sheet": ws.name,
            "header": header,
            "row_count": len(data_rows),
            "rows": data_rows[:500],
        })
        text_parts.append(f"【工作表：{ws.name}】")
        text_parts.append(" | ".join(header))
        for row in data_rows:
            text_parts.append(" | ".join(f"{k}={v}" for k, v in row.items()))
    res.text = "\n".join(text_parts)
    res.structure = {"sheets": sheets, "total_rows": sum(s["row_count"] for s in sheets)}


def _xls_cell_text(v) -> str:
    """xlrd 单元格值转字符串：整数值的 float 去掉 '.0'（数量 12 不能变成 12.0）。"""
    if v is None:
        return ""
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return str(v)
    return str(v)


def _looks_like_html(path: str) -> bool:
    """文件头判断「后缀是表格、内容其实是网页表格」（国内系统导出的 .xls 常见）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    head = head.lstrip(b"\xef\xbb\xbf").lstrip()
    low = head[:1024].lower()
    return low.startswith(b"<html") or low.startswith(b"<table") \
        or b"<html" in low or b"<table" in low


class _TableCollector(HTMLParser):
    """从 HTML 里抓所有 <table> 的行列文本（只用标准库，不新增依赖）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._depth = 0
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            self.tables.append([])
        elif self._depth and tag == "tr":
            self._row = []
        elif self._depth and tag in ("td", "th"):
            self._cell = []
        elif self._depth and tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag == "table" and self._depth:
            self._depth -= 1
            self._row = None
            self._cell = None
        elif self._depth and tag == "tr":
            if self._row is not None and any(c.strip() for c in self._row):
                self.tables[-1].append(self._row)
            self._row = None
        elif self._depth and tag in ("td", "th") and self._cell is not None:
            if self._row is None:
                self._row = []
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _read_full_text(path: str) -> str:
    """整文件解码（utf-8 → gb18030 → latin1），不截断 —— 表格动辄几百 KB。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8", "gb18030", "latin1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _parse_html_table(res: ParseResult):
    """解析 HTML 表格 → 与 parse_excel 同构的 structure.sheets。"""
    html = _read_full_text(res.file_path)
    tc = _TableCollector()
    try:
        tc.feed(html)
    except Exception:  # noqa: BLE001
        pass
    sheets = []
    text_parts = []
    for ti, rows in enumerate(tc.tables):
        rows = [[c.strip() for c in r] for r in rows]
        rows = [r for r in rows if any(r)]
        if len(rows) < 2:
            continue
        header = _normalize_header(rows[0])
        data_rows = []
        for r in rows[1:]:
            row = {}
            for i, v in enumerate(r):
                if i < len(header) and v:
                    row[header[i]] = v
            if row:
                data_rows.append(row)
        sheets.append({
            "sheet": f"表格{ti + 1}",
            "header": header,
            "row_count": len(data_rows),
            "rows": data_rows[:500],
        })
        text_parts.append(f"【表格{ti + 1}】")
        text_parts.append(" | ".join(header))
        for row in data_rows:
            text_parts.append(" | ".join(f"{k}={v}" for k, v in row.items()))
    res.text = "\n".join(text_parts)
    res.structure = {"sheets": sheets,
                     "total_rows": sum(s["row_count"] for s in sheets),
                     "source_format": "html"}


# ============ CSV（台账结构化，v0.1.167 新增） ============
def parse_csv(res: ParseResult):
    """CSV 台账结构化解析。

    v0.1.167：修复缺陷 —— .csv 原先归入 EXT_TEXT 走 parse_text，只产出纯文本、
    没有 structure.sheets，导致 equipment_merge（按 parser=="excel" 逐行取
    位号/名称）完全读不到 CSV 设备台账，台账里的设备全部丢失。
    这里复用 excel 的行结构（structure.sheets），并把 parser 标为 "excel"，
    使下游（设备归并 / 关系图 / 空间模型 / 标高）对台账文件的处理保持一致，
    与 xlsx 行为对齐；解析失败时优雅回退到纯文本，不阻塞扫描。
    """
    import csv
    res.parser = "excel"
    text = _read_text_auto(res.file_path)
    try:
        # utf-8-sig 已在 _read_text_auto 里通过 utf-8 解码带 BOM 的情况兼容
        lines = text.splitlines()
        rows = list(csv.reader(lines))
        rows = [[c.strip() for c in r] for r in rows if any(c.strip() for c in r)]
        if not rows:
            res.text = text
            res.structure = {"chars": len(text), "sheets": [], "csv_fallback": "empty"}
            return
        header = _normalize_header(rows[0])
        data_rows = []
        for r in rows[1:]:
            row = {}
            for i, v in enumerate(r):
                if i < len(header) and v:
                    row[header[i]] = v
            if row:
                data_rows.append(row)
        res.structure = {
            "sheets": [{
                "sheet": os.path.splitext(res.file_name)[0],
                "header": header,
                "row_count": len(data_rows),
                "rows": data_rows[:500],
            }],
            "total_rows": len(data_rows),
            "csv": True,
        }
        parts = [" | ".join(header)]
        for row in data_rows:
            parts.append(" | ".join(f"{k}={v}" for k, v in row.items()))
        res.text = "\n".join(parts)
    except Exception as e:  # noqa: BLE001
        # CSV 格式异常不致命：退回纯文本，至少能进资料库被检索
        res.text = text
        res.structure = {"chars": len(text), "csv_error": f"{type(e).__name__}: {e}"[:200]}


# ============ 文本 ============
def _read_text_auto(path: str) -> str:
    """v0.1.129：自动探测文本编码（utf-8 → gbk/gb18030 → latin1），
    解决中文 GBK 编码 txt/csv 乱码问题。"""
    with open(path, "rb") as f:
        raw = f.read(65536)
    for enc in ("utf-8", "gb18030", "latin1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", errors="ignore")


def parse_text(res: ParseResult):
    res.parser = "text"
    res.text = _read_text_auto(res.file_path)
    res.structure = {"chars": len(res.text)}


# ============ 图片 OCR（可选，需 PaddleOCR） ============
_ocr_engine = None


# v0.1.224：PDF 无文本层时的 OCR 兜底熔断标记。空串=可用；
# 非空=本进程内已判定引擎不可用，原因就存在这里（见 _ocr_pdf_text）。
_OCR_PDF_DISABLED = ""


def _tessdata_dir():
    """返回可用的 tessdata 目录（含中文字包），没有中文包就返回 ""。

    为什么要在安装目录里放一份：Tesseract 的官方安装包默认只带 eng + osd，
    中文图纸一个字都识别不出来，而装语言包要管理员权限写 Program Files ——
    现场机器往往拿不到。所以随程序带一份 chi_sim（tessdata_fast 2.4MB），
    放在 workbench/ocrdata/，通过 TESSDATA_PREFIX 指过去，免安装、免管理员。

    Tesseract 要求**同一个目录**里放着所有要用的语种，所以首次使用时
    把系统 tessdata 里的 eng/osd 复制过来（不随仓库分发，避免体积翻倍）。
    """
    here = os.path.dirname(os.path.abspath(__file__))       # workbench/parsers
    d = os.path.join(os.path.dirname(here), "ocrdata")      # workbench/ocrdata
    if not os.path.isdir(d) or not os.path.isfile(os.path.join(d, "chi_sim.traineddata")):
        return ""
    sysdirs = []
    tools = _find_external_tools()
    tess = tools.get("tesseract") or ""
    if tess:
        sysdirs.append(os.path.join(os.path.dirname(tess), "tessdata"))
    for s in sysdirs:
        for fn in ("eng.traineddata", "osd.traineddata"):
            dst = os.path.join(d, fn)
            if os.path.isfile(os.path.join(s, fn)) and not os.path.isfile(dst):
                try:
                    import shutil as _sh
                    _sh.copy2(os.path.join(s, fn), dst)
                except Exception:  # noqa: BLE001
                    pass
    return d


def _ocr_png_with_tesseract(png_path):
    """用 Tesseract 识别一张图，返回 (文本, 说明)。不可用时返回 ("", 原因)。

    为什么优先 Tesseract 而不是 PaddleOCR（2026-11-10 本机实测）：
      PaddleOCR 3.7.0 + paddlepaddle 3.3.1 在这台机器上 predict 必崩：
        NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support
        [pir::ArrayAttribute<pir::DoubleAttribute>] (onednn_instruction.cc:118)
      试过 FLAGS_use_mkldnn=0 / FLAGS_enable_pir_api=0/1 三组组合，全部照样崩，
      属 PaddlePaddle 3.3 的 oneDNN 后端缺陷，不是我们代码能修的。
    Tesseract 5.4 同一台机器 1.7~2.7 秒/页，能出数字与部分中文 ——
    对"图纸能不能被搜到"来说，有字远好过 0 字。
      · 识别质量：工程图纸以尺寸数字/符号为主，Tesseract 对成段表格不如
        PaddleOCR，但它至少能把图号、位号、尺寸值带进检索。
    """
    tools = _find_external_tools()
    tess = tools.get("tesseract") or ""
    if not tess:
        return "", "未找到 Tesseract"
    td = _tessdata_dir()
    env = dict(os.environ)
    lang = "eng"
    if td:
        env["TESSDATA_PREFIX"] = td
        lang = "chi_sim+eng"
    try:
        import subprocess
        r = subprocess.run(
            [tess, png_path, "stdout", "-l", lang, "--psm", "11"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, env=env)
        txt = (r.stdout or "").strip()
        if not txt:
            return "", f"Tesseract 无输出（lang={lang}）"
        # 质量闸门：工程图纸上 Tesseract 会吐出大量 "一一|"、"11"、"———" 这类
        # 由线框/标注线引发的噪声。全部收进正文会把检索词表撑爆，也可能喂出
        # 假设备位号。只保留「至少 2 个字母/数字/汉字」的行。
        keep = []
        for ln in txt.splitlines():
            s = ln.strip()
            if sum(1 for ch in s if ch.isalnum()) < 2:
                continue
            keep.append(s)
        if not keep:
            return "", f"Tesseract 只出噪声（lang={lang}）"
        return "\n".join(keep), f"tesseract lang={lang}"
    except Exception as e:  # noqa: BLE001
        return "", f"Tesseract 失败：{type(e).__name__}: {e}"


def _get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        # v0.1.227：**先 import torch，再 import paddleocr**。
        #
        # paddlex 的导入链会走到 modelscope → torch。若 paddle 先加载、torch 后加载，
        # torch/lib/shm.dll 会报 WinError 127「找不到指定的程序」——原因是两者各自
        # 捆绑的 MKL/OpenMP DLL 冲突，后加载的那一方拿不到符号。
        # 实测本机 venv：直接 `import paddleocr` 必崩；先 `import torch` 再导入
        # paddleocr 则正常（torch 2.14.1 → paddleocr 导入 6.0s）。
        # 这一步只解决"导不进来"；predict 的 oneDNN 崩溃见 _ocr_png_with_tesseract
        # 的说明，那是 PaddlePaddle 自身的缺陷，靠 Tesseract 顶上。
        try:
            import torch  # noqa: F401
        except Exception:  # noqa: BLE001
            pass
        from paddleocr import PaddleOCR
        # v0.1.134：PaddleOCR 3.x 移除 use_angle_cls/show_log 参数（2.x 必需）；
        # 先按 3.x 构造，失败再按 2.x 构造，保证两版都可用
        try:
            _ocr_engine = PaddleOCR(lang="ch")
        except Exception:  # noqa: BLE001
            try:
                _ocr_engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
            except Exception:  # noqa: BLE001
                _ocr_engine = PaddleOCR(lang="ch", show_log=False)
    return _ocr_engine


def parse_image(res: ParseResult):
    """图片 OCR：提取文本块（带置信度与位置）→ 铭牌结构化（位号/型号/参数/厂家）→ 全文。
    支持 PaddleOCR 2.x（ocr.ocr）与 3.x（ocr.predict），Tesseract 作首选。
    v0.1.227：优先 Tesseract（中文包随程序带，见 _tessdata_dir）—— 本机
    PaddleOCR predict 必崩（oneDNN 缺陷），不加这条分支图片会一律 failed。"""
    res.parser = "ocr"
    if _find_external_tools().get("tesseract"):
        txt, why = _ocr_png_with_tesseract(res.file_path)
        if txt:
            res.text = txt
            res.structure = {
                "engine": why,
                "line_count": len(txt.splitlines()),
                "plate": {},
                "is_plate": False,
            }
            return
        res.status = "failed"
        res.error = f"OCR 未取得文字：{why}"
        return
    ocr = _get_ocr()
    lines = []
    blocks = []
    try:
        # PaddleOCR 2.x：ocr.ocr(path, cls=True) → [[(box, (text, conf)), ...], ...]
        result = ocr.ocr(res.file_path, cls=True)
        for page in result or []:
            for item in page or []:
                box, (text, conf) = item
                lines.append(text)
                blocks.append({"text": text, "conf": round(float(conf), 3), "box": box})
    except Exception:  # noqa: BLE001 —— 3.x 无 ocr.ocr，走 predict
        try:
            result = ocr.predict(res.file_path)
        except Exception as e:  # noqa: BLE001
            res.status = "failed"
            res.error = f"OCR 失败：{e}"
            return
        for page in result or []:
            # 兼容 dict / 对象 / 嵌套list 三种返回结构
            if isinstance(page, dict):
                texts = page.get("rec_texts") or page.get("rec_text") or []
            elif hasattr(page, "rec_texts"):
                texts = page.rec_texts or []
            elif isinstance(page, (list, tuple)):
                # 嵌套 list：每项可能是 [box, (text, conf)] 或纯文本
                for item in page:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        txt = item[1]
                        if isinstance(txt, (list, tuple)) and txt:
                            txt = txt[0]
                        conf = None
                        if isinstance(item[1], (list, tuple)) and len(item[1]) > 1:
                            conf = item[1][1]
                        lines.append(str(txt))
                        blocks.append({"text": str(txt), "conf": conf, "box": item[0]})
                    elif isinstance(item, str):
                        lines.append(item)
                        blocks.append({"text": item, "conf": None, "box": None})
                continue
            else:
                texts = []
            for item in texts or []:
                # 3.x 的 rec_texts 是纯文本列表；个别版本嵌套 [text, conf]
                if isinstance(item, (list, tuple)):
                    lines.append(str(item[0]))
                    blocks.append({"text": str(item[0]), "conf": item[1] if len(item) > 1 else None, "box": None})
                else:
                    lines.append(str(item))
                    blocks.append({"text": str(item), "conf": None, "box": None})

    full = "\n".join(lines)
    # 铭牌结构化：位号 / 参数 / 厂家
    plate = {
        "tags": [m.group(1) for m in _TAG_RE.finditer(full)][:20],
        "params": [kv for kv in (_m.group(0).strip() for _m in _PARAM_RE.finditer(full))][:30],
        "manufacturers": [m.group(0) for m in _MFR_RE.finditer(full)][:5],
        "workshops": [m.group(0) for m in re.finditer(r"\d+\s*号\s*车间", full)][:5],
    }
    res.text = full
    res.structure = {
        "blocks": blocks, "line_count": len(lines),
        "plate": plate,
        "is_plate": bool(plate["tags"] or plate["params"] or plate["manufacturers"]),
    }


# ============ CAD（可选，需 ezdxf；DWG 需 ODA 转 DXF）
# 深度解析 v2（v0.1.4）：图框检测 + 标题栏键值提取 + 尺寸标注 + 设备块属性 + 图层统计 + 空间结构
# ============
def parse_cad(res: ParseResult):
    import ezdxf
    res.parser = "cad"
    path = res.file_path
    if path.lower().endswith(".dwg"):
        converted = _dwg_to_dxf(path)
        if not converted:
            if _find_oda_converter():
                res.status = "failed"
                res.error = "ODA File Converter 已找到但转换失败：请确认 DWG 文件未损坏、版本受支持；或用 AutoCAD 另存为 DXF 后重传"
            else:
                res.status = "failed"
                res.error = "未找到 ODA File Converter：请安装（自动搜索 Program Files 任意版本目录），或设置环境变量 ODA_CONVERTER 指向 ODAFileConverter.exe，或用 AutoCAD 另存为 DXF"
            return
        path = converted
        # v0.1.144：converted 在 work_dir/out/ 下，清理整个 work_dir（含 in/ DWG 副本）
        _tmp_dxf_root = os.path.dirname(os.path.dirname(converted))
    try:
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()

        texts, labels, tags, dims, layers, lines_p = [], [], [], [], {}, []
        for e in msp:
            t = e.dxftype()
            if t == "TEXT":
                texts.append(e.dxf.text)
                labels.append({"text": e.dxf.text, "x": round(e.dxf.insert.x, 2), "y": round(e.dxf.insert.y, 2), "layer": e.dxf.layer})
            elif t == "MTEXT":
                texts.append(e.plain_text())
                labels.append({"text": e.plain_text(), "x": round(e.dxf.insert.x, 2), "y": round(e.dxf.insert.y, 2), "layer": e.dxf.layer})
            elif t == "INSERT":
                attrs = []
                try:
                    for a in e.attribs:
                        attrs.append({"tag": a.dxf.tag, "value": a.dxf.text})
                except Exception:  # noqa: BLE001
                    pass
                tags.append({
                    "block": e.dxf.name,
                    "x": round(e.dxf.insert.x, 2),
                    "y": round(e.dxf.insert.y, 2),
                    "layer": e.dxf.layer,
                    "attrs": attrs[:50],
                    "scale": round(e.dxf.xscale or 1, 3),
                })
            elif t == "DIMENSION":
                try:
                    m = e.get_measurement()
                except Exception:  # noqa: BLE001
                    m = None
                dims.append({
                    "text": (e.dxf.text or "").strip(),
                    "measurement": round(m, 3) if m is not None else None,
                    "x": round(e.dxf.defpoint.x, 2), "y": round(e.dxf.defpoint.y, 2),
                    "layer": e.dxf.layer,
                })
            elif t == "LINE":
                lines_p.append((round(e.dxf.start.x, 2), round(e.dxf.start.y, 2), round(e.dxf.end.x, 2), round(e.dxf.end.y, 2)))
            layers[e.dxf.layer] = layers.get(e.dxf.layer, 0) + 1

        # —— 图框检测：取几何范围（若有闭合矩形 LWPOLYLINE 则用其范围）——
        frame = _detect_frame(msp, lines_p)
        # —— 标题栏：图框/图面右下角区域的键值字段提取 ——
        title_fields = _extract_title_block(labels, frame)

        res.text = "\n".join(texts)
        res.structure = {
            "spatial": {
                "frame": frame,                       # 图框边界 [xmin, ymin, xmax, ymax]
                "title_block": title_fields,          # 图号/图名/比例/设计/日期等
                "blocks": tags[:800],                 # 设备/图块 + 坐标 + 属性（空间库打底）
                "dimensions": dims[:800],             # 尺寸标注 + 测量值
                "lines": lines_p[:2000],              # v0.1.47：线段（管线/管道/连接线）
            },
            "text_labels": labels[:500],
            "version": doc.dxfversion,
            "layers": [{"layer": k, "count": v} for k, v in sorted(layers.items(), key=lambda x: -x[1])][:100],
            "entity_counts": {
                "TEXT": len([1 for e in msp.query("TEXT")]),
                "MTEXT": len([1 for e in msp.query("MTEXT")]),
                "INSERT": len([1 for e in msp.query("INSERT")]),
                "LINE": len([1 for e in msp.query("LINE")]),
                "DIMENSION": len([1 for e in msp.query("DIMENSION")]),
            },
        }
        res.entities = extract_entities("\n".join(texts + [a.get("value", "") for t in tags for a in t.get("attrs", [])]))
    finally:
        # v0.1.144：清理 DWG→DXF 临时根目录（in/ DWG 副本 + out/ 转换结果），
        # 用 finally 确保解析异常时也清理（此前仅正常路径清理，异常时 %TEMP% 无限膨胀）
        if "_tmp_dxf_root" in dir() and _tmp_dxf_root and os.path.isdir(_tmp_dxf_root):
            try:
                import shutil as _sh
                _sh.rmtree(_tmp_dxf_root, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass


def _detect_frame(msp, lines_p):
    """图框检测：优先找面积最大的闭合 LWPOLYLINE 矩形；否则退回全图几何范围。"""
    best = None
    for e in msp.query("LWPOLYLINE"):
        try:
            pts = list(e.get_points("xy"))
            if len(pts) >= 4 and pts[0] == pts[-1]:
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                w, h = max(xs) - min(xs), max(ys) - min(ys)
                if w > 0 and h > 0:
                    area = w * h
                    if best is None or area > best[0]:
                        best = (area, [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)])
        except Exception:  # noqa: BLE001
            continue
    if best:
        return best[1]
    if lines_p:
        xs = [c for p in lines_p for c in (p[0], p[2])]
        ys = [c for p in lines_p for c in (p[1], p[3])]
        return [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]
    return None


_TITLE_KEYS = [
    ("图号", ["图号", "图纸编号", "编号", "drawing no", "drw no"]),
    ("图名", ["图名", "图纸名称", "名称", "title"]),
    ("工程名", ["工程名称", "项目名称", "project"]),
    ("车间", ["车间", "workshop", "unit"]),
    ("专业", ["专业", "discipline"]),
    ("比例", ["比例", "scale"]),
    ("设计", ["设计", "design"]),
    ("制图", ["制图", "drawn", "drawing by"]),
    ("审核", ["审核", "checked", "check"]),
    ("批准", ["批准", "approved"]),
    ("日期", ["日期", "date"]),
    ("版本", ["版本", "rev", "version"]),
    ("图幅", ["图幅", "a0", "a1", "a2", "a3", "a4"]),
]


def _extract_title_block(labels, frame):
    """标题栏键值提取：取图框右下 40% 区域（含右下 20% 高的横条）内的文本，按常见键词解析。
    无图框时用全图文本边界兜底（部分简图/示意图没有图框线）。"""
    if not labels:
        return {}
    if frame is None:
        # 兜底：以文本范围为边界，取右下 50%×50% 区域
        xs = [lb["x"] for lb in labels]
        ys = [lb["y"] for lb in labels]
        frame = [min(xs), min(ys), max(xs), max(ys)]
        xmin, ymin, xmax, ymax = frame
        w, h = xmax - xmin, ymax - ymin
        rx0 = round(xmin + w * 0.5, 2)
        ymax_limit = round(ymin + h * 0.5, 2)
    else:
        xmin, ymin, xmax, ymax = frame
        w, h = xmax - xmin, ymax - ymin
        if w <= 0 or h <= 0:
            return {}
        rx0 = round(xmin + w * 0.55, 2)
        ymax_limit = round(ymin + h * 0.45, 2)
    zone = [lb for lb in labels
            if lb["x"] >= rx0 and lb["y"] >= ymin
            and lb["x"] <= xmax and lb["y"] <= ymax_limit]
    # v0.1.227：区域为空**不再直接 return {}**，交给下面的全图兜底。
    # 原来这一步就返回，等于"图框右下没东西 → 整张图的图签都不要了"，
    # 而这恰恰是最常见的失败形态（模型空间并排多图 / 包围盒被拉远）。
    # 同一行按 y 聚拢，按 x 排序拼成行文本
    def _rows_of(labels_):
        rows_ = {}
        for lb in labels_:
            key = round(lb["y"], 1)
            rows_.setdefault(key, []).append(lb)
        return [
            " ".join(lb["text"] for lb in sorted(rows_[k], key=lambda z: z["x"]))
            for k in sorted(rows_.keys(), reverse=True)   # 从高到低（标题栏顶部行优先）
        ]

    def _match(lines_):
        joined_ = "\n".join(lines_)
        found = {}
        for field, keys in _TITLE_KEYS:
            if field in found:
                continue
            for k in keys:
                # 独立键匹配："键 值" 或 "键:值"，键前必须是行首或分隔符（避免命中"1号车间"里的"车间"）
                m = re.search(r"(?:^|[\s:：])({})[\s:：]*(.+)$".format(re.escape(k)), joined_, re.M)
                if not m:
                    continue
                rest = m.group(2).strip()
                if rest:
                    found[field] = rest
                    break
        return found

    out = _match(_rows_of(zone))
    # v0.1.227：右下角区域没匹配到键词时，**再拿全图找一遍**。
    #
    # 原实现到此为止就 `return {}`（顶多给个"图名(候选)"），结果实测两张真实
    # 布置图/流程图 DWG：正文能抽出 1300 / 26251 字，title_block 却是空的 ——
    # 界面上"图号/图名/比例"整块是空白，看起来像图纸没解析。
    #
    # 原因不在抽取逻辑，在**几何范围假设**：取"图框右下 45%"要求模型空间只有
    # 一张图。而现场图纸经常是模型空间里并排摆着几张图、或带大片空白/外部参照
    # 残留，全局包围盒被拉到很远，右下角那一片其实什么都没有。
    # 图签字段（"图号：XXX"）本身很独特，全图匹配比死守一块区域可靠得多。
    if not out:
        out = _match(_rows_of(labels))
        if out:
            out["_source"] = "全图匹配（图框右下区域无内容）"
    # 若仍无键词，取最大字体/首行作为图名候选
    if not out and zone:
        zone_sorted = sorted(zone, key=lambda z: -z["y"])
        out["图名(候选)"] = zone_sorted[0]["text"]
    if not out and labels:
        out["图名(候选)"] = sorted(labels, key=lambda z: -z["y"])[0]["text"]
        out["_source"] = "全图首行（未匹配到任何图签键词）"
    return out


_ODA_CACHE = None          # None=未查过；""=查过但没有；其它=路径
_ODA_SEARCHED = []          # 查过哪些位置（写进错误信息，便于现场排查）


def _find_external_tools():
    r"""把本机可用的外部工具一次查清（ODA / AutoCAD 控制台 / Tesseract）。

    为什么要有这个函数：v0.1.225 之前 ODA 只搜 `%ProgramFiles%`（= C 盘）和
    写死的 `C:////ODA////...`。实测本机（2026-11-10）ODA 装在
    `D:////ODA////ODAFileConverter////`、AutoCAD 2020 装在
    `D:////Program Files\\Autodesk\\AutoCAD 2020\\` —— 两样都在 D 盘，
    于是 25 张 DWG 全部报「未找到 ODA File Converter」，老板一句
    「本机应该有这些条件」才发现是搜索范围写死了盘符。

    搜索顺序（全部先看环境变量，再看注册表，再看各盘符常见目录，最后 where）：
      ODA      : ODA_CONVERTER -> 注册表卸载项 InstallLocation -> <盘>:\ODA\ ->
                 <盘>:\Program Files[ (x86)]\ODA\ -> PATH
      AutoCAD  : acad 安装目录下的 accoreconsole.exe（无界面脚本引擎，
                 ODA 不可用时的 DWG→DXF 备选方案）
      Tesseract: TESSERACT_CMD -> <盘>:\Program Files\Tesseract-OCR\tesseract.exe -> PATH
    """
    import glob
    import subprocess

    roots = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        d = letter + ":\\"
        if os.path.isdir(d):
            roots.append(d)
    pf_names = ("Program Files", "Program Files (x86)")

    def _reg_paths(match):
        out = []
        try:
            import winreg
        except Exception:  # noqa: BLE001
            return out
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"),
        ]
        for hive, sub in keys:
            try:
                with winreg.OpenKey(hive, sub) as k:
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        try:
                            name = winreg.EnumKey(k, i)
                            with winreg.OpenKey(k, name) as sk:
                                dn = ""
                                try:
                                    dn = str(winreg.QueryValueEx(sk, "DisplayName")[0])
                                except Exception:  # noqa: BLE001
                                    pass
                                if not match(dn):
                                    continue
                                try:
                                    loc = str(winreg.QueryValueEx(sk, "InstallLocation")[0] or "")
                                except Exception:  # noqa: BLE001
                                    loc = ""
                                if loc:
                                    out.append(loc)
                        except Exception:  # noqa: BLE001
                            continue
            except Exception:  # noqa: BLE001
                continue
        return out

    # ---------- ODA File Converter ----------
    oda = ""
    cands = []
    env = os.environ.get("ODA_CONVERTER", "")
    if env:
        cands.append(env)
    for loc in _reg_paths(lambda n: "ODA" in n.upper() or "TEIGHA" in n.upper()):
        cands.append(os.path.join(loc, "ODAFileConverter.exe"))
        cands.append(os.path.join(loc, "ODAFileConverter", "ODAFileConverter.exe"))
    for r in roots:
        _ODA_SEARCHED.append(r)
        cands += [
            os.path.join(r, "ODA", "ODAFileConverter", "ODAFileConverter.exe"),
            os.path.join(r, "ODA", "ODAFileConverter.exe"),
            os.path.join(r, "ODAFileConverter", "ODAFileConverter.exe"),
        ]
        for pfn in pf_names:
            cands += [
                os.path.join(r, pfn, "ODA", "ODAFileConverter", "ODAFileConverter.exe"),
                os.path.join(r, pfn, "ODAFileConverter", "ODAFileConverter.exe"),
            ]
    for c in cands:
        if c and os.path.isfile(c):
            oda = c
            break
    if not oda:
        # 深度受限的通配（只在 ODA* 目录里找，不做全盘递归，避免拖慢启动）
        for r in roots:
            for pat in (os.path.join(r, "ODA*", "**", "ODAFileConverter.exe"),
                        os.path.join(r, "Program Files*", "ODA*", "**", "ODAFileConverter.exe")):
                try:
                    hits = glob.glob(pat, recursive=True)
                except Exception:  # noqa: BLE001
                    hits = []
                hits = [h for h in hits if os.path.isfile(h)]
                if hits:
                    oda = sorted(hits, key=len)[0]
                    break
            if oda:
                break
    if not oda:
        try:
            r = subprocess.run(["where", "ODAFileConverter"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=10)
            lines = [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]
            if lines and os.path.isfile(lines[0]):
                oda = lines[0]
        except Exception:  # noqa: BLE001
            pass

    # ---------- AutoCAD accoreconsole（ODA 缺失时的 DWG→DXF 备选） ----------
    acc = ""
    acands = []
    for loc in _reg_paths(lambda n: "AUTOCAD" in n.upper()):
        acands.append(os.path.join(loc, "accoreconsole.exe"))
    for r in roots:
        for pat in (os.path.join(r, "Program Files", "Autodesk", "AutoCAD*", "accoreconsole.exe"),
                    os.path.join(r, "Program Files (x86)", "Autodesk", "AutoCAD*", "accoreconsole.exe"),
                    os.path.join(r, "Autodesk", "AutoCAD*", "accoreconsole.exe")):
            try:
                acands += [h for h in glob.glob(pat) if os.path.isfile(h)]
            except Exception:  # noqa: BLE001
                pass
            acands += [c for c in [os.path.join(r, "Program Files", "Autodesk", "AutoCAD 2020", "accoreconsole.exe")] if os.path.isfile(c)]
    for c in acands:
        if c and os.path.isfile(c):
            acc = c
            break

    # ---------- Tesseract ----------
    tess = os.environ.get("TESSERACT_CMD", "")
    if not tess or not os.path.isfile(tess):
        tess = ""
        t_cands = []
        for r in roots:
            t_cands.append(os.path.join(r, "Program Files", "Tesseract-OCR", "tesseract.exe"))
            t_cands.append(os.path.join(r, "Program Files (x86)", "Tesseract-OCR", "tesseract.exe"))
            t_cands.append(os.path.join(r, "Tesseract-OCR", "tesseract.exe"))
        for c in t_cands:
            if os.path.isfile(c):
                tess = c
                break
        if not tess:
            try:
                r2 = subprocess.run(["where", "tesseract"], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace",
                                    timeout=10)
                lines = [x.strip() for x in (r2.stdout or "").splitlines() if x.strip()]
                if lines and os.path.isfile(lines[0]):
                    tess = lines[0]
            except Exception:  # noqa: BLE001
                pass

    return {"oda": oda, "accoreconsole": acc, "tesseract": tess, "searched_roots": roots}


def _find_oda_converter():
    """自动发现 ODA File Converter（v0.1.226：跨盘符 + 注册表，不再写死 C 盘）。"""
    global _ODA_CACHE
    if _ODA_CACHE is not None:
        return _ODA_CACHE or None
    try:
        tools = _find_external_tools()
        _ODA_CACHE = tools.get("oda") or ""
    except Exception:  # noqa: BLE001
        _ODA_CACHE = ""
    return _ODA_CACHE or None


def _dwg_to_dxf(dwg_path: str) -> Optional[str]:
    """调用 ODA File Converter 命令行将 DWG 转 DXF；失败返回 None。
    v0.1.134（P4）：转换输出到独立临时目录（不再落在 uploads/_dxf_converted，
    避免被扫描器递归重复处理）；调用方 parse_cad 用完即删。
    v0.1.144：用独立 work_dir（in/ 只放单个 DWG 副本），避免 ODA 按目录批量转换
    时把原始目录里所有 DWG 都转一遍（慢且产生大量临时文件）；异常时清理 work_dir。"""
    import subprocess
    import tempfile
    import shutil as _shutil
    oda = _find_oda_converter()
    if not oda:
        return None
    work_dir = tempfile.mkdtemp(prefix="dxf_convert_")
    in_dir = os.path.join(work_dir, "in")
    out_dir = os.path.join(work_dir, "out")
    os.makedirs(in_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    try:
        # 只复制单个 DWG 到 in/，避免 ODA 转换整个原始目录
        _shutil.copy2(dwg_path, os.path.join(in_dir, os.path.basename(dwg_path)))
        # ODAFileConverter 输入目录 输出目录 输出版本 输出类型 递归 审计
        cmd = [oda, in_dir, out_dir, "ACAD2018", "DXF", "0", "1"]
        subprocess.run(cmd, timeout=300, check=True, capture_output=True)
        base = os.path.splitext(os.path.basename(dwg_path))[0] + ".dxf"
        cand = os.path.join(out_dir, base)
        if not os.path.exists(cand):
            # 兜底：找转换目录下任意 .dxf
            hits = [os.path.join(out_dir, x) for x in os.listdir(out_dir) if x.lower().endswith(".dxf")]
            cand = hits[0] if hits else None
        return cand
    except Exception:  # noqa: BLE001
        _shutil.rmtree(work_dir, ignore_errors=True)
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
