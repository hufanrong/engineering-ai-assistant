# -*- coding: utf-8 -*-
"""核心处理流程：process_file / process_folder。

不依赖 UI，返回结构化结果，可被 GUI、CLI 或其他程序直接 import 调用。

v0.1.156 全情况整改：
- 布局空间优先：图纸在 Layout 出图时，逐布局检测图框/清理/打印（每布局一页）
- 标题栏真实边界识别（线框聚类锁定小矩形）+ 四角/底部/右侧配置 + 红线区外扩
- 无标题栏页识别（区域内无保护词簇 → 跳过清理，防误删目录页/说明页）
- 代理实体（天正）Convert 优先、炸开兜底，炸出文字重新收集判定
- 区域内光栅图像（扫描签名/图章）、表格对象（AcDbTable）处理
- 锁定图层删除前临时解锁、恢复
- 外部参照（Xref）炸开 + 明确告警
- 斜置图框（rotation）文字坐标逆变换判定
"""

import hashlib
import os
import shutil
from datetime import datetime

from dwg_cleaner import cad, pdfmerge, rules, titleblock

FRAME_BLOCK_NAME_KEYS = ("图框", "标题", "frame", "title", "titleblock", "tb")


def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_log(item_dir, base, deleted, replaced, frames_count, pdf_pages, md5_ok, notes):
    path = os.path.join(item_dir, "处理日志.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("=== DWG 竣工图清稿处理日志 ===\n")
        f.write("文件        : %s\n" % base)
        f.write("处理时间    : %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        f.write("图框数量    : %d\n" % frames_count)
        f.write("PDF 页数    : %d\n" % pdf_pages)
        f.write("原文件校验  : %s\n" % ("未改动（MD5 一致）" if md5_ok else "警告：原文件被改动！"))
        f.write("\n--- 删除明细 ---\n")
        for e in deleted:
            f.write("[%s] (%s) %r\n" % (e.get("reason", ""), e.get("pos", "?"), e.get("text", "")))
        f.write("\n--- 替换明细 ---\n")
        for e in replaced:
            f.write("[%s] %r -> %r\n" % (e.get("reason", ""), e.get("old", ""), e.get("new", "")))
        f.write("\n--- 备注 ---\n")
        for n in notes:
            f.write("- %s\n" % n)
    return path


def process_file(dwg_path, out_dir, config=None, on_progress=None):
    """处理单个 DWG/DXF：清理标题栏 → 另存清稿副本 → 导出合并 PDF。

    流程：
    1) 布局空间优先：文档存在图纸空间布局（非 Model）且有实体 → 逐布局处理
       （图框检测/清理/整布局范围打印），每布局一页；
    2) 模型空间兜底：无可用布局时走原逻辑（多图框逐框窗口打印）；
    3) 另存清稿副本 + PDF 合并 + 验收缩略图 + 处理日志。
    """
    cfg = config or rules.load_config()

    def log(msg):
        if on_progress:
            on_progress(msg)

    base = os.path.splitext(os.path.basename(dwg_path))[0]
    item_dir = os.path.join(out_dir, base)
    os.makedirs(item_dir, exist_ok=True)
    ext_out = "dxf" if dwg_path.lower().endswith(".dxf") else "dwg"
    cleaned_path = os.path.join(item_dir, "%s_清稿.%s" % (base, ext_out))
    pdf_path = os.path.join(item_dir, "%s_竣工.pdf" % base)

    deleted, replaced, notes = [], [], []
    frames_count, pdf_pages = 0, 0
    md5_before = file_md5(dwg_path)
    temp_pdfs = []

    result = {
        "status": "failed",
        "file": dwg_path,
        "output_dir": item_dir,
        "cleaned_dwg": cleaned_path,
        "pdf": pdf_path,
        "frame_count": 0,
        "pdf_pages": 0,
        "deleted_count": 0,
        "replaced_count": 0,
        "log_file": "",
        "previews": [],
        "notes": [],
        "error": "",
    }

    try:
        with cad.CadSession() as session:
            doc = session.open_document(dwg_path, readonly=True)
            log("已打开（只读）：%s" % base)

            # 布局空间优先：图纸出在 Layout 的情况
            paper_layouts = []
            for layout in session.iter_layouts(doc):
                if not session.is_paperspace_layout(layout):
                    continue
                sp = session.layout_space(layout)
                if sp is not None and sp.Count > 0:
                    paper_layouts.append((layout, sp))
            if paper_layouts:
                log("检测到 %d 个图纸空间布局，按布局逐页处理" % len(paper_layouts))
                for idx, (layout, space) in enumerate(paper_layouts):
                    d, r, nt, fc, has_content = _process_space(
                        session, doc, space, cfg, log, notes,
                        layout_name=str(getattr(layout, "Name", "Layout")))
                    deleted.extend(d)
                    replaced.extend(r)
                    notes.extend(nt)
                    frames_count += fc
                    if has_content:
                        tmp = os.path.join(item_dir, "_tmp_layout_%d.pdf" % idx)
                        _plot_layout_page(session, doc, space, tmp, cfg)
                        temp_pdfs.append(tmp)
            else:
                # 模型空间（原逻辑：多图框逐框窗口打印）
                space = doc.ModelSpace
                d, r, nt, fc, has_content = _process_space(
                    session, doc, space, cfg, log, notes)
                deleted.extend(d)
                replaced.extend(r)
                notes.extend(nt)
                frames_count += fc
                if has_content:
                    _plot_model_frames(session, doc, space, cfg, temp_pdfs, item_dir,
                                       len(temp_pdfs))

            # PDF 合并
            if temp_pdfs:
                pdf_pages = pdfmerge.merge_pdfs(temp_pdfs, pdf_path)
                log("已生成 PDF：%d 页" % pdf_pages)
            else:
                notes.append("未生成任何 PDF 页（布局与模型空间均无可打印内容）")

            # 另存清稿副本
            session.save_as(doc, cleaned_path)
            doc.Close(False)
            session._doc = None
            log("已保存清稿：%s_清稿.%s" % (base, ext_out))

        md5_after = file_md5(dwg_path)
        md5_ok = md5_before == md5_after
        if not md5_ok:
            notes.append("警告：原文件 MD5 发生变化，请检查！")

        log_file = _write_log(item_dir, base, deleted, replaced, frames_count,
                              pdf_pages, md5_ok, notes)
        previews = _render_pdf_previews(pdf_path, item_dir)
        result.update(
            status="success",
            frame_count=frames_count,
            pdf_pages=pdf_pages,
            deleted_count=len(deleted),
            replaced_count=len(replaced),
            log_file=log_file,
            previews=previews,
            notes=notes,
        )
        log("完成：%s（删 %d / 改 %d）" % (base, len(deleted), len(replaced)))
    except cad.CadError as e:
        result["error"] = str(e)
        log("失败：%s" % e)
    except Exception as e:
        result["error"] = "%s: %s" % (type(e).__name__, e)
        log("失败：%s: %s" % (type(e).__name__, e))
    finally:
        for t in temp_pdfs:
            if os.path.exists(t):
                try:
                    os.remove(t)
                except Exception:
                    pass

    return result


def _process_space(session, doc, space, cfg, log, notes, layout_name=""):
    """处理一个空间（布局/模型）内的图框与标题栏清理。

    返回 (deleted, replaced, notes, frames_count, has_content)。
    """
    tag = ("布局 %s " % layout_name) if layout_name else ""
    if space is None or space.Count == 0:
        return [], [], [], 0, False
    log("%s空间实体 %d 个" % (tag, space.Count))

    # 0) 代理实体总量检测
    try:
        proxy_total = _count_proxy_entities(session, space)
        if proxy_total:
            notes.append("%s检测到 %d 个代理实体（天正等），将转换/炸开解析；无法解析的需人工核对"
                         % (tag, proxy_total))
    except Exception:
        pass

    # 1) 炸开/转换图框块（含代理与外部参照）
    _explode_frame_blocks(session, doc, space, cfg, log, notes, tag)

    # 2) 图框检测
    rects = _collect_rects(session, space, cfg)
    frames = titleblock.detect_frames(rects, cfg)
    if not frames:
        notes.append("%s未检测到标准图框矩形，整空间作为一页处理" % tag)
        log("%s警告：未检测到图框矩形" % tag)
        ext = session.space_extents(space)
        frames = [titleblock.Frame(ext[0], ext[1], ext[2], ext[3])]
    ordered = titleblock.sort_frames(frames)
    log("%s检测到图框 %d 个" % (tag, len(ordered)))

    deleted, replaced = [], []
    for i, frame in enumerate(ordered):
        region = _resolve_region(session, space, frame, rects, cfg, log, notes)
        if region is None:
            notes.append("%s图 %d：未识别到标题栏特征（无标题栏页/纯图例页），跳过清理"
                         % (tag, i + 1))
            continue
        d, r, nt = _clean_titleblock(session, doc, space, region, frame, cfg, log)
        deleted.extend(d)
        replaced.extend(r)
        notes.extend(nt)
        log("%s图 %d/%d：删除 %d 条，替换 %d 条" % (tag, i + 1, len(ordered), len(d), len(r)))
    return deleted, replaced, [], len(ordered), True


def _plot_model_frames(session, doc, space, cfg, temp_pdfs, item_dir, start_idx):
    """模型空间逐图框窗口打印（多图框逐页）。"""
    rects = _collect_rects(session, space, cfg)
    frames = titleblock.detect_frames(rects, cfg)
    if not frames:
        ext = session.space_extents(space)
        frames = [titleblock.Frame(ext[0], ext[1], ext[2], ext[3])]
    for i, frame in enumerate(titleblock.sort_frames(frames)):
        tmp = os.path.join(item_dir, "_tmp_p%d.pdf" % (start_idx + i))
        session.plot_frame(doc, frame, tmp, cfg)


def _plot_layout_page(session, doc, space, pdf_path, cfg):
    """布局整页范围打印（布局通常一页一图框；范围打印最稳）。"""
    ext = session.space_extents(space)
    frame_all = titleblock.Frame(ext[0], ext[1], ext[2], ext[3])
    session.plot_frame(doc, frame_all, pdf_path, cfg)


def _resolve_region(session, space, frame, rects, cfg, log, notes):
    """确定标题栏区域，返回 (minx,miny,maxx,maxy) 或 None（无标题栏页）。

    优先真实小矩形（detect_titleblock_region，须含保护词文字验证）；
    回退默认区域（corner 配置 + 红线区外扩）；仍无保护词 → None。
    """
    cand = titleblock.detect_titleblock_region(frame, rects, cfg)
    if cand and _region_has_protect_text(session, space, cand, frame, cfg):
        log("标题栏真实边界：%s" % (cand,))
        return cand
    region = titleblock.titleblock_region(frame, cfg)
    if _region_has_protect_text(session, space, region, frame, cfg):
        return region
    return None


def _region_has_protect_text(session, space, region, frame, cfg):
    """区域内是否出现保护词文字簇（图名/图号/比例/工程名称等任一）。

    用于：①验证真实边界候选确实落在标题栏上；②识别无标题栏页（目录页/说明页）。
    """
    for ent in session.iter_entities(space):
        txt = session.get_text(ent)
        if not txt:
            continue
        p = _entity_pos(session, ent, frame)
        if p and titleblock.in_region(p[0], p[1], region):
            if any(k in txt for k in cfg.get("protect_keywords", [])):
                return True
    return False


def _entity_pos(session, ent, frame):
    """实体位置：优先包围盒中心（MTEXT/TEXT 都稳），插入点兜底；
    斜置图框时按 rotation 逆变换回正轴系。"""
    b = session.get_bounds(ent)
    if b:
        x, y = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
    else:
        p = session.get_insertion(ent)
        if p is None:
            return None
        x, y = p[0], p[1]
    if frame is not None and frame.rotation:
        x, y = titleblock.rotate_point(x, y, frame.cx, frame.cy, frame.rotation)
    return (x, y)


def process_folder(input_path, out_dir, config=None, recursive=True, on_progress=None):
    """批量处理：input_path 为 DWG/DXF 文件或文件夹。返回汇总报告。"""
    cfg = config or rules.load_config()
    files = []
    if os.path.isdir(input_path):
        for root, dirs, fnames in os.walk(input_path):
            for fn in sorted(fnames):
                if fn.lower().endswith((".dwg", ".dxf")):
                    files.append(os.path.join(root, fn))
            if not recursive:
                break
    elif os.path.isfile(input_path):
        files = [input_path]
    else:
        raise FileNotFoundError("输入路径不存在：%s" % input_path)

    items = []
    for f in files:
        if on_progress:
            on_progress("开始处理：%s" % os.path.basename(f))
        items.append(process_file(f, out_dir, cfg, on_progress))
        if on_progress:
            on_progress("")

    return {
        "total": len(files),
        "success": sum(1 for r in items if r["status"] == "success"),
        "failed": sum(1 for r in items if r["status"] != "success"),
        "items": items,
    }


# ---------- 内部实现 ----------

def _count_proxy_entities(session, space):
    """统计代理实体数量（天正等第三方对象，COM 读不出内容）。"""
    n = 0
    for ent in session.iter_entities(space):
        if session.is_proxy(ent):
            n += 1
    return n


def _explode_frame_blocks(session, doc, space, cfg, log, notes, tag=""):
    """炸开/转换图框与标题栏块引用。

    - 块名命中关键词或外框尺寸命中标准图幅 → 炸开；
    - 代理实体（天正）先 ConvertToAutoCADType，失败再炸开；
    - 外部参照（Xref）承载图框 → 炸开并把内容并入本图，明确告警。
    """
    rounds = 3
    while rounds > 0:
        rounds -= 1
        targets = []
        for ent in session.iter_entities(space):
            if session.is_proxy(ent):
                targets.append(("proxy", ent))
                continue
            if ent.ObjectName != "AcDbBlockReference":
                continue
            try:
                name = str(ent.Name or "").lower()
            except Exception:
                name = ""
            is_name_hit = any(k in name for k in FRAME_BLOCK_NAME_KEYS)
            is_size_hit = False
            b = session.get_bounds(ent)
            if b:
                is_size_hit = titleblock.match_standard_size(b[2] - b[0], b[3] - b[1])
            if is_name_hit or is_size_hit:
                if session.is_xref(ent, doc):
                    targets.append(("xref", ent))
                else:
                    targets.append(("block", ent))
        if not targets:
            break
        for kind, ent in targets:
            if kind == "proxy":
                if session.convert_to_autocad_type(ent):
                    notes.append("%s代理实体已转换为 AutoCAD 基础实体（图框/标题栏可读）" % tag)
                    continue
                try:
                    out = session.explode_ref(ent)
                    if out:
                        notes.append("%s代理实体（图框/标题栏）已炸开解析" % tag)
                except Exception as e:
                    notes.append("%s代理实体炸开异常 %s: %s" % (tag, ent, e))
            elif kind == "xref":
                try:
                    session.explode_ref(ent)
                    notes.append("%s外部参照图框已炸开并入本图；若标题栏仍在参照文件中清理不净，请在 AutoCAD 执行 XREF 绑定后重试" % tag)
                except Exception as e:
                    notes.append("%s外部参照图框炸开失败：%s" % (tag, e))
            else:
                try:
                    out = session.explode_ref(ent)
                    if not out:
                        notes.append("%s炸开块失败或空：%s" % (tag, ent.Name))
                except Exception as e:
                    notes.append("%s炸开块异常 %s: %s" % (tag, ent.Name, e))
        log("%s炸开/转换图框块 %d 个" % (tag, len(targets)))


def _collect_rects(session, space, cfg):
    """收集空间中所有候选矩形（闭合多段线矩形[含斜置转正] + LINE 组合矩形）。"""
    rects = []
    for ent in session.iter_entities(space):
        r = session.get_polyline_rect(ent)
        if r:
            rects.append(r)
    tb_cfg = cfg.get("titleblock", {})
    if tb_cfg.get("use_line_detection", True):
        h_lines, v_lines = session.collect_lines(space)
        rects.extend(titleblock.build_rects_from_lines(h_lines, v_lines))
    return rects


def _clean_titleblock(session, doc, space, region, frame, cfg, log):
    """清理一个图框内的标题栏：炸开/转换区域内块 → 按规则删/改区域内对象。

    v0.1.156 全情况：
    - 区域内代理实体（天正）Convert 优先、炸开兜底；炸出/转换出的文字重新收集
    - 区域内文字：白名单模式（非 protect 全删）或黑名单模式；保护词混合文本局部清洗
    - 区域内光栅图像（扫描签名/图章/照片）删除
    - 区域内表格对象（AcDbTable）：无保护词 → 删除整表；含保护词 → 保留+告警
    - 删除/替换前对锁定图层临时解锁，操作后恢复
    - 外部参照块引用 → 炸开 + 告警
    - 位置判定优先 GetBoundingBox 中心（斜置图框按 rotation 逆变换）
    """
    deleted, replaced, notes = [], [], []
    whitelist = bool(cfg.get("titleblock", {}).get("whitelist_mode", True))

    def in_reg(x, y):
        return titleblock.in_region(x, y, region)

    # 1) 循环处理区域内块/代理实体（转换或炸开，直到没有可处理目标）
    rounds = 6
    while rounds > 0:
        rounds -= 1
        targets = []
        for ent in session.iter_entities(space):
            if session.is_proxy(ent):
                targets.append(("proxy", ent))
                continue
            if ent.ObjectName != "AcDbBlockReference":
                continue
            p = _entity_pos(session, ent, frame)
            if p and in_reg(p[0], p[1]):
                targets.append(("xref", ent) if session.is_xref(ent, doc) else ("block", ent))
        if not targets:
            break
        for kind, ent in targets:
            if kind == "proxy":
                if session.convert_to_autocad_type(ent):
                    notes.append("代理实体已转换（区域内标题栏可读）")
                    continue
                try:
                    out = session.explode_ref(ent)
                    if out:
                        notes.append("代理实体已炸开解析")
                    else:
                        notes.append("警告：区域内存在无法读取的代理实体（天正等），其内容可能未清理，请人工核对")
                except Exception as e:
                    notes.append("警告：代理实体处理失败（%s），请人工核对" % e)
            elif kind == "xref":
                try:
                    session.explode_ref(ent)
                    notes.append("区域内外部参照块已炸开并入本图；若标题栏内容仍缺，请在 AutoCAD XREF 绑定后重试")
                except Exception as e:
                    notes.append("区域内外部参照块炸开失败：%s" % e)
            else:
                try:
                    session.explode_ref(ent)
                except Exception as e:
                    notes.append("炸开标题栏块失败 %s: %s" % (ent.Name, e))
        log("处理区域内块/代理实体一批（剩余循环 %d）" % rounds)

    # 2) 收集区域内可处理对象
    text_targets = []    # (ent, txt, pos)
    raster_targets = []  # (ent, pos)
    table_targets = []   # (ent, pos, cell_texts)
    for ent in session.iter_entities(space):
        p = _entity_pos(session, ent, frame)
        if p is None or not in_reg(p[0], p[1]):
            continue
        if session.is_raster(ent):
            raster_targets.append((ent, p))
            continue
        if session.is_table(ent):
            table_targets.append((ent, p, session.table_cell_texts(ent)))
            continue
        txt = session.get_text(ent)
        if txt is not None:
            text_targets.append((ent, txt, p))

    # 3) 判定
    delete_queue = []    # (ent, desc)
    replace_queue = []   # (ent, new_text, desc)
    for ent, txt, pos in text_targets:
        if whitelist:
            action, reason, new_text = rules.judge_whitelist_text(txt, cfg)
        else:
            action, reason, new_text = rules.judge_text(txt, cfg)
        pos_str = "%.1f,%.1f" % (pos[0], pos[1])
        if action == "delete":
            delete_queue.append((ent, "%r [%s] (%s)" % (txt, reason, pos_str)))
            log("删除 (%s) %r" % (reason, txt))
        elif action == "replace":
            replace_queue.append((ent, new_text, "%r -> %r [%s] (%s)"
                                  % (txt, new_text, reason, pos_str)))
            log("替换 %r -> %r" % (txt, new_text))
    for ent, pos in raster_targets:
        delete_queue.append((ent, "光栅图像（扫描签名/图章/照片）(%.1f,%.1f)"
                             % (pos[0], pos[1])))
        log("删除光栅图像 (%.1f,%.1f)" % (pos[0], pos[1]))
    for ent, pos, cells in table_targets:
        has_protect = any(any(k in c for k in cfg.get("protect_keywords", [])) for c in cells)
        if has_protect:
            notes.append("区域内表格标题栏含保护内容（图名/图号等），已保留表格本体，请人工核对")
        else:
            delete_queue.append((ent, "表格对象（标题栏表格，无保护内容）(%.1f,%.1f)"
                                 % (pos[0], pos[1])))
            log("删除表格对象 (%.1f,%.1f)" % (pos[0], pos[1]))

    # 4) 执行：先解锁涉及的锁定图层，操作后恢复
    locked_layers = {}
    all_ops = delete_queue + [(e, "", "") for e, _n, _d in replace_queue]
    for ent, _desc, _extra in all_ops:
        try:
            layer = str(ent.Layer or "")
        except Exception:
            layer = ""
        if layer and layer not in locked_layers:
            locked_layers[layer] = session.get_layer_lock(doc, layer)
    for layer, was in locked_layers.items():
        if was:
            session.set_layer_lock(doc, layer, False)
    try:
        for ent, desc in delete_queue:
            try:
                ent.Delete()
                deleted.append({"text": desc, "reason": "deleted", "pos": ""})
            except Exception as e:
                notes.append("删除失败 %s: %s" % (desc, e))
        for ent, new_text, desc in replace_queue:
            try:
                session.set_text(ent, new_text)
                replaced.append({"old": desc, "new": new_text, "reason": "replaced", "pos": ""})
            except Exception as e:
                notes.append("替换失败 %s: %s" % (desc, e))
    finally:
        for layer, was in locked_layers.items():
            if was:
                session.set_layer_lock(doc, layer, True)

    return deleted, replaced, notes


def _render_pdf_previews(pdf_path, out_dir, max_pages=6):
    """清稿 PDF 每页渲染缩略图（PNG）供人工验收（2026-10-25 整改）。

    依赖 PyMuPDF（fitz）；未安装时返回 []，不阻塞主流程。
    """
    previews = []
    try:
        import fitz  # PyMuPDF
    except Exception:
        return []
    try:
        doc = fitz.open(pdf_path)
        prev_dir = os.path.join(out_dir, "验收缩略图")
        os.makedirs(prev_dir, exist_ok=True)
        for i in range(min(doc.page_count, max_pages)):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
            p = os.path.join(prev_dir, "page_%02d.png" % (i + 1))
            pix.save(p)
            previews.append(p)
        doc.close()
    except Exception:
        return []
    return previews
