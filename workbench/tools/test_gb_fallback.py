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
import os
import shutil
import sys
import tempfile

WB = os.environ.get("FANGONG_WB",
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WB)
os.environ.setdefault("FANGONG_NO_BROWSER", "1")

from app import gb_form as gb  # noqa: E402
from app import supervision_templates as st  # noqa: E402
from app import supervision_integration as si  # noqa: E402

_PASS = [0]
_FAIL = []


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

    print(f"\n结果：{_PASS[0]} passed, {len(_FAIL)} failed")
    if _FAIL:
        for f in _FAIL:
            print("  FAIL:", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
