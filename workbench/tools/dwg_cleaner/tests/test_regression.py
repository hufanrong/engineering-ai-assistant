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


def test_f03_mtext_codes():
    """F-03：MText 内联格式码（\\T1.5;\\Q10;）穿插在文字中，判定前剥离，写回保留。"""
    print("[F-03] MText 格式码剥离后判定")
    # 剥离函数本身
    check("F-03 日期格式码剥成可见文本",
          rules.strip_mtext_codes(r"{\Q10;\T1.5;2024\Q0;年\Q10;07\Q0;月 }").strip() == "2024年07月")
    check("F-03 人名格式码剥成可见文本",
          rules.strip_mtext_codes(r"{\T1.5;李安武}") == "李安武")
    # 白名单：带格式码的日期/人名/证书 → 删除（真机残留的 2024年07月 / 李安武 / A135036965）
    expect(r"{\Q10;\T1.5;2024\Q0;年\Q10;07\Q0;月 }", "delete",
           rules.judge_whitelist_text, "F-03 白名单-带格式码日期")
    expect(r"{\T1.5;李安武}", "delete", rules.judge_whitelist_text, "F-03 白名单-带格式码人名")
    expect(r"{\T1.5;A135036965}", "delete", rules.judge_whitelist_text, "F-02 白名单-带格式码证书号")
    # 黑名单：带格式码日期应判 date（旧逻辑完整匹配失效）；人名/证书裸值靠标签关联删除
    expect(r"{\Q10;\T1.5;2024\Q0;年\Q10;07\Q0;月 }", "delete",
           rules.judge_text, "F-03 黑名单-带格式码日期")
    # 保护词带格式码不得误删
    expect(r"{\T1.5;竣工图}", "keep", rules.judge_text, "F-03 保护-竣工图")
    expect(r"{\T1.5;设计阶段}", "keep", rules.judge_text, "F-03 保护-设计阶段")
    expect(r"{\T1.5;竣工图}", "keep", rules.judge_whitelist_text, "F-03 白名单保护-竣工图")


class _FakeEnt:
    def __init__(self, name, text, box, layer="0", oname="AcDbMText"):
        self.ObjectName = oname
        self.Name = name
        self.TextString = text
        self._box = box
        self.Layer = layer
        self.deleted = False

    def GetBoundingBox(self):
        return (self._box[:2], self._box[2:])

    def Delete(self):
        self.deleted = True


class _FakeSession:
    """最小 mock，满足 core._clean_titleblock 的纯逻辑路径。"""
    def __init__(self, ents, block_attrs=None):
        self.ents = ents
        self.block_attrs = block_attrs or {}   # id(ent) -> [(text, box, attr_ent)]
        self.nested = {}                       # id(ent) -> [(text, box)]

    def iter_entities(self, space):
        return list(self.ents)

    def is_proxy(self, e): return False
    def is_xref(self, e, doc): return False
    def is_raster(self, e): return False
    def is_table(self, e): return False
    def get_text(self, e): return e.TextString
    def get_bounds(self, e): return e._box
    def get_insertion(self, e):
        return ((e._box[0] + e._box[2]) / 2.0, (e._box[1] + e._box[3]) / 2.0, 0)
    def get_layer_lock(self, doc, layer): return False
    def set_layer_lock(self, doc, layer, v): pass
    def explode_ref(self, e): return []
    def convert_to_autocad_type(self, e): return False
    def table_cell_texts(self, e): return []
    def set_text(self, e, t): e.TextString = t
    def drain_plot_warnings(self): return []
    def collect_block_attributes(self, e):
        return list(self.block_attrs.get(id(e), []))
    def collect_block_nested_texts(self, e):
        return list(self.nested.get(id(e), []))


def _x398_titleblock_ents():
    """真机 X398 粗碎车间标题栏简化布局（A3 横 420x297，标签与值分离，无闭合矩形）。"""
    date = r"{\Q10;\T1.5;2024\Q0;年\Q10;07\Q0;月 }"
    E = _FakeEnt
    return [
        E("图号", "图号", (250, 6, 274, 12)), E("图号值", "X398·301Z-02", (278, 6, 330, 12)),
        E("比例", "比例", (340, 6, 360, 12)), E("比例值", "1:500", (364, 6, 390, 12)),
        E("工程名称", "工程名称", (250, 13, 292, 19)),
        E("工程值", "刚果（金）Manono锂矿项目", (296, 13, 400, 19)),
        E("图名", "图名", (250, 20, 274, 26)), E("图名值", "粗碎车间平面布置图", (278, 20, 380, 26)),
        E("公司", "紫金(厦门)工程设计有限公司", (250, 27, 380, 33)),
        E("设计", "设计", (250, 34, 268, 40)), E("设计人", "李安武", (272, 34, 298, 40)),
        E("审核", "审核", (305, 34, 323, 40)), E("审核人", "陈伟晖", (327, 34, 353, 40)),
        E("审定", "审定", (360, 34, 378, 40)), E("审定人", "段仪惠", (382, 34, 408, 40)),
        E("标图", "标图", (250, 41, 268, 47)), E("标图人", "粟子翔", (272, 41, 298, 47)),
        E("日期", "日期", (305, 41, 323, 47)), E("日期值", date, (327, 41, 368, 47)),
        E("证书", "设计证书编号", (250, 48, 306, 54)), E("证书值", "A135036965", (310, 48, 356, 54)),
        E("X", "X9193800", (30, 200, 70, 206)), E("Y", "Y549350", (30, 210, 65, 216)),
    ]


def test_f01_f02_f05_titleblock():
    """F-01/F-02 标签→值删除 + F-05 文字簇反推（线条表格无闭合矩形）。

    真机根因：标题栏是直线表格、无闭合小矩形，锁不住区域全走黑名单；
    且"设计/审核/审定/标图"标签与"李安武/陈伟晖…"值是两个实体，黑名单只能删标签。
    """
    print("[F-01/F-02/F-05] 文字簇反推 + 标签→值删除（白名单 & 黑名单）")
    frame = titleblock.Frame(0, 0, 420, 297)
    fl, pl, dl, cl = core._titleblock_label_sets(CFG)
    seed = fl | pl | dl | cl

    # F-05①：不给任何闭合矩形（rects=[]），仅靠文字簇反推锁定真实区域
    sess = _FakeSession(_x398_titleblock_ents())
    alltp = core._all_text_pos(sess, "model", frame)
    boxes = core._collect_text_boxes(sess, alltp, frame)
    infer = titleblock.infer_titleblock_region_from_texts(frame, boxes, seed, fl, CFG)
    check("F-05 文字簇反推到标题栏区域（无闭合矩形）", infer is not None, str(infer))
    assert infer
    region = infer[0]
    check("F-05 反推区域含 4 个强字段标签", infer[1] >= 4, "strong=%d" % infer[1])

    keep = ["图号值", "比例值", "工程值", "图名值", "X", "Y"]
    delete_ = ["设计人", "审核人", "审定人", "标图人", "日期值", "证书值", "公司"]

    def run(mode, reg):
        ents = [_FakeEnt(e.Name, e.TextString, e._box) for e in _x398_titleblock_ents()]
        s = _FakeSession(ents)
        core._clean_titleblock(s, "doc", "model", reg, frame, CFG, lambda m: None, mode=mode)
        return {e.Name: e for e in ents}

    # 白名单 real_rect（文字簇反推）
    emap = run("real_rect", region)
    check("F-01 白名单 4 个人名全删", all(emap[n].deleted for n in delete_[:4]),
          str([n for n in delete_[:4] if not emap[n].deleted]))
    check("F-02/F-03 白名单 证书/日期/公司全删",
          all(emap[n].deleted for n in ["证书值", "日期值", "公司"]))
    check("白名单 图号/工程名/图名/比例值全保留",
          all(not emap[n].deleted for n in keep[:4]))
    check("C3 白名单 坐标 X/Y 保留", all(not emap[n].deleted for n in ["X", "Y"]))

    # 黑名单 fallback_band（F-01/F-02 标签→值双保险，裸人名/证书即使不匹配规则也删）
    band = titleblock.titleblock_region(frame, CFG)
    emap2 = run("fallback_band", band)
    check("F-01 黑名单 标签关联删除 4 个人名", all(emap2[n].deleted for n in delete_[:4]),
          str([n for n in delete_[:4] if not emap2[n].deleted]))
    check("F-02/F-03 黑名单 标签关联删除 证书/日期/公司",
          all(emap2[n].deleted for n in ["证书值", "日期值", "公司"]))
    check("C1 黑名单 图号/工程名/图名/比例值仍保留（保护优先）",
          all(not emap2[n].deleted for n in keep[:4]))


def test_f06_multi_frame():
    """F-06：多图框并排时，文字簇反推必须先按图框分组，各自独立锁定本框区域。

    v0.1.159 真机：三框标题栏被聚成一个跨框大簇，夹取后对图1/图2产生反向矩形
    （minx>maxx），整框删除 0 条，只有最后一个图框被清理。
    """
    print("[F-06] 多图框独立反推（不跨框、不反向）")
    frames = [titleblock.Frame(0, 0, 210, 297),     # A4纵
              titleblock.Frame(230, 0, 650, 297),   # A3横
              titleblock.Frame(670, 0, 967, 210)]   # A4横

    def titlebar(fi, f):
        bx, by = f.maxx - 148, f.miny + 6

        def mk(n, t, rx0, ry0, rx1, ry1):
            return _FakeEnt("%d_%s" % (fi, n), t,
                            (bx + rx0, by + ry0, bx + rx1, by + ry1))

        return [
            mk("图号", "图号", 0, 0, 22, 6), mk("图号值", "X398-%dZ-02" % fi, 26, 0, 80, 6),
            mk("工程名称", "工程名称", 0, 8, 40, 14), mk("工程值", "Manono锂矿项目", 44, 8, 146, 14),
            mk("图名", "图名", 0, 16, 22, 22), mk("图名值", "粗碎车间布置图", 26, 16, 120, 22),
            mk("设计", "设计", 0, 24, 18, 30), mk("设计人", "李安武", 22, 24, 48, 30),
            mk("审核", "审核", 55, 24, 73, 30), mk("审核人", "陈伟晖", 77, 24, 103, 30),
            mk("日期", "日期", 0, 32, 18, 38), mk("日期值", r"{\Q10;2024\Q0;年07月}", 22, 32, 70, 38),
        ]

    ents = []
    for i, f in enumerate(frames):
        ents.extend(titlebar(i, f))

    regs = []
    for i, f in enumerate(frames):
        sess = _FakeSession([_FakeEnt(e.Name, e.TextString, e._box) for e in ents])
        reg, mode = core._resolve_region(sess, "model", f, [], CFG, lambda m: None, [])
        regs.append(reg)
        forward = reg and reg[0] < reg[2] and reg[1] < reg[3]
        inside = (reg and reg[0] >= f.minx - 2 and reg[2] <= f.maxx + 2
                  and reg[1] >= f.miny - 2 and reg[3] <= f.maxy + 2)
        check("F-06 图%d 反推为正向矩形且在本框内（mode=%s）" % (i + 1, mode),
              mode == "real_rect" and forward and inside, str(reg))
    no_overlap = all(regs[i][2] <= regs[j][0] or regs[j][2] <= regs[i][0]
                     for i in range(3) for j in range(i + 1, 3))
    check("F-06 三框标题栏区域互不重叠（未跨框聚类）", no_overlap, str(regs))

    for i, f in enumerate(frames):
        es = [_FakeEnt(e.Name, e.TextString, e._box) for e in ents]
        ss = _FakeSession(es)
        reg, mode = core._resolve_region(ss, "model", f, [], CFG, lambda m: None, [])
        core._clean_titleblock(ss, "doc", "model", reg, f, CFG, lambda m: None, mode=mode)
        emap = {e.Name: e for e in es}
        del_ok = all(emap["%d_%s" % (i, n)].deleted for n in ["设计人", "审核人", "日期值"])
        keep_ok = all(not emap["%d_%s" % (i, n)].deleted for n in ["图号值", "工程值", "图名值"])
        other_ok = all(not emap["%d_设计人" % j].deleted for j in range(3) if j != i)
        check("F-06 图%d 独立清理（本框删/留正确，未动别框）" % (i + 1),
              del_ok and keep_ok and other_ok,
              "del=%s keep=%s other=%s" % (del_ok, keep_ok, other_ok))


def test_f07_label_delete_protection():
    """F-07：标签关联删除不得误删含保护词文本（图名）与坐标标注。"""
    print("[F-07] 标签关联删除的保护优先（图名/坐标不得误删）")
    frame = titleblock.Frame(0, 0, 420, 297)
    region = (270, 20, 415, 55)
    E = _FakeEnt
    ents = [
        E("设计", "设计", (272, 42, 290, 48)),
        E("设计人", "李安武", (294, 42, 320, 48)),       # 设计右侧 → 应删
        E("审核", "审核", (350, 42, 368, 48)),
        E("审核人", "陈伟晖", (372, 42, 398, 48)),       # 审核右侧 → 应删
        # 图名值落在"设计"正下方（真机误删场景），含"车间" → 必须保留
        E("图名值", "粗碎车间\\P平面布置图", (272, 30, 340, 36)),
        # 坐标落在"审核"正下方 → 必须保留
        E("坐标", "Y549625", (350, 30, 385, 36)),
    ]
    sess = _FakeSession([_FakeEnt(e.Name, e.TextString, e._box) for e in ents])
    core._clean_titleblock(sess, "doc", "model", region, frame, CFG, lambda m: None,
                           mode="real_rect")
    emap = {e.Name: e for e in sess.ents}
    del_ok = emap["设计人"].deleted and emap["审核人"].deleted
    name_ok = not emap["图名值"].deleted
    coord_ok = not emap["坐标"].deleted
    check("F-07 人名仍删除", del_ok, "")
    check("F-07 图名（含车间）不被标签关联误删", name_ok, "")
    check("F-07 坐标 Y549625 不被标签关联误删", coord_ok, "")


def test_f08_cert_number_outside_region():
    """F-08：证书编号在标签正下方、标题栏区域外时，由全图框扩展删除。"""
    print("[F-08] 证书编号扩展（区域外正下方）+ 图号/坐标不误删")
    frame = titleblock.Frame(0, 0, 420, 297)
    region = (270, 20, 415, 55)
    E = _FakeEnt
    ents = [
        # 证书标签在区域内，证书号在其正下方且在区域外（maxy=18 < region.miny=20）
        E("证书标签", "设计证书编号", (272, 24, 340, 30)),
        E("证书号", "A135036965", (272, 12, 332, 18)),
        # 区域内的图号（含连字符，不得被证书规则误删）
        E("图号", "图号", (380, 24, 398, 30)),
        E("图号值", "X398-301Z-02", (380, 12, 410, 18)),
    ]
    sess = _FakeSession([_FakeEnt(e.Name, e.TextString, e._box) for e in ents])
    core._clean_titleblock(sess, "doc", "model", region, frame, CFG, lambda m: None,
                           mode="real_rect")
    emap = {e.Name: e for e in sess.ents}
    check("F-08 区域外证书号 A135036965 被扩展删除", emap["证书号"].deleted, "")
    check("F-08 图号 X398-301Z-02 不误删", not emap["图号值"].deleted, "")
    # 纯函数层：编号识别
    check("F-08 is_cert_number 识别 A135036965", rules.is_cert_number("A135036965"), "")
    check("F-08 纯数字 9 位识别", rules.is_cert_number("123456789"), "")
    check("F-08 图号不识别为证书号", not rules.is_cert_number("X398-301Z-02"), "")
    check("F-08 坐标 X/Y 开头不识别为证书号", not rules.is_cert_number("X9193900"), "")
    # find_cert_numbers 几何：标签下方左对齐命中
    targets = [
        {"key": 0, "norm": "设计证书编号", "minx": 272, "miny": 24, "maxx": 340, "maxy": 30},
        {"key": 1, "norm": "A135036965", "minx": 272, "miny": 12, "maxx": 332, "maxy": 18},
    ]
    got = titleblock.find_cert_numbers(targets, set(["设计证书编号"]), frame)
    check("F-08 find_cert_numbers 命中下方编号", got == {1}, str(got))


def test_f09_protected_field_replace():
    """F-09：保护字段"设计阶段"关联的值"施工图"仍须替换为"竣工图"。"""
    print("[F-09] 保护字段值内的施工图→竣工图替换")
    frame = titleblock.Frame(0, 0, 420, 297)
    region = (270, 20, 415, 55)
    E = _FakeEnt
    ents = [
        E("设计阶段", "设计阶段", (272, 42, 320, 48)),
        E("阶段值", "施工图", (324, 42, 360, 48)),
    ]
    sess = _FakeSession([_FakeEnt(e.Name, e.TextString, e._box) for e in ents])
    core._clean_titleblock(sess, "doc", "model", region, frame, CFG, lambda m: None,
                           mode="real_rect")
    emap = {e.Name: e for e in sess.ents}
    v = emap["阶段值"]
    check("F-09 施工图未被删除", not v.deleted, "")
    check("F-09 施工图替换为竣工图", v.TextString == "竣工图", repr(v.TextString))


def test_n04_project_name_not_deleted():
    """N-04：工程名称类值（长文本含项目/锂矿）不被"设计证书编号"删除关联误删。"""
    print("[N-04] 工程名称值保护（删除关联右侧 gap 收紧 + 内容规则双保险）")
    frame = titleblock.Frame(0, 0, 420, 297)
    region = (270, 20, 415, 55)
    E = _FakeEnt
    # 真机几何：设计证书编号标签 (549662.5,9193904.5)，工程名称值在其右侧上方
    # (549700.0,9193906.8)，dy=2.3 落在旧 row_tol 内、gap≈30 超过收紧阈值。
    ents = [
        E("证书标签", "设计证书编号", (272, 42, 280, 48)),
        E("工程值", "刚果（金）Manono锂矿5Mt/年采选冶项目", (310, 48, 395, 52)),
        E("人名", "李安武", (284, 30, 300, 36)),
        E("人名标签", "设计", (272, 28, 280, 34)),
    ]
    sess = _FakeSession([_FakeEnt(e.Name, e.TextString, e._box) for e in ents])
    core._clean_titleblock(sess, "doc", "model", region, frame, CFG, lambda m: None,
                           mode="real_rect")
    emap = {e.Name: e for e in sess.ents}
    check("N-04 工程名称值未被删除", not emap["工程值"].deleted, "")
    check("N-04 人名仍被删除", emap["人名"].deleted, "")
    # 函数级：工程名称识别 / 公司名不误判为工程名
    check("N-04 is_project_name_like 识别工程值",
          rules._is_project_name_like("刚果（金）Manono锂矿5Mt/年采选冶项目", CFG), "")
    check("N-04 公司名不误判为工程名",
          not rules._is_project_name_like("紫金(厦门)工程设计有限公司", CFG), "")
    check("N-04 短文本/坐标不误判",
          not rules._is_project_name_like("Y549625", CFG)
          and not rules._is_project_name_like("李安武", CFG), "")
    # delete 模式右侧 gap 收紧：人名（gap 小）关联，工程名（gap 大）不关联
    tg = [
        {"key": 0, "norm": "设计证书编号", "minx": 272, "miny": 42, "maxx": 280, "maxy": 48},
        {"key": 1, "norm": "刚果（金）Manono锂矿5Mt/年采选冶项目", "minx": 310, "miny": 48, "maxx": 395, "maxy": 52},
        {"key": 2, "norm": "李安武", "minx": 284, "miny": 30, "maxx": 300, "maxy": 36},
    ]
    fl, pl, dl, cl = core._titleblock_label_sets(CFG)
    got = titleblock.associate_label_values(
        tg, dl | cl, fl, frame, mode="delete",
        right_max_gap=max(frame.height * 0.05, 8.0))
    check("N-04 delete 关联不再命中工程名称值", 1 not in got, str(got))
    check("N-04 字段标签文字保留（子项名称）",
          rules.judge_whitelist_text("子项名称", CFG)[0] == "keep", "")


def test_n01_block_attributes_collected():
    """N-01：块属性文字（公司名/证书号）被收集并删除。"""
    print("[N-01] 块属性文字收集删除 + 嵌套文字判定提示")
    frame = titleblock.Frame(0, 0, 420, 297)
    region = (270, 20, 415, 55)
    E = _FakeEnt
    blk = E("标题栏块", "", (300, 20, 410, 55), oname="AcDbBlockReference")
    attr_co = E("attr公司", "紫金(厦门)工程设计有限公司", (310, 42, 370, 48),
                oname="AcDbAttribute")
    attr_cert = E("attr证书", "A135036965", (310, 34, 360, 40), oname="AcDbAttribute")
    attrs = [(attr_co.TextString, attr_co._box, attr_co),
             (attr_cert.TextString, attr_cert._box, attr_cert)]
    sess = _FakeSession([blk], block_attrs={id(blk): attrs})
    core._clean_titleblock(sess, "doc", "model", region, frame, CFG, lambda m: None,
                           mode="real_rect")
    check("N-01 块属性公司名被删除", attr_co.deleted, "")
    check("N-01 块属性证书号被删除", attr_cert.deleted, "")
    # 嵌套文字：命中删除只提示不删（块定义保护）
    blk2 = E("块2", "", (300, 20, 410, 55), oname="AcDbBlockReference")
    sess2 = _FakeSession([blk2], block_attrs={id(blk2): []})
    sess2.nested[id(blk2)] = [("陈伟晖", (310, 42, 330, 48))]
    _d, _r, notes = core._clean_titleblock(
        sess2, "doc", "model", region, frame, CFG, lambda m: None, mode="real_rect")
    check("N-01 嵌套人名不直接删除（防破坏块定义）", not blk2.deleted, "")
    check("N-01 嵌套文字给出提示", any("嵌套文字" in n for n in notes), str(notes))


def test_n02_region_signature_expand():
    """N-02：文字簇反推区域按签署列扩展，盖住全部人名列。"""
    print("[N-02] 签署列区域扩展（漏删人名补回）")
    frame = titleblock.Frame(0, 0, 420, 297)
    # 反推区域上界恰切在人名列中间（真机图3：代必虎在区域外）
    region = (300, 20, 410, 48)
    boxes = [
        {"norm": "设计", "minx": 300, "miny": 40, "maxx": 306, "maxy": 44},
        {"norm": "审核", "minx": 300, "miny": 35, "maxx": 306, "maxy": 39},
        {"norm": "审定", "minx": 300, "miny": 30, "maxx": 306, "maxy": 34},
        {"norm": "制图", "minx": 300, "miny": 25, "maxx": 306, "maxy": 29},
        {"norm": "李安武", "minx": 310, "miny": 40, "maxx": 320, "maxy": 44},
        {"norm": "代必虎", "minx": 310, "miny": 30, "maxx": 320, "maxy": 34},
    ]
    fl, pl, dl, cl = core._titleblock_label_sets(CFG)
    exp = titleblock.expand_region_for_signature_rows(region, boxes, frame, pl, CFG)
    check("N-02 区域下界扩展到签署列底（盖住制图行 25）", exp[1] <= 25.0, str(exp))
    # 扩展后的区域应覆盖此前漏掉的"代必虎"行
    check("N-02 区域覆盖值列全部行（含代必虎 34）", exp[3] >= 44.0 and exp[1] <= 29.0, str(exp))


def test_n05_top_band_signature_clean():
    """N-05：目录页（top_band）底部签署栏全图框关联删除。"""
    print("[N-05] 目录页签署栏删除（top_band 全图框关联）")
    frame = titleblock.Frame(0, 0, 420, 297)
    # top_band 只覆盖顶部条带，签署栏在底部（区域外）
    region = (0, 250, 420, 297)
    E = _FakeEnt
    ents = [
        E("顶部公司", "紫金(厦门)工程设计有限公司", (30, 260, 80, 265)),
        E("负责人标签", "项目负责人", (40, 20, 70, 26)),
        E("负责人", "陈彪文", (72, 20, 90, 26)),
        E("校核标签", "校核", (40, 12, 56, 18)),
        E("校核人", "林子程", (58, 12, 76, 18)),
        E("目录图名", "粗碎车间布置图", (120, 30, 200, 36)),
        E("目录图号", "X398·301Z-02", (60, 30, 110, 36)),
    ]
    sess = _FakeSession([_FakeEnt(e.Name, e.TextString, e._box) for e in ents])
    core._clean_titleblock(sess, "doc", "model", region, frame, CFG, lambda m: None,
                           mode="top_band")
    emap = {e.Name: e for e in sess.ents}
    check("N-05 项目负责人值删除", emap["负责人"].deleted, "")
    check("N-05 校核值删除", emap["校核人"].deleted, "")
    check("N-05 目录图名保留（含保护词）", not emap["目录图名"].deleted, "")
    check("N-05 目录图号保留", not emap["目录图号"].deleted, "")


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
    test_f03_mtext_codes()
    test_f01_f02_f05_titleblock()
    test_f06_multi_frame()
    test_f07_label_delete_protection()
    test_f08_cert_number_outside_region()
    test_f09_protected_field_replace()
    test_n04_project_name_not_deleted()
    test_n01_block_attributes_collected()
    test_n02_region_signature_expand()
    test_n05_top_band_signature_clean()
    print("=" * 64)
    print("结果：通过 %d，失败 %d" % (_PASS, _FAIL))
    print("=" * 64)
    sys.exit(1 if _FAIL else 0)


if __name__ == "__main__":
    main()
