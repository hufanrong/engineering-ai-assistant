# -*- coding: utf-8 -*-
"""核心处理流程：process_file / process_folder。

不依赖 UI，返回结构化结果，可被 GUI、CLI 或其他程序直接 import 调用。
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
    """处理单个 DWG：清理标题栏 → 另存清稿 DWG → 逐图导出合并 PDF。

    返回结果字典：
    {status, file, output_dir, cleaned_dwg, pdf, frame_count, pdf_pages,
     deleted_count, replaced_count, log_file, error}
    """
    cfg = config or rules.load_config()

    def log(msg):
        if on_progress:
            on_progress(msg)

    base = os.path.splitext(os.path.basename(dwg_path))[0]
    item_dir = os.path.join(out_dir, base)
    os.makedirs(item_dir, exist_ok=True)
    cleaned_path = os.path.join(item_dir, "%s_清稿.dwg" % base)
    pdf_path = os.path.join(item_dir, "%s_竣工.pdf" % base)

    deleted, replaced, notes = [], [], []
    frames_count, pdf_pages = 0, 0
    md5_before = file_md5(dwg_path)

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
        "error": "",
    }

    try:
        with cad.CadSession() as session:
            doc = session.open_document(dwg_path, readonly=True)
            space = doc.ModelSpace
            log("已打开（只读）：%s" % base)

            # 1) 炸开"图框/标题栏"块（整框为块、多图共用同一块的情况）
            _explode_frame_blocks(session, space, cfg, log, notes)

            # 2) 检测图框
            rects = _collect_rects(session, space, cfg)
            frames = titleblock.detect_frames(rects, cfg)
            if not frames:
                notes.append("未检测到标准图框矩形，整文件作为一页处理")
                log("警告：未检测到图框矩形，整文件作为一页处理")
                ext = session.space_extents(space)
                frames = [titleblock.Frame(ext[0], ext[1], ext[2], ext[3])]
            ordered = titleblock.sort_frames(frames)
            frames_count = len(ordered)
            log("检测到图框 %d 个" % frames_count)

            # 3) 逐图框清理标题栏
            for i, frame in enumerate(ordered):
                region = titleblock.titleblock_region(frame, cfg)
                d, r, nt = _clean_titleblock(session, space, region, cfg, log)
                deleted.extend(d)
                replaced.extend(r)
                notes.extend(nt)
                log("图 %d/%d：删除 %d 条，替换 %d 条" % (i + 1, frames_count, len(d), len(r)))

            # 4) 逐图框导出 PDF 并合并
            temp_pdfs = []
            try:
                for i, frame in enumerate(ordered):
                    tmp = os.path.join(item_dir, "_tmp_p%d.pdf" % i)
                    session.plot_frame(doc, frame, tmp, cfg)
                    temp_pdfs.append(tmp)
                pdf_pages = pdfmerge.merge_pdfs(temp_pdfs, pdf_path)
                log("已生成 PDF：%d 页" % pdf_pages)
            finally:
                for t in temp_pdfs:
                    if os.path.exists(t):
                        try:
                            os.remove(t)
                        except Exception:
                            pass

            # 5) 另存清稿副本
            session.save_as(doc, cleaned_path)
            doc.Close(False)
            session._doc = None
            log("已保存清稿：%s_清稿.dwg" % base)

        md5_after = file_md5(dwg_path)
        md5_ok = md5_before == md5_after
        if not md5_ok:
            notes.append("警告：原文件 MD5 发生变化，请检查！")

        log_file = _write_log(item_dir, base, deleted, replaced, frames_count, pdf_pages, md5_ok, notes)
        result.update(
            status="success",
            frame_count=frames_count,
            pdf_pages=pdf_pages,
            deleted_count=len(deleted),
            replaced_count=len(replaced),
            log_file=log_file,
        )
        log("完成：%s（删 %d / 改 %d）" % (base, len(deleted), len(replaced)))
    except cad.CadError as e:
        result["error"] = str(e)
        log("失败：%s" % e)
    except Exception as e:
        result["error"] = "%s: %s" % (type(e).__name__, e)
        log("失败：%s: %s" % (type(e).__name__, e))

    return result


def process_folder(input_path, out_dir, config=None, recursive=True, on_progress=None):
    """批量处理：input_path 为 DWG 文件或文件夹。返回汇总报告。"""
    cfg = config or rules.load_config()
    files = []
    if os.path.isdir(input_path):
        for root, dirs, fnames in os.walk(input_path):
            for fn in sorted(fnames):
                if fn.lower().endswith(".dwg"):
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

def _explode_frame_blocks(session, space, cfg, log, notes):
    """炸开图框/标题栏块引用（块名命中关键词，或外框尺寸命中标准图幅）。"""
    rounds = 3
    while rounds > 0:
        rounds -= 1
        targets = []
        for ent in session.iter_entities(space):
            if ent.ObjectName != "AcDbBlockReference":
                continue
            if session.is_proxy(ent):
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
                targets.append(ent)
        if not targets:
            break
        for ent in targets:
            try:
                out = session.explode_ref(ent)
                if not out:
                    notes.append("炸开块失败或空：%s" % ent.Name)
            except Exception as e:
                notes.append("炸开块异常 %s: %s" % (ent.Name, e))
        log("炸开图框/标题栏块 %d 个" % len(targets))


def _collect_rects(session, space, cfg):
    """收集模型空间中所有候选矩形（闭合多段线矩形 + LINE 组合矩形）。"""
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


def _clean_titleblock(session, space, region, cfg, log):
    """清理一个图框内的标题栏：炸开区域内块 → 按规则删/改区域内文字。"""
    deleted, replaced, notes = [], [], []

    # 1) 炸开区域内所有块引用（含属性块，属性值炸开后转为 TEXT 一并处理；多图共用块则逐实例处理）
    rounds = 4
    while rounds > 0:
        rounds -= 1
        targets = []
        for ent in session.iter_entities(space):
            if ent.ObjectName != "AcDbBlockReference":
                continue
            if session.is_proxy(ent):
                continue
            p = session.get_insertion(ent)
            if p and titleblock.in_region(p[0], p[1], region):
                targets.append(ent)
        if not targets:
            break
        for ent in targets:
            try:
                session.explode_ref(ent)
            except Exception as e:
                notes.append("炸开标题栏块失败 %s: %s" % (ent.Name, e))
        log("炸开标题栏块 %d 个" % len(targets))

    # 2) 收集区域内文字（先收集后处理，避免遍历中修改集合）
    text_targets = []
    for ent in session.iter_entities(space):
        if session.is_proxy(ent):
            continue
        txt = session.get_text(ent)
        if txt is None:
            continue
        p = session.get_insertion(ent)
        if p is None:
            b = session.get_bounds(ent)
            p = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0) if b else None
        if p and titleblock.in_region(p[0], p[1], region):
            text_targets.append((ent, txt, p))

    # 3) 判定并执行
    for ent, txt, pos in text_targets:
        action, reason, new_text = rules.judge_text(txt, cfg)
        pos_str = "%.1f,%.1f" % (pos[0], pos[1])
        if action == "delete":
            try:
                session.delete_entity(ent)
                deleted.append({"text": txt, "reason": reason, "pos": pos_str})
                log("删除 (%s) %r" % (reason, txt))
            except Exception as e:
                notes.append("删除失败 %r: %s" % (txt, e))
        elif action == "replace":
            try:
                session.set_text(ent, new_text)
                replaced.append({"old": txt, "new": new_text, "reason": reason, "pos": pos_str})
                log("替换 %r -> %r" % (txt, new_text))
            except Exception as e:
                notes.append("替换失败 %r: %s" % (txt, e))

    return deleted, replaced, notes
