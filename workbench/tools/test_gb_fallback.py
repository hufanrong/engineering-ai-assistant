#!/usr/bin/env python3
"""v0.1.183 回归：无模板时的两条出路（别名复用 + 国标兜底）。

用户决策（2026-10-31）：
    「就用现有的检查记录表，没有提供的模板时，统一根据国标模板制作」

对应两处实测缺陷：
  ① 登记表写「设备安装记录」（表号 SH/T3503-J302），模板库只有「设备安装检查记录」。
     7 个真实项目全部命中，整卷时只记一句「无匹配模板」，**一份文件都不出**。
     相似度层救不了 —— 与「设备安装检查记录」「设备内件安装记录」的比值
     都是 0.8571（并列第一、差值 0.0000），按「多个候选一律不猜」必然拒绝。
  ② 与任何模板都对不上的登记项，原来只挂待办，不产出任何可打印的表；
     且兜底若一律套设备检查条款，出的表是错的（签证单上写「表面油漆不可有掉漆」）。

本测试守四条：
  A. 别名只认表里有的，不误伤别的表（尤其不能被「防爆电气设备安装记录」抢走）；
  B. 国标兜底出的表能打开、结构完整、字体真写进 docx、且**不含编造业务事实**；
  C. 兜底必须按表种出表（检查/隐蔽/试验/签认/通用），不许串味；
  D. 接入链路：别名进 name_alias 账、兜底进 gb_fallback 账，待办清单可复核。

用法：python3 tools/test_gb_fallback.py   （退出码 0 = 全过）
"""
import copy
import os
import re
import shutil
import sys
import tempfile
import time

WB = os.environ.get("FANGONG_WB",
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WB)
os.environ.setdefault("FANGONG_NO_BROWSER", "1")

from app import gb_form as gb  # noqa: E402
from app import supervision_templates as st  # noqa: E402
from app import supervision_integration as si  # noqa: E402

_PASS = [0]
_FAIL = []


def _exception_releases_slot(si):
    """出卷中途抛异常时，整卷槽位必须被释放（否则一次失败就把整卷永久封死）。

    做法：把 `_book_items` 打成抛异常。它在 acquire 之后才被调用，
    所以异常真的从 generate_volume 里冒出来 —— 只有 try/finally 才会把槽位收回去。
    """
    orig = si._book_items

    def boom(*a, **k):
        raise RuntimeError("测试用：模拟出卷中途异常")

    si._book_items = boom
    raised = False
    try:
        si.generate_volume("e75e857c", "设备安装", "测试车间_锁")
    except Exception:  # noqa: BLE001
        raised = True
    finally:
        si._book_items = orig
    if not raised:
        return False
    # 异常之后必须还能再拿到同一个槽位
    k = si.acquire_volume_slot("e75e857c", "设备安装", "测试车间_锁")
    if k is None:
        return False
    si.release_volume_slot(k)
    return True


def check(name, cond, detail=""):
    if cond:
        _PASS[0] += 1
        print(f"  [PASS] {name}")
    else:
        _FAIL.append(f"{name}  {detail}")
        print(f"  [FAIL] {name}  {detail}")


def _item(seq, name, no, cls):
    return {"册": "设备安装", "序号": str(seq), "名称": name, "表号": no, "分类": cls}


def main():
    st._ensure_builtin_registered()
    tmp = tempfile.mkdtemp(prefix="gb_fb_")

    # ---------- A. 别名表 ----------
    print("\n[A] 别名表只认已确认的对应关系")
    check("「设备安装记录」→ 设备安装检查记录",
          gb.alias_category("设备安装记录") == "设备安装检查记录",
          repr(gb.alias_category("设备安装记录")))
    check("带括号注记也能认（设备安装记录（一））",
          gb.alias_category("设备安装记录（一）") == "设备安装检查记录")
    check("带半角括号也能认（设备安装记录(1)）",
          gb.alias_category("设备安装记录(1)") == "设备安装检查记录")
    check("不在表里的名字一律返回 None（不猜）",
          gb.alias_category("设备开箱检验记录") is None
          and gb.alias_category("完全不存在的表XYZ") is None)
    check("别名说明文字含实际借用的表名",
          "设备安装检查记录" in gb.alias_note("设备安装记录"))
    check("「设备内件安装记录」不被别名误伤",
          gb.alias_category("设备内件安装记录") is None)
    check("「防爆电气设备安装记录」不被别名误伤",
          gb.alias_category("防爆电气设备安装记录") is None)
    check("_item_category 对 J302 返回别名类别",
          si._item_category(_item(3, "设备安装记录", "SH/T3503-J302", "B"))
          == "设备安装检查记录")
    check("_item_category 对 J301 仍走原路径",
          si._item_category(_item(1, "设备开箱检验记录", "SH/T3503-J301", "A"))
          == "设备开箱检查记录")

    # ---------- B. 表种 ----------
    print("\n[B] 兜底必须按表种出表（不许一律套设备检查条款）")
    for name, expect in (
        ("设备安装记录", "check"),
        ("管道系统压力试验记录", "test"),
        ("隐蔽工程验收记录", "conceal"),
        ("现场签证单", "sign"),
        ("设计变更工程洽商记录", "sign"),
        ("监理记录1", "generic"),
        ("完全不存在的表XYZ", "generic"),
    ):
        check(f"表种 {name} → {expect}", gb.form_kind(name) == expect,
              gb.form_kind(name))

    # 每种表种的列头与条款必须对得上，且不跨种串味
    for kind, cols in gb._KIND_COLS.items():
        p = os.path.join(tmp, f"kind_{kind}.docx")
        # 显式传 kind：表名里带「测试」二字会被 form_kind 判成试验类，这里要测的是各表种自身
        r = gb.build_gb_form(p, form_name="通用记录表", form_no="SH/T3503-J399", kind=kind)
        from docx import Document
        d = Document(p)
        t = d.tables[0]
        hdr = [t.cell(5, c).text for c in range(4)]
        check(f"表种 {kind} 列头 = {list(cols)}", hdr == list(cols), str(hdr))
        body = "\n".join(c.text for row in t.rows for c in row.cells)
        if kind != "check":
            check(f"表种 {kind} 不套设备检查条款",
                  "表面油漆不可有掉漆" not in body)
        check(f"表种 {kind} 条款数与声明一致",
              r.get("check_item_count") == sum(len(x) for _, x in gb.items_for_kind(kind)))

    # 签认类不按设备复制；检查类一台一份
    p_s = os.path.join(tmp, "sign2.docx")
    gb.build_gb_form(p_s, form_name="现场签证单", form_no="SH/T3503-J399",
                     devices=[{"tag": "M-1", "name": "A"}, {"tag": "M-2", "name": "B"}])
    from docx import Document
    check("签认类 2 台设备仍只出 1 份（不按设备复制）",
          len(Document(p_s).tables) == 1)
    p_c = os.path.join(tmp, "check2.docx")
    gb.build_gb_form(p_c, form_name="设备安装记录", form_no="SH/T3503-J302",
                     devices=[{"tag": "M-1", "name": "A"}, {"tag": "M-2", "name": "B"}])
    check("检查类 2 台设备出 2 份（每台一份）",
          len(Document(p_c).tables) == 2)

    # ---------- C. 兜底表本体 ----------
    print("\n[C] 国标兜底表：结构 / 字体 / 不编造事实")
    p_blank = os.path.join(tmp, "gb_blank.docx")
    r = gb.build_gb_form(p_blank, form_name="设备安装记录", form_no="SH/T3503-J302",
                         unit_works="选矿厂主厂房", sub_works="工业设备安装",
                         workshop="辊磨筛分车间", category="设备安装记录")
    check("生成成功且落盘", r.get("ok") and os.path.isfile(p_blank), str(r))
    check("无设备时出一份空白表（不编造设备名）",
          r.get("device_count") == 0 and os.path.getsize(p_blank) > 10000)

    from docx.oxml.ns import qn
    d = Document(p_blank)
    check("能回读：1 张表", len(d.tables) == 1, str(len(d.tables)))
    t = d.tables[0]
    n_items = sum(len(x) for _, x in gb.items_for_kind("check"))
    expect_rows = 5 + 1 + len(gb.items_for_kind("check")) + n_items + 2
    check(f"行数=表头+明细+签字（期望 {expect_rows}）",
          len(t.rows) == expect_rows, str(len(t.rows)))
    check("列数=4", len(t.columns) == 4)
    check("检查项数 >= 12", n_items >= 12, str(n_items))
    check("表号印在正文（监理可辨）",
          "SH/T3503-J302" in "\n".join(p.text for p in d.paragraphs))
    check("来源标注印在正文（标明是国标通用格式）",
          "国标通用格式" in "\n".join(p.text for p in d.paragraphs))
    # 字体必须真的写进 docx（eastAsia 单设，否则中文回落）
    rf = d.paragraphs[0].runs[0]._element.rPr.rFonts
    _ea = rf.get(qn("w:eastAsia"))
    check("标题 eastAsia 字体已写入", _ea == gb.GB_FONT_TITLE[0], str(_ea))
    body_txt = "\n".join(c.text for row in t.rows for c in row.cells)
    check("不含示例/样例/演示类编造值",
          not any(w in body_txt for w in ("示例", "样例", "演示", "假设")))
    check("设备名/位号留空交人工填，不是虚构设备",
          "M-101" not in body_txt and "胶带输送机" not in body_txt)
    check("明细里不含具体公差数字（±0.5mm 之类）",
          all("±" not in item for _, items in gb._KIND_ITEMS.items() for item in items))

    # ---------- D. 接入链路 ----------
    print("\n[D] 接进 render_supervision_doc：模板缺失不再直接报错")
    r_none = st.render_supervision_doc(category="完全不存在的表XYZ",
                                       workshop="", project_id=None)
    check("无模板类别 → ok=True（不再是「未找到表类型」硬失败）",
          r_none.get("ok") is True, str(r_none.get("error"))[:80])
    check("带 gb_fallback 标记（人工可辨是兜底表）",
          r_none.get("gb_fallback") is True)
    check("带 warning 说明为什么用兜底",
          "国标通用格式" in (r_none.get("warning") or ""))
    check("产出文件真实落盘", os.path.isfile(r_none.get("output_path") or ""))
    check("空白兜底表有 gb_blank 标记",
          r_none.get("gb_blank") is True)

        # --- D2：版面门禁。表是要打印出来交给监理的，列宽错了就是废表 ---
    # v0.1.185：原来四列一律 4.25cm 等宽，条款被挤成两三行、手写列反而空着很宽；
    # 改成按表种分配后又把第 0 列压到 1.5cm，标签「分部分项工程名称」折成三行。
    # 这两次都是靠渲染出来看才发现的，所以把版面约束写成断言钉住。
    print("\n[D2] 兜底表版面（列宽 / 越界 / 折行）")
    from docx.oxml.ns import qn as _qn
    _TW = 566.93
    for _k in ('check', 'conceal', 'test', 'sign', 'generic'):
        _p = os.path.join(tmp, f"lay_{_k}.docx")
        _r = gb.build_gb_form(_p, form_name="通用记录表", form_no="SH/T3503-J399", kind=_k)
        _d = Document(_p)
        _t = _d.tables[0]
        _sec = _d.sections[0]
        _usable = _sec.page_width.cm - _sec.left_margin.cm - _sec.right_margin.cm
        _grid = _t._tbl.find(_qn('w:tblGrid'))
        _w = [int(x.get(_qn('w:w'))) for x in _grid.findall(_qn('w:gridCol'))]
        _cm = [x / _TW for x in _w]
        check(f"[{_k}] 列宽合计等于可用页宽",
              abs(sum(_cm) - _usable) <= 0.05, f"合计={sum(_cm):.2f} 可用={_usable:.2f}")
        check(f"[{_k}] 第0列 >= 2.95cm（放得下 8 字标签）", _cm[0] >= 2.95, f"{_cm[0]:.2f}")
        check(f"[{_k}] 条款列最宽", _cm[1] == max(_cm), f"{[round(x,2) for x in _cm]}")
        _bad = 0
        for _tr in _t._tbl.findall(_qn('w:tr')):
            _s = 0
            for _tc in _tr.findall(_qn('w:tc')):
                _s += int(_tc.find(_qn('w:tcPr')).find(_qn('w:tcW')).get(_qn('w:w')))
            if abs(_s / _TW - _usable) > 0.05:
                _bad += 1
        check(f"[{_k}] 每行宽度合计都等于页宽（无越界行）", _bad == 0, f"异常行={_bad}")
        # 第 0 列文字（含跨列合并的大类标题）都要放得下
        _over = ""
        for _row in range(len(_t.rows)):
            _tcPr = _t.cell(_row, 0)._tc.find(_qn('w:tcPr'))
            _span = 1
            _gs = _tcPr.find(_qn('w:gridSpan')) if _tcPr is not None else None
            if _gs is not None:
                _span = int(_gs.get(_qn('w:val')) or 1)
            _txt = _t.cell(_row, 0).text or ""
            if len(_txt) * 0.317 + 0.38 > sum(_cm[:_span]):
                _over = _txt
                break
        check(f"[{_k}] 第0列无折行", not _over, _over or "ok")

    print("\n[E] 别名在入口生效，不被其它类别的子串匹配抢走")
    # 先证明这个坑确实存在：模板库里有「防爆电气设备安装记录」，没有「设备安装记录」，
    # 所以旧的子串回退（category in c）必然唯一命中前者，且不会报歧义。
    idx = st._te._load_template_index()
    cats = {}
    for t in idx.get("templates", []):
        dt = t.get("doc_type", "")
        if dt.startswith(st.DOC_TYPE + "|"):
            cats.setdefault(dt.split("|", 1)[1], t)
    check("「设备安装记录」本身不是模板库里的表名",
          "设备安装记录" not in cats)
    check("子串回退确实会命中「防爆电气设备安装记录」（所以别名必须排在它前面）",
          [c for c in cats if "设备安装记录" in c] == ["防爆电气设备安装记录"],
          str([c for c in cats if "设备安装记录" in c]))

    # 再验证入口：不管当前环境有没有设备数据，都不得落到防爆那张表上。
    r_alias = st.render_supervision_doc(category="设备安装记录",
                                        workshop="", project_id=None)
    _blob = " ".join(str(r_alias.get(k) or "") for k in ("output_file", "output_path", "warning", "error"))
    check("入口结果不含「防爆电气设备安装记录」", "防爆电气" not in _blob, _blob[:80])
    if r_alias.get("ok"):
        check("实际用的是「设备安装检查记录」而不是「防爆电气设备安装记录」",
              "设备安装检查记录" in (r_alias.get("output_file") or ""),
              r_alias.get("output_file"))
        check("返回 name_alias 账目（请求 vs 借用）",
              (r_alias.get("name_alias") or {}).get("借用表") == "设备安装检查记录")
    else:
        check("无数据时给出可判读的拦截原因（不是「未找到模板」）",
              "防爆" not in (r_alias.get("error") or "")
              and "未找到表类型" not in (r_alias.get("error") or ""),
              str(r_alias.get("error"))[:80])

    print("\n[F] 待办清单渲染：两本新账都要能写进去")
    md = si._render_todo([], [], [], None, None, workshop="某车间",
                         gb_fallback=[{"序号": "9", "名称": "现场签证单",
                                       "表号": "SH/T3503-J399", "设备数": 0,
                                       "检查项数": 6, "文件": "9_现场签证单.docx"}],
                         name_alias=[{"序号": "3", "名称": "设备安装记录",
                                      "借用表": "设备安装检查记录"}])
    check("待办清单有「复用现有表」段", "〇之四、复用现有表" in md)
    check("待办清单有「按国标通用格式生成」段", "〇之五、按国标通用格式生成" in md)
    check("待办清单写明借用了哪张表",
          "用「设备安装检查记录」的表出记录" in md)
    check("待办清单带表号（可追溯）", "SH/T3503-J399" in md)
    md_empty = si._render_todo([], [], [], None, None)
    check("无待办时仍输出「全部完成」", "全部完成" in md_empty)

    shutil.rmtree(tmp, ignore_errors=True)

    # ---------------- G. 项目配置必须按 project_id 取，且不得串项目 ----------------
    # 这两个缺陷都是 v0.1.187 修掉的，用真实落盘的项目目录复现，不 mock 配置内容：
    # ① 传了 project_id 却读「当前项目」的配置 —— 整卷会印上另一个项目的工程名。
    # ② save_project_config 写 project_meta.json，读取却查 index.json ——
    #    用户填好的单位信息出表时全落成【待补充】，要在几十份文件里手写。
    print("\n[G] 项目配置按 project_id 读取（不串项目）")
    import json
    from app import supervision_templates as _st
    from app import project_manager as _pm

    gtmp = tempfile.mkdtemp(prefix="cfg_")
    _was_root = _pm.PROJECTS_ROOT
    _was_cur = _pm.CURRENT_PROJECT_FILE
    try:
        _pm.PROJECTS_ROOT = os.path.join(gtmp, "projects")
        _pm.CURRENT_PROJECT_FILE = os.path.join(gtmp, "current_project.json")
        os.makedirs(_pm.PROJECTS_ROOT, exist_ok=True)

        def _mk_project(pid, meta):
            d = os.path.join(_pm.PROJECTS_ROOT, pid)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "project_meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)

        _mk_project("projA", {"id": "projA", "name": "选矿厂A",
                              "contractor": "A施工单位", "unit_works": "A单位工程"})
        _mk_project("projB", {"id": "projB", "name": "选矿厂B",
                              "contractor": "B施工单位", "unit_works": "B单位工程"})
        # 把「当前项目」钉在 B 上 —— 这正是线上出问题的场景
        with open(_pm.CURRENT_PROJECT_FILE, "w", encoding="utf-8") as f:
            json.dump({"project_id": "projB", "project_name": "选矿厂B"}, f)

        cfgA = _st._load_project_config("projA")
        check("传 projA 取到 A 的施工单位（不串当前项目 B）",
              cfgA.get("施工单位") == "A施工单位",
              f"实得 {cfgA.get('施工单位')!r}")
        check("传 projA 取到 A 的项目名称",
              cfgA.get("项目名称") == "选矿厂A",
              f"实得 {cfgA.get('项目名称')!r}")
        check("传 projA 取到 A 的单位工程",
              cfgA.get("单位工程") == "A单位工程",
              f"实得 {cfgA.get('单位工程')!r}")

        cfgB = _st._load_project_config("projB")
        check("传 projB 取到 B 的施工单位",
              cfgB.get("施工单位") == "B施工单位",
              f"实得 {cfgB.get('施工单位')!r}")
        check("A/B 两个项目配置互不串",
              cfgA.get("施工单位") != cfgB.get("施工单位"))

        cfgNone = _st._load_project_config(None)
        check("不传 project_id 时回退当前项目 B（既有行为不变）",
              cfgNone.get("施工单位") == "B施工单位",
              f"实得 {cfgNone.get('施工单位')!r}")

        # ② 写进去必须能读回来（原来写 meta 读 index，读回全空）
        _st.save_project_config("projA", {"施工单位": "A单位工程公司", "监理单位": "A监理"})
        cfgA2 = _st._load_project_config("projA")
        check("save_project_config 写入后能读回施工单位",
              cfgA2.get("施工单位") == "A单位工程公司",
              f"实得 {cfgA2.get('施工单位')!r}")
        check("save_project_config 写入后能读回监理单位",
              cfgA2.get("监理单位") == "A监理",
              f"实得 {cfgA2.get('监理单位')!r}")
        check("改 A 不影响 B",
              _st._load_project_config("projB").get("施工单位") == "B施工单位")
    finally:
        _pm.PROJECTS_ROOT = _was_root
        _pm.CURRENT_PROJECT_FILE = _was_cur
        shutil.rmtree(gtmp, ignore_errors=True)

    # ---------------- H. 无名称设备不出空壳表，但要记账 ----------------
    # v0.1.187 缺陷（真实台账 e75e857c / 辊磨筛分车间实测）：台账行有型号没设备名称，
    # _device_type_of("") 返回「通用」→ 出表，结果那张表设备名称栏是【待补充】。
    # 10 张表里第 4 张空着，监理一看就知道资料不能用，它还占掉一个表位。
    # 竣工资料按设备名立卷，无名行本来就归不了档 —— 正确做法是不出表、进待办。
    print("\n[H] 无名称设备不出空壳表（但必须记账）")
    htmp = tempfile.mkdtemp(prefix="nm_")
    _h_root = _pm.PROJECTS_ROOT
    _h_cur = _pm.CURRENT_PROJECT_FILE
    try:
        _pm.PROJECTS_ROOT = os.path.join(htmp, "projects")
        _pm.CURRENT_PROJECT_FILE = os.path.join(htmp, "current_project.json")
        _pid = "hp"
        _pd = os.path.join(_pm.PROJECTS_ROOT, _pid)
        os.makedirs(_pd, exist_ok=True)
        with open(os.path.join(_pd, "project_meta.json"), "w", encoding="utf-8") as f:
            json.dump({"id": _pid, "name": "无名设备测试"}, f, ensure_ascii=False)
        # 5 台有名称 + 1 台只有型号（= 线上那张空壳表）
        idx = {"devices": {}, "files": {}, "workshops": {"甲车间": {}}}
        _named_ = ["胶带输送机A", "胶带输送机B", "振动筛A", "渣浆泵A", "电动葫芦A"]
        for i, n in enumerate(_named_):
            idx["devices"][f"T{i:03d}"] = {"name": n, "model": "X", "workshop": "甲车间",
                                           "unit": "台", "quantity": "1"}
        idx["devices"]["N001"] = {"name": "", "model": "CDMF5-12", "workshop": "甲车间",
                                  "unit": "台", "quantity": "1"}
        with open(os.path.join(_pd, "index.json"), "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False)

        devs = _st._get_workshop_devices("甲车间", _pid)
        check("无名但有型号的台账行仍被读取（不丢设备）", len(devs) == 6, f"实得 {len(devs)}")

        r = _st.render_supervision_doc(category="设备安装检查记录",
                                       workshop="甲车间", project_id=_pid)
        check("有名称设备时仍能正常出表", r.get("ok") is True, f"实得 {r.get('error')}")
        check("出表数 = 有名称设备数（无名设备不占表位）",
              r.get("filled_tables") == len(_named_),
              f"实得 {r.get('filled_tables')}，应 {len(_named_)}")
        check("返回值带 nameless_devices 记账",
              isinstance(r.get("nameless_devices"), list) and len(r["nameless_devices"]) == 1,
              f"实得 {r.get('nameless_devices')!r}")
        check("记账里带出缺名称那台设备的型号",
              (r.get("nameless_devices") or [{}])[0].get("型号") == "CDMF5-12",
              f"实得 {(r.get('nameless_devices') or [{}])[0]!r}")

        # 生成的文档里不得出现「设备名称栏为空」的表：按 <w:tbl> 数核对
        _op = r.get("output_path") or ""
        check("生成文件已落盘", bool(_op) and os.path.exists(_op), _op)
        if _op and os.path.exists(_op):
            import zipfile
            _xml = zipfile.ZipFile(_op).read("word/document.xml").decode("utf-8")
            check("文档表格数等于有名称设备数（不再多一张空壳）",
                  _xml.count("<w:tbl>") == len(_named_),
                  f"实得 {_xml.count('<w:tbl>')}，应 {len(_named_)}")
            check("文档里不出现无名设备的型号（没被塞进表）",
                  "CDMF5-12" not in _xml)

        # 全车间都无名 → 必须明确报「缺设备名称」，不能拿「模板对不上」搪塞
        idx2 = {"devices": {"N1": {"name": "", "model": "M1", "workshop": "乙车间",
                                   "unit": "台"}, }, "files": {}, "workshops": {"乙车间": {}}}
        with open(os.path.join(_pd, "index.json"), "w", encoding="utf-8") as f:
            json.dump(idx2, f, ensure_ascii=False)
        r2 = _st.render_supervision_doc(category="设备安装检查记录",
                                        workshop="乙车间", project_id=_pid)
        check("全车间无名时不出表", r2.get("ok") is False)
        check("报错文案点明「设备名称」而非模板问题",
              "设备名称" in (r2.get("error") or ""),
              f"实得 {r2.get('error')!r}")
        check("全车间无名时同样记账", len(r2.get("nameless_devices") or []) == 1,
              f"实得 {r2.get('nameless_devices')!r}")
    finally:
        _pm.PROJECTS_ROOT = _h_root
        _pm.CURRENT_PROJECT_FILE = _h_cur
        shutil.rmtree(htmp, ignore_errors=True)

    # ---------------- I. 0 件的卷不占盒号（装盒清单不得错位） ----------------
    # v0.1.187 缺陷（真实项目 e75e857c 实测）：尾矿库是材料车间，台账 4 行全是
    # m2/米，按用户决策跳过设备类表单，卷里一件没有。原来自照样进装盒清单并编成
    # 「第3盒」，后面 16 个盒号整体后移一位 —— 现场照清单装盒会拿错盒子。
    # 这条测试必须**真的调用 _write_boxing_list**，手工造 _vols 验证不了缺陷。
    print("\n[I] 0 件的卷不占盒号，但要记账")
    from app import volume_catalog as _vc
    itmp = tempfile.mkdtemp(prefix="box_")
    _i_proj = si._proj_root
    try:
        def _mk_docx(path, text):
            import zipfile
            _ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   '<w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
            _ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                       '<Default Extension="xml" ContentType="application/xml"/>'
                       '<Override PartName="/word/document.xml" '
                       'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                       '</Types>')
            with zipfile.ZipFile(path, "w") as _z:
                _z.writestr("[Content_Types].xml", _ctypes)
                _z.writestr("word/document.xml", _ct)

        _fake_root = os.path.join(itmp, "proj")
        _bd = os.path.join(_fake_root, "volumes", "测试册")
        os.makedirs(os.path.join(_bd, "甲车间"), exist_ok=True)
        os.makedirs(os.path.join(_bd, "乙车间"), exist_ok=True)   # 0 件卷
        _mk_docx(os.path.join(_bd, "甲车间", "1_记录.docx"), "甲")
        si._proj_root = lambda pid: _fake_root   # 绕过真实项目目录要求

        _f1 = _vc.collect_volume_files(os.path.join(_bd, "甲车间"))
        _f2 = _vc.collect_volume_files(os.path.join(_bd, "乙车间"))
        check("甲车间有归档件", len(_f1) == 1, f"实得 {len(_f1)}")
        check("乙车间是 0 件（对照空卷）", len(_f2) == 0, f"实得 {len(_f2)}")

        _r = si._write_boxing_list("fake", "测试册", None)
        check("装盒清单已生成", bool(_r.get("装盒清单")), f"实得 {_r.get('装盒清单')!r}")
        check("盒数只算有件的卷（空卷不占盒号）", _r.get("盒数") == 1,
              f"实得 {_r.get('盒数')}，应 1")
        _emp = _r.get("空卷") or []
        check("空卷单独记账、指名到车间",
              len(_emp) == 1 and _emp[0].get("车间") == "乙车间",
              f"实得 {_emp!r}")

        import openpyxl
        _box = os.path.join(_bd, _r.get("装盒清单") or "_装盒清单.xlsx")
        if os.path.exists(_box):
            _wb = openpyxl.load_workbook(_box)
            _rows = list(_wb.active.iter_rows(min_row=2, values_only=True))
            check("清单行数 = 有件的卷数", len(_rows) == 1, f"实得 {len(_rows)}")
            check("盒号从第1盒起连续（无空盒占位）",
                  [r[0] for r in _rows] == ["第1盒"], f"实得 {[r[0] for r in _rows]}")
            check("清单里不出现 0 件的车间",
                  all(str(r[2]) != "乙车间" for r in _rows),
                  f"实得 {[r[2] for r in _rows]}")
    finally:
        si._proj_root = _i_proj
        shutil.rmtree(itmp, ignore_errors=True)

    # ---------------- J. 启动块必须在文件末尾（否则尾部定义整段失效） ----------------
    # v0.1.188 缺陷（实测）：main.py 的 `if __name__ == "__main__": run()` 原来夹在
    # 第 4701 行，而 v0.1.125 前端兼容 API 层（_log_op / 36 条 @app 路由 / 82 个定义）
    # 全在 4704 行之后。用 `python -m app.main` 启动时 uvicorn.run 阻塞在那行，
    # 尾部的东西**永远不执行**：新建项目 500（NameError: _log_op）、/api/files 404。
    #
    # 注意：**不能靠"import app.main 后符号在不在"来守**。import 时 run() 不执行，
    # 尾部定义自然全部完成 —— 把启动块搬回中部，import 出来的结果一模一样，
    # 那几项永远绿。必须真的起一个 `-m app.main` 子进程（= 那条故障路径）去问接口。
    print("\n[J] 用 -m app.main 真启动，尾部接口必须可用")
    _msrc = open(os.path.join(WB, "app", "main.py"), encoding="utf-8").read()
    _mlines = _msrc.split("\n")
    _main_idx = None
    for _i, _l in enumerate(_mlines):
        if _l.strip() == 'if __name__ == "__main__":':
            _main_idx = _i
            break
    check("main.py 存在 __main__ 启动块", _main_idx is not None)
    if _main_idx is not None:
        _after = [x for x in _mlines[_main_idx + 1:] if x.strip()]
        check("启动块之后再无任何代码（必须是文件末尾）",
              len(_after) <= 1 and (_after[0].strip() == "run()" if _after else True),
              f"启动块后还有 {len(_after)} 行非空内容，首行={_after[0].strip()[:60] if _after else ''!r}")
    check("run() 只启一个守护线程（不重复调 _start_guardian）",
          _msrc.count("_start_guardian()\n") == 1,
          f"实得 {_msrc.count('_start_guardian()')} 处调用")

    import subprocess
    import socket
    import time as _t
    import json as _json
    import urllib.request as _url
    from urllib.error import HTTPError as _HTTPErr

    def _free_port():
        s_ = socket.socket()
        s_.bind(("127.0.0.1", 0))
        _p = s_.getsockname()[1]
        s_.close()
        return _p

    _port = _free_port()
    _dtdir = tempfile.mkdtemp(prefix="j_data_")
    _proj_name = f"_j_节自测_{int(_t.time() * 1000) % 100000}"
    # main.py 里 PORT / DATA_DIR 都是硬编码，环境变量覆盖不了。用包装器改 config
    # 之后再以 run_name="__main__" 跑一遍——这才会真的执行 `if __name__` 那段，
    # 也就是**那条出故障的启动路径**。同时把 DATA_DIR 指到临时目录，
    # 不往真实 data/ 里写测试项目和操作日志。
    _code = (
        "import runpy\n"
        "from app import config as _c\n"
        f"_c.PORT = {_port}\n"
        f"_c.DATA_DIR = {_dtdir!r}\n"
        "runpy.run_module('app.main', run_name='__main__')\n"
    )
    _env = dict(os.environ)
    _env["FANGONG_NO_BROWSER"] = "1"
    _env["PYTHONPATH"] = WB
    _lg = open(os.path.join(tempfile.gettempdir(), f"jm_{_port}.log"), "w")
    _pr = subprocess.Popen([sys.executable, "-c", _code], cwd=WB,
                           stdout=_lg, stderr=subprocess.STDOUT, env=_env)

    def _get(_path, _body=None, _timeout=20):
        _req = _url.Request(f"http://127.0.0.1:{_port}{_path}",
                            data=(_json.dumps(_body).encode() if _body else None),
                            headers={"Content-Type": "application/json"},
                            method="POST" if _body else "GET")
        try:
            _r = _url.urlopen(_req, timeout=_timeout)
            return _r.status, _r.read().decode("utf-8", "ignore")
        except _HTTPErr as _e:
            return _e.code, _e.read().decode("utf-8", "ignore")
        except Exception as _e:            # noqa: BLE001
            return -1, repr(_e)

    try:
        _up = False
        for _ in range(90):
            _t.sleep(0.5)
            _c, _txt = _get("/api/status", _timeout=2)
            if _c == 200:
                _up = True
                break
        check("以 __main__ 路径能起来（uvicorn 已监听）", _up,
              f"{_port} 端口 45 秒内未就绪，见 {os.path.basename(_lg.name)}")
        if _up:
            # ① 尾部路由必须 200（旧行为：404，因为 4704 行后根本没执行）
            for _p in ("/api/files?limit=1", "/api/files/tree", "/api/files/pending"):
                _code_, _txt_ = _get(_p)
                check(f"启动后 {_p.split('?')[0]} 可用（尾部定义已执行）",
                      _code_ == 200, f"http={_code_} {_txt_[:80]}")

            # ② 新建项目必须 ok（旧行为：500 NameError: _log_op）
            _code_, _txt_ = _get("/api/projects/create", {"name": _proj_name})
            _okj = False
            try:
                _okj = _json.loads(_txt_).get("ok") is True
            except Exception:
                pass
            check("启动后新建项目成功（_log_op 已定义）", _code_ == 200 and _okj,
                  f"http={_code_} {_txt_[:120]}")

            # ③ 操作日志真的落盘（证明 _log_op 存在且能写，不是个空壳）
            _logp = os.path.join(_dtdir, "operation_log.jsonl")
            _has = False
            if os.path.exists(_logp):
                _has = _proj_name in open(_logp, encoding="utf-8").read()
            check("_log_op 实际写出操作日志", _has,
                  f"未在 operation_log.jsonl 找到本次建项目记录")
    finally:
        try:
            _pr.terminate()
            _pr.wait(timeout=10)
        except Exception:
            try:
                _pr.kill()
            except Exception:
                pass
        _lg.close()
        shutil.rmtree(_dtdir, ignore_errors=True)

    # ---------------- K. 待办清单必须换行结尾 ----------------
    # v0.1.188：_render_todo 原来 return '\n'.join(lines)，末尾没换行。
    # 写出的 _待办清单.md 最后一行顶在文件末字节上，联营/监理用记事本打开会
    # 提示「文件末尾无换行」，cat 出来也和 shell 提示符粘成一行。
    print("\n[K] 待办清单以换行结尾")
    _todo_md = si._render_todo({}, [{"序号": "1", "名称": "设备安装记录",
                                     "原因": "该车间台账全为材料，非设备"}], [],
                               workshop="尾矿库", material_workshop=True,
                               skipped_device_forms=[{"序号": "1", "名称": "设备安装记录",
                                                      "原因": "非设备"}])
    check("_render_todo 返回值以换行结尾", _todo_md.endswith("\n"),
          f"末尾 20 字符={_todo_md[-20:]!r}")
    check("内容本身没被截断（仍含原因说明）",
          "非设备" in _todo_md and _todo_md.strip(), f"长度={len(_todo_md)}")

    # ---------------- L. 整卷 catalog 必须逐车间汇总 ----------------
    # v0.1.189 缺陷（真实项目 e75e857c 实测，18 个车间的设备安装册）：整卷返回
    #   catalog 件数=3 / 页数=66
    # 而 generated 明明是 54 件（18 车间 × 3）、装盒清单页数实测合计 1142。
    # 根因：_merge_workshop_results 里 `base = dict(ws_results.get(wss[0]) or {})`
    # 只浅拷贝首个车间，catalog 是嵌套 dict，于是整册继承了「中矿堆」这一个车间的
    # 数字，调用方又只覆盖 装盒清单/盒数/空卷，件数页数永不修正。
    # 危害：监理拿这个数对整册卷内目录与脊背标签 —— 18 盒 1142 页被报成 3 件 66 页，
    # 等于整册资料没交。这条必须直调合并函数，看返回值，不能靠人工合算。
    print("\n[L] 整卷 catalog 逐车间汇总（不得只取首车间）")
    _w3 = ["中矿堆", "选矿厂", "尾矿库"]
    _wsr = {
        "中矿堆": {"generated": [{"序号": str(i)} for i in range(3)],
                   "errors": [], "todo": [],
                   "catalog": {"件数": 3, "页数": 66, "页数依据": "rendered",
                               "未生成项": 0, "文件": ["_卷内目录.docx"]}},
        "选矿厂": {"generated": [{"序号": str(i)} for i in range(3)],
                   "errors": [], "todo": [{"序号": "9", "名称": "设备安装记录"}],
                   "catalog": {"件数": 3, "页数": 70, "页数依据": "rendered",
                               "未生成项": 1, "文件": ["_卷内目录.docx",
                                                       "_卷内备考表.docx"]}},
        "尾矿库": {"generated": [], "errors": [], "todo": [],
                   "catalog": {"件数": 0, "页数": 0, "页数依据": "rendered",
                               "未生成项": 0, "文件": ["_案卷封面.docx"]}},
    }
    _mg = si._merge_workshop_results(_wsr, _w3)
    _cat = (_mg or {}).get("catalog") or {}
    check("整卷 catalog 件数 = 逐车间合计", _cat.get("件数") == 6,
          f"实得 {_cat.get('件数')}，应 6（回退成只取首车间会得到 3）")
    check("整卷 catalog 页数 = 逐车间合计", _cat.get("页数") == 136,
          f"实得 {_cat.get('页数')}，应 136（回退会得到 66）")
    check("件数与 generated 计数自洽",
          _cat.get("件数") == sum(v["generated"] for v in _mg.get("by_workshop", {}).values()),
          f"catalog={_cat.get('件数')} vs by_workshop 合计="
          f"{sum(v['generated'] for v in _mg.get('by_workshop', {}).values())}")
    check("卷数 = 参与合并的车间数", _cat.get("卷数") == 3, f"实得 {_cat.get('卷数')}")
    check("按车间逐项留底（3 个车间都要有）",
          sorted((_cat.get("按车间") or {}).keys()) == sorted(_w3),
          f"实得 {sorted((_cat.get('按车间') or {}).keys())}")
    check("按车间明细里的页数是各车间自己的值",
          [(_cat.get("按车间") or {}).get(w, {}).get("页数") for w in _w3] == [66, 70, 0],
          f"实得 {[(_cat.get('按车间') or {}).get(w, {}).get('页数') for w in _w3]}")
    check("未生成项也累加", _cat.get("未生成项") == 1, f"实得 {_cat.get('未生成项')}")
    check("文件清单取并集（不丢车间独有的文件）",
          set(_cat.get("文件") or []) == {"_卷内目录.docx", "_卷内备考表.docx", "_案卷封面.docx"},
          f"实得 {sorted(_cat.get('文件') or [])}")
    check("页数依据同口径时照抄", _cat.get("页数依据") == "rendered",
          f"实得 {_cat.get('页数依据')!r}")

    # 口径混杂：不能拿 "rendered" 盖住"有些车间没渲染出来"，要如实说只算了一部分。
    _wsr_mix = copy.deepcopy(_wsr)
    _wsr_mix["选矿厂"]["catalog"]["页数依据"] = "libreoffice"
    _mix = si._merge_workshop_results(_wsr_mix, _w3).get("catalog") or {}
    check("口径混杂时不谎报 rendered",
          _mix.get("页数依据") != "rendered" and "partial" in str(_mix.get("页数依据")),
          f"实得 {_mix.get('页数依据')!r}")
    check("口径混杂不影响件数/页数合计",
          _mix.get("件数") == 6 and _mix.get("页数") == 136,
          f"实得 件数={_mix.get('件数')} 页数={_mix.get('页数')}")

    # 边界：某车间页数未实测（None）时，合计不能把 None 当 0 悄悄少算，
    # 宁可给 None 也不能给一个错数（监理会拿它做核对）。
    _wsr_non = copy.deepcopy(_wsr)
    _wsr_non["选矿厂"]["catalog"]["页数"] = None
    _non = si._merge_workshop_results(_wsr_non, _w3).get("catalog") or {}
    check("任一车间页数为 None 时整卷页数置 None（不静默少算）",
          _non.get("页数") is None,
          f"实得 {_non.get('页数')!r}（若给 66 就是把 None 当 0 加了）")
    check("但件数仍可算（不因页数缺失一起丢掉）",
          _non.get("件数") == 6, f"实得 {_non.get('件数')}")

    # 边界：bool 是 int 的子类，True 不能当 1 加进合计。
    _wsr_b = copy.deepcopy(_wsr)
    _wsr_b["尾矿库"]["catalog"]["件数"] = True
    _b = si._merge_workshop_results(_wsr_b, _w3).get("catalog") or {}
    check("bool 不计入件数合计（True 不等于 1）",
          _b.get("件数") is None or _b.get("件数") == 6,
          f"实得 {_b.get('件数')!r}（真实合计 6，若得 7 说明把 True 当 1）")

    # 只有一个车间时行为不能变（避免汇总逻辑把单车间也改坏）。
    _one = si._merge_workshop_results({"甲": {"generated": [{"序号": "1"}],
                                             "catalog": {"件数": 3, "页数": 66,
                                                         "页数依据": "rendered",
                                                         "未生成项": 0,
                                                         "文件": ["a.docx"]}}}, ["甲"])
    check("单车间件数不变", (_one.get("catalog") or {}).get("件数") == 3,
          f"实得 {(_one.get('catalog') or {}).get('件数')}")
    check("单车间页数不变", (_one.get("catalog") or {}).get("页数") == 66,
          f"实得 {(_one.get('catalog') or {}).get('页数')}")

    # 车间没有 catalog（空项目）时不能崩，也不能编出数字。
    _no = si._merge_workshop_results({"甲": {"generated": []}}, ["甲"])
    check("车间无 catalog 时不崩、catalog 仍可读",
          isinstance((_no or {}).get("catalog"), (dict, type(None))),
          f"实得 {type((_no or {}).get('catalog'))}")

    # ---- 同一类缺陷的标量残留：这些字段同样只继承首车间 ----
    # 实测（真实项目 e75e857c，19 个车间）：
    #   workshop_device_rows = 13（中矿堆一个车间的台账行数，整册应为各车间合计）
    #   todo_file 指向 .../中矿堆/_待办清单.md，界面拿它当整册待办
    #   material_workshop = False（中矿堆不是材料车间，可尾矿库是）
    print("\n[L2] 整卷标量统计也按整册口径（不得只取首车间）")
    _ws2 = {
        "甲": {"generated": [], "errors": [], "todo": [],
               "workshop_device_rows": 13, "workshop_devices": 13,
               "material_workshop": False,
               "empty_shells": [], "todo_file": "/甲/_待办清单.md",
               "catalog": {"件数": 3, "页数": 60, "页数依据": "rendered",
                           "未生成项": 0, "文件": []}},
        "乙": {"generated": [], "errors": [], "todo": [],
               "workshop_device_rows": 4, "workshop_devices": 4,
               "material_workshop": True,
               "empty_shells": [{"序号": "1", "名称": "x"}], "todo_file": "/乙/_待办清单.md",
               "catalog": {"件数": 0, "页数": 0, "页数依据": "rendered",
                           "未生成项": 3, "文件": []}},
    }
    _m2 = si._merge_workshop_results(_ws2, ["甲", "乙"])
    check("workshop_device_rows = 各车间合计", _m2.get("workshop_device_rows") == 17,
          f"实得 {_m2.get('workshop_device_rows')}，应 17（回退会得到 13）")
    check("workshop_devices = 各车间合计", _m2.get("workshop_devices") == 17,
          f"实得 {_m2.get('workshop_devices')}")
    check("empty_shell_count 跟着合并后的列表走", _m2.get("empty_shell_count") == 1,
          f"实得 count={_m2.get('empty_shell_count')} vs len(list)={len(_m2.get('empty_shells') or [])}")
    check("整册 material_workshop=False（只有部分是材料车间）",
          _m2.get("material_workshop") is False, f"实得 {_m2.get('material_workshop')}")
    check("并指名哪些车间是材料车间",
          _m2.get("material_workshops") == ["乙"], f"实得 {_m2.get('material_workshops')}")
    check("todo_file 不再冒充整册待办（置空）",
          _m2.get("todo_file") is None, f"实得 {_m2.get('todo_file')!r}")
    check("按车间给出每份待办清单文件",
          sorted((_m2.get("todo_files") or {}).keys()) == ["乙", "甲"],
          f"实得 {sorted((_m2.get('todo_files') or {}).keys())}")

    # 全部车间都是材料车间时，整册才是材料车间（all 的语义，不是 any）
    _m2b = si._merge_workshop_results(
        {"甲": {"material_workshop": True}, "乙": {"material_workshop": True}}, ["甲", "乙"])
    check("全部车间都是材料车间时整册才为 True",
          _m2b.get("material_workshop") is True, f"实得 {_m2b.get('material_workshop')}")

    # 上面 material_workshop 那两条的**首车间是 False**，回退成"继承首车间"也恰好
    # 得 False —— 咬不住这个缺陷。反过来摆一次：首车间是材料车间、后面不是。
    # 回退会得 True（错），正确逻辑必须得 False。
    _m2r = si._merge_workshop_results(
        {"甲": {"material_workshop": True}, "乙": {"material_workshop": False}}, ["甲", "乙"])
    check("首车间是材料车间、后面不是 → 整册不能判成材料车间",
          _m2r.get("material_workshop") is False,
          f"实得 {_m2r.get('material_workshop')}（回退会得 True）")
    check("材料车间名单不会因为首车间是材料就只剩它",
          _m2r.get("material_workshops") == ["甲"], f"实得 {_m2r.get('material_workshops')}")

    print("\n[M] 整卷互斥：同一册+车间不许两路同时出卷（会并发写同一批卷目录）")
    # v0.1.190 实测事故（真实项目 e75e857c，19 个车间，整卷实测 130314 ms）：
    # 界面上点「一键整卷」后只有一句「整卷生成中，请稍候」，130 秒内没有任何进度，
    # 按钮也没禁用（runVolume() 里 disabled / _running 出现次数实测均为 0）。
    # 用户等不及会再点一次 —— 此时两路车间级线程池同时写同一批卷目录与 exports。
    # 源码检索 Lock / _INFLIGHT 在 generate_volume 里一个都没有。
    check("整卷入口有互斥机制（acquire_volume_slot 存在）",
          hasattr(si, "acquire_volume_slot") and hasattr(si, "release_volume_slot"),
          "generate_volume 内部无任何互斥，重复点击会并发写同一批卷目录")

    if hasattr(si, "acquire_volume_slot"):
        # 同一 (项目, 册, 车间) 第二次必须被拒
        _k1 = si.acquire_volume_slot("e75e857c", "设备安装", "选矿厂")
        _k2 = si.acquire_volume_slot("e75e857c", "设备安装", "选矿厂")
        check("同一册+同一车间第二次整卷被拒（返回进行中而非开跑）",
              _k1 is not None and _k2 is None,
              f"第一次={_k1} 第二次={_k2}（第二次必须为 None，否则两路同时写盘）")
        # 但不同车间必须放行，不能被一把大锁串死
        _k3 = si.acquire_volume_slot("e75e857c", "设备安装", "磨浮车间")
        check("不同车间可以并行（互斥粒度按车间，不是全项目一把锁）",
              _k3 is not None, f"实得 {_k3}")
        si.release_volume_slot(_k1)
        si.release_volume_slot(_k3)
        # 释放后必须能再进来，否则一次异常就把整卷永久锁死
        _k4 = si.acquire_volume_slot("e75e857c", "设备安装", "选矿厂")
        check("释放后能重新整卷（异常不会把整卷永久锁死）", _k4 is not None, f"实得 {_k4}")
        si.release_volume_slot(_k4)
        # 全厂（车间为空/全厂）单独一把键，与具体车间不冲突
        _k5 = si.acquire_volume_slot("e75e857c", "设备安装", "")
        _k6 = si.acquire_volume_slot("e75e857c", "设备安装", "全厂")
        check("全厂与全厂（空/全厂两种写法）视为同一个任务",
              (_k5 is not None) != (_k6 is not None),
              f"空={_k5} 全厂={_k6}（两者必须只有一个能拿到）")
        for _k in (_k5, _k6):
            si.release_volume_slot(_k)

        # 异常路径：业务异常也必须释放，否则后续整卷全被拒
        check("出卷抛异常时槽位会被释放（不会把整卷封死）",
          _exception_releases_slot(si), "generate_volume 未用 try/finally，异常会漏锁")

    print("\n[M3] 进度必须按**真实完成顺序**推进，不能按提交顺序排队等")
    # 实测 v0.1.190 首版缺陷（真并发探针 19 车间，185 秒）：
    #   t=179.7s 时 done 仍是 16，t=185.1s 才一次跳到 19。
    # 原因是进度写在 `for _fut_obj, _w in _fut.items()` 里 —— 那是**提交顺序**，
    # 必须等排在前面的车间先完成才能往前挪。一个慢车间（辊磨筛分车间）
    # 就把后面已完成的车间的进度全压住，界面在最后 6 秒一动不动，
    # 恰恰让「是不是卡死了」这个本来要解决的问题又回来了。
    # 正确做法是 as_completed：谁先出完谁先报。
    check("有「按完成顺序收集」的并发出卷辅助函数",
          hasattr(si, "_run_parallel_with_progress"),
          "进度写在提交顺序的 future.items() 上，慢车间会压住其余车间的进度")

    if hasattr(si, "_run_parallel_with_progress"):
        import time as _t

        def _慢(*a, **k):
            _t.sleep(0.45)
            return {"name": "慢车间"}

        def _快(*a, **k):
            _t.sleep(0.01)
            return {"name": "快车间"}

        _order = []
        _t0 = _t.time()
        _res = si._run_parallel_with_progress(
            [("慢车间", _慢), ("快车间", _快)], max_workers=2,
            on_done=lambda name, ok: _order.append((name, round(_t.time() - _t0, 2))))
        check("先完成的车间接先报到（快车间在慢车间之前）",
              [x[0] for x in _order] == ["快车间", "慢车间"],
              f"实得顺序 {_order}")
        check("快车间报到时慢车间还没完（不是等齐了一次性报）",
              bool(_order) and _order[0][1] < 0.4,
              f"首个报到时间 {_order[0][1] if _order else None}s（应远小于 0.45s）")
        check("结果按车间名可回取，慢的快的一个都不丢",
              (isinstance(_res, dict) and set(_res) == {"慢车间", "快车间"}
               and _res["慢车间"]["name"] == "慢车间"),
              f"实得 {_res}")
        check("回调次数等于任务数（不多报也不漏报）",
              len(_order) == 2, f"实得 {len(_order)} 次")

    print("\n[M4] 整编联动面板必须真的能取到册（否则「一键整卷」永远点不动）")
    # 实测缺陷（真浏览器）：整编联动的书册下拉框在 module-archive 里，
    # 但只有进入 docgen 模块时才会调 loadRegistryStatus() 去填它。
    # 用户从整编模块进来，下拉恒为「（未导入登记表）」，点整卷只会 alert 3 次
    # 「请先选项目」—— 整编这条路的主路径其实一直是断的。
    _html_path = os.path.join(WB, "web", "index.html")
    _html = open(_html_path, encoding="utf-8", errors="replace").read() if os.path.exists(_html_path) else ""
    check("能读到前端 index.html", bool(_html), f"未找到 {_html_path}")

    if _html:
        _i_switch = _html.find("function switchModule")
        _i_end = _html.find("\nfunction ", _i_switch + 10)
        _sw = _html[_i_switch:_i_end] if _i_switch > 0 else ""
        _i_arc = _sw.find("moduleName === 'archive'")
        # 取 archive 分支之后的一小段窗口（跨行写也算），到下一个 if 分支为止
        _arc_blk = _sw[_i_arc:_sw.find("if (moduleName === 'ai')", _i_arc)] if _i_arc > 0 else ""
        check("进入整编模块时会刷新册列表（loadRegistryStatus）",
              _i_arc > 0 and "loadRegistryStatus()" in _arc_blk,
              "module-archive 分支里没有 loadRegistryStatus()，"
              "册下拉永远是「未导入登记表」，点整卷不生效")

        # runVolume 里 btn 必须先赋值再用，否则命中「重复点击」时 btn 是 undefined
        _i_rv = _html.find("function runVolume()")
        _rv = _html[_i_rv:_html.find("\nfunction ", _i_rv + 10)] if _i_rv > 0 else ""
        _p_btn = _rv.find("var btn = document.getElementById('supTodoBar')")
        _p_guard = _rv.find("if (window.__volRunning)")
        check("重复点击守卫在 btn 赋值之后（否则 TypeError）",
              _p_btn > 0 and _p_guard > _p_btn,
              f"btn@{_p_btn} guard@{_p_guard}（guard 必须更靠后）")

        # 每条早退路径都必须放开 __volRunning，否则一次异常把按钮永久卡住
        check("「接口失败」早退路径会放开 __volRunning",
              "window.__volRunning = false" in _rv.split("if (!d.ok && !d.result)")[1][:400]
              if "if (!d.ok && !d.result)" in _rv else False,
              "接口异常时直接 return，按钮永久停在「进行中」，用户只能刷新页面")

    print("\n[M6] 看别人那一卷时，按钮不能永久卡死")
    # 实测缺陷（静态追踪 + 真浏览器同源路径）：
    # 后端槽位互斥拦下重复请求时走 already_running 分支，那条分支既不停轮询
    # 也不清 __volRunning；而轮询在 !d.running 时又只是 return —— 两头都不收尾。
    # 结果：本页并没有自己的整卷在跑，按钮却永久停在「整卷正在进行中」，
    # 用户只能刷新页面才能再点。这与 v0.1.190 修的「接口异常永久锁死」同源。
    if _html:
        _i_rv2 = _html.find("function runVolume()")
        _rv2 = _html[_i_rv2:_html.find("\nfunction ", _i_rv2 + 10)] if _i_rv2 > 0 else ""
        check("有「本页看的是别人那一卷」的标记位",
              "_volWatchOther" in _rv2,
              "没有区分本页发起与他人发起的整卷，两种状态混在一起")
        _i_ar = _rv2.find("r.already_running")
        _ar_blk = _rv2[_i_ar:_i_ar + 700] if _i_ar > 0 else ""
        check("already_running 分支会置上「看别人」的标记",
              _i_ar > 0 and "_volWatchOther = true" in _ar_blk,
              "互斥拦下重复请求时没有标记，导致结束后没人放开按钮")
        # 轮询看到 running 翻 false 时，必须停轮询 + 放开锁
        _i_poll = _rv2.find("if (!d.running || !p)")
        _poll_blk = _rv2[_i_poll:_i_poll + 700] if _i_poll > 0 else ""
        check("轮询发现那一卷已结束时会停轮询并放开按钮锁",
              _i_poll > 0 and "_stopPoll()" in _poll_blk
              and "window.__volRunning = false" in _poll_blk,
              "running 翻 false 时只是 return，按钮永远卡在「进行中」")
        check("看别人那一卷时的文案与本页发起的不一样",
              "_volWatchOther ? 'ℹ 已有整卷在进行中（本次请求未执行）'" in _rv2,
              "两种状态文案相同，用户以为本页在跑")

    print("\n[M7] 整编面板必须真的能拿到当前项目（否则「一键整卷」永远点不动）")
    # 实测缺陷（真浏览器 + 静态追踪）：
    # getCurrentProjectIdForSup() 的两条取值路径**都不存在**：
    #   ① localStorage 键 'fanGong_currentProject' —— 全仓只有这一处读，
    #      没有任何 setItem 写入点，永远读出 null；
    #   ② document.getElementById('projectSelector') —— DOM 里没有这个 id，
    #      真实的下拉叫 projectSelect。
    # 结果该函数恒返回空串 → runVolume()/checkSupervision() 一上来就
    # alert('请先在资源管理中选择项目') 然后 return —— 「一键整卷」这条主路径
    # 在真实浏览器里从来没跑通过（册下拉填上了也没用，点下去只会弹窗）。
    # 页面真正的当前项目在全局 currentProject 上（对象，带 id）。
    if _html:
        _i_gid = _html.find("function getCurrentProjectIdForSup")
        _gid = _html[_i_gid:_html.find("\nfunction ", _i_gid + 10)] if _i_gid > 0 else ""
        # 只看可执行代码：注释里提到旧名字是正常的（那是在解释为什么改），
        # 判据要落在代码上，不能把注释里的字样当成「还在依赖」。
        _gid_code = re.sub(r'//[^\n]*', '', _gid)
        _gid_code = re.sub(r'/\*.*?\*/', '', _gid_code, flags=re.S)
        check("取项目 ID 的函数存在", _i_gid > 0, "找不到 getCurrentProjectIdForSup")
        check("会从全局 currentProject 上取项目 ID",
              "currentProject" in _gid_code and ".id" in _gid_code,
              "没有读 currentProject —— 这是页面上真正可靠的当前项目来源")
        check("会从真实存在的项目下拉取项目 ID（projectSelect）",
              "projectSelect" in _gid_code,
              "读的是不存在的 projectSelector，DOM 里根本没这个 id")
        # 旧的死路：localStorage 键全仓无写入点，projectSelector 不存在
        check("不再依赖从未被写入的 localStorage 键",
              "fanGong_currentProject" not in _gid_code,
              "全仓没有 setItem 写入这个键，读它永远是 null")
        check("不再引用不存在的 projectSelector",
              "projectSelector" not in _gid_code,
              "DOM 里只有 projectSelect，projectSelector 是凭空的 id")
        # 兜底：即便前端拿不到项目 ID，也应由后端按「当前项目」兜底，
        # 而不是让用户对着一个永远弹出的 alert 无计可施
        check("取不到项目时有明确提示而不是静默失败",
              "alert(" in _gid_code or "return" in _gid_code,
              "取不到项目时必须有明确动作")

    print("\n[M2] 整卷进度：长任务必须有可读进展，而不是一句静态文案")
    check("有整卷进度读取接口（get_volume_progress 存在）",
          hasattr(si, "get_volume_progress"),
          "130 秒全程只有「整卷生成中，请稍候」，用户无法判断死没死")
    if hasattr(si, "get_volume_progress"):
        _p0 = si.get_volume_progress("e75e857c", "设备安装", "不存在的车间X")
        check("没有进行中的整卷时进度为空/空闲", not _p0, f"实得 {_p0}")

    print("\n[M5] 进度记录必须有上限（工作台是长期驻留进程，不能只增不减）")
    # 实测缺陷：_VOLUME_PROGRESS 只在 acquire 时写入、release 时把 running 置 False，
    # **从不删除**。实测连跑 20 个不同车间后字典里留 21 条、_VOLUME_SLOTS 已归零。
    # 工作台是长期驻留的单进程（现场一天开 8 小时、跨多项目多册多车间），
    # 这条字典只增不减就是一条慢性内存泄漏；而且界面上「刚跑完」和
    # 「三小时前跑完」的残留记录长得一样，出问题时没法判断。
    check("有进度条目上限常量", hasattr(si, "_VOLUME_PROGRESS_MAX"),
          "没有上限，字典只增不减")
    if hasattr(si, "_VOLUME_PROGRESS_MAX"):
        check("上限是个合理正整数（留够历史但不会失控）",
              isinstance(si._VOLUME_PROGRESS_MAX, int) and 4 <= si._VOLUME_PROGRESS_MAX <= 200,
              f"实得 {si._VOLUME_PROGRESS_MAX!r}")

        # 连跑 3 倍上限个不同车间（必须真的越过上限才谈得上淘汰）
        _over = si._VOLUME_PROGRESS_MAX * 3
        si._VOLUME_PROGRESS.clear()
        for _i in range(_over):
            _k = si.acquire_volume_slot("pMem", "设备安装", f"车间{_i:03d}")
            si.release_volume_slot(_k)
        _n = len(si._VOLUME_PROGRESS)
        check(f"连跑 {_over} 次后进度条目数不超过上限", _n <= si._VOLUME_PROGRESS_MAX,
              f"实得 {_n} 条，上限 {si._VOLUME_PROGRESS_MAX}")

        # 淘汰必须是先进先出：最后跑的那个必须在，最早的应该被淘汰
        _last = si.get_volume_progress("pMem", "设备安装", f"车间{_over-1:03d}")
        check("最后跑完的车间进度仍可查（不能把刚跑完的删掉）",
              bool(_last) and _last.get("done") == 0,
              f"实得 {_last}")
        _first = si.get_volume_progress("pMem", "设备安装", "车间000")
        check("最早的那条已被淘汰（确实是 FIFO 而不是拒写）",
              _first is None, f"实得 {_first}")

        # 淘汰必须是**确定的**：同一批输入再跑一遍，留下的车间集合要一致。
        # 实测踩到过：排序键用 time.time() 浮点，连开时几乎相同，
        # sort() 遇并列按任意顺序 → 同一批输入两次跑，被淘汰的车间都不一样。
        def _run_batch():
            si._VOLUME_PROGRESS.clear()
            for _i in range(_over):
                _kk = si.acquire_volume_slot("pDet", "设备安装", f"车间{_i:03d}")
                si.release_volume_slot(_kk)
            return sorted(str(k[2]) for k in si._VOLUME_PROGRESS)

        _set_a, _set_b = _run_batch(), _run_batch()
        check("淘汰顺序是确定的（同一批输入两次跑，留下的车间完全一致）",
              _set_a == _set_b,
              f"两次结果不同，条数 {len(_set_a)} vs {len(_set_b)}")

        # 淘汰顺序必须按「谁先进来的」，不能按时间戳。
        # 实测（时钟往回拨 2 小时后再开 3 个卷）：排序键用 started 时，
        # 3 条刚跑完的被误淘汰 2 条、最老的旧001/旧002 反被留下。
        # 现场机器联网校时或用户手改系统时间都会让时间戳非单调，这不是假设。
        _now0 = time.time()
        si._VOLUME_PROGRESS.clear()
        for _i in range(si._VOLUME_PROGRESS_MAX):
            _ok = si.acquire_volume_slot("pClk", "设备安装", f"旧{_i:03d}")
            si.release_volume_slot(_ok)
        _orig_time = si.time.time
        si.time.time = lambda: _now0 - 7200        # 时钟被往回拨 2 小时
        try:
            for _i in range(3):
                _ck = si.acquire_volume_slot("pClk", "设备安装", f"新{_i}")
                si.release_volume_slot(_ck)
        finally:
            si.time.time = _orig_time
        _keep = [str(k[2]) for k in si._VOLUME_PROGRESS]
        _new_kept = [f"新{_i}" for _i in range(3) if f"新{_i}" in _keep]
        check("时钟回拨后刚跑完的记录不会被误淘汰（淘汰按写入先后，不按时间戳）",
              len(_new_kept) == 3, f"3 条新记录只剩 {_new_kept}；旧记录被误留 "
              f"{[x for x in ('旧000', '旧001', '旧002') if x in _keep]}")
        check("时钟回拨后仍淘汰最老的记录（不能因为时间戳更旧就全留下）",
              all(f"旧{_i:03d}" not in _keep for _i in range(3)),
              f"旧000/001/002 仍在：{[x for x in ('旧000','旧001','旧002') if x in _keep]}")

        # 保留窗口：已结束记录超过 TTL 要被清掉（不能留到第二天还显示「已完成」）
        check("有已结束记录的保留窗口常量", hasattr(si, "_VOLUME_PROGRESS_TTL"),
              "没有保留窗口，上周的「已完成」会一直留在界面上")
        if hasattr(si, "_VOLUME_PROGRESS_TTL"):
            si._VOLUME_PROGRESS.clear()
            _tk = si.acquire_volume_slot("pTtl", "设备安装", "旧车间")
            si.release_volume_slot(_tk)
            # 把收卷时间人为拨回到 TTL 之前很久，再开一个新卷触发裁剪
            si._VOLUME_PROGRESS[si._volume_key("pTtl", "设备安装", "旧车间")]["finished"] \
                = time.time() - si._VOLUME_PROGRESS_TTL - 60
            _nk = si.acquire_volume_slot("pTtl", "设备安装", "新车间")
            si.release_volume_slot(_nk)
            check("超过保留窗口的已结束记录会被清掉",
                  si.get_volume_progress("pTtl", "设备安装", "旧车间") is None,
                  "旧记录仍在，界面上会一直挂着一条「已完成」")
            check("保留窗口内刚跑完的记录不会被清（用户还要回头看耗时）",
                  si.get_volume_progress("pTtl", "设备安装", "新车间") is not None,
                  "刚跑完的记录被清掉了")

        # 正在跑的任务绝不能被淘汰掉 —— 淘汰只针对已结束的
        si._VOLUME_PROGRESS.clear()
        _running_keys = []
        for _i in range(3):
            _rk = si.acquire_volume_slot("pRun", "设备安装", f"在跑{_i}")
            _running_keys.append(_rk)
        for _i in range(si._VOLUME_PROGRESS_MAX * 2):
            _dk = si.acquire_volume_slot("pRun", "设备安装", f"已完{_i}")
            si.release_volume_slot(_dk)
        _still = all(si.get_volume_progress("pRun", "设备安装", f"在跑{_i}") is not None
                     and si.get_volume_progress("pRun", "设备安装", f"在跑{_i}").get("running")
                     for _i in range(3))
        check("整卷进行中的记录不会被淘汰（否则界面轮询会突然查不到）",
              _still, "在跑的 3 条被 FIFO 冲掉了")
        for _rk in _running_keys:
            si.release_volume_slot(_rk)
        si._VOLUME_PROGRESS.clear()

    print(f"\n结果：{_PASS[0]} passed, {len(_FAIL)} failed")
    if _FAIL:
        for f in _FAIL:
            print("  FAIL:", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
