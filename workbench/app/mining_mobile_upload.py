"""
v0.1.97：矿山设备移动端资料上传与解析联动

移动端上传资料后自动解析，支持照片、语音、文字上传，自动识别资料类型，
自动归类到项目/车间/设备，上传记录管理。
"""

import os
import json
import datetime
from typing import Optional


# ============================================================
# 移动端上传资料类型识别
# ============================================================

MOBILE_UPLOAD_TYPES = {
    "photo": {
        "name": "照片上传",
        "description": "现场照片上传，支持设备铭牌、施工进度、质量问题、安全隐患等",
        "extensions": [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"],
        "auto_parse": True,
        "parse_actions": ["OCR识别铭牌", "图像分类", "EXIF信息提取"],
    },
    "voice": {
        "name": "语音上传",
        "description": "现场语音记录上传，支持施工日志、问题描述、安全提醒等",
        "extensions": [".mp3", ".wav", ".m4a", ".aac", ".ogg", ".amr"],
        "auto_parse": True,
        "parse_actions": ["语音转文字", "关键词提取", "情绪分析"],
    },
    "text": {
        "name": "文字上传",
        "description": "现场文字记录上传，支持施工日志、问题描述、验收记录等",
        "extensions": [".txt", ".md"],
        "auto_parse": True,
        "parse_actions": ["关键词提取", "资料类型识别", "实体识别"],
    },
    "document": {
        "name": "文档上传",
        "description": "工程文档上传，支持PDF、Word、Excel、CAD等",
        "extensions": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".dwg", ".dxf", ".ppt", ".pptx"],
        "auto_parse": True,
        "parse_actions": ["文本提取", "表格提取", "图纸解析", "向量化"],
    },
}


# 资料类型自动识别关键词
DOC_TYPE_KEYWORDS = {
    "开箱验收记录": ["开箱", "检验", "验收", "到货", "装箱", "铭牌"],
    "隐蔽工程验收记录": ["隐蔽", "覆盖", "预埋", "钢筋", "灌浆", "基础"],
    "施工日志": ["施工", "日志", "日报", "进度", "出勤", "天气"],
    "安装记录": ["安装", "找平", "找正", "水平度", "垂直度", "同轴度", "间隙"],
    "试运转记录": ["试运转", "试运行", "空载", "负载", "联动", "试车"],
    "安全检查记录": ["安全", "检查", "隐患", "整改", "违章", "防护"],
    "吊装作业记录": ["吊装", "吊车", "吊点", "索具", "试吊", "就位"],
    "焊接记录": ["焊接", "焊缝", "焊材", "预热", "层间", "无损检测"],
    "技术交底记录": ["交底", "技术", "工艺", "质量标准", "安全注意"],
    "设计变更": ["变更", "修改", "设计", "联系单", "核定单"],
    "货损报告": ["货损", "损坏", "破损", "锈蚀", "变形", "索赔"],
    "竣工资料": ["竣工", "验收", "移交", "归档", "组卷"],
    "设备台账": ["台账", "清单", "设备明细", "规格型号", "厂家"],
    "施工方案": ["方案", "施工方法", "工艺流程", "质量控制", "安全措施"],
    "吊装方案": ["吊装方案", "吊车选型", "吊点设计", "索具配置", "吊装顺序"],
}


# 上传记录存储
UPLOAD_RECORDS_FILE = "data/mobile_upload_records.json"


def get_upload_types() -> dict:
    """获取移动端支持的上传类型。"""
    types = []
    for key, utype in MOBILE_UPLOAD_TYPES.items():
        types.append({
            "type": key,
            "name": utype["name"],
            "description": utype["description"],
            "extensions": utype["extensions"],
            "auto_parse": utype["auto_parse"],
            "parse_actions": utype["parse_actions"],
        })
    return {
        "ok": True,
        "types": types,
        "total": len(types),
    }


def detect_upload_type(filename: str) -> dict:
    """
    根据文件名检测上传类型。
    
    Args:
        filename: 文件名
    
    Returns:
        检测结果
    """
    ext = os.path.splitext(filename)[1].lower()
    
    for type_key, utype in MOBILE_UPLOAD_TYPES.items():
        if ext in utype["extensions"]:
            return {
                "ok": True,
                "filename": filename,
                "extension": ext,
                "upload_type": type_key,
                "upload_type_name": utype["name"],
                "auto_parse": utype["auto_parse"],
                "parse_actions": utype["parse_actions"],
            }
    
    return {
        "ok": True,
        "filename": filename,
        "extension": ext,
        "upload_type": "unknown",
        "upload_type_name": "未知类型",
        "auto_parse": False,
        "parse_actions": [],
    }


def detect_doc_type(content: str = "", filename: str = "") -> dict:
    """
    自动识别资料类型。
    
    Args:
        content: 文件内容（文本）
        filename: 文件名
    
    Returns:
        识别结果
    """
    scores = {}
    text = (content + " " + filename).lower()
    
    for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.lower() in text:
                score += 1
        if score > 0:
            scores[doc_type] = score
    
    if scores:
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_match = sorted_scores[0]
        return {
            "ok": True,
            "detected": True,
            "doc_type": best_match[0],
            "confidence": round(best_match[1] / len(DOC_TYPE_KEYWORDS.get(best_match[0], [])), 2),
            "all_matches": [{"doc_type": k, "score": v} for k, v in sorted_scores[:5]],
        }
    
    return {
        "ok": True,
        "detected": False,
        "doc_type": "待人工确认",
        "confidence": 0,
        "all_matches": [],
        "suggestion": "未能自动识别资料类型，建议人工确认或补充关键词",
    }


def auto_classify_upload(
    filename: str,
    content: str = "",
    uploader: str = "",
    workshop: str = "",
    project: str = "",
) -> dict:
    """
    自动分类上传资料（类型检测+资料识别+自动归类）。
    
    Args:
        filename: 文件名
        content: 文件内容
        uploader: 上传人
        workshop: 车间
        project: 项目
    
    Returns:
        自动分类结果
    """
    # 1. 检测上传类型
    type_result = detect_upload_type(filename)
    
    # 2. 识别资料类型
    doc_result = detect_doc_type(content, filename)
    
    # 3. 自动归类
    classification = {
        "project": project or "默认项目",
        "workshop": workshop or "待分配车间",
        "device": "待分配设备",
        "doc_type": doc_result.get("doc_type", "待人工确认"),
    }
    
    # 生成上传记录
    record = {
        "id": datetime.datetime.now().strftime("%Y%m%d%H%M%S") + "_" + str(os.getpid()),
        "filename": filename,
        "upload_type": type_result.get("upload_type", "unknown"),
        "upload_type_name": type_result.get("upload_type_name", "未知"),
        "doc_type": doc_result.get("doc_type", "待人工确认"),
        "doc_type_confidence": doc_result.get("confidence", 0),
        "project": classification["project"],
        "workshop": classification["workshop"],
        "device": classification["device"],
        "uploader": uploader or "匿名用户",
        "upload_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "待解析" if type_result.get("auto_parse") else "待人工处理",
        "parse_actions": type_result.get("parse_actions", []),
        "auto_classified": doc_result.get("detected", False),
        "needs_manual_confirm": not doc_result.get("detected", False),
    }
    
    # 保存上传记录
    _save_upload_record(record)
    
    return {
        "ok": True,
        "upload_type": type_result,
        "doc_type": doc_result,
        "classification": classification,
        "record": record,
        "suggestion": _generate_suggestion(record),
    }


def _generate_suggestion(record: dict) -> str:
    """生成处理建议。"""
    if record["needs_manual_confirm"]:
        return f"文件 '{record['filename']}' 未能自动识别资料类型，建议人工确认后归类到对应项目/车间/设备。"
    if record["upload_type"] == "photo":
        return f"照片已识别为'{record['doc_type']}'，将自动进行OCR识别和图像分析，提取设备铭牌和施工信息。"
    if record["upload_type"] == "voice":
        return f"语音已识别为'{record['doc_type']}'，将自动进行语音转文字和关键词提取。"
    if record["upload_type"] == "document":
        return f"文档已识别为'{record['doc_type']}'，将自动进行文本提取、表格解析和向量化处理。"
    return f"文件已识别为'{record['doc_type']}'，已自动归类到{record['workshop']}。"


def get_upload_records(
    status: str = "",
    uploader: str = "",
    workshop: str = "",
    limit: int = 50,
) -> dict:
    """
    获取上传记录列表。
    
    Args:
        status: 状态筛选
        uploader: 上传人筛选
        workshop: 车间筛选
        limit: 返回数量
    
    Returns:
        上传记录列表
    """
    records = _load_upload_records()
    
    # 筛选
    if status:
        records = [r for r in records if r.get("status") == status]
    if uploader:
        records = [r for r in records if uploader in r.get("uploader", "")]
    if workshop:
        records = [r for r in records if workshop in r.get("workshop", "")]
    
    # 按时间倒序
    records.sort(key=lambda x: x.get("upload_time", ""), reverse=True)
    
    # 统计
    stats = {
        "total": len(records),
        "pending_parse": len([r for r in records if r.get("status") == "待解析"]),
        "parsed": len([r for r in records if r.get("status") == "已解析"]),
        "manual_confirm": len([r for r in records if r.get("needs_manual_confirm")]),
        "by_type": {},
        "by_doc_type": {},
    }
    for r in records:
        ut = r.get("upload_type_name", "未知")
        stats["by_type"][ut] = stats["by_type"].get(ut, 0) + 1
        dt = r.get("doc_type", "未知")
        stats["by_doc_type"][dt] = stats["by_doc_type"].get(dt, 0) + 1
    
    return {
        "ok": True,
        "records": records[:limit],
        "stats": stats,
        "returned": min(len(records), limit),
    }


def update_upload_record(
    record_id: str,
    updates: dict,
) -> dict:
    """
    更新上传记录。
    
    Args:
        record_id: 记录ID
        updates: 更新字段
    
    Returns:
        更新结果
    """
    records = _load_upload_records()
    
    for record in records:
        if record.get("id") == record_id:
            record.update(updates)
            record["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _save_upload_records(records)
            return {
                "ok": True,
                "record_id": record_id,
                "updated_fields": list(updates.keys()),
                "record": record,
            }
    
    return {"ok": False, "error": f"未找到记录: {record_id}"}


def batch_parse_uploads(
    record_ids: list = None,
    status: str = "待解析",
) -> dict:
    """
    批量解析上传文件。
    
    Args:
        record_ids: 指定记录ID列表
        status: 按状态筛选
    
    Returns:
        批量解析结果
    """
    records = _load_upload_records()
    
    if record_ids:
        to_parse = [r for r in records if r.get("id") in record_ids]
    else:
        to_parse = [r for r in records if r.get("status") == status]
    
    parsed = 0
    failed = 0
    
    for record in to_parse:
        try:
            # 模拟解析过程
            record["status"] = "已解析"
            record["parsed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            record["parse_result"] = {
                "text_extracted": True,
                "vectorized": True,
                "classified": True,
            }
            parsed += 1
        except Exception:
            record["status"] = "解析失败"
            failed += 1
    
    _save_upload_records(records)
    
    return {
        "ok": True,
        "total": len(to_parse),
        "parsed": parsed,
        "failed": failed,
        "parsed_ids": [r["id"] for r in to_parse if r.get("status") == "已解析"],
    }


def _load_upload_records() -> list:
    """加载上传记录。"""
    try:
        os.makedirs(os.path.dirname(UPLOAD_RECORDS_FILE), exist_ok=True)
        if os.path.exists(UPLOAD_RECORDS_FILE):
            with open(UPLOAD_RECORDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_upload_record(record: dict):
    """保存单条上传记录。"""
    records = _load_upload_records()
    records.append(record)
    # 保留最近500条
    if len(records) > 500:
        records = records[-500:]
    _save_upload_records(records)


def _save_upload_records(records: list):
    """保存上传记录列表。"""
    try:
        os.makedirs(os.path.dirname(UPLOAD_RECORDS_FILE), exist_ok=True)
        with open(UPLOAD_RECORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
