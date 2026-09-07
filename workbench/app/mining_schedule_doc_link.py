"""
v0.1.96：矿山设备施工进度与资料生成联动

根据施工进度自动生成对应阶段的工程资料，施工进度到资料类型的映射，
进度检查时自动检查对应资料是否齐全，进度更新时自动提醒需要生成的资料。
"""

import os
import json
import datetime
from typing import Optional


# ============================================================
# 施工进度阶段到工程资料的映射
# ============================================================

SCHEDULE_PHASE_TO_DOCS = {
    "施工准备": {
        "phase": "施工准备",
        "description": "施工准备阶段应完成的资料",
        "required_docs": [
            {"doc_type": "施工组织设计", "priority": "high", "description": "项目总体施工组织设计"},
            {"doc_type": "施工方案", "priority": "high", "description": "各专业专项施工方案"},
            {"doc_type": "技术交底记录", "priority": "high", "description": "施工技术交底"},
            {"doc_type": "安全交底记录", "priority": "high", "description": "安全技术交底"},
            {"doc_type": "施工日志", "priority": "medium", "description": "每日施工日志"},
            {"doc_type": "图纸会审记录", "priority": "medium", "description": "施工图纸会审"},
            {"doc_type": "设计交底记录", "priority": "medium", "description": "设计单位技术交底"},
            {"doc_type": "开工报告", "priority": "high", "description": "工程开工申请"},
        ],
    },
    "基础施工": {
        "phase": "基础施工",
        "description": "设备基础施工阶段应完成的资料",
        "required_docs": [
            {"doc_type": "基础验收记录", "priority": "high", "description": "设备基础交接验收"},
            {"doc_type": "隐蔽工程验收记录", "priority": "high", "description": "基础钢筋/预埋螺栓隐蔽验收"},
            {"doc_type": "二次灌浆记录", "priority": "high", "description": "设备基础二次灌浆"},
            {"doc_type": "混凝土试块报告", "priority": "medium", "description": "基础混凝土强度试验"},
            {"doc_type": "测量放线记录", "priority": "medium", "description": "设备基础定位放线"},
            {"doc_type": "施工日志", "priority": "medium", "description": "基础施工日志"},
        ],
    },
    "设备开箱": {
        "phase": "设备开箱",
        "description": "设备开箱检验阶段应完成的资料",
        "required_docs": [
            {"doc_type": "设备开箱检验记录", "priority": "high", "description": "设备开箱检验"},
            {"doc_type": "设备质量证明文件", "priority": "high", "description": "设备合格证/质量证明书"},
            {"doc_type": "设备说明书", "priority": "medium", "description": "设备安装使用说明书"},
            {"doc_type": "设备装箱单", "priority": "medium", "description": "设备零部件装箱清单"},
            {"doc_type": "进口设备商检报告", "priority": "low", "description": "进口设备商检证明（如适用）"},
        ],
    },
    "设备安装": {
        "phase": "设备安装",
        "description": "设备安装阶段应完成的资料",
        "required_docs": [
            {"doc_type": "设备安装记录", "priority": "high", "description": "设备安装过程记录"},
            {"doc_type": "设备找平找正记录", "priority": "high", "description": "设备水平度/垂直度/同轴度检测"},
            {"doc_type": "地脚螺栓紧固记录", "priority": "high", "description": "地脚螺栓紧固力矩"},
            {"doc_type": "隐蔽工程验收记录", "priority": "high", "description": "设备底座/管道隐蔽验收"},
            {"doc_type": "大件吊装方案", "priority": "high", "description": "重型设备吊装专项方案"},
            {"doc_type": "吊装作业记录", "priority": "medium", "description": "设备吊装作业记录"},
            {"doc_type": "焊接记录", "priority": "medium", "description": "设备管道焊接记录"},
            {"doc_type": "焊接无损检测报告", "priority": "medium", "description": "焊缝RT/UT/MT/PT检测"},
            {"doc_type": "施工日志", "priority": "medium", "description": "设备安装日志"},
        ],
    },
    "管道安装": {
        "phase": "管道安装",
        "description": "工艺管道安装阶段应完成的资料",
        "required_docs": [
            {"doc_type": "管道安装记录", "priority": "high", "description": "工艺管道安装记录"},
            {"doc_type": "管道压力试验记录", "priority": "high", "description": "管道水压/气压试验"},
            {"doc_type": "管道吹扫记录", "priority": "high", "description": "管道吹扫/清洗记录"},
            {"doc_type": "管道焊接记录", "priority": "medium", "description": "管道焊接记录"},
            {"doc_type": "阀门试验记录", "priority": "medium", "description": "阀门强度/严密性试验"},
            {"doc_type": "管道防腐保温记录", "priority": "low", "description": "管道防腐绝热施工"},
        ],
    },
    "电气安装": {
        "phase": "电气安装",
        "description": "电气仪表安装阶段应完成的资料",
        "required_docs": [
            {"doc_type": "电气安装记录", "priority": "high", "description": "电气设备安装记录"},
            {"doc_type": "接地电阻测试记录", "priority": "high", "description": "接地系统电阻测试"},
            {"doc_type": "绝缘电阻测试记录", "priority": "high", "description": "电缆/电机绝缘测试"},
            {"doc_type": "电缆敷设记录", "priority": "medium", "description": "电缆敷设及标识"},
            {"doc_type": "电机试运转记录", "priority": "medium", "description": "电机空载/负载试运转"},
            {"doc_type": "DCS/PLC调试记录", "priority": "medium", "description": "控制系统调试"},
            {"doc_type": "仪表校准记录", "priority": "medium", "description": "检测仪表校准"},
            {"doc_type": "联锁试验记录", "priority": "high", "description": "安全联锁功能试验"},
        ],
    },
    "试运转": {
        "phase": "试运转",
        "description": "设备试运转阶段应完成的资料",
        "required_docs": [
            {"doc_type": "单机试运转记录", "priority": "high", "description": "单台设备空载/负载试运转"},
            {"doc_type": "联动试运转记录", "priority": "high", "description": "系统联动试运转"},
            {"doc_type": "试运转方案", "priority": "high", "description": "设备试运转专项方案"},
            {"doc_type": "设备性能测试报告", "priority": "medium", "description": "设备性能参数测试"},
            {"doc_type": "润滑系统调试记录", "priority": "medium", "description": "润滑系统调试"},
            {"doc_type": "液压系统调试记录", "priority": "medium", "description": "液压系统调试"},
            {"doc_type": "施工日志", "priority": "medium", "description": "试运转期间日志"},
        ],
    },
    "竣工验收": {
        "phase": "竣工验收",
        "description": "竣工验收阶段应完成的资料",
        "required_docs": [
            {"doc_type": "竣工报告", "priority": "high", "description": "工程竣工报告"},
            {"doc_type": "竣工验收证书", "priority": "high", "description": "竣工验收证书"},
            {"doc_type": "竣工图", "priority": "high", "description": "竣工图纸"},
            {"doc_type": "工程移交单", "priority": "high", "description": "工程移交证书"},
            {"doc_type": "竣工资料组卷", "priority": "high", "description": "竣工资料整理归档"},
            {"doc_type": "设备清单", "priority": "medium", "description": "已安装设备清单"},
            {"doc_type": "备品备件清单", "priority": "medium", "description": "备品备件移交清单"},
            {"doc_type": "专用工具清单", "priority": "low", "description": "专用工具移交清单"},
        ],
    },
}


# 矿山设备专用施工阶段资料
MINING_EQUIPMENT_PHASE_DOCS = {
    "球磨机": {
        "设备安装": [
            {"doc_type": "主轴承轴瓦刮研记录", "priority": "high", "description": "球磨机主轴承轴瓦刮研"},
            {"doc_type": "大齿圈安装检测记录", "priority": "high", "description": "大齿圈端面/径向跳动检测"},
            {"doc_type": "齿轮啮合检测记录", "priority": "high", "description": "齿轮啮合间隙/接触率检测"},
            {"doc_type": "衬板安装记录", "priority": "medium", "description": "筒体衬板安装紧固"},
            {"doc_type": "筒体吊装记录", "priority": "high", "description": "球磨机筒体吊装"},
        ],
        "试运转": [
            {"doc_type": "球磨机试运转轴承温升记录", "priority": "high", "description": "主轴承温度监测"},
            {"doc_type": "球磨机试运转振动测试记录", "priority": "medium", "description": "筒体振动测试"},
            {"doc_type": "高低压润滑系统调试记录", "priority": "high", "description": "高低压润滑系统调试"},
        ],
    },
    "半自磨机": {
        "设备安装": [
            {"doc_type": "筒体翻身记录", "priority": "high", "description": "半自磨机筒体翻身"},
            {"doc_type": "环形电机气隙检测记录", "priority": "high", "description": "环形电机气隙均匀度"},
            {"doc_type": "静压轴承调试记录", "priority": "high", "description": "静压轴承高压油膜"},
            {"doc_type": "波形衬板安装记录", "priority": "medium", "description": "波形衬板/提升条安装"},
        ],
    },
    "高压釜": {
        "设备安装": [
            {"doc_type": "钛衬里电火花检测记录", "priority": "high", "description": "钛衬里针孔检测"},
            {"doc_type": "机械密封静压试验记录", "priority": "high", "description": "搅拌轴机械密封试验"},
            {"doc_type": "耐压试验记录", "priority": "high", "description": "高压釜水压试验1.25倍"},
            {"doc_type": "气密性试验记录", "priority": "high", "description": "高压釜气密试验"},
            {"doc_type": "安全阀校验记录", "priority": "high", "description": "安全阀/压力表校验"},
        ],
    },
    "闪速炉": {
        "设备安装": [
            {"doc_type": "反应塔垂直度检测记录", "priority": "high", "description": "反应塔安装垂直度"},
            {"doc_type": "铜水套水压试验记录", "priority": "high", "description": "铜水套逐块水压试验"},
            {"doc_type": "炉壳焊接无损检测记录", "priority": "high", "description": "炉壳焊缝RT/UT检测"},
            {"doc_type": "耐火砌筑记录", "priority": "high", "description": "耐火砖/浇注料砌筑"},
        ],
        "试运转": [
            {"doc_type": "烘炉记录", "priority": "high", "description": "按烘炉曲线升温记录"},
            {"doc_type": "烘炉曲线记录", "priority": "high", "description": "烘炉温度曲线"},
        ],
    },
    "浮选机": {
        "设备安装": [
            {"doc_type": "搅拌轴垂直度检测记录", "priority": "high", "description": "搅拌轴垂直度≤0.5mm/m"},
            {"doc_type": "叶轮间隙检测记录", "priority": "high", "description": "叶轮与槽底/定子间隙"},
            {"doc_type": "槽体渗漏试验记录", "priority": "high", "description": "槽体盛水24h渗漏试验"},
            {"doc_type": "充气系统调试记录", "priority": "medium", "description": "充气量调节测试"},
        ],
    },
}


def get_schedule_phase_docs() -> dict:
    """获取施工进度阶段到工程资料的映射。"""
    phases = []
    for phase_key, phase_info in SCHEDULE_PHASE_TO_DOCS.items():
        phases.append({
            "phase": phase_key,
            "description": phase_info["description"],
            "required_docs_count": len(phase_info["required_docs"]),
            "high_priority_count": len([d for d in phase_info["required_docs"] if d["priority"] == "high"]),
        })
    return {
        "ok": True,
        "phases": phases,
        "total_phases": len(phases),
    }


def check_schedule_phase_docs(
    phase: str,
    existing_docs: list,
    device_type: str = "",
) -> dict:
    """
    检查指定施工阶段的资料完整性。
    
    Args:
        phase: 施工阶段
        existing_docs: 已有资料列表
        device_type: 设备类型（可选，用于检查设备专用资料）
    
    Returns:
        资料完整性检查结果
    """
    if phase not in SCHEDULE_PHASE_TO_DOCS:
        return {"ok": False, "error": f"未找到施工阶段: {phase}"}
    
    phase_info = SCHEDULE_PHASE_TO_DOCS[phase]
    required_docs = phase_info["required_docs"]
    
    # 设备专用资料
    equipment_docs = []
    if device_type and device_type in MINING_EQUIPMENT_PHASE_DOCS:
        dev_phase_docs = MINING_EQUIPMENT_PHASE_DOCS[device_type]
        if phase in dev_phase_docs:
            equipment_docs = dev_phase_docs[phase]
    
    all_required = required_docs + equipment_docs
    
    # 检查资料完整性
    missing_high = []
    missing_medium = []
    missing_low = []
    existing = []
    
    for doc in all_required:
        doc_type = doc["doc_type"]
        if _doc_exists(doc_type, existing_docs):
            existing.append(doc)
        else:
            if doc["priority"] == "high":
                missing_high.append(doc)
            elif doc["priority"] == "medium":
                missing_medium.append(doc)
            else:
                missing_low.append(doc)
    
    total_required = len(all_required)
    total_existing = len(existing)
    completion_rate = round(total_existing / max(total_required, 1) * 100, 1)
    
    can_proceed = len(missing_high) == 0
    
    return {
        "ok": True,
        "phase": phase,
        "description": phase_info["description"],
        "device_type": device_type,
        "total_required": total_required,
        "total_existing": total_existing,
        "missing_high": len(missing_high),
        "missing_medium": len(missing_medium),
        "missing_low": len(missing_low),
        "completion_rate": completion_rate,
        "can_proceed": can_proceed,
        "existing_docs": existing,
        "missing_high_list": missing_high,
        "missing_medium_list": missing_medium,
        "missing_low_list": missing_low,
        "suggestion": "资料齐全，可以进入下一阶段" if can_proceed else f"缺少{len(missing_high)}项必备资料，建议先补充：{', '.join([d['doc_type'] for d in missing_high[:3]])}",
    }


def generate_docs_for_phase(
    phase: str,
    device_type: str = "",
    device_tag: str = "",
    workshop: str = "",
) -> dict:
    """
    为指定施工阶段生成需要的资料清单。
    
    Args:
        phase: 施工阶段
        device_type: 设备类型
        device_tag: 设备位号
        workshop: 车间
    
    Returns:
        需要生成的资料清单
    """
    if phase not in SCHEDULE_PHASE_TO_DOCS:
        return {"ok": False, "error": f"未找到施工阶段: {phase}"}
    
    phase_info = SCHEDULE_PHASE_TO_DOCS[phase]
    required_docs = phase_info["required_docs"]
    
    # 设备专用资料
    equipment_docs = []
    if device_type and device_type in MINING_EQUIPMENT_PHASE_DOCS:
        dev_phase_docs = MINING_EQUIPMENT_PHASE_DOCS[device_type]
        if phase in dev_phase_docs:
            equipment_docs = dev_phase_docs[phase]
    
    all_docs = required_docs + equipment_docs
    
    # 按优先级排序
    all_docs.sort(key=lambda x: 0 if x["priority"] == "high" else (1 if x["priority"] == "medium" else 2))
    
    return {
        "ok": True,
        "phase": phase,
        "description": phase_info["description"],
        "device_type": device_type,
        "device_tag": device_tag,
        "workshop": workshop,
        "total_docs": len(all_docs),
        "high_priority": len([d for d in all_docs if d["priority"] == "high"]),
        "medium_priority": len([d for d in all_docs if d["priority"] == "medium"]),
        "low_priority": len([d for d in all_docs if d["priority"] == "low"]),
        "docs_to_generate": all_docs,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def check_full_schedule_docs(
    schedule_phases: list,
    existing_docs: list,
    device_type: str = "",
) -> dict:
    """
    检查完整施工进度各阶段的资料完整性。
    
    Args:
        schedule_phases: 施工阶段列表
        existing_docs: 已有资料列表
        device_type: 设备类型
    
    Returns:
        各阶段资料完整性检查结果
    """
    results = []
    total_required = 0
    total_existing = 0
    total_missing_high = 0
    
    for phase in schedule_phases:
        result = check_schedule_phase_docs(phase, existing_docs, device_type)
        if result.get("ok"):
            results.append(result)
            total_required += result["total_required"]
            total_existing += result["total_existing"]
            total_missing_high += result["missing_high"]
    
    overall_completion = round(total_existing / max(total_required, 1) * 100, 1)
    
    return {
        "ok": True,
        "phases_checked": len(results),
        "total_required": total_required,
        "total_existing": total_existing,
        "total_missing_high": total_missing_high,
        "overall_completion_rate": overall_completion,
        "phase_results": results,
        "checked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _doc_exists(doc_type: str, existing_docs: list) -> bool:
    """检查资料是否已存在（模糊匹配）。"""
    doc_type_lower = doc_type.lower()
    for existing in existing_docs:
        existing_lower = existing.lower()
        if doc_type_lower == existing_lower:
            return True
        if doc_type_lower in existing_lower or existing_lower in doc_type_lower:
            return True
        doc_keywords = doc_type_lower.replace("记录", "").replace("报告", "").replace("证书", "").strip()
        existing_keywords = existing_lower.replace("记录", "").replace("报告", "").replace("证书", "").strip()
        if doc_keywords and existing_keywords and (doc_keywords in existing_keywords or existing_keywords in doc_keywords):
            return True
    return False
