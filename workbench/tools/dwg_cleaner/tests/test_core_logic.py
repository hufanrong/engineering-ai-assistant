# -*- coding: utf-8 -*-
"""dwg_cleaner core 纯逻辑测试（不依赖 AutoCAD/pypdf，沙箱/CI 可直接跑）。

运行：
    cd tools && python -m dwg_cleaner.tests.test_core_logic

覆盖（对应清稿四查② + 工程四性②）：
- file_md5：原文件只读校验的底层函数（内容变化必须能检出）
- _norm_region：区域坐标归一化（F-06/P2 打印畸形反向矩形）
- _write_log：处理日志内容（删除/替换明细、图框数、PDF 页数、MD5 结果）——可追溯
- CleanOp：R3 删除/替换强类型载体
- 干净环境可 import：本文件能在未安装 pypdf 的环境导入 core（pdfmerge 延迟导入）
"""

import hashlib
import os
import sys
import tempfile

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from dwg_cleaner import core  # noqa: E402

_FAIL = 0
_PASS = 0


def check(name, cond, detail=""):
    global _FAIL, _PASS
    if cond:
        _PASS += 1
        print("  ✓ %s" % name)
    else:
        _FAIL += 1
        print("  ✗ %s  %s" % (name, detail))


def test_file_md5():
    print("[file_md5 原文件校验底层]")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.dwg")
        with open(p, "wb") as f:
            f.write(b"hello")
        expect = hashlib.md5(b"hello").hexdigest()
        check("MD5 值正确", core.file_md5(p) == expect)
        p2 = os.path.join(d, "b.dwg")
        with open(p2, "wb") as f:
            f.write(b"hello")
        check("同内容不同文件 MD5 一致", core.file_md5(p) == core.file_md5(p2))
        with open(p, "ab") as f:
            f.write(b"!")
        check("内容变化后 MD5 检出（清稿四查②底层）",
              core.file_md5(p) != expect)


def test_norm_region():
    print("[区域坐标归一化]")
    check("反向矩形交换", core._norm_region((5, 1, 3, -1)) == (3, -1, 5, 1))
    check("空值透传", core._norm_region(None) is None)
    check("正常矩形不变", core._norm_region((0, 0, 10, 10)) == (0, 0, 10, 10))


def test_write_log():
    print("[处理日志可追溯]")
    deleted = [{"reason": "P-01", "pos": "(100,50)", "text": "某设计院"}]
    replaced = [{"reason": "R-02", "old": "施工图", "new": "竣工图"}]
    with tempfile.TemporaryDirectory() as d:
        path = core._write_log(d, "测试图纸.dwg", deleted, replaced,
                               2, 3, True, ["备注一"])
        check("日志文件生成", os.path.basename(path) == "处理日志.txt")
        content = open(path, encoding="utf-8").read()
        check("含文件名", "测试图纸.dwg" in content)
        check("含图框数量", "图框数量    : 2" in content)
        check("含 PDF 页数", "PDF 页数    : 3" in content)
        check("含 MD5 一致结论", "未改动（MD5 一致）" in content)
        check("含删除明细", "--- 删除明细 ---" in content and "某设计院" in content)
        check("含替换明细", "--- 替换明细 ---" in content
              and "'施工图' -> '竣工图'" in content)
        check("含备注", "备注一" in content)

        path2 = core._write_log(d, "测试图纸.dwg", [], [], 1, 1, False, [])
        content2 = open(path2, encoding="utf-8").read()
        check("MD5 不一致时告警", "警告：原文件被改动！" in content2)


def test_cleanop():
    print("[CleanOp 强类型载体]")
    op_del = core.CleanOp(ent="实体1", kind="delete")
    check("删除操作默认描述", op_del.desc == "" and op_del.new_text is None)
    op_rep = core.CleanOp(ent="实体2", kind="replace", desc="R-02",
                           new_text="竣工图")
    check("替换操作携带新文字", op_rep.new_text == "竣工图")
    check("kind 取值", op_del.kind == "delete" and op_rep.kind == "replace")


def test_import_without_pypdf():
    print("[干净环境导入]")
    try:
        import pypdf  # noqa: F401
        check("当前环境已装 pypdf（跳过严格校验）", True)
    except ImportError:
        check("无 pypdf 环境仍可 import core（本文件已导入成功）", True)


def main():
    test_file_md5()
    test_norm_region()
    test_write_log()
    test_cleanop()
    test_import_without_pypdf()
    print("=" * 64)
    print("结果：通过 %d，失败 %d" % (_PASS, _FAIL))
    print("=" * 64)
    sys.exit(1 if _FAIL else 0)


if __name__ == "__main__":
    main()
