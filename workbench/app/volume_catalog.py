#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.1.175：阶段③收尾 —— 卷内目录 / 案卷封面 / 卷内备考表 / 装盒清单。

三件事都围绕一个前提：**卷里已经真实落盘了哪些文件**。所以
`build_catalog()` 只读磁盘，不读接口自报的「已生成」。

页次是**真实页数**：用 LibreOffice 把每个 docx 渲成 PDF 再数页，数不出来
（没装 soffice / 转换失败）就如实标 `未计算`，绝不用「1 份文件算 1 页」这种
估算去顶替 —— 页次排在监理的正式卷内目录上，估错了就是错卷。

装盒清单按登记表的「册 / 序号」两级组织，与监理给的登记表同序，
不另造一册顺序。
"""
import datetime
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from typing import Dict, List, Optional

DEFAULT_ORG_UNIT = "【待补充】"   # 编制单位：未登记时落可见占位，不留空也不编造


# ---------------- 页数：真实渲染 ----------------

_PAGE_CACHE: Dict[str, tuple] = {}

# 页数渲染并发度。LibreOffice 每次转换都是独立进程（几十 MB 内存），
# 并发太高会把机器压死；3 路是既能明显提速、又不至于卡死的取值。
_PAGE_WORKERS = int(os.environ.get("FANGONG_PAGE_WORKERS", "3"))


def _soffice_path() -> Optional[str]:
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    return None


def count_pdf_pages(pdf_path: str) -> Optional[int]:
    """数 PDF 页数。优先 pypdf；不可用则读 PDF 里的 /Type /Page 计数兜底。"""
    try:
        import pypdf
        return len(pypdf.PdfReader(pdf_path).pages)
    except Exception:  # noqa: BLE001
        pass
    try:
        raw = open(pdf_path, "rb").read()
        # 排除 /Type /Pages（复数）节点
        hits = re.findall(rb"/Type\s*/Page(?![s])", raw)
        return len(hits) or None
    except Exception:  # noqa: BLE001
        return None


def _word_page_count(docx_path: str, timeout: int = 120) -> Dict:
    """用本机 Word（COM）打开文档读取真实分页数。仅 Windows + pywin32 可用。

    Word 的 ComputeStatistics(wdStatisticPages)=2 返回的是真实排版页数，
    与打印结果一致。打不开/没装 Word 就返回 unavailable，由上层降级。
    """
    try:
        import win32com.client  # noqa: F401
        import pythoncom
    except Exception:  # noqa: BLE001
        return {"pages": None, "how": "unavailable", "note": "本机无 Word COM（pywin32/Word 未装）"}

    word = None
    doc = None
    try:
        pythoncom.CoInitialize()
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(os.path.abspath(docx_path), ReadOnly=True,
                                  AddToRecentFiles=False)
        n = int(doc.ComputeStatistics(2))   # wdStatisticPages
        return {"pages": n if n > 0 else None,
                "how": "rendered" if n > 0 else "unavailable",
                "note": "Word COM 分页实测"}
    except Exception as e:  # noqa: BLE001
        return {"pages": None, "how": "unavailable",
                "note": f"Word COM 失败：{type(e).__name__}: {str(e)[:80]}"}
    finally:
        try:
            if doc is not None:
                doc.Close(False)
        except Exception:  # noqa: BLE001
            pass
        try:
            if word is not None:
                word.Quit()
        except Exception:  # noqa: BLE001
            pass
        try:
            pythoncom.CoUninitialize()
        except Exception:  # noqa: BLE001
            pass


def _content_fingerprint(path: str) -> str:
    """文件内容指纹。

    页数只取决于文档正文，所以指纹必须只覆盖**真正的内容**：
      - docx 是 zip 容器，每次保存 zip 条目时间戳都会变，整个文件 sha256 必然变，
        用整文件哈希当缓存键 = 缓存永远失效（实测第二次整卷仍要 197s）。
      - 所以对 docx 只取 word/ 下的 XML + [Content_Types].xml 求哈希；
        这些才是渲染出页数的东西。
      - 非 docx（xlsx 等）退回整文件哈希。
    mtime 会被「重写但内容相同」的动作推翻，同样不能当缓存键。
    """
    try:
        h = hashlib.sha256()
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                for name in sorted(z.namelist()):
                    if name.startswith("word/") or name == "[Content_Types].xml":
                        h.update(name.encode("utf-8"))
                        h.update(z.read(name))
            return f"zip-{h.hexdigest()[:16]}"
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(262144), b""):
                h.update(chunk)
        return f"raw-{os.path.getsize(path)}-{h.hexdigest()[:16]}"
    except (OSError, zipfile.BadZipFile):
        return "missing"


def real_page_count(docx_path: str, timeout: int = 120) -> Dict:
    """真实页数。返回 {'pages': int|None, 'how': 'rendered'|'unavailable', 'note': str}"""
    if not os.path.isfile(docx_path):
        return {"pages": None, "how": "unavailable", "note": "文件不存在"}
    key = os.path.abspath(docx_path)
    # v0.1.179：缓存键用**内容指纹**，不再用 mtime。
    # 实测整卷时同一个文件被重复渲染：卷内目录等文件每轮被重写，mtime 变了但
    # 内容其实一样，mtime 判定就让缓存全部失效 → 34 个文件渲染了 66 次。
    fp = _content_fingerprint(key)
    if key in _PAGE_CACHE and _PAGE_CACHE[key][0] == fp:
        return _PAGE_CACHE[key][1]

    # Windows 本机首选 Word COM：安装包默认带 pywin32，用户机器上通常有 Word，
    # 直接读 Word 自己的分页结果，与打印出来的一致（LibreOffice 的分页可能有细微差异）
    _w = _word_page_count(key, timeout)
    if _w["pages"]:
        _PAGE_CACHE[key] = (fp, _w)
        return _w

    binp = _soffice_path()
    if not binp:
        res = {"pages": None, "how": "unavailable",
               "note": "本机没装 LibreOffice，无法渲染算页数（未估算，避免页次错卷）"}
        _PAGE_CACHE[key] = (fp, res)
        return res

    with tempfile.TemporaryDirectory(prefix="fg_pg_") as td:
        try:
            # v0.1.179：给每个渲染进程**独立的 LibreOffice 用户配置目录**。
            # 并发渲染时多个 soffice 实例默认共用 ~/.config/libreoffice，会互相抢占：
            # 实测 3 路并发时有实例直接失败、PDF 没产出，页次退化成「未计算」
            # （页次错卷比慢更严重）。用 -env:UserInstallation 隔开后并发才安全。
            _prof = os.path.join(td, "profile")
            os.makedirs(_prof, exist_ok=True)
            r = subprocess.run([binp, "--headless", "--norestore", "--nolockcheck",
                                f"-env:UserInstallation=file://{_prof}",
                                "--convert-to", "pdf",
                                "--outdir", td, key],
                               capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            res = {"pages": None, "how": "unavailable", "note": f"渲染超时（{timeout}s）"}
            _PAGE_CACHE[key] = (fp, res)
            return res
        except Exception as e:  # noqa: BLE001
            res = {"pages": None, "how": "unavailable", "note": f"渲染失败：{type(e).__name__}"}
            _PAGE_CACHE[key] = (fp, res)
            return res

        pdf = os.path.join(td, os.path.splitext(os.path.basename(key))[0] + ".pdf")
        if not os.path.isfile(pdf):
            tail = (r.stderr or b"").decode("utf-8", "replace")[-200:]
            res = {"pages": None, "how": "unavailable", "note": f"未产出 PDF（{tail.strip()[:120]}）"}
            _PAGE_CACHE[key] = (fp, res)
            return res
        n = count_pdf_pages(pdf)
        res = ({"pages": n, "how": "rendered", "note": "LibreOffice 渲染后数页"}
               if n else {"pages": None, "how": "unavailable", "note": "PDF 里数不到页对象"})
        _PAGE_CACHE[key] = (fp, res)
        return res


# ---------------- 卷内目录数据 ----------------

def _seq_sort_key(seq: str) -> tuple:
    """序号排序：1 / 2 / 10 按数值排，不是字符串排（'10' < '2' 是错的）。
    非纯数字（如 1.1、附1）退回原始串比较，保证稳定。"""
    s = str(seq or "").strip()
    if re.fullmatch(r"\d+", s):
        return (0, int(s), "")
    m = re.match(r"(\d+)(.*)$", s)
    if m:
        return (1, int(m.group(1)), m.group(2))
    return (2, 0, s)


def collect_volume_files(volume_dir: str) -> List[Dict]:
    """卷目录里真实的资料文件（排除本工具自己产出的封面/目录/备考表/清单/待办）。"""
    if not os.path.isdir(volume_dir):
        return []
    own = ("_卷内目录", "_案卷封面", "_卷内备考表", "_装盒清单", "_待办清单")
    out = []
    for fn in os.listdir(volume_dir):
        p = os.path.join(volume_dir, fn)
        if not os.path.isfile(p):
            continue
        if any(fn.startswith(o) for o in own):
            continue
        if fn.startswith("."):
            continue
        m = re.match(r"(\d+(?:_\d+)?)_(.+)\.(docx|xlsx|pdf)$", fn)
        seq = m.group(1).replace("_", ".") if m else ""
        title = m.group(2) if m else os.path.splitext(fn)[0]
        out.append({
            "序号": seq, "名称": title, "文件": fn, "路径": p,
            "大小": os.path.getsize(p),
            "扩展名": os.path.splitext(fn)[1].lstrip(".").lower(),
        })
    out.sort(key=lambda x: (_seq_sort_key(x["序号"]), x["文件"]))
    return out


def _safe_page_count(path: str) -> Dict:
    """并发场景下的页数计算：单份失败不能带塌整批。"""
    try:
        return real_page_count(path)
    except Exception as e:  # noqa: BLE001
        return {"pages": None, "how": "unavailable",
                "note": f"页数计算异常：{type(e).__name__}"}


def build_catalog(volume_dir: str, book: str = "", workshop: str = "",
                  org_unit: str = "", registry_items: Optional[List[Dict]] = None,
                  count_pages: bool = True) -> Dict:
    """生成卷内目录数据。页次按真实渲染页数累计。"""
    files = collect_volume_files(volume_dir)

    # 登记表里该册的项（用来标「表号」和「登记表里还没生成」的项）
    reg_names = {}
    reg_seq = {}
    for it in (registry_items or []):
        nm = (it.get("名称") or "").strip()
        if nm:
            reg_names[nm] = it.get("表号") or ""
            reg_seq[nm] = it.get("序号") or ""

    rows = []
    page_cursor = 1
    page_note = "rendered"
    # v0.1.179：逐份渲染改成**有限并发**。
    # LibreOffice/Word 每次都是独立进程，串行渲 34 份实测 109s；
    # 并发 3 路后同一批文件降到 ~40s。并发度写死不高（沙箱 2 核也不该开满）。
    _page_results = {}
    if count_pages and files:
        from concurrent.futures import ThreadPoolExecutor
        _paths = [f["路径"] for f in files]
        with ThreadPoolExecutor(max_workers=_PAGE_WORKERS) as _pool:
            for _p, _r in zip(_paths, _pool.map(_safe_page_count, _paths)):
                _page_results[_p] = _r
    for f in files:
        pages, how, note = (None, "unavailable", "未计算")
        if count_pages:
            r = _page_results.get(f["路径"]) or {"pages": None, "how": "unavailable",
                                                 "note": "未计算页数"}
            pages, how, note = r["pages"], r["how"], r["note"]
        start = page_cursor if pages else None
        end = (page_cursor + pages - 1) if pages else None
        if pages:
            page_cursor += pages
        else:
            page_note = how
        # 表号 / 登记表序号：按名称匹配（生成文件名 = 序号_名称）
        tbl_no = reg_names.get(f["名称"], "")
        reg_no = reg_seq.get(f["名称"], f["序号"])
        rows.append({
            "序号": reg_no,
            "文件": f["文件"],
            "名称": f["名称"],
            "表号": tbl_no,
            "页次": f"{start}-{end}" if pages else "未计算",
            "页数": pages,
            "编制单位": org_unit or DEFAULT_ORG_UNIT,
            "真实页数依据": how,
            "备注": "" if pages else note,
        })

    # 登记表里有、卷里还没产出的项 —— 必须列出来，监理一眼能看出缺哪几份
    present = {(r["名称"] or "").strip() for r in rows}
    missing = []
    for it in (registry_items or []):
        nm = (it.get("名称") or "").strip()
        if not nm or nm in present:
            continue
        if it.get("分类") == "C":      # C 类是归集目录，不算缺文件
            continue
        missing.append({"序号": it.get("序号") or "", "名称": nm,
                        "表号": it.get("表号") or "", "页次": "—"})

    total_pages = page_cursor - 1
    return {
        "book": book, "workshop": workshop,
        "rows": rows, "missing": missing,
        "file_count": len(rows), "missing_count": len(missing),
        "total_pages": total_pages if page_note == "rendered" else None,
        "page_basis": page_note,
        "org_unit": org_unit or DEFAULT_ORG_UNIT,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ---------------- 四份成品文档 ----------------

def _new_doc():
    """建一份国标版式空文档（与 template_engine 的样式一致）。"""
    from docx import Document
    from docx.shared import Cm, Pt
    from docx.oxml.ns import qn
    doc = Document()
    for s in doc.sections:
        s.top_margin = Cm(3.7)
        s.bottom_margin = Cm(3.5)
        s.left_margin = Cm(2.8)
        s.right_margin = Cm(2.6)
    st = doc.styles["Normal"]
    st.font.name = "宋体"
    st.font.size = Pt(12)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    return doc


def _title(doc, text, size=16):
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(size)
    r.font.name = "黑体"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    return p


def _line(doc, text, size=12, align=None, bold=False):
    from docx.shared import Pt
    from docx.oxml.ns import qn
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.bold = bold
    r.font.name = "宋体"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    return p


def _style_table(tbl, header_bold=True):
    """表格实线边框 + 表头加粗居中 + 表内五号字（与国标样式一致）。"""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    tblPr = tbl._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:color"), "000000")
        borders.append(el)
    tblPr.append(borders)
    for i, row in enumerate(tbl.rows):
        for cell in row.cells:
            for para in cell.paragraphs:
                if i == 0 and header_bold:
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for r in para.runs:
                    r.font.size = Pt(10.5)
                    r.font.name = "宋体"
                    r._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
                    if i == 0 and header_bold:
                        r.bold = True


def write_catalog_docx(catalog: Dict, out_path: str) -> str:
    """卷内目录（正式表）：序号 / 文件 / 名称 / 表号 / 页次 / 编制单位。"""
    doc = _new_doc()
    _title(doc, "卷　内　目　录", 18)
    _line(doc, f"册：{catalog['book'] or DEFAULT_ORG_UNIT}　　"
               f"车间：{catalog['workshop'] or DEFAULT_ORG_UNIT}　　"
               f"编制单位：{catalog['org_unit']}", 10.5)
    doc.add_paragraph()

    headers = ["序号", "文件编号", "资料名称", "表号", "页次", "编制单位"]
    tbl = doc.add_table(rows=1, cols=len(headers))
    for j, h in enumerate(headers):
        tbl.rows[0].cells[j].text = h
    for r in catalog["rows"]:
        cells = tbl.add_row().cells
        cells[0].text = str(r["序号"])
        cells[1].text = r["文件"]
        cells[2].text = r["名称"]
        cells[3].text = r["表号"] or "—"
        cells[4].text = r["页次"]
        cells[5].text = r["编制单位"]
    for m in catalog["missing"]:
        cells = tbl.add_row().cells
        cells[0].text = str(m["序号"])
        cells[1].text = "—"
        cells[2].text = m["名称"]
        cells[3].text = m["表号"] or "—"
        cells[4].text = "—"
        cells[5].text = "尚未生成"
    _style_table(tbl)

    doc.add_paragraph()
    if catalog["total_pages"] is not None:
        _line(doc, f"本卷共 {catalog['file_count']} 份文件，合计 {catalog['total_pages']} 页"
                   f"（页数为渲染实测）；登记表内 {catalog['missing_count']} 项尚未生成。", 10.5)
    else:
        _line(doc, f"本卷共 {catalog['file_count']} 份文件；页次未计算"
                   f"（{catalog.get('page_basis') or '无法渲染'}，请在本机用 Word 核对后手填）；"
                   f"登记表内 {catalog['missing_count']} 项尚未生成。", 10.5)
    _line(doc, f"生成时间：{catalog['generated_at']}", 9)
    doc.save(out_path)
    return out_path


def write_cover_docx(catalog: Dict, out_path: str, archive_no: str = "") -> str:
    """案卷封面。卷号/案卷题名/编制单位/编制日期/保管期限/密级。"""
    doc = _new_doc()
    for _ in range(3):
        doc.add_paragraph()
    _title(doc, "工 程 竣 工 资 料 案 卷 封 面", 20)
    doc.add_paragraph()
    _line(doc, f"档　号：{archive_no or DEFAULT_ORG_UNIT}", 12, bold=False)
    _line(doc, f"案卷号：{catalog['book'] or DEFAULT_ORG_UNIT}", 12)
    doc.add_paragraph()
    _title(doc, f"案卷题名：{catalog['book'] or DEFAULT_ORG_UNIT}"
                f"　{catalog['workshop'] or DEFAULT_ORG_UNIT}", 14)
    doc.add_paragraph()
    _line(doc, f"编制单位：{catalog['org_unit']}", 12)
    _line(doc, f"编制日期：{catalog['generated_at'][:10]}", 12)
    _line(doc, "保管期限：长期", 12)
    _line(doc, "密　　级：内部", 12)
    doc.add_paragraph()
    _line(doc, f"本卷共 {catalog['file_count']} 份文件"
               + (f"，{catalog['total_pages']} 页" if catalog["total_pages"] else ""), 10.5)
    doc.add_paragraph()
    _line(doc, "（本封面由繁工AI生成；档号、密级、保管期限如与本项目档案要求不符，请按监理/档案馆要求改填）", 9)
    doc.save(out_path)
    return out_path


def write_exam_record_docx(catalog: Dict, out_path: str, reviewer: str = "",
                           check_note: str = "") -> str:
    """卷内备考表：本卷情况说明 / 立卷人 / 检查人 / 立卷时间。"""
    doc = _new_doc()
    _title(doc, "卷　内　备　考　表", 18)
    doc.add_paragraph()

    tbl = doc.add_table(rows=0, cols=2)
    rows = [
        ("本卷文件件数", f"{catalog['file_count']} 件"),
        ("本卷文件页数",
         f"{catalog['total_pages']} 页（渲染实测）" if catalog["total_pages"]
         else "未计算（无法渲染，请用 Word 核对后手填）"),
        ("登记表未生成项", f"{catalog['missing_count']} 项"),
        ("本卷情况说明",
         check_note or ("登记表所列各项中已生成部分均按模板填写；"
                        "标注【待补充】的字段需人工补齐后签字。"
                        + (f" 另有 {catalog['missing_count']} 项尚未生成，见卷内目录。"
                           if catalog["missing_count"] else ""))),
        ("立卷人", "【待补充】"),
        ("检查人", reviewer or "【待补充】"),
        ("立卷时间", catalog["generated_at"][:10]),
    ]
    for k, v in rows:
        cells = tbl.add_row().cells
        cells[0].text = k
        cells[1].text = str(v)
    _style_table(tbl, header_bold=False)

    doc.add_paragraph()
    _line(doc, "说明：本备考表由繁工AI按卷内实际文件生成，件数/页数取自磁盘与渲染结果，不是估算。", 9)
    doc.save(out_path)
    return out_path


def write_boxing_list_xlsx(volumes: List[Dict], out_path: str) -> str:
    """装盒清单：按「册 → 卷」组织，一册一行，用于实际装盒核对与贴签。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    wb = Workbook()
    ws = wb.active
    ws.title = "装盒清单"
    headers = ["盒号", "册（案卷号）", "车间", "件数", "页数", "页数依据",
               "未生成项", "脊背标签建议", "备注"]
    ws.append(headers)
    for i, v in enumerate(volumes, start=1):
        ws.append([
            f"第{i}盒",
            v.get("book") or DEFAULT_ORG_UNIT,
            v.get("workshop") or "全厂",
            v.get("file_count", 0),
            v.get("total_pages") if v.get("total_pages") is not None else "未计算",
            "渲染实测" if v.get("total_pages") is not None else (v.get("page_basis") or "未计算"),
            v.get("missing_count", 0),
            f"{v.get('book') or ''}／{v.get('workshop') or ''}／共{v.get('file_count', 0)}件",
            "页数未计算时脊背标签先不印页数" if v.get("total_pages") is None else "",
        ])
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=ws.max_row)):
        for c in row:
            c.font = Font(name="微软雅黑", size=10, bold=(i == 0))
            c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    for col, w in zip("ABCDEFGHI", [8, 18, 14, 8, 10, 14, 10, 32, 26]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    wb.save(out_path)
    return out_path


def build_volume_package(volume_dir: str, book: str, workshop: str,
                         org_unit: str = "", registry_items: Optional[List[Dict]] = None,
                         archive_no: str = "", reviewer: str = "",
                         count_pages: bool = True) -> Dict:
    """在卷目录里生成四份成品：卷内目录 / 案卷封面 / 卷内备考表（装盒清单按册汇总另出）。"""
    os.makedirs(volume_dir, exist_ok=True)
    cat = build_catalog(volume_dir, book=book, workshop=workshop,
                        org_unit=org_unit, registry_items=registry_items,
                        count_pages=count_pages)
    outs = {}
    outs["卷内目录"] = write_catalog_docx(cat, os.path.join(volume_dir, "_卷内目录.docx"))
    outs["案卷封面"] = write_cover_docx(cat, os.path.join(volume_dir, "_案卷封面.docx"),
                                        archive_no=archive_no)
    outs["卷内备考表"] = write_exam_record_docx(
        cat, os.path.join(volume_dir, "_卷内备考表.docx"), reviewer=reviewer)
    return {"ok": True, "catalog": cat, "files": outs}
