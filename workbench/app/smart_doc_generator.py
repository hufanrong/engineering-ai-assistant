"""
v0.1.107：智能工程文件生成器

输入自然语言（如"生成球磨机安装的安全技术交底"），自动：
1. 识别要生成的文件类型
2. 识别设备名称
3. 从项目数据库读取已有数据自动填充
4. 列出缺失数据提示人工补充
5. 调用对应模块生成文件
"""

import os
import json
import re
import datetime
from typing import Optional, Dict, List, Tuple


# 支持的文件类型映射
DOC_TYPE_MAP = {
    # 安全交底
    "安全交底": {"module": "mining_safety_disclosure", "method": "generate_safety_disclosure",
                "keywords": ["安全交底", "安全技术交底", "安全措施交底"],
                "required_fields": ["设备名称", "项目名称", "施工单位"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 技术交底
    "技术交底": {"module": "mining_technical_disclosure_enhanced", "method": "generate_technical_disclosure",
                "keywords": ["技术交底", "施工技术交底", "技术措施交底"],
                "required_fields": ["设备名称", "项目名称", "施工单位"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 施工方案
    "施工方案": {"module": "mining_construction_plan_enhanced", "method": "generate_construction_plan",
                "keywords": ["施工方案", "安装方案", "施工组织设计"],
                "required_fields": ["设备名称", "项目名称", "施工单位", "编制人"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 吊装方案
    "吊装方案": {"module": "mining_lifting_plan_enhanced", "method": "generate_lifting_plan",
                "keywords": ["吊装方案", "起重方案", "吊装作业方案"],
                "required_fields": ["设备名称", "项目名称", "设备重量", "吊装高度"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 基础验收记录
    "基础验收": {"module": "field_record", "method": "generate_unboxing_record",
                "keywords": ["基础验收", "基础验收记录", "设备基础验收"],
                "required_fields": ["设备名称", "项目名称", "车间", "基础编号", "验收日期"],
                "auto_fill_fields": ["设备名称", "项目名称", "车间"]},
    # 开箱检验记录
    "开箱检验": {"module": "unboxing_record", "method": "generate_unboxing_record",
                "keywords": ["开箱检验", "开箱记录", "设备开箱", "开箱验收"],
                "required_fields": ["设备名称", "项目名称", "车间", "开箱日期", "供货厂家"],
                "auto_fill_fields": ["设备名称", "项目名称", "车间", "供货厂家"]},
    # 隐蔽工程验收
    "隐蔽工程": {"module": "concealment_record", "method": "generate_concealment_record",
                "keywords": ["隐蔽工程", "隐蔽验收", "隐蔽记录"],
                "required_fields": ["设备名称", "项目名称", "车间", "隐蔽部位", "验收日期"],
                "auto_fill_fields": ["设备名称", "项目名称", "车间"]},
    # 施工日志
    "施工日志": {"module": "construction_log", "method": "generate_log_data_enhanced",
                "keywords": ["施工日志", "施工日记", "日志"],
                "required_fields": ["日期", "项目名称", "天气", "施工内容"],
                "auto_fill_fields": ["项目名称", "日期"]},
    # 竣工资料组卷
    "竣工资料": {"module": "mining_completion_archive_enhanced", "method": "generate_completion_archive",
                "keywords": ["竣工资料", "竣工组卷", "资料组卷", "竣工归档"],
                "required_fields": ["设备名称", "项目名称", "施工单位"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 设计变更
    "设计变更": {"module": "design_change", "method": "generate_design_change",
                "keywords": ["设计变更", "变更单", "设计修改"],
                "required_fields": ["设备名称", "项目名称", "变更内容", "变更原因"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 货损报告
    "货损报告": {"module": "damage_report", "method": "generate_damage_report",
                "keywords": ["货损", "货损报告", "损坏报告", "设备损坏"],
                "required_fields": ["设备名称", "项目名称", "损坏部位", "损坏程度"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 设备安装记录
    "安装记录": {"module": "field_record", "method": "generate_installation_record",
                "keywords": ["安装记录", "设备安装记录", "安装施工记录"],
                "required_fields": ["设备名称", "项目名称", "车间", "安装日期"],
                "auto_fill_fields": ["设备名称", "项目名称", "车间"]},
    # 试运转记录
    "试运转": {"module": "field_record", "method": "generate_test_run_record",
                "keywords": ["试运转", "试运行", "试车", "空运转"],
                "required_fields": ["设备名称", "项目名称", "车间", "试运转日期"],
                "auto_fill_fields": ["设备名称", "项目名称", "车间"]},
}


# 设备名称识别（从知识库中匹配）
def _extract_equipment(text: str) -> Tuple[Optional[str], float]:
    """从文本中提取设备名称。"""
    from . import mining_equipment_detail as _med
    
    # 获取所有支持的设备
    all_equipment = _med.EQUIPMENT_DETAIL.keys() if hasattr(_med, 'EQUIPMENT_DETAIL') else [
        "球磨机", "半自磨机", "高压釜", "闪速炉", "浮选机", "颚式破碎机", "浓缩机", "压滤机"
    ]
    
    best_match = None
    best_score = 0
    
    for eq in all_equipment:
        if eq in text:
            score = len(eq) / len(text) * 10
            if score > best_score:
                best_score = score
                best_match = eq
    
    # 也检查常见别名
    aliases = {
        "磨机": "球磨机", "球磨": "球磨机", "自磨机": "半自磨机", "半自磨": "半自磨机",
        "反应釜": "高压釜", "加压釜": "高压釜", "闪速熔炼炉": "闪速炉",
        "浮选槽": "浮选机", "破碎机": "颚式破碎机", "鄂破": "颚式破碎机",
        "浓密机": "浓缩机", "过滤机": "压滤机",
    }
    for alias, real in aliases.items():
        if alias in text and best_match is None:
            best_match = real
            best_score = 0.5
            break
    
    return best_match, best_score


def _extract_doc_type(text: str) -> Tuple[Optional[str], Dict]:
    """从文本中识别文件类型。"""
    best_type = None
    best_config = None
    best_match_len = 0
    
    for doc_type, config in DOC_TYPE_MAP.items():
        for keyword in config["keywords"]:
            if keyword in text and len(keyword) > best_match_len:
                best_match_len = len(keyword)
                best_type = doc_type
                best_config = config
    
    return best_type, best_config


def _extract_project_name(text: str) -> Optional[str]:
    """从文本中提取项目名称（如果有的话）。"""
    # 匹配"XX项目"模式
    match = re.search(r'([\u4e00-\u9fa5a-zA-Z0-9]+项目)', text)
    if match:
        return match.group(1)
    return None


def _extract_workshop(text: str) -> Optional[str]:
    """从文本中提取车间名称。"""
    match = re.search(r'([\u4e00-\u9fa50-9]+车间)', text)
    if match:
        return match.group(1)
    return None


def _get_project_data(project_id: str = None) -> Dict:
    """从项目数据库读取已有数据。"""
    from . import project_manager as _pm
    
    data_dir = _pm.get_project_data_dir(project_id)
    index_path = os.path.join(data_dir, "index.json")
    relations_path = os.path.join(data_dir, "relations.json")
    
    result = {
        "project_name": "",
        "devices": {},
        "workshops": {},
        "files": [],
        "relations": [],
    }
    
    # 读取当前项目名称
    current = _pm.get_current_project()
    if current:
        result["project_name"] = current.get("name", "")
    
    # 读取 index.json
    if os.path.isfile(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
            result["devices"] = idx.get("devices", {})
            result["workshops"] = idx.get("workshops", {})
            result["files"] = idx.get("files", [])
        except Exception:
            pass
    
    # 读取 relations.json
    if os.path.isfile(relations_path):
        try:
            with open(relations_path, "r", encoding="utf-8") as f:
                rel = json.load(f)
            result["relations"] = rel.get("relations", [])
        except Exception:
            pass
    
    return result


def _auto_fill_fields(doc_type: str, equipment: str, project_data: Dict,
                      text: str) -> Tuple[Dict, List[str]]:
    """
    自动填充字段，并返回缺失字段列表。
    
    Returns:
        (filled_fields, missing_fields)
    """
    config = DOC_TYPE_MAP.get(doc_type, {})
    required = config.get("required_fields", [])
    
    filled = {}
    missing = []
    
    # 设备名称
    if "设备名称" in required:
        if equipment:
            filled["设备名称"] = equipment
        else:
            missing.append("设备名称")
    
    # 项目名称
    if "项目名称" in required:
        project_name = _extract_project_name(text)
        if not project_name:
            project_name = project_data.get("project_name", "")
        if project_name:
            filled["项目名称"] = project_name
        else:
            missing.append("项目名称")
    
    # 施工单位
    if "施工单位" in required:
        missing.append("施工单位（可选填）")
    
    # 车间
    if "车间" in required:
        workshop = _extract_workshop(text)
        if not workshop and equipment:
            # 从项目数据中查找设备所在车间
            devices = project_data.get("devices", {})
            for tag, dev in devices.items():
                if equipment in str(dev.get("name", "")) or equipment in tag:
                    workshop = dev.get("workshop", "")
                    if workshop:
                        break
        if workshop:
            filled["车间"] = workshop
        else:
            missing.append("车间")
    
    # 日期类字段
    date_fields = ["验收日期", "开箱日期", "安装日期", "试运转日期", "日期"]
    for df in date_fields:
        if df in required:
            filled[df] = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # 供货厂家
    if "供货厂家" in required:
        if equipment:
            devices = project_data.get("devices", {})
            for tag, dev in devices.items():
                if equipment in str(dev.get("name", "")):
                    manufacturer = dev.get("manufacturer", "")
                    if manufacturer:
                        filled["供货厂家"] = manufacturer
                        break
        if "供货厂家" not in filled:
            missing.append("供货厂家")
    
    # 其他需要人工填写的字段
    manual_fields = ["基础编号", "隐蔽部位", "变更内容", "变更原因",
                     "损坏部位", "损坏程度", "设备重量", "吊装高度",
                     "编制人", "天气", "施工内容"]
    for mf in manual_fields:
        if mf in required:
            missing.append(mf)
    
    return filled, missing


def generate_from_natural_language(text: str, project_id: str = None) -> Dict:
    """
    从自然语言生成工程文件。
    
    Args:
        text: 用户输入的自然语言，如"生成球磨机安装的安全技术交底"
        project_id: 项目ID，为None时使用当前项目
    
    Returns:
        生成结果，包含识别信息、自动填充数据、缺失字段、生成的文件内容
    """
    # 1. 识别文件类型
    doc_type, config = _extract_doc_type(text)
    if not doc_type:
        return {
            "ok": False,
            "error": "无法识别要生成的文件类型",
            "supported_types": list(DOC_TYPE_MAP.keys()),
            "suggestion": "请在输入中包含文件类型，如'生成球磨机安全交底'、'制作高压釜施工方案'等",
        }
    
    # 2. 识别设备名称
    equipment, eq_score = _extract_equipment(text)
    
    # 3. 读取项目数据
    project_data = _get_project_data(project_id)
    
    # 4. 自动填充字段
    filled, missing = _auto_fill_fields(doc_type, equipment, project_data, text)
    
    # 5. 如果缺少关键信息（设备名称），返回待补充状态
    if not equipment and "设备名称" in missing:
        return {
            "ok": False,
            "stage": "need_equipment",
            "doc_type": doc_type,
            "message": f"已识别要生成「{doc_type}」，但未识别到设备名称",
            "filled_fields": filled,
            "missing_fields": missing,
            "available_equipment": list(project_data.get("devices", {}).keys()),
            "suggestion": "请补充设备名称，或从已有设备中选择",
        }
    
    # 6. 调用对应模块生成文件
    try:
        result = _call_generator(doc_type, equipment, filled, text)
    except Exception as e:
        return {
            "ok": False,
            "error": f"生成文件时出错：{str(e)}",
            "doc_type": doc_type,
            "equipment": equipment,
            "filled_fields": filled,
            "missing_fields": missing,
        }
    
    return {
        "ok": True,
        "stage": "generated",
        "doc_type": doc_type,
        "equipment": equipment,
        "input_text": text,
        "filled_fields": filled,
        "missing_fields": missing,
        "missing_count": len(missing),
        "has_missing": len(missing) > 0,
        "result": result,
        "message": f"已生成「{equipment}{doc_type}」" + (f"，有{len(missing)}项数据需要人工补充完善" if missing else "，数据完整"),
    }


def _call_generator(doc_type: str, equipment: str, filled: Dict, text: str) -> Dict:
    """调用对应模块生成文件。"""
    project_name = filled.get("项目名称", "矿山工程项目")
    workshop = filled.get("车间", "")
    
    if doc_type == "安全交底":
        from . import mining_safety_disclosure as _msd
        return _msd.generate_safety_disclosure(equipment, project_name, workshop)
    
    elif doc_type == "技术交底":
        from . import mining_technical_disclosure_enhanced as _mtde
        return _mtde.generate_technical_disclosure(equipment, project_name, workshop)
    
    elif doc_type == "施工方案":
        from . import mining_construction_plan_enhanced as _mcpe
        return _mcpe.generate_construction_plan(equipment, project_name, workshop)
    
    elif doc_type == "吊装方案":
        from . import mining_lifting_plan_enhanced as _mlpe
        return _mlpe.generate_lifting_plan(equipment, project_name, workshop)
    
    elif doc_type == "竣工资料":
        from . import mining_completion_archive_enhanced as _mcae
        return _mcae.generate_completion_archive(equipment, project_name, workshop)
    
    elif doc_type == "施工日志":
        from . import construction_log as _cl
        date = filled.get("日期", datetime.datetime.now().strftime("%Y-%m-%d"))
        return _cl.generate_log_data_enhanced(date, project_name, workshop)
    
    else:
        # 其他类型返回模板结构
        return {
            "ok": True,
            "title": f"{equipment}{doc_type}",
            "doc_type": doc_type,
            "equipment": equipment,
            "project_name": project_name,
            "workshop": workshop,
            "status": "template_generated",
            "note": "该文件类型模板已生成，详细内容请在前端填写缺失字段后导出",
        }


def get_supported_types() -> Dict:
    """获取支持的文件类型列表。"""
    types = []
    for doc_type, config in DOC_TYPE_MAP.items():
        types.append({
            "type": doc_type,
            "keywords": config["keywords"],
            "required_fields": config["required_fields"],
        })
    return {
        "ok": True,
        "total": len(types),
        "types": types,
    }


def analyze_input(text: str) -> Dict:
    """
    仅分析输入，不生成文件。用于前端实时提示。
    """
    doc_type, config = _extract_doc_type(text)
    equipment, eq_score = _extract_equipment(text)
    project_name = _extract_project_name(text)
    workshop = _extract_workshop(text)
    
    return {
        "ok": True,
        "input": text,
        "recognized_doc_type": doc_type,
        "recognized_equipment": equipment,
        "recognized_project": project_name,
        "recognized_workshop": workshop,
        "can_generate": doc_type is not None,
        "confidence": "高" if (doc_type and equipment) else ("中" if doc_type else "低"),
    }
