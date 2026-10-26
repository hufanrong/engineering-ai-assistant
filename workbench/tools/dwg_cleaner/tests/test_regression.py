# -*- coding: utf-8 -*-
"""dwg_cleaner 清稿规则纯逻辑回归测试（不依赖 AutoCAD，沙箱/CI 可直接跑）。

运行：
    cd tools && python -m dwg_cleaner.tests.test_regression
    或：python tools/dwg_cleaner/tests/test_regression.py

覆盖（对应 2026-10-26 补丁交付单）：
- P-07 保护词仲裁：人名标签「设计」不得误伤保护词「设计阶段」
- C1  标签→值几何关联：工程名称/图号/图名的"值"实体即使无保护词也保留
- C2  空格归一化：「图  号」「工 程 名 称」这类带字间距标签也识别为保护字段
- C3  坐标网格/测量数值：X9193900 / Y549350 / 630 等任何模式下不删
- R3  CleanOp 强类型：删除/替换队列结构
- 日期正则防误伤图号：X2025-01 不应被当日期删除
"""

import os
import sys

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from dwg_cleaner import rules, titleblock, core  # noqa: E402

CFG = rules.load_config()
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


def expect(text, want, fn, label):
    action, reason, new = fn(text, CFG)
    check("%s | %r → %s（期望 %s）" % (label, text, action, want),
          action == want, "实际 %s/%s" % (action, reason))


def test_p07_protect_arbitration():
    print("[P-07] 保护词仲裁（人名标签不误伤保护字段）")
    wl = rules.judge_whitelist_text
    expect(r"{\T1.5;设计阶段}", "keep", wl, "P07")
    expect(r"{\T1.5;设计}", "delete", wl, "P07")
    expect("设计 李四", "delete", wl, "P07")
    expect("审核  王五", "delete", wl, "P07")
    expect("图号：X301 审核 王五", "replace", wl, "P07")
    expect("日期：2025.4.14", "delete", wl, "P07")
    # 图号值局部清洗后只剩图号
    _a, _r, new = wl("图号：X301 审核 王五", CFG)
    check("P07 混合文本清洗后只剩图号", new == "图号：X301", repr(new))


def test_c2_space_normalize():
    print("[C2] 空格归一化（带字间距标签识别为保护字段）")
    wl = rules.judge_whitelist_text
    for t in ["图  号", "工 程 名 称", "图纸  名称", "设 计 阶 段", "图\u3000号"]:
        expect(t, "keep", wl, "C2")


def test_c3_axis_coordinate():
    print("[C3] 坐标网格/测量数值（白名单与黑名单均保留）")
    for t in ["Y549350", "X9193900", "x:12345", "630", "1234.567"]:
        expect(t, "keep", rules.judge_whitelist_text, "C3白名单")
        expect(t, "keep", rules.judge_text, "C3黑名单")


def test_blacklist_mode():
    print("[C3/R5] 条带黑名单模式：公司/人名/日期删，图号/图名留")
    bl = rules.judge_text
    expect("紫金(厦门)工程设计有限公司", "delete", bl, "黑名单")
    expect("设计 李四", "delete", bl, "黑名单")
    expect("2024年11月", "delete", bl, "黑名单")
    expect("X398·301Z-02", "keep", bl, "黑名单")
    expect("粗碎车间布置图", "keep", bl, "黑名单")


def test_date_not_eat_drawing_no():
    print("[防误伤] 日期正则不得吃掉图号 X2025-01")
    bl = rules.judge_text
    expect("X2025-01", "keep", bl, "图号")


def test_c1_label_value():
    print("[C1] 标签→值几何关联")
    frame = titleblock.Frame(0, 0, 841, 594)

    def T(key, text, x0, y0, x1, y1):
        return {"key": key, "norm": rules._norm_spaces(text),
                "minx": x0, "miny": y0, "maxx": x1, "maxy": y1}

    targets = [
        T("proj_lab", "工程名称", 400, 20, 440, 32),
        T("proj_val", "刚果（金）Manono锂矿5Mt/年采选冶项目", 445, 20, 710, 32),
        T("no_lab", "图号", 400, 36, 428, 48),
        T("no_val", "X398·301Z-02", 433, 36, 520, 48),
        T("audit_lab", "审核", 600, 36, 620, 48),
        T("audit_val", "王五", 625, 36, 650, 48),
        T("company", "紫金(厦门)工程设计有限公司", 400, 52, 610, 64),
        T("coord", "Y549350", 100, 100, 140, 112),
    ]
    fl = set(rules._norm_spaces(x) for x in titleblock.DEFAULT_FIELD_LABELS)
    bl_ = set(rules._norm_spaces(x) for x in ["审核", "设计", "校对", "日期", "制图"])
    prot = titleblock.associate_label_values(targets, fl, bl_, frame)
    check("C1 工程名称值保留", "proj_val" in prot, str(prot))
    check("C1 图号值保留", "no_val" in prot, str(prot))
    check("C1 人名值不被保护", "audit_val" not in prot, str(prot))
    check("C1 公司名不被保护", "company" not in prot, str(prot))
    check("C1 坐标不参与关联", "coord" not in prot, str(prot))

    # 相邻标签：值归紧挨着的标签，不串到左侧其它标签
    t2 = [
        T("a_lab", "图号", 100, 10, 130, 22),
        T("b_lab", "图名", 150, 10, 180, 22),
        T("b_val", "粗碎车间布置图", 185, 10, 320, 22),
    ]
    p2 = titleblock.associate_label_values(t2, fl, bl_, frame)
    check("C1 相邻标签不串值", "b_val" in p2 and "b_lab" not in p2 and "a_lab" not in p2, str(p2))


def test_c1_spaced_label():
    print("[C1+C2] 带字间距的标签同样能关联到值")
    frame = titleblock.Frame(0, 0, 841, 594)

    def T(key, text, x0, y0, x1, y1):
        return {"key": key, "norm": rules._norm_spaces(text),
                "minx": x0, "miny": y0, "maxx": x1, "maxy": y1}

    targets = [
        T("lab", "图  号", 100, 10, 135, 22),
        T("val", "X398·301Z-02", 140, 10, 230, 22),
    ]
    fl = set(rules._norm_spaces(x) for x in titleblock.DEFAULT_FIELD_LABELS)
    prot = titleblock.associate_label_values(targets, fl, set(), frame)
    check("C1 空格标签「图  号」关联到图号值", "val" in prot, str(prot))


def test_r3_cleanop():
    print("[R3] CleanOp 强类型")
    op_del = core.CleanOp(ent="E1", kind="delete", desc="d")
    op_rep = core.CleanOp(ent="E2", kind="replace", desc="r", new_text="竣工图")
    check("CleanOp delete 字段", op_del.ent == "E1" and op_del.kind == "delete" and op_del.new_text is None)
    check("CleanOp replace 字段", op_rep.new_text == "竣工图" and op_rep.kind == "replace")
    # 统一队列遍历不会再出现裸元组解包错误
    for op in [op_del, op_rep]:
        assert op.kind in ("delete", "replace")
    check("CleanOp 统一遍历无解包异常", True)


def main():
    print("=" * 64)
    print("dwg_cleaner 纯逻辑回归测试（无 AutoCAD 依赖）")
    print("=" * 64)
    test_p07_protect_arbitration()
    test_c2_space_normalize()
    test_c3_axis_coordinate()
    test_blacklist_mode()
    test_date_not_eat_drawing_no()
    test_c1_label_value()
    test_c1_spaced_label()
    test_r3_cleanop()
    print("=" * 64)
    print("结果：通过 %d，失败 %d" % (_PASS, _FAIL))
    print("=" * 64)
    sys.exit(1 if _FAIL else 0)


if __name__ == "__main__":
    main()
