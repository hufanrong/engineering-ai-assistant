"""
v0.1.183：国标兜底表（用户决策 —— 「就用现有的检查记录表，没有提供的模板时，
统一根据国标模板制作」）。

两条规则分开实现，互不干扰：

① **优先复用现有表**（`alias_category`）。
   登记表里写的是国标/行业标准的正式表名，内置模板用的是另一套叫法。
   实测真实登记表：7 个项目里都写了「设备安装记录」（表号 SH/T3503-J302），
   而模板库里只有「设备安装检查记录」。
   相似度回退救不了它 —— 与「设备安装检查记录」「设备内件安装记录」的比值
   都是 0.8571（并列第一、差值为 0），按既有策略「多个候选一律不猜」必然拒绝。
   所以这里给**显式别名**：只处理经确认过的对应关系，不做自动猜测。

② **无模板时按国标格式生成**（`build_gb_form`）。
   连别名都对不上的登记项，不再只丢进待办「无匹配模板，需人工确认表类型」，
   而是按国标表格式生成一份可打印的表，并在表头印出表号与来源标注。

   **表种必须分开**（否则出的表是错的）：实测把「现场签证单XYZ」按
   设备外观检查条款出表，监理一眼就知道这不是签证单。
   所以先按表名判表种（`form_kind`），每种表种用对应的国标骨架：

      check   检查/安装/检验/验收/试运转  → 序号/检查项目/检查情况/检查结果
      sign    签证/洽商/报审/报验/交接/移交通知/报告 → 事项/内容说明/签认意见
      conceal 隐蔽 → 隐蔽部位/隐蔽内容/检查结论
      test    试验/测试/调试/校验 → 试验项目/试验条件/标准要求/试验结果
      generic 其它 → 记录事项/内容/结论（不硬套任何专业条款）

硬约束：
- 生成出来的表**不含任何编造的业务事实**：单位工程/车间/设备名称只取项目配置与
  设备台账，取不到就留空交人工填写（竣工资料的正常做法）。
- 检查项目只取国标通用条款，**不臆造某种设备的具体公差数值**；
  需要数值的地方留空，不填示例数字。
"""

import re
from typing import Dict, List, Optional

# ---- ① 表名别名：登记表正式表名 → 内置模板类别 ----
# 只收录**已确认真实存在对应关系**的条目；新增必须写明来源，禁止猜测性添加。
NAME_ALIAS = {
    # 用户 2026-10-31 决策：SH/T3503-J302「设备安装记录」就用现有的「设备安装检查记录」。
    # 依据：两者都是设备安装工序的监理用表，用户明确指示「就用现有的检查记录表」。
    "设备安装记录": "设备安装检查记录",
}

# ---- 表种判定：按表名的表种词归到对应国标骨架 ----
# 顺序即优先级；前面的更具体，先命中先用。只认表种词，不猜业务内容。
_KIND_RULES = [
    # (表种, 关键词)
    ('conceal', ('隐蔽', '封闭前检查', '封闭记录')),
    ('test', ('试验', '测试', '调试', '校验', '标定', '化验', '检测')),
    ('check', ('检查', '检验', '安装', '验收', '试运转', '找正', '找平',
               '复测', '测量', '探伤', '清扫')),
    ('sign', ('签证', '洽商', '报审', '报验', '交接', '移交', '通知单',
              '报告', '申请', '审批', '会签', '交底', '纪要', '台账',
              '清单', '记录表')),
]

GB_FONT_TITLE = ("方正小标宋_GBK", "黑体")
GB_FONT_BODY = ("方正书宋_GBK", "宋体")

# 表头来源标注 —— 写进文档正文，人工复核时一眼可辨
GB_SOURCE_NOTE = "（专用表未提供，本表按国标通用格式生成）"

# ---- 各表种的国标通用条款 ----
# 只列通用条款；不写具体设备公差数值（那属于设计文件/专用标准，不能臆造）。
_KIND_ITEMS = {
    'check': [
        ("外观质量", [
            "设备外观无锈蚀、变形、磕碰损伤，油漆涂层完好，无掉漆、气泡、流痕、刮痕",
            "铭牌清晰完整，型号、规格与设计文件一致",
            "焊缝外观均匀，无裂纹、未熔合、夹渣、气孔等缺陷",
            "各零（部）件表面清洁，无油污、无杂物",
        ]),
        ("安装位置与几何尺寸", [
            "设备中心线、标高、方位与设计图纸一致",
            "设备安装的水平度、垂直度符合设计文件或设备技术文件规定",
            "地脚螺栓规格、数量、紧固方式符合设计文件，螺栓露出螺母长度均匀",
            "垫铁组布置、接触面积、层数符合规范要求",
        ]),
        ("连接与紧固", [
            "法兰连接面平整，垫片规格、材质符合设计文件，螺栓紧固均匀",
            "螺纹连接紧固可靠，无松动，外露螺纹长度符合要求",
            "联轴器对中偏差符合设备技术文件规定",
            "支吊架安装牢固，间距、型式符合设计文件",
        ]),
        ("附属与防护", [
            "设备接地、防静电连接可靠，接地标识清晰",
            "隔热、防腐层施工完好，无破损、空鼓",
            "随机附件、备件、专用工具齐全，交接记录完整",
        ]),
    ],
    'conceal': [
        ("隐蔽部位", [
            "隐蔽部位与设计图纸一致，几何尺寸符合设计要求",
            "预埋件位置准确、固定牢靠，标高符合设计",
            "隐蔽前已完成规定的检验（试验）且结论合格",
        ]),
        ("隐蔽内容", [
            "基层处理、防腐/隔热做法符合设计文件与规范要求",
            "接头、接口处理符合工艺文件，无渗漏隐患",
            "回填/封闭材料规格、材质符合设计文件",
            "隐蔽部位无遗留杂物、无积水",
        ]),
        ("影像与资料", [
            "隐蔽前影像资料齐全，能反映实际隐蔽状态",
            "相关检验记录、材质证明齐全并与实物对应",
        ]),
    ],
    'test': [
        ("试验条件", [
            "试验介质、环境温度、环境条件符合设计文件与规范要求",
            "试验用仪表、量具均在检定有效期内，精度满足要求",
            "试验方案已报审，安全措施已落实",
        ]),
        ("试验项目与结果", [
            "外观检查合格，无渗漏、无异常变形",
            "压力/绝缘/强度等主控指标满足设计文件规定值",
            "各项功能动作正确，信号、联锁响应符合设计要求",
            "试验过程中出现的异常已处理并复验合格",
        ]),
        ("试验后状态", [
            "试验后设备状态恢复正常，无遗留介质、无遗留工装",
            "试验数据记录完整，结论明确",
        ]),
    ],
    'sign': [
        ("事项", [
            "事项名称与内容：",
            "发生部位 / 涉及设备：",
            "发生原因与依据：",
        ]),
        ("处理意见", [
            "承包单位意见：",
            "监理单位意见：",
            "建设单位意见：",
        ]),
        ("费用与工期影响", [
            "费用影响：",
            "工期影响：",
        ]),
    ],
    'generic': [
        ("记录事项", [
            "事项名称：",
            "涉及部位 / 设备：",
            "依据文件：",
        ]),
        ("记录内容", [
            "主要内容：",
            "检查 / 实施情况：",
            "发现问题及处理：",
        ]),
    ],
}

# 各表种的明细列头（序号 / 项目 / 情况 / 结果）——签认类不打「检查结果」，改「签认」
_KIND_COLS = {
    'check': ("序号", "检查项目", "检查情况", "检查结果"),
    'conceal': ("序号", "隐蔽内容", "检查情况", "检查结论"),
    'test': ("序号", "试验项目", "标准要求", "试验结果"),
    'sign': ("序号", "事项 / 内容", "说明", "签认"),
    'generic': ("序号", "记录事项", "内容说明", "备注"),
}

_KIND_TITLE_NOTE = {
    'check': "检查项目",
    'conceal': "隐蔽内容",
    'test': "试验项目",
    'sign': "签认事项",
    'generic': "记录事项",
}


def alias_category(name: str) -> Optional[str]:
    """按别名表把登记表表名映射到内置模板类别（无别名返回 None）。

    先整名精确匹配，再退一步做规范化匹配（去空格、去「（一）」这类注记）——
    登记表里常见「设备安装记录（一）」「设备安装记录 (1)」这类写法。
    """
    n = (name or "").strip()
    if not n:
        return None
    if n in NAME_ALIAS:
        return NAME_ALIAS[n]
    _norm = n.replace(" ", "").replace("　", "")
    for sep in ("（", "("):
        _norm = _norm.split(sep)[0]
    if _norm in NAME_ALIAS:
        return NAME_ALIAS[_norm]
    return None


def alias_note(name: str) -> str:
    """别名对应的说明文字（写进待办清单，让用户知道为什么用的是这张表）。"""
    cat = alias_category(name)
    if not cat:
        return ""
    return (f"「{name}」复用现有模板「{cat}」"
            f"（按你的决定：没提供模板时用现有检查记录表）")


def form_kind(name: str) -> str:
    """按表名判表种（check / conceal / test / sign / generic）。

    只认表种词，不猜业务内容。判不出就返回 generic —— 出一张中性的
    「记录事项」表，**绝不硬套设备检查条款**（那是把表出错，比不出更糟）。
    """
    n = (name or "").strip()
    if not n:
        return 'generic'
    for kind, words in _KIND_RULES:
        if any(w in n for w in words):
            return kind
    return 'generic'


def items_for_kind(kind: str) -> List[tuple]:
    return _KIND_ITEMS.get(kind) or _KIND_ITEMS['generic']


def _set_run_font(run, fonts, size_pt=None, bold=None):
    """设置中英文字体。eastAsia 必须单独设，否则中文回落成默认字体。"""
    from docx.oxml.ns import qn
    from docx.shared import Pt
    run.font.name = fonts[0]
    rfonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    for attr in ("w:eastAsia", "w:ascii", "w:hAnsi"):
        rfonts.set(qn(attr), fonts[0])
    if size_pt:
        run.font.size = Pt(size_pt)
    if bold is not None:
        run.bold = bold


def _set_cell(table, r, c, text, bold=False, center=False, size=9):
    """写单元格文字。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    cell = table.cell(r, c)
    cell.text = ""
    p = cell.paragraphs[0]
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text or "")
    _set_run_font(run, GB_FONT_BODY, size, bold=bold)


def _add_row(table):
    """追加一行，返回该行索引。"""
    table.add_row()
    return len(table.rows) - 1


def _span(table, r, c_start, c_end):
    """把第 r 行 c_start..c_end 横向合并成一个单元格。"""
    try:
        a = table.cell(r, c_start)
        b = table.cell(r, c_end)
        if a._tc is not b._tc:
            a.merge(b)
    except Exception:  # noqa: BLE001
        pass


def build_gb_form(out_path: str,
                  form_name: str,
                  form_no: str = "",
                  unit_works: str = "",
                  sub_works: str = "",
                  workshop: str = "",
                  devices: Optional[List[Dict]] = None,
                  category: str = "",
                  standard: str = "",
                  kind: str = "") -> Dict:
    """按国标表格式生成一份可打印的表（无模板时的兜底）。

    版式沿用内置模板的国标骨架：标题（小标宋 20pt 居中）→ 表号与来源标注
    → 表头（单位工程 / 分部分项 / 设备名称 / 规格型号 / 设备位号 / 日期）
    → 明细（按表种分列头）→ 签字栏 → 说明。

    **一台设备一份表**（签认类无设备数据时出一份，不按设备复制）；
    设备台账为空时出一份空白表交人工填写（不编造设备名）。
    返回结构与 render_supervision_doc 兼容，调用方可直接复用。
    """
    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn

    kind = kind or form_kind(form_name or category)
    cols = _KIND_COLS.get(kind, _KIND_COLS['generic'])
    items = items_for_kind(kind)

    devices = devices or []
    # 检查/隐蔽/试验类：一台设备一份；签认/通用类：不按设备复制
    if kind in ('sign', 'generic'):
        rows_dev = [devices[0] if devices else None]
    else:
        rows_dev = devices if devices else [None]

    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.left_margin = Cm(2.0)
    sec.right_margin = Cm(2.0)
    sec.top_margin = Cm(1.6)
    sec.bottom_margin = Cm(1.6)

    style = doc.styles["Normal"]
    style.font.name = GB_FONT_BODY[0]
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), GB_FONT_BODY[0])

    _sub = "-".join(x for x in (sub_works, workshop) if x)

    for idx, dev in enumerate(rows_dev):
        if idx:
            doc.add_page_break()

        # 标题
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_run_font(p.add_run(form_name), GB_FONT_TITLE, 20)

        # 表号 + 来源标注
        p2 = doc.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _no = f"表号：{form_no}" if form_no else "表号：＿＿＿＿"
        _set_run_font(p2.add_run(f"{_no}　　{GB_SOURCE_NOTE}"), GB_FONT_BODY, 9)

        t = doc.add_table(rows=0, cols=4)
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER

        # 表头：标签占第 0 列，值横跨 1..3 列
        for label, value in (
            ("单位工程名称", unit_works or ""),
            ("分部分项工程名称", _sub),
            ("设备名称", (dev or {}).get("name", "") if dev else ""),
            ("设备位号", (dev or {}).get("tag", "") if dev else ""),
        ):
            r = _add_row(t)
            _span(t, r, 1, 3)
            _set_cell(t, r, 0, label, bold=True)
            _set_cell(t, r, 1, value)

        # 规格型号 / 日期
        r = _add_row(t)
        _set_cell(t, r, 0, "规格型号", bold=True)
        _set_cell(t, r, 1, (dev or {}).get("model", "") if dev else "")
        _set_cell(t, r, 2, "日期", bold=True)
        _set_cell(t, r, 3, "")

        # 明细表头（按表种换列名）
        r = _add_row(t)
        for c, h in enumerate(cols):
            _set_cell(t, r, c, h, bold=True, center=True)

        # 明细（按表种换条款）
        _seq = 0
        for group, group_items in items:
            r = _add_row(t)
            _span(t, r, 0, 3)
            _set_cell(t, r, 0, group, bold=True)
            for item in group_items:
                _seq += 1
                r = _add_row(t)
                _set_cell(t, r, 0, str(_seq), center=True)
                _set_cell(t, r, 1, item)
                _set_cell(t, r, 2, "")
                _set_cell(t, r, 3, "")

        # 结论 + 签字
        r = _add_row(t)
        _span(t, r, 1, 3)
        _set_cell(t, r, 0, "检查结论" if kind != 'sign' else "签认结论", bold=True)
        _set_cell(t, r, 1, "")

        r = _add_row(t)
        _span(t, r, 1, 3)
        _set_cell(t, r, 0, "签字", bold=True)
        _set_cell(t, r, 1, "施工班组：　　　　专业工程师：　　　　监理工程师：　　　　日期：")

        _tn = _KIND_TITLE_NOTE.get(kind, '记录事项')
        _n = (f"说明：本表按国标通用格式生成，「{_tn}」按该类记录的通用条款列出；"
              f"具体数值与专业条款按设计文件、设备技术文件及适用标准填写。")
        if standard:
            _n += f"依据：{standard}。"
        pn = doc.add_paragraph()
        _set_run_font(pn.add_run(_n), GB_FONT_BODY, 9)

    doc.save(out_path)
    return {"ok": True, "path": out_path, "device_count": len(devices),
            "form_name": form_name, "form_no": form_no, "kind": kind,
            "check_item_count": sum(len(x) for _, x in items)}
