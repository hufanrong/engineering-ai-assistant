# -*- coding: utf-8 -*-
"""PDF 合并与页数校验（基于 pypdf）。

pypdf 在函数内延迟导入：纯逻辑回归测试（不触碰 PDF 的用例）在未安装 pypdf 的
沙箱/CI 环境也能 import 本模块；真正执行合并/页数校验时才要求 pypdf 可用。
"""


def _load_pypdf():
    from pypdf import PdfReader, PdfWriter
    return PdfReader, PdfWriter


def merge_pdfs(paths, out_path):
    """按给定顺序把多个 PDF 合并为一个，返回总页数。"""
    PdfReader, PdfWriter = _load_pypdf()
    writer = PdfWriter()
    for p in paths:
        reader = PdfReader(p)
        for page in reader.pages:
            writer.add_page(page)
    with open(out_path, "wb") as f:
        writer.write(f)
    return len(writer.pages)


def count_pages(path):
    """返回 PDF 页数。"""
    PdfReader, _ = _load_pypdf()
    return len(PdfReader(path).pages)
