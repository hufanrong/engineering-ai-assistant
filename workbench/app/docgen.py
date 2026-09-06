# 繁工AI 本地解析工作台 - 工程资料生成引擎（v0.1.7）
# 依据 v3.7 口径：内置方案类型 → 数据可自动从解析库预填 → 缺失字段列出待补充 → 生成 Word 下载
# 优先 Word（python-docx）；后续可扩展 PDF/Excel。签字由人工下载打印完成。

import datetime
import json
import os

from . import config

# 方案类型注册：名称 / 说明 / 必填字段（缺失时前端提示）/ 可选字段
TYPES = {
    "施工方案": {
        "label": "施工方案",
        "required": ["项目名称", "车间", "编制单位", "编制人", "施工内容", "施工日期"],
        "optional": ["施工单位", "审核人", "批准人", "施工工艺", "质量措施", "安全措施", "进度安排", "涉及设备"],
        "construction_params": ["施工内容", "施工工艺", "涉及设备"],
        "default_text": {
            "编制依据": "1. 设计图纸及设计交底文件\n2. 现行国家及行业标准规范\n3. 设备技术文件及随机资料\n4. 现场施工条件调查结果",
            "质量保证措施": "1. 严格执行三检制（自检、互检、专检）\n2. 关键工序设质量控制点，报验合格后进入下道工序\n3. 施工人员持证上岗，特种作业人员证件齐全",
            "安全文明施工措施": "1. 进入现场正确佩戴劳动防护用品\n2. 用电设备执行一机一闸一漏保\n3. 现场材料定置摆放，工完场清",
        },
    },
    "吊装方案": {
        "label": "吊装方案",
        "required": ["项目名称", "车间", "编制单位", "编制人", "吊装日期", "吊装设备名称", "设备重量"],
        "optional": ["施工单位", "审核人", "批准人", "吊装机械", "吊装半径", "吊装高度", "吊车站位", "吊索具", "吊装安全措施"],
        "lifting_params": ["吊装设备名称", "设备重量", "吊装半径", "吊装高度", "吊车型号", "吊车站位", "吊索具"],
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
    # ---- v0.1.12 新增：工程资料深度生成（按项目进度、缺项待办） ----
    "施工计划": {
        "label": "施工计划",
        "required": ["项目名称", "车间", "编制单位", "编制人", "计划工期"],
        "optional": ["施工单位", "审核人", "开工日期", "竣工日期", "进度安排", "资源配置", "关键节点"],
        "default_text": {
            "编制依据": "1. 施工图纸及工程量清单\n2. 合同约定的工期要求\n3. 现行施工及验收规范",
            "进度安排": "1. 施工准备阶段（场地、材料、机具、人员）\n2. 主体施工阶段（按车间/工序流水作业）\n3. 收尾验收阶段（自检、整改、报验）",
        },
    },
    "施工日志": {
        "label": "施工日志",
        "required": ["项目名称", "车间", "记录人", "记录日期", "当日工作内容"],
        "optional": ["天气", "温度", "到场人员", "进场材料", "机械使用", "安全质量情况", "问题及处理"],
        "default_text": {
            "记录要求": "1. 逐日记录，不得补记、漏记\n2. 与当日施工部位、工序对应\n3. 问题与处理结果闭环记录",
        },
    },
    "设计变更": {
        "label": "设计变更",
        "required": ["项目名称", "车间", "变更编号", "变更内容", "提出人"],
        "optional": ["原设计图号", "变更图号", "变更原因", "涉及设备", "工程量变化", "审批人", "日期"],
        "default_text": {
            "变更依据": "1. 现场与设计不符情况\n2. 业主/设计/监理会签意见",
            "处理要求": "1. 变更单与原图纸一同归档\n2. 变更内容落实到相关专业图纸与施工\n3. 变更工程量作为结算依据",
        },
    },
    "货损报告": {
        "label": "货损报告",
        "required": ["项目名称", "车间", "设备位号", "损失情况", "报告人", "报告日期"],
        "optional": ["箱单号", "数量", "损失程度", "影像资料编号", "处理意见", "责任方"],
        "default_text": {
            "报告依据": "开箱/到货验收记录、随货装箱单、运输单据",
            "处理流程": "1. 现场拍照留存，保护受损设备\n2. 会同运输方/厂家确认损失程度\n3. 出具报告并提交索赔或补发申请",
        },
    },
    "竣工资料": {
        "label": "竣工资料",
        "required": ["项目名称", "车间", "编制单位", "编制人", "竣工日期"],
        "optional": ["施工单位", "监理单位", "隐蔽工程资料编号", "验收记录编号", "交工范围", "遗留问题及处理"],
        "default_text": {
            "编制依据": "1. 竣工图及变更文件\n2. 各分项验收记录\n3. 设备调试及试运行记录",
            "资料构成": "1. 竣工图（含变更反映）\n2. 隐蔽工程验收记录\n3. 设备开箱/安装/调试记录\n4. 质量验收与移交清单",
        },
    },
}


def list_types() -> list:
    return [{"key": k, "label": v["label"], "required": v["required"],
             "optional": v["optional"]} for k, v in TYPES.items()]


def std_citations(doc_type: str, limit: int = 3) -> list:
    """从平台规范库检索与当前资料类型相关的规范正文（非仅名称），供『编制依据』引用。v0.1.17"""
    try:
        from . import platform_store
        idx = platform_store.list_items().get("items", [])
        hits = [it for it in idx if it.get("std_no") and it.get("status") in ("现行", "待核验")]
        if not hits:
            return []
        # 用模板名关键词粗筛（检索不到就取前几条现行规范）
        kw = (doc_type or "").replace("记录", "").replace("资料", "")
        scored = []
        for it in hits:
            name = str(it.get("std_name", ""))
            score = 0
            for ch in kw:
                if ch and ch in name:
                    score += 1
            scored.append((score, it))
        scored.sort(key=lambda x: -x[0])
        out = []
        for score, it in scored[:limit]:
            text = ""
            try:
                cache = os.path.join(platform_store.CACHE_DIR, f"{it['sha256']}.json")
                if os.path.exists(cache):
                    with open(cache, encoding="utf-8") as f:
                        text = str(json.load(f).get("text", ""))[:600].strip()
            except Exception:  # noqa: BLE001
                text = ""
            if not text:
                text = "（正文已入库，可在平台库页检索全文）"
            out.append({"std_no": it["std_no"], "std_name": it.get("std_name", ""),
                        "status": it.get("status", ""), "snippet": text[:300]})
        return out
    except Exception:  # noqa: BLE001
        return []


def prefill_from_db(doc_type: str, workshop: str = "") -> dict:
    """v0.1.30：从解析库深度预填资料数据。
    来源：relations layout（车间设备）→ device_workshop（设备车间归属）→
          vector_store（设备参数/重量/型号检索）→ platform_store（规范正文引用）。
    返回 {data: {...}, missing: [...], devices: [...], citations: [...]}。"""
    data = {}
    missing = []
    t = TYPES.get(doc_type)
    if not t:
        return {"data": data, "missing": [], "devices": [], "citations": []}

    # 项目名称（从配置或第一个车间推断）
    data["项目名称"] = getattr(config, "PROJECT_NAME", "") or "紫金矿业工程项目"

    # 车间
    if workshop:
        data["车间"] = workshop

    # 从 relations 取车间设备
    devices = []
    try:
        from . import relations
        g = relations.load_relations()
        all_devs = g.get("devices", [])
        if workshop:
            ws_devs = [d for d in all_devs if workshop in d.get("workshops", [])]
        else:
            ws_devs = all_devs
        devices = [{"tag": d["tag"], "name": "见台账", "count": 1,
                    "workshops": d.get("workshops", [])} for d in ws_devs[:60]]
    except Exception:  # noqa: BLE001
        pass

    # 设备级车间归属补充（v0.1.29）
    try:
        from . import device_workshop
        for dv in devices:
            dw = device_workshop.get_workshop(dv["tag"])
            if dw and dw not in dv["workshops"]:
                dv["workshops"].append(dw)
    except Exception:  # noqa: BLE001
        pass

    data["_devices"] = devices

    # 吊装方案专项：从设备台账/向量库检索重量等参数
    if doc_type == "吊装方案" and devices:
        first_dev = devices[0]
        data["吊装设备名称"] = first_dev["tag"] + "（详见设备清单）"
        # 尝试从向量库检索设备重量
        try:
            from . import vector_store
            store = vector_store.VectorStore()
            hits = store.search(f"{first_dev['tag']} 重量 设备参数", top_k=3)
            for h in hits:
                txt = str(h.get("text", ""))
                import re as _re
                m = _re.search(r"(重量|净重|毛重)\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(t|吨|kg|公斤)", txt, _re.I)
                if m:
                    w = float(m.group(2))
                    unit = m.group(3).lower()
                    if unit in ("kg", "公斤"):
                        w = w / 1000.0
                    data["设备重量"] = f"{w} t"
                    break
        except Exception:  # noqa: BLE001
            pass
        if "设备重量" not in data:
            missing.append("设备重量（需从设备铭牌/台账补充）")
        # 吊装参数默认建议
        if "吊装半径" not in data:
            missing.append("吊装半径（需现场测量）")
        if "吊装高度" not in data:
            missing.append("吊装高度（需根据设备安装高度确定）")
        if "吊车型号" not in data:
            data["吊车型号"] = "根据设备重量与吊装半径选择（建议25t汽车吊，具体以吊装计算为准）"
        if "吊索具" not in data:
            data["吊索具"] = "钢丝绳/吊带（根据设备重量选择，安全系数≥6）"

    # 施工方案专项
    if doc_type == "施工方案":
        if devices:
            data["涉及设备"] = "、".join(d["tag"] for d in devices[:10]) + (f" 等{len(devices)}台" if len(devices) > 10 else "")
        if "施工内容" not in data:
            missing.append("施工内容（需明确具体施工范围与工序）")

    # 规范正文引用（v0.1.17 增强：只取现行规范）
    citations = std_citations(doc_type, limit=4)
    data["_std_citations"] = citations

    # 检查必填字段缺失
    for k in t["required"]:
        if not str(data.get(k, "")).strip() and k not in missing:
            missing.append(k)

    return {"data": data, "missing": missing, "devices": devices, "citations": citations}


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

    # 吊装方案专项参数（v0.1.30）
    if doc_type == "吊装方案":
        add_h("二、吊装参数")
        lifting_keys = ["吊装设备名称", "设备重量", "吊装半径", "吊装高度", "吊车型号", "吊车站位", "吊索具"]
        for k in lifting_keys:
            if data.get(k) or k in t["required"]:
                add_kv(k, data.get(k, ""))
        # 吊装计算提示
        p = doc.add_paragraph()
        r = p.add_run("注：吊装半径、吊装高度需现场实测后填入；吊车型号应根据吊装重量与半径经吊装计算确定，本方案仅为建议。")
        r.font.size = Pt(10)
        r.font.color.rgb = __import__("docx.shared", fromlist=["RGBColor"]).RGBColor(0x66, 0x66, 0x66)

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
        cites = data.get("_std_citations") or std_citations(doc_type)
        if cites:
            doc.add_paragraph(t["default_text"]["编制依据"])
            doc.add_paragraph("本资料编制所引用的现行规范条款如下：")
            for ci in cites:
                p = doc.add_paragraph()
                r = p.add_run(f"▶ {ci['std_no']}《{ci['std_name']}》（{ci['status']}）：{ci['snippet']}")
                r.font.size = Pt(11)
        else:
            doc.add_paragraph(t["default_text"]["编制依据"])
            p = doc.add_paragraph("（平台库尚未收录相关现行规范正文，请人工补充编制依据）")
            p.runs[0].font.color.rgb = __import__("docx.shared", fromlist=["RGBColor"]).RGBColor(0xC0, 0x39, 0x2B)
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
    p.add_run(f"\n生成工具：繁工AI 本地解析工作台 v0.1.30 · 生成时间 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")

    import io
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), missing
