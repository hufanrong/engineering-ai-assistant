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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from dwg_cleaner import cad, pdfmerge, rules, titleblock

FRAME_BLOCK_NAME_KEYS = ("图框", "标题", "frame", "title", "titleblock", "tb")


@dataclass
class CleanOp:
    """R3：清稿操作的强类型载体，替代跨函数传递的裸元组（根治 P-01 解包错误）。

    kind="delete"  删除实体；kind="replace" 用 new_text 改写文字。
    """
    ent: Any
    kind: str
    desc: str = ""
    new_text: Optional[str] = None


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

            # PDF 合并（R1：合并前先做逐页产物断言，存在性 + 页数）
            valid_pdfs, _pt = _verify_pdf_pages(
                temp_pdfs, expected=frames_count, notes=notes, log=log)
            if valid_pdfs:
                pdf_pages = pdfmerge.merge_pdfs(valid_pdfs, pdf_path)
                log("已生成 PDF：%d 页" % pdf_pages)
                if pdf_pages <= 0:
                    notes.append("警告：PDF 合并后页数为 0，打印链路异常，请人工核对成品目录")
            else:
                notes.append("未生成任何有效 PDF 页（存在性/页数校验未通过，打印链路异常；"
                             "清稿后的 DWG 已另存，可手动打印）")

            # R2：打印阶段被容错跳过的属性设置透出到 notes（不静默）
            for w in getattr(session, "drain_plot_warnings", lambda: [])():
                notes.append("打印参数：%s" % w)

            # 另存清稿副本（F-04：save_as 返回规整后的真实路径，纠正双扩展名）
            cleaned_path = session.save_as(doc, cleaned_path) or cleaned_path
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
        # 2026-10-26：COM 报错（如"输入无效"）只给一句话无法定位，
        # 支持 FANGONG_DEBUG=1 时把完整堆栈落到日志，便于反馈开发者。
        try:
            import os as _os
            if _os.environ.get("FANGONG_DEBUG") == "1":
                import traceback as _tb
                for _ln in _tb.format_exc().splitlines():
                    log("  [debug] %s" % _ln)
        except Exception:  # noqa: BLE001
            pass
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
        region, mode = _resolve_region(session, space, frame, rects, cfg, log, notes)
        if region is None:
            notes.append("%s图 %d：未识别到标题栏特征（无标题栏页/纯图例页），跳过清理"
                         % (tag, i + 1))
            continue
        d, r, nt = _clean_titleblock(session, doc, space, region, frame, cfg, log, mode=mode)
        deleted.extend(d)
        replaced.extend(r)
        notes.extend(nt)
        log("%s图 %d/%d（区域模式 %s）：删除 %d 条，替换 %d 条"
            % (tag, i + 1, len(ordered), mode, len(d), len(r)))
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
        # 2026-10-26 修复（v0.1.156 回归 Bug）：原实现打印后未登记到 temp_pdfs，
        # 导致合并步骤拿不到页、最终 PDF 不生成且临时文件残留在成品目录。
        temp_pdfs.append(tmp)


def _plot_layout_page(session, doc, space, pdf_path, cfg):
    """布局整页范围打印（布局通常一页一图框；范围打印最稳）。"""
    ext = session.space_extents(space)
    frame_all = titleblock.Frame(ext[0], ext[1], ext[2], ext[3])
    session.plot_frame(doc, frame_all, pdf_path, cfg)


def _verify_pdf_pages(paths, expected=0, notes=None, log=None):
    """R1：产物断言——逐页校验 PDF 真实存在、可读、页数≥1。

    "调用成功但结果错"（PlotToFile 返回 True 却没文件、整图缩一页）在本模块连续
    重犯，故在合并前统一断言，剔除无效页并把异常透出到 notes。
    返回 (有效路径列表, 总页数)。
    """
    notes = notes if notes is not None else []
    valid, total = [], 0
    for p in paths:
        name = os.path.basename(p)
        if not os.path.exists(p) or os.path.getsize(p) <= 0:
            notes.append("警告：临时打印页缺失或为空：%s" % name)
            if log:
                log("产物断言失败：%s 缺失/为空" % name)
            continue
        try:
            n = pdfmerge.count_pages(p)
        except Exception as e:  # noqa: BLE001
            notes.append("警告：临时 PDF 无法读取 %s：%s" % (name, e))
            continue
        if n <= 0:
            notes.append("警告：临时 PDF 页数为 0：%s" % name)
            continue
        valid.append(p)
        total += n
    if expected and total and abs(total - expected) > max(1, int(expected * 0.2)):
        notes.append("提示：PDF 页数 %d 与检测到的图框/布局数 %d 不一致（可能整图缩页或"
                     "多框一页），请逐页核对" % (total, expected))
    return valid, total


def _all_text_pos(session, space, frame):
    """一次遍历收集空间内全部文字实体 (ent, txt, pos)，供多区域过滤复用。"""
    out = []
    for ent in session.iter_entities(space):
        txt = session.get_text(ent)
        if not txt:
            continue
        p = _entity_pos(session, ent, frame)
        if p:
            out.append((ent, txt, p))
    return out


def _texts_in_region(alltp, region):
    return [(txt, p) for _e, txt, p in alltp
            if titleblock.in_region(p[0], p[1], region)]


def _texts_have_protect(texts, cfg):
    """区域内文字是否命中保护词（C2：空格归一化，识别"图  号"等）。"""
    return any(rules._is_protected(txt, cfg) for txt, _p in texts)


def _texts_have_header_signature(texts, cfg):
    """C4：区域内是否出现顶部页眉特征（公司名 / 人名标签 / 日期）。

    目录页页眉通常有设计单位名、设计/审核/校对手写人名、日期；
    以此作为"值得保守清理"的判据，避免对普通说明页误动。
    """
    dk = cfg.get("delete_keywords", {})
    person_labels = dk.get("person_labels", [])
    institutions = dk.get("institution", [])
    norm = rules._norm_spaces
    for txt, _p in texts:
        nt = norm(txt)
        if any(norm(k) in nt for k in institutions if k):
            return True
        if any(norm(lab) in nt for lab in person_labels if lab):
            return True
        if rules._is_date_text(txt, cfg):
            return True
    return False


def _norm_region(region):
    """日志/记录用：规范化区域坐标（min<=max），避免打印畸形反向矩形（F-06/P2）。"""
    if not region:
        return region
    minx, miny, maxx, maxy = region
    return (min(minx, maxx), min(miny, maxy), max(minx, maxx), max(miny, maxy))


def _resolve_region(session, space, frame, rects, cfg, log, notes):
    """确定标题栏区域与清理模式，返回 (region, mode) 或 (None, None)。

    区域分级（R5，2026-10-26）：
      "real_rect"     真实标题栏（小矩形或文字簇反推，含保护词验证）→ 白名单模式
      "fallback_band" 底部回退条带（含保护词）  → 强制黑名单模式（C3：只删公司名/
                      人名/日期，坐标网格等不整删，避免误删图框底部坐标）
      "top_band"      顶部页眉条带（有公司/人名/日期特征）→ 黑名单模式（C4 目录页）

    F-05（2026-10-26）：①真实小矩形改为**候选列表逐个验保护词**（不再 top1 误判即放弃）；
    ②新增**文字簇反推**——线条表格标题栏无闭合小矩形时，由图号/工程名/设计/审核等标签
    文字簇包围盒外扩锁定真实区域，进入白名单，从根上解决人名/日期/证书删不掉。
    """
    tb = cfg.get("titleblock", {})
    alltp = _all_text_pos(session, space, frame)
    # F-06（2026-10-26）：先把文字裁剪到**当前图框内**。多图框并排同处一个模型空间时，
    # 若把相邻框的"设计/审核/图号"也纳入，会跨框聚成一个大簇，夹取后产生反向矩形，
    # 导致只有最后一个图框被清理。本框内的文字/矩形才参与本框的区域检测与清理。
    alltp = [(e, t, p) for (e, t, p) in alltp
             if (frame.minx - 2 <= p[0] <= frame.maxx + 2
                 and frame.miny - 2 <= p[1] <= frame.maxy + 2)]

    # 1) 真实小矩形候选列表，逐个验保护词（F-05②）
    for cand in titleblock.detect_titleblock_regions(frame, rects, cfg):
        if _texts_have_protect(_texts_in_region(alltp, cand), cfg):
            log("标题栏真实边界（白名单模式，小矩形）：%s" % (_norm_region(cand),))
            return cand, "real_rect"

    # 2) 文字簇反推真实区域（F-05①，线条表格标题栏兜底；F-06 已限本框）
    text_boxes = _collect_text_boxes(session, alltp, frame)
    field_lab, person_lab, date_lab, cert_lab = _titleblock_label_sets(cfg)
    seed_lab = field_lab | person_lab | date_lab | cert_lab
    infer = titleblock.infer_titleblock_region_from_texts(
        frame, text_boxes, seed_lab, field_lab, cfg)
    if infer:
        region, strong, seeds = infer
        notes.append("已由标题栏文字簇反推锁定真实区域（命中 %d 个字段标签），"
                     "按白名单模式清理" % strong)
        log("标题栏真实边界（白名单模式，文字簇反推，强标签%d/标签%d）：%s"
            % (strong, seeds, _norm_region(region)))
        return region, "real_rect"

    # 3) 底部回退条带 + 保护词 → 强制黑名单（C3：不再白名单整删，坐标安全）
    band = titleblock.titleblock_region(frame, cfg)
    if _texts_have_protect(_texts_in_region(alltp, band), cfg):
        notes.append("未锁定标题栏真实小矩形，回退到底部条带，按黑名单模式保守清理"
                     "（只删公司名/人名/日期，坐标网格标注不删）")
        log("标题栏回退底部条带（黑名单模式，防误删坐标）")
        return band, "fallback_band"

    # 4) C4 顶部页眉（目录页/说明页）→ 黑名单保守清理
    if tb.get("clean_top_header", True):
        top = titleblock.top_header_region(frame, cfg)
        ttexts = _texts_in_region(alltp, top)
        if _texts_have_header_signature(ttexts, cfg):
            notes.append("右下角未识别到标题栏，检测到页面顶部页眉，按黑名单模式"
                         "保守清理（公司名/人名/日期），其余内容保留")
            log("检测到顶部页眉（黑名单模式）")
            return top, "top_band"

    return None, None


def _titleblock_label_sets(cfg):
    """标题栏标签集（归一化）：(字段保护, 人名签署, 日期, 证书)。"""
    tb = cfg.get("titleblock", {})
    dk = cfg.get("delete_keywords", {})
    field_lab = set(rules._norm_spaces(x) for x in
                    (tb.get("field_labels") or titleblock.DEFAULT_FIELD_LABELS))
    person_lab = set(rules._norm_spaces(x) for x in dk.get("person_labels", []))
    date_lab = set(rules._norm_spaces(x) for x in dk.get("date_labels", []))
    cert_lab = set(rules._norm_spaces(x) for x in dk.get("cert_labels", []))
    return field_lab, person_lab, date_lab, cert_lab


def _collect_text_boxes(session, alltp, frame):
    """从 (ent, txt, pos) 列表构造文字簇反推所需的包围盒结构（norm 已剥格式码）。"""
    out = []
    for ent, txt, _p in alltp:
        box = _entity_box(session, ent, frame)
        if not box:
            continue
        out.append({
            "norm": rules._norm_spaces(rules.strip_mtext_codes(txt)),
            "minx": box[0], "miny": box[1], "maxx": box[2], "maxy": box[3],
        })
    return out


def _region_has_protect_text(session, space, region, frame, cfg):
    """区域内是否出现保护词文字簇（兼容旧调用；内部走 C2 归一化判定）。"""
    for ent in session.iter_entities(space):
        txt = session.get_text(ent)
        if not txt:
            continue
        p = _entity_pos(session, ent, frame)
        if p and titleblock.in_region(p[0], p[1], region):
            if rules._is_protected(txt, cfg):
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


def _entity_box(session, ent, frame):
    """实体转正后的包围盒 (minx,miny,maxx,maxy)；无 bbox 时以插入点兜底小框。

    供 C1 标签→值几何关联使用（同行/右侧/间距判定）。
    """
    b = session.get_bounds(ent)
    if b:
        minx, miny, maxx, maxy = b[0], b[1], b[2], b[3]
        if frame is not None and frame.rotation:
            pts = [titleblock.rotate_point(x, y, frame.cx, frame.cy, frame.rotation)
                   for x, y in ((minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy))]
            minx = min(p[0] for p in pts)
            maxx = max(p[0] for p in pts)
            miny = min(p[1] for p in pts)
            maxy = max(p[1] for p in pts)
        return (minx, miny, maxx, maxy)
    p = session.get_insertion(ent)
    if p is None:
        return None
    fh = frame.height if frame else 1.0
    fw = frame.width if frame else 1.0
    s = max(fh * 0.01, 1.0)
    return (p[0] - s, p[1] - s * 0.5, p[0] + s + fw * 0.02, p[1] + s * 0.5)


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


def _clean_titleblock(session, doc, space, region, frame, cfg, log, mode="real_rect"):
    """清理一个图框内的标题栏：炸开/转换区域内块 → 按规则删/改区域内对象。

    mode（R5 区域分级，2026-10-26）：
      real_rect     真实小矩形 → 白名单模式（标题栏只留保护字段）
      fallback_band / top_band  回退条带/顶部页眉 → 强制黑名单模式（只删公司名/
                    人名/日期，坐标网格等不整删，避免误删图纸内容）
    全情况：
    - 区域内代理实体（天正）Convert 优先、炸开兜底；炸出/转换出的文字重新收集
    - C1：标签→值几何关联，"工程名称/图号/图名"标签旁的值实体即使无保护词也保留
    - C2：保护词匹配空白归一化（"图  号"也识别）
    - C3/R5：条带/页眉强制黑名单，坐标网格标注保留
    - 区域内光栅图像（扫描签名/图章/照片）删除
    - 区域内表格对象（AcDbTable）：无保护词 → 删除整表；含保护词 → 保留+告警
    - 删除/替换前对锁定图层临时解锁，操作后恢复
    - R3：删除/替换统一用 CleanOp 强类型，杜绝裸元组解包
    """
    deleted, replaced, notes = [], [], []
    tb = cfg.get("titleblock", {})
    # 只有真实小矩形才启用白名单整删；条带/页眉强制黑名单（C3/R5）
    use_whitelist = bool(tb.get("whitelist_mode", True)) if mode == "real_rect" else False

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

    # 2) 收集区域内可处理对象（F-08：同时收集整个图框文字，供区域外证书号扩展）
    text_targets = []    # (ent, txt, pos, box) 标题栏区域内
    frame_all_texts = []  # (ent, txt, pos, box) 整个图框内（含区域外）
    raster_targets = []  # (ent, pos)
    table_targets = []   # (ent, pos, cell_texts)

    def in_frame(x, y):
        return (frame.minx - 1e-6 <= x <= frame.maxx + 1e-6
                and frame.miny - 1e-6 <= y <= frame.maxy + 1e-6)

    for ent in session.iter_entities(space):
        p = _entity_pos(session, ent, frame)
        if p is None or not in_frame(p[0], p[1]):
            continue
        txt = session.get_text(ent)
        if txt is not None:
            box = _entity_box(session, ent, frame)
            if box is None:
                box = (p[0], p[1], p[0], p[1])
            frame_all_texts.append((ent, txt, p, box))
        if not in_reg(p[0], p[1]):
            continue
        if session.is_raster(ent):
            raster_targets.append((ent, p))
            continue
        if session.is_table(ent):
            table_targets.append((ent, p, session.table_cell_texts(ent)))
            continue
        if txt is not None:
            text_targets.append((ent, txt, p, box))

    # 2.5) C1 标签→值【保护】 + F-01/F-02 标签→值【删除】
    # norm 同时剥 MText 格式码（F-03），使 {\T1.5;李安武} 这类值也能被几何关联。
    field_lab, person_lab, date_lab, cert_lab = _titleblock_label_sets(cfg)
    delete_lab = person_lab | date_lab | cert_lab
    assoc_targets = [{
        "key": i,
        "norm": rules._norm_spaces(rules.strip_mtext_codes(txt)),
        "minx": box[0], "miny": box[1], "maxx": box[2], "maxy": box[3],
    } for i, (_e, txt, _p, box) in enumerate(text_targets)]
    # 保护：字段标签（图号/工程名/图名…）右侧/下方紧邻的值 → 保留；遇人名/日期/证书标签即止
    protected_idx = titleblock.associate_label_values(
        assoc_targets, field_lab, delete_lab, frame, mode="protect")
    # 删除：人名/日期/证书标签右侧/下方紧邻的值（人名/日期/证书号）→ 删除；
    # 遇字段标签即止；并剔除受保护值（保护优先，C1 优先级最高）。
    # 白名单模式下这些裸值本就会被规则删除，此处主要是黑名单模式的双保险（F-01/F-02）。
    delete_idx = titleblock.associate_label_values(
        assoc_targets, delete_lab, field_lab, frame, mode="delete") - protected_idx
    # F-07（2026-10-26 真机 P0）：保护优先是绝对原则。标签关联删除只减了 C1 几何保护集，
    # 未排除"含保护词文本"（图名 '粗碎车间\\P平面布置图' 含"车间"）与 C3 坐标标注（Y549625），
    # 导致它们几何上落在签署标签邻域时被误删。这里逐项过滤，凡含保护词/坐标一律不删。
    _safe_delete = set()
    for i in delete_idx:
        raw_txt = text_targets[i][1]
        if rules._is_protected(raw_txt, cfg):
            log("F-07 保护优先，跳过标签关联删除（含保护词）%r" % raw_txt)
        elif rules._is_axis_coordinate(raw_txt):
            log("F-07 保护优先，跳过标签关联删除（坐标标注）%r" % raw_txt)
        else:
            _safe_delete.add(i)
    delete_idx = _safe_delete
    if protected_idx:
        log("C1 标签→值关联，保护 %d 个值实体（工程名/图号/图名的值）" % len(protected_idx))
    if delete_idx:
        log("F-01/F-02 标签→值关联，删除 %d 个签署值实体（人名/日期/证书号）" % len(delete_idx))

    # 3) 判定（R3：统一收集为 CleanOp）
    ops = []
    for i, (ent, txt, pos, _box) in enumerate(text_targets):
        if i in protected_idx:
            # F-09（2026-10-26）：保护字段值默认保留，但仍须执行"施工图→竣工图"等替换。
            # 此前直接 continue，导致"设计阶段"标签关联到的"施工图"值永不替换（图2 漏改）。
            if cfg.get("drawing_type_mode") == "replace":
                new_txt = rules.apply_replacements(txt, cfg)
                if new_txt != txt:
                    ops.append(CleanOp(
                        ent, "replace",
                        "%r -> %r [%s] (%.1f,%.1f)" % (
                            txt, new_txt, "protected_field_replace", pos[0], pos[1]),
                        new_txt))
                    log("替换（保护字段值内）%r -> %r" % (txt, new_txt))
            continue
        pos_str = "%.1f,%.1f" % (pos[0], pos[1])
        if i in delete_idx:
            # F-01/F-02：标签（设计/审核/审定/标图/日期/证书编号）旁的值，黑名单也删
            ops.append(CleanOp(ent, "delete",
                               "%r [%s] (%s)" % (txt, "label_value", pos_str)))
            log("删除（标签关联签署值）%r" % txt)
            continue
        if use_whitelist:
            action, reason, new_text = rules.judge_whitelist_text(txt, cfg)
        else:
            action, reason, new_text = rules.judge_text(txt, cfg)
        if action == "delete":
            ops.append(CleanOp(ent, "delete",
                               "%r [%s] (%s)" % (txt, reason, pos_str)))
            log("删除 (%s) %r" % (reason, txt))
        elif action == "replace":
            ops.append(CleanOp(ent, "replace",
                               "%r -> %r [%s] (%s)" % (txt, new_text, reason, pos_str),
                               new_text))
            log("替换 %r -> %r" % (txt, new_text))
    for ent, pos in raster_targets:
        ops.append(CleanOp(ent, "delete",
                           "光栅图像（扫描签名/图章/照片）(%.1f,%.1f)" % (pos[0], pos[1])))
        log("删除光栅图像 (%.1f,%.1f)" % (pos[0], pos[1]))
    for ent, pos, cells in table_targets:
        has_protect = any(rules._is_protected(c, cfg) for c in cells)
        if has_protect:
            notes.append("区域内表格标题栏含保护内容（图名/图号等），已保留表格本体，请人工核对")
        else:
            ops.append(CleanOp(ent, "delete",
                               "表格对象（标题栏表格，无保护内容）(%.1f,%.1f)" % (pos[0], pos[1])))
            log("删除表格对象 (%.1f,%.1f)" % (pos[0], pos[1]))

    # F-08：证书编号扩展——标题栏区域外、"设计证书编号"标签正下方/右侧的编号串也删除。
    # 真机证书号常被文字簇反推区域裁掉，区域内白名单/关联够不到，故在全图框内定位。
    cert_targets = [{
        "key": i,
        "norm": rules._norm_spaces(rules.strip_mtext_codes(txt)),
        "minx": box[0], "miny": box[1], "maxx": box[2], "maxy": box[3],
    } for i, (_e, txt, _p, box) in enumerate(frame_all_texts)]
    cert_del_idx = titleblock.find_cert_numbers(cert_targets, cert_lab, frame)
    _handled_ent_ids = {id(op.ent) for op in ops}
    for i, (ent, txt, pos, _box) in enumerate(frame_all_texts):
        if i not in cert_del_idx or id(ent) in _handled_ent_ids:
            continue
        # 双保险：保护词/坐标绝不删
        if rules._is_protected(txt, cfg) or rules._is_axis_coordinate(txt):
            log("F-08 证书扩展跳过（保护/坐标）%r" % txt)
            continue
        ops.append(CleanOp(ent, "delete",
                           "%r [%s] (%.1f,%.1f)" % (
                               txt, "cert_number_extension", pos[0], pos[1])))
        log("删除（证书编号扩展·区域外）%r" % txt)

    # 4) 执行：先解锁涉及的锁定图层，操作后恢复
    locked_layers = {}
    for op in ops:
        try:
            layer = str(op.ent.Layer or "")
        except Exception:
            layer = ""
        if layer and layer not in locked_layers:
            locked_layers[layer] = session.get_layer_lock(doc, layer)
    for layer, was in locked_layers.items():
        if was:
            session.set_layer_lock(doc, layer, False)
    try:
        for op in ops:
            if op.kind == "delete":
                try:
                    op.ent.Delete()
                    deleted.append({"text": op.desc, "reason": "deleted", "pos": ""})
                except Exception as e:
                    notes.append("删除失败 %s: %s" % (op.desc, e))
            else:
                try:
                    session.set_text(op.ent, op.new_text)
                    replaced.append({"old": op.desc, "new": op.new_text,
                                     "reason": "replaced", "pos": ""})
                except Exception as e:
                    notes.append("替换失败 %s: %s" % (op.desc, e))
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
