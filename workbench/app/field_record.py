# 繁工AI 本地解析工作台 - 现场记录快速生成（v0.1.33）
# 目的：手机端上传照片/OCR/语音/文字后，自动识别记录类型（开箱验收/隐蔽验收/施工日志等），
#       提取关键字段预填模板，列出缺失字段，补充后生成 Word 工程资料。
#
# 口径（用户锁定）：
#   - 自动识别类型，支持手动修改
#   - 资料不全时提醒缺少哪些关键内容，按项补充
#   - 允许延后补充，不影响新内容输入
#   - 按照模板生成，优先 Word

import re
import datetime

from . import docgen

# 记录类型识别关键词（优先级从高到低）
_TYPE_KEYWORDS = [
    ("开箱验收记录", ["开箱", "开箱验收", "开箱记录", "拆箱", "到货验收", "装箱单核对"]),
    ("隐蔽工程验收记录", ["隐蔽", "隐蔽工程", "隐蔽验收", "隐蔽记录", "覆土前", "封闭前"]),
    ("施工日志", ["施工日志", "日志", "今日施工", "当日工作", "天气", "出勤", "施工日记"]),
    ("技术交底", ["交底", "技术交底", "安全交底", "交底记录"]),
    ("货损报告", ["货损", "损坏", "破损", "索赔", "运输损坏", "到货损坏"]),
    ("设计变更", ["变更", "设计变更", "工程变更", "变更单", "洽商"]),
    ("吊装方案", ["吊装", "吊车", "吊装方案", "起重"]),
    ("施工方案", ["施工方案", "施工组织", "施工工艺", "施工方法"]),
    ("施工计划", ["施工计划", "进度计划", "工期", "计划安排"]),
    ("竣工资料", ["竣工", "交工", "验收移交", "竣工资料"]),
]

# 字段提取正则
_TAG_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,3}-\d{1,6}(?:[/-][A-Z]{0,3}\d{0,4})?)(?![A-Za-z0-9])")
_WORKSHOP_RE = re.compile(r"(\d{1,2}|[一二三四五六七八九十]+)\s*号?\s*车间")
_DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
_DATE_RE2 = re.compile(r"(\d{1,2})月(\d{1,2})日")
_PERSON_RE = re.compile(r"(?:验收人|检查人|记录人|交底人|编制人|施工员|负责人|班长)[:：]?\s*([\u4e00-\u9fa5]{2,4})")
_RESULT_RE = re.compile(r"(?:验收结果|检查结果|结果|结论|评定)[:：]?\s*(合格|不合格|符合要求|不符合|通过|未通过|良好|一般)")
_BOX_RE = re.compile(r"(?:箱单号|箱号|装箱单号)[:：]?\s*([A-Za-z0-9\-_]+)")
_DEVICE_NAME_RE = re.compile(r"(?:设备名称|设备名|名称)[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9（）()\- ]{2,30})")
_QTY_RE = re.compile(r"(?:数量|台数|件数)[:：]?\s*(\d+)")
_CONTENT_RE = re.compile(r"(?:施工内容|工作内容|当日工作|作业内容)[:：]?\s*(.{10,200})")
_WEATHER_RE = re.compile(r"(晴|阴|雨|雪|多云|小雨|大雨|雷阵雨)(?:\s|$|，|。)")
_TEMP_RE = re.compile(r"(-?\d{1,2})\s*[℃°]")


def detect_type(text: str) -> tuple:
    """从文本识别记录类型。返回 (doc_type, confidence, matched_keywords)。"""
    if not text:
        return ("", 0.0, [])
    text = text.strip()
    scores = []
    for doc_type, keywords in _TYPE_KEYWORDS:
        matched = [kw for kw in keywords if kw in text]
        if matched:
            # 关键词越多置信度越高，长文本中关键词占比也考虑
            score = min(0.95, 0.4 + 0.15 * len(matched) + 0.05 * sum(len(kw) for kw in matched) / max(len(text), 1))
            scores.append((doc_type, round(score, 2), matched))
    if not scores:
        return ("", 0.0, [])
    scores.sort(key=lambda x: -x[1])
    return scores[0]


def extract_fields(text: str, doc_type: str = "") -> dict:
    """从现场文本提取关键字段。返回 {字段: 值}。"""
    fields = {}
    if not text:
        return fields

    # 位号
    tags = _TAG_RE.findall(text)
    if tags:
        fields["位号"] = tags[0]
        if len(tags) > 1:
            fields["_all_tags"] = tags

    # 车间
    m = _WORKSHOP_RE.search(text)
    if m:
        cn = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
        num = cn.get(m.group(1), m.group(1))
        fields["车间"] = f"{num}号车间"

    # 日期
    m = _DATE_RE.search(text)
    if m:
        fields["日期"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    else:
        m = _DATE_RE2.search(text)
        if m:
            year = datetime.datetime.now().year
            fields["日期"] = f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    # 人员
    for m in _PERSON_RE.finditer(text):
        role = m.group(0)[:4]
        name = m.group(1)
        if "验收" in role:
            fields["验收人"] = name
        elif "记录" in role:
            fields["记录人"] = name
        elif "交底" in role:
            fields["交底人"] = name
        elif "编制" in role:
            fields["编制人"] = name

    # 结果
    m = _RESULT_RE.search(text)
    if m:
        fields["验收结果"] = m.group(1)

    # 箱单号
    m = _BOX_RE.search(text)
    if m:
        fields["箱单号"] = m.group(1)

    # 设备名称
    m = _DEVICE_NAME_RE.search(text)
    if m:
        fields["设备名称"] = m.group(1).strip()

    # 数量
    m = _QTY_RE.search(text)
    if m:
        fields["数量"] = m.group(1)

    # 施工内容
    m = _CONTENT_RE.search(text)
    if m:
        fields["施工内容"] = m.group(1).strip()

    # 天气/温度（施工日志）
    m = _WEATHER_RE.search(text)
    if m:
        fields["天气"] = m.group(1)
    m = _TEMP_RE.search(text)
    if m:
        fields["温度"] = m.group(1) + "℃"

    return fields


def get_required_fields(doc_type: str) -> list:
    """获取某记录类型的必填字段。"""
    t = docgen.TYPES.get(doc_type)
    if not t:
        return []
    return list(t.get("required", []))


def analyze(text: str, ocr_text: str = "", transcript: str = "",
            metadata: dict = None) -> dict:
    """分析现场文本：识别类型 + 提取字段 + 列出缺失。
    text: 文字说明/note；ocr_text: 照片OCR结果；transcript: 语音转写；metadata: {project, uploader, ts, kind}
    返回 {doc_type, confidence, matched_keywords, data, missing, all_fields}。"""
    metadata = metadata or {}
    # 合并所有文本来源
    full_text = "\n".join(filter(None, [text, ocr_text, transcript]))
    if not full_text.strip():
        return {"doc_type": "", "confidence": 0.0, "matched_keywords": [],
                "data": {}, "missing": [], "all_fields": [],
                "message": "无文本内容，请输入文字说明或上传照片/语音"}

    # 识别类型
    doc_type, confidence, matched = detect_type(full_text)

    # 提取字段
    data = extract_fields(full_text, doc_type)

    # 元数据补充
    if metadata.get("uploader") and "记录人" not in data and "验收人" not in data:
        data["记录人"] = metadata["uploader"]
    if metadata.get("ts") and "日期" not in data:
        try:
            data["日期"] = metadata["ts"][:10]
        except Exception:  # noqa: BLE001
            pass
    if metadata.get("project"):
        data["项目名称"] = metadata["project"]

    # 缺失字段
    required = get_required_fields(doc_type) if doc_type else []
    missing = [k for k in required if not str(data.get(k, "")).strip()]

    return {
        "doc_type": doc_type,
        "confidence": confidence,
        "matched_keywords": matched,
        "data": data,
        "missing": missing,
        "all_fields": required,
        "ocr_preview": (ocr_text or "")[:200],
        "transcript_preview": (transcript or "")[:200],
    }


def generate(doc_type: str, data: dict) -> tuple:
    """生成现场记录 Word。返回 (bytes, missing)。"""
    if not doc_type or doc_type not in docgen.TYPES:
        raise ValueError(f"不支持的记录类型：{doc_type}")
    # 补充规范引用
    if "_std_citations" not in data:
        data["_std_citations"] = docgen.std_citations(doc_type)
    content, missing = docgen.fill_template(doc_type, data)
    return content, missing
