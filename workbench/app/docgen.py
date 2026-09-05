# 繁工AI 本地解析工作台 - 工程资料生成引擎（v0.1.7）
# 依据 v3.7 口径：内置方案类型 → 数据可自动从解析库预填 → 缺失字段列出待补充 → 生成 Word 下载
# 优先 Word（python-docx）；后续可扩展 PDF/Excel。签字由人工下载打印完成。

import datetime
import os

# 方案类型注册：名称 / 说明 / 必填字段（缺失时前端提示）/ 可选字段
TYPES = {
    "施工方案": {
        "label": "施工方案",
        "required": ["项目名称", "车间", "编制单位", "编制人", "施工内容", "施工日期"],
        "optional": ["施工单位", "审核人", "批准人", "施工工艺", "质量措施", "安全措施", "进度安排"],
        "default_text": {
            "编制依据": "1. 设计图纸及设计交底文件\n2. 现行国家及行业标准规范\n3. 设备技术文件及随机资料\n4. 现场施工条件调查结果",
            "质量保证措施": "1. 严格执行三检制（自检、互检、专检）\n2. 关键工序设质量控制点，报验合格后进入下道工序\n3. 施工人员持证上岗，特种作业人员证件齐全",
            "安全文明施工措施": "1. 进入现场正确佩戴劳动防护用品\n2. 用电设备执行一机一闸一漏保\n3. 现场材料定置摆放，工完场清",
        },
    },
    "吊装方案": {
        "label": "吊装方案",
        "required": ["项目名称", "车间", "编制单位", "编制人", "吊装日期"],
        "optional": ["施工单位", "审核人", "批准人", "吊装机械", "吊装安全措施"],
        "default_text": {
            "编制依据": "1. 设备安装图纸及技术文件\n2.《起重机械安全规程》GB/T 6067\n3.《建筑机械使用安全技术规程》JGJ 33\n4. 设备随机装箱单及发货资料",
            "吊装安全措施": "1. 吊装前办理吊装作业票，检查吊索具完好\n2. 明确指挥信号，专人指挥，无关人员撤离吊装区\n3. 六级及以上大风、雷雨等恶劣天气停止吊装\n4. 设备就位后立即找正固定，方可摘钩",
        },
    },
    "技术交底": {
        "label": "技术交底",
        "required": ["项目名称", "车间", "交底人", "交底日期", "交底内容"],
        "optional": ["被交底单位", "被交底人", "交底依据", "注意事项"],
        "default_text": {
            "交底依据": "施工图纸、施工方案、国家现行规范",
            "注意事项": "1. 作业前逐条学习交底内容并签字确认\n2. 发现与图纸不符时停止作业并及时上报\n3. 交底内容作为现场施工和检查验收依据",
        },
    },
    "开箱验收记录": {
        "label": "开箱验收记录",
        "required": ["项目名称", "车间", "箱单号", "验收人", "验收日期", "验收结果"],
        "optional": ["位号", "设备名称", "数量", "外观检查情况", "随机资料", "备注"],
        "default_text": {
            "验收依据": "设备装箱单、发货清单、采购合同及技术协议",
            "验收流程": "1. 核对箱体编号与装箱单一致\n2. 开箱后核对设备名称、型号、数量\n3. 检查外观有无锈蚀、变形、损坏\n4. 清点随机附件与资料",
        },
    },
    "隐蔽工程验收记录": {
        "label": "隐蔽工程验收记录",
        "required": ["项目名称", "车间", "隐蔽部位", "验收人", "验收日期", "验收结果"],
        "optional": ["施工单位", "监理单位", "隐蔽内容", "检查情况", "影像资料编号"],
        "default_text": {
            "验收依据": "施工图纸、施工方案、现行验收规范",
            "检查情况": "1. 隐蔽内容与图纸相符，几何尺寸符合要求\n2. 预埋件位置准确，固定牢靠\n3. 隐蔽前影像资料留存齐全",
        },
    },
}


def list_types() -> list:
    return [{"key": k, "label": v["label"], "required": v["required"],
             "optional": v["optional"]} for k, v in TYPES.items()]


def fill_template(doc_type: str, data: dict) -> bytes:
    """按模板生成 .docx 并返回字节流。缺字段用『待补充』占位并标注。"""
    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    t = TYPES[doc_type]
    doc = Document()
    # 全局中文字体
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(12)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    def add_title(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        r.bold = True
        r.font.size = Pt(18)
        r.font.name = "黑体"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

    def add_h(text):
        p = doc.add_paragraph()
        r = p.add_run(text)
        r.bold = True
        r.font.size = Pt(14)
        r.font.name = "黑体"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

    def add_kv(key, value):
        v = str(value or "").strip()
        if not v:
            v = "【待补充】"
        p = doc.add_paragraph()
        r = p.add_run(f"{key}：{v}")
        if v == "【待补充】":
            r.font.color.rgb = __import__("docx.shared", fromlist=["RGBColor"]).RGBColor(0xC0, 0x39, 0x2B)
        return v

    missing = []
    add_title(f"{doc_type}")
    add_h("一、基本信息")
    for k in t["required"]:
        v = data.get(k, "")
        if not str(v or "").strip():
            missing.append(k)
        add_kv(k, v)
    for k in t["optional"]:
        if data.get(k):
            add_kv(k, data[k])

    # 设备清单（吊装方案/开箱验收自动带出）
    devices = data.get("_devices") or []
    if devices:
        add_h("二、涉及设备清单")
        tbl = doc.add_table(rows=1, cols=4)
        tbl.style = "Table Grid"
        hdr = tbl.rows[0].cells
        for i, h in enumerate(["位号", "设备名称", "数量", "备注"]):
            hdr[i].text = h
        for dv in devices[:60]:
            row = tbl.add_row().cells
            row[0].text = str(dv.get("tag", ""))
            row[1].text = str(dv.get("name", "见台账"))
            row[2].text = str(dv.get("count", "1"))
            row[3].text = ""
    else:
        add_h("二、相关设备")
        add_kv("设备清单", data.get("_devices_hint", "可到关联图谱页选择车间自动带出"))

    # 默认章节文本
    section_no = 2 if (devices or doc_type in ("吊装方案", "开箱验收记录", "隐蔽工程验收记录")) else 2
    if "编制依据" in t["default_text"]:
        add_h(f"{'三' if section_no == 2 else '二'}、编制依据")
        doc.add_paragraph(t["default_text"]["编制依据"])
    for k, default in t["default_text"].items():
        if k == "编制依据":
            continue
        add_h(f"四、{k}")
        doc.add_paragraph(default)

    add_h("五、签字栏")
    tbl = doc.add_table(rows=1, cols=4)
    tbl.style = "Table Grid"
    for i, h in enumerate(["编制", "审核", "批准", "日期"]):
        tbl.rows[0].cells[i].text = h
    add_paragraph = doc.add_paragraph
    p = add_paragraph()
    p.add_run(f"\n生成工具：繁工AI 本地解析工作台 v0.1.7 · 生成时间 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")

    import io
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), missing
