# -*- coding: utf-8 -*-
"""PDF 合并与页数校验（基于 pypdf）。"""

from pypdf import PdfReader, PdfWriter


def merge_pdfs(paths, out_path):
    """按给定顺序把多个 PDF 合并为一个，返回总页数。"""
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
    return len(PdfReader(path).pages)
