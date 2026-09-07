"""
v0.1.93：矿山设备资料生成与现场记录联动

将现场记录与工程资料生成联动，根据现场记录自动生成对应的工程资料，
现场记录数据自动填充到资料模板中，支持从现场记录一键生成各类工程资料。
"""

import os
import json
import datetime
from typing import Optional


# ============================================================
# 现场记录到工程资料的映射关系
# ============================================================

RECORD_TO_DOC_MAPPING = {
    "construction_log": {
        "doc_type": "施工日志",
        "description": "根据现场施工日志记录自动生成标准施工日志文档",
        "field_mapping": {
            "date": "日期",
            "weather": "天气",
            "temperature": "气温",
            "workshop": "施工部位",
            "construction_content": "施工内容",
            "equipment_used": "使用机械",
            "personnel": "出勤人数",
            "progress": "进度情况",
            "quality": "质量情况",
            "safety": "安全情况",
            "problems": "存在问题",
            "next_plan": "明日计划",
            "recorder": "记录人",
        },
    },
    "unboxing_record": {
        "doc_type": "设备开箱检验记录",
        "description": "根据现场开箱记录自动生成标准设备开箱检验记录文档",
        "field_mapping": {
            "date": "检验日期",
            "workshop": "施工区域",
            "equipment_name": "设备名称",
            "equipment_model": "规格型号",
            "equipment_tag": "位号",
            "manufacturer": "制造厂家",
            "contract_no": "合同号",
            "packing_condition": "包装情况",
            "appearance": "外观检查",
            "parts_check": "零部件清点",
            "documents": "随机文件",
            "defects": "缺损情况",
            "conclusion": "检验结论",
            "handover_person": "移交人",
            "receiver": "接收人",
            "supervisor": "监理",
        },
    },
    "concealment_record": {
        "doc_type": "隐蔽工程验收记录",
        "description": "根据现场隐蔽记录自动生成标准隐蔽工程验收记录文档",
        "field_mapping": {
            "date": "验收日期",
            "workshop": "施工区域",
            "equipment_name": "设备名称",
            "equipment_tag": "位号",
            "concealment_part": "隐蔽部位",
            "construction_content": "施工内容",
            "material": "材料规格",
            "quality_check": "质量检查",
            "test_results": "试验结果",
            "conclusion": "验收结论",
            "construction_unit": "施工单位",
            "constructor": "施工负责人",
            "quality_inspector": "质检员",
            "supervisor": "监理工程师",
            "owner_rep": "建设单位",
        },
    },
    "installation_record": {
        "doc_type": "设备安装记录",
        "description": "根据现场安装记录自动生成标准设备安装记录文档",
        "field_mapping": {
            "date": "安装日期",
            "workshop": "施工区域",
            "equipment_name": "设备名称",
            "equipment_model": "规格型号",
            "equipment_tag": "位号",
            "location": "安装位置",
            "elevation": "设备标高",
            "levelness": "水平度",
            "verticality": "垂直度",
            "alignment": "同轴度",
            "clearance": "关键间隙",
            "bolt_torque": "螺栓力矩",
            "grouting": "二次灌浆",
            "quality_standard": "质量标准",
            "conclusion": "安装结论",
            "constructor": "施工负责人",
            "quality_inspector": "质检员",
        },
    },
    "trial_run_record": {
        "doc_type": "设备试运转记录",
        "description": "根据现场试运转记录自动生成标准设备试运转记录文档",
        "field_mapping": {
            "date": "试运转日期",
            "workshop": "施工区域",
            "equipment_name": "设备名称",
            "equipment_model": "规格型号",
            "equipment_tag": "位号",
            "trial_type": "试运转类型",
            "duration": "运转时长",
            "current": "电流",
            "voltage": "电压",
            "temperature": "轴承温度",
            "vibration": "振动值",
            "noise": "噪声",
            "pressure": "压力",
            "flow": "流量",
            "lubrication": "润滑情况",
            "sealing": "密封情况",
            "abnormal": "异常情况",
            "conclusion": "试运转结论",
            "operator": "操作人",
            "recorder": "记录人",
            "supervisor": "监护人",
        },
    },
    "safety_check": {
        "doc_type": "安全检查记录",
        "description": "根据现场安全检查记录自动生成标准安全检查记录文档",
        "field_mapping": {
            "date": "检查日期",
            "workshop": "检查区域",
            "check_type": "检查类型",
            "check_content": "检查内容",
            "high_place": "高处作业",
            "lifting": "起重吊装",
            "hot_work": "动火作业",
            "confined_space": "受限空间",
            "electricity": "临时用电",
            "machinery": "机械设备",
            "ppe": "防护用品",
            "hazards": "发现隐患",
            "rectification": "整改措施",
            "rectification_person": "整改责任人",
            "inspector": "检查人",
            "checked_person": "被检查人",
        },
    },
    "lifting_record": {
        "doc_type": "吊装作业记录",
        "description": "根据现场吊装记录自动生成标准吊装作业记录文档",
        "field_mapping": {
            "date": "吊装日期",
            "workshop": "吊装区域",
            "equipment_name": "吊装设备",
            "equipment_weight": "设备重量",
            "equipment_size": "设备尺寸",
            "lifting_height": "吊装高度",
            "crane_type": "吊车类型",
            "crane_working_radius": "作业半径",
            "lifting_method": "吊装方法",
            "lifting_points": "吊点设置",
            "slings": "索具配置",
            "safety_factor": "安全系数",
            "wind_speed": "风速",
            "trial_lift": "试吊情况",
            "lifting_process": "吊装过程",
            "positioning": "就位情况",
            "abnormal": "异常情况",
            "conclusion": "吊装结论",
            "commander": "指挥",
            "crane_operator": "司机",
            "signalman": "信号工",
            "safety_officer": "安全员",
        },
    },
    "welding_record": {
        "doc_type": "焊接记录",
        "description": "根据现场焊接记录自动生成标准焊接记录文档",
        "field_mapping": {
            "date": "焊接日期",
            "workshop": "施工区域",
            "welding_part": "焊接部位",
            "material": "母材材质",
            "welding_process": "焊接方法",
            "welding_material": "焊材牌号",
            "welding_material_batch": "焊材质保书",
            "preheat_temp": "预热温度",
            "interpass_temp": "层间温度",
            "current": "焊接电流",
            "voltage": "焊接电压",
            "welding_speed": "焊接速度",
            "welding_layers": "焊接层数",
            "post_weld_heat": "焊后热处理",
            "appearance_check": "外观检查",
            "ndt": "无损检测",
            "ndt_result": "检测结果",
            "welder": "焊工",
            "inspector": "检查员",
        },
    },
}


# ============================================================
# 资料生成与现场记录联动
# ============================================================

def get_record_doc_mapping() -> dict:
    """获取现场记录到工程资料的映射关系。"""
    mappings = []
    for key, mapping in RECORD_TO_DOC_MAPPING.items():
        mappings.append({
            "record_type": key,
            "doc_type": mapping["doc_type"],
            "description": mapping["description"],
            "field_count": len(mapping["field_mapping"]),
        })
    return {
        "ok": True,
        "mappings": mappings,
        "total": len(mappings),
    }


def generate_doc_from_record(
    record_type: str,
    record_data: dict,
    device_type: str = "",
    device_tag: str = "",
    workshop: str = "",
) -> dict:
    """
    根据现场记录生成工程资料文档。
    
    Args:
        record_type: 现场记录类型
        record_data: 现场记录数据
        device_type: 设备类型（可选，用于获取设备专用要点）
        device_tag: 设备位号（可选）
        workshop: 车间（可选）
    
    Returns:
        生成的工程资料
    """
    if record_type not in RECORD_TO_DOC_MAPPING:
        return {"ok": False, "error": f"未找到记录类型: {record_type}"}
    
    mapping = RECORD_TO_DOC_MAPPING[record_type]
    
    # 填充字段映射
    doc_fields = []
    filled_count = 0
    missing_fields = []
    
    for record_key, doc_label in mapping["field_mapping"].items():
        value = record_data.get(record_key, "")
        if value and value != "待填写":
            filled_count += 1
            status = "filled"
        else:
            missing_fields.append(doc_label)
            status = "missing"
            value = value or "待填写"
        
        doc_fields.append({
            "label": doc_label,
            "value": value,
            "source_field": record_key,
            "status": status,
        })
    
    # 获取设备专用要点
    equipment_points = []
    if device_type:
        try:
            from . import mining_field_record as _mfr
            points_result = _mfr.get_equipment_record_points(device_type)
            if points_result.get("ok"):
                point_key_map = {
                    "unboxing_record": "unboxing",
                    "installation_record": "installation",
                    "concealment_record": "concealment",
                    "trial_run_record": "trial_run",
                }
                point_key = point_key_map.get(record_type)
                if point_key and point_key in points_result["points"]:
                    equipment_points = points_result["points"][point_key]
        except Exception:
            pass
    
    # 计算完成率
    total_fields = len(doc_fields)
    completion_rate = round(filled_count / max(total_fields, 1) * 100, 1)
    
    # 生成文档内容
    doc_content = _generate_doc_content(
        mapping["doc_type"],
        doc_fields,
        device_type,
        device_tag,
        workshop,
        equipment_points
    )
    
    return {
        "ok": True,
        "record_type": record_type,
        "doc_type": mapping["doc_type"],
        "device_type": device_type,
        "device_tag": device_tag,
        "workshop": workshop,
        "fields": doc_fields,
        "total_fields": total_fields,
        "filled_count": filled_count,
        "missing_fields": missing_fields,
        "completion_rate": completion_rate,
        "equipment_specific_points": equipment_points,
        "doc_content": doc_content,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _generate_doc_content(
    doc_type: str,
    fields: list,
    device_type: str,
    device_tag: str,
    workshop: str,
    equipment_points: list,
) -> str:
    """生成文档内容（文本格式）。"""
    lines = []
    lines.append("=" * 60)
    lines.append(f"  {doc_type}")
    lines.append("=" * 60)
    lines.append("")
    
    if device_type:
        lines.append(f"设备名称：{device_type}")
    if device_tag:
        lines.append(f"设备位号：{device_tag}")
    if workshop:
        lines.append(f"施工区域：{workshop}")
    lines.append("")
    lines.append("-" * 40)
    lines.append("")
    
    for field in fields:
        value = field["value"]
        if field["status"] == "missing":
            value = "【待填写】"
        lines.append(f"{field['label']}：{value}")
        lines.append("")
    
    if equipment_points:
        lines.append("-" * 40)
        lines.append("设备专用要点：")
        lines.append("")
        for point in equipment_points:
            lines.append(f"  • {point}")
        lines.append("")
    
    lines.append("-" * 40)
    lines.append("")
    lines.append("编制：__________  日期：__________")
    lines.append("审核：__________  日期：__________")
    lines.append("批准：__________  日期：__________")
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)


def batch_generate_docs_from_records(
    records: list,
) -> dict:
    """
    批量根据现场记录生成工程资料。
    
    Args:
        records: 现场记录列表，每条包含 record_type 和 record_data
    
    Returns:
        批量生成结果
    """
    results = []
    success_count = 0
    fail_count = 0
    
    for record in records:
        record_type = record.get("record_type", "")
        record_data = record.get("record_data", {})
        device_type = record.get("device_type", "")
        device_tag = record.get("device_tag", "")
        workshop = record.get("workshop", "")
        
        result = generate_doc_from_record(
            record_type, record_data, device_type, device_tag, workshop
        )
        
        if result.get("ok"):
            success_count += 1
        else:
            fail_count += 1
        
        results.append(result)
    
    return {
        "ok": True,
        "total": len(records),
        "success_count": success_count,
        "fail_count": fail_count,
        "results": results,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def check_record_completeness_for_doc(
    record_type: str,
    record_data: dict,
) -> dict:
    """
    检查现场记录是否足够生成完整的工程资料。
    
    Args:
        record_type: 现场记录类型
        record_data: 现场记录数据
    
    Returns:
        完整性检查结果
    """
    if record_type not in RECORD_TO_DOC_MAPPING:
        return {"ok": False, "error": f"未找到记录类型: {record_type}"}
    
    mapping = RECORD_TO_DOC_MAPPING[record_type]
    
    required_fields = []
    optional_fields = []
    filled_required = 0
    filled_optional = 0
    
    for record_key, doc_label in mapping["field_mapping"].items():
        value = record_data.get(record_key, "")
        is_filled = bool(value) and value != "待填写"
        
        # 简单判断：日期、设备名称、结论等为必填
        required_keys = ["date", "equipment_name", "conclusion", "workshop",
                        "construction_content", "appearance", "quality_check",
                        "levelness", "trial_type", "temperature", "check_content",
                        "equipment_weight", "crane_type", "welding_part", "material",
                        "welding_process", "current", "voltage"]
        
        if record_key in required_keys:
            required_fields.append({"key": record_key, "label": doc_label, "filled": is_filled})
            if is_filled:
                filled_required += 1
        else:
            optional_fields.append({"key": record_key, "label": doc_label, "filled": is_filled})
            if is_filled:
                filled_optional += 1
    
    required_completion = round(filled_required / max(len(required_fields), 1) * 100, 1)
    can_generate = required_completion >= 60  # 必填项完成60%以上可以生成
    
    missing_required = [f["label"] for f in required_fields if not f["filled"]]
    
    return {
        "ok": True,
        "record_type": record_type,
        "doc_type": mapping["doc_type"],
        "required_fields": len(required_fields),
        "filled_required": filled_required,
        "optional_fields": len(optional_fields),
        "filled_optional": filled_optional,
        "required_completion_rate": required_completion,
        "can_generate": can_generate,
        "missing_required_fields": missing_required,
        "suggestion": "可以生成工程资料" if can_generate else f"建议先补充必填项：{', '.join(missing_required[:5])}",
    }
