"""
v0.1.103：矿山设备故障诊断AI助手（基于常见故障库）

基于设备常见故障库进行智能故障诊断，支持症状描述、故障现象分析、
可能原因排查、处理建议、预防措施等。
"""

import os
import json
import datetime
from typing import Optional


# 故障诊断知识库（扩展常见故障）
FAULT_DATABASE = {
    "球磨机": {
        "common_faults": [
            {
                "fault": "主轴承温度过高",
                "symptoms": ["轴承温度超过65℃", "轴承温升超过35℃", "轴承有异响", "润滑油温度升高"],
                "causes": [
                    "润滑不良：润滑油不足、油质恶化、油路堵塞",
                    "轴瓦接触不良：轴瓦刮研不合格、接触点不均匀",
                    "冷却水中断或水量不足",
                    "负荷过大：给矿量过多、钢球装载量过多",
                    "轴承安装不正：轴瓦间隙不当、同轴度超差",
                    "润滑油牌号不对或油温过高",
                ],
                "solutions": [
                    "检查润滑系统，补充或更换润滑油，清洗油路",
                    "停机检查轴瓦接触情况，必要时重新刮研",
                    "恢复冷却水供应，检查冷却水管路",
                    "调整给矿量和钢球装载量，降低负荷",
                    "检查轴承安装精度，调整轴瓦间隙和同轴度",
                    "更换正确牌号的润滑油，检查冷却系统",
                ],
                "prevention": [
                    "定期检查润滑系统，按规定更换润滑油",
                    "定期检查轴瓦接触情况，及时维护",
                    "保证冷却水供应正常，定期清理冷却器",
                    "严格控制给矿量和钢球装载量",
                    "定期检测轴承温度，建立温度监测记录",
                ],
                "severity": "high",
                "urgency": "立即停机检查",
            },
            {
                "fault": "齿轮异响或振动大",
                "symptoms": ["齿轮啮合有异响", "齿轮箱振动增大", "齿面有磨损或点蚀", "齿轮温度升高"],
                "causes": [
                    "齿轮啮合间隙不当：间隙过大或过小",
                    "齿面磨损严重：齿面点蚀、剥落、胶合",
                    "润滑不良：润滑油不足、油质恶化",
                    "齿轮安装不正：两轴不平行、中心距超差",
                    "负荷过大或冲击负荷",
                    "齿轮制造质量差：齿形误差、热处理不合格",
                ],
                "solutions": [
                    "检查并调整齿轮啮合间隙至规定范围",
                    "检查齿面磨损情况，严重磨损时更换齿轮",
                    "补充或更换润滑油，检查润滑系统",
                    "检查齿轮安装精度，调整两轴平行度和中心距",
                    "调整负荷，避免冲击负荷",
                    "更换合格齿轮，检查制造质量",
                ],
                "prevention": [
                    "定期检查齿轮啮合间隙和齿面磨损情况",
                    "保证润滑系统正常，按规定更换润滑油",
                    "定期检测齿轮振动和温度",
                    "严格控制负荷，避免超负荷运行",
                    "安装时严格控制安装精度",
                ],
                "severity": "medium",
                "urgency": "尽快检查处理",
            },
            {
                "fault": "筒体振动大",
                "symptoms": ["筒体振动明显增大", "基础有振动", "衬板螺栓松动", "轴承振动增大"],
                "causes": [
                    "衬板松动或脱落：衬板螺栓松动、衬板磨损",
                    "钢球装载不均：钢球偏载、钢球级配不合理",
                    "基础松动：地脚螺栓松动、基础沉降",
                    "给矿不均：给矿量波动大、偏载",
                    "筒体变形：筒体椭圆度超差",
                    "轴承间隙过大",
                ],
                "solutions": [
                    "停机检查衬板，紧固或更换松动衬板",
                    "调整钢球装载量和级配，保证均匀装载",
                    "紧固地脚螺栓，检查基础沉降情况",
                    "稳定给矿量，避免偏载",
                    "检查筒体变形情况，必要时修复",
                    "调整轴承间隙至规定范围",
                ],
                "prevention": [
                    "定期检查衬板紧固情况，及时紧固或更换",
                    "定期补充钢球，保持合理级配",
                    "定期检查地脚螺栓和基础",
                    "稳定给矿量，避免大幅波动",
                    "定期检测筒体振动",
                ],
                "severity": "medium",
                "urgency": "尽快检查处理",
            },
            {
                "fault": "漏浆",
                "symptoms": ["端盖处漏浆", "筒体法兰漏浆", "出料口漏浆", "基础有矿浆"],
                "causes": [
                    "端盖密封磨损：密封胶条老化、密封面磨损",
                    "衬板螺栓松动：螺栓密封垫损坏",
                    "法兰连接螺栓松动：法兰密封面损坏",
                    "筒体焊缝开裂",
                    "出料端密封损坏",
                    "矿浆液位过高",
                ],
                "solutions": [
                    "更换端盖密封胶条，修复密封面",
                    "紧固衬板螺栓，更换密封垫",
                    "紧固法兰螺栓，更换密封垫片",
                    "检查筒体焊缝，补焊修复",
                    "更换出料端密封",
                    "调整矿浆液位至正常范围",
                ],
                "prevention": [
                    "定期检查密封件，及时更换老化密封",
                    "定期紧固衬板螺栓和法兰螺栓",
                    "定期检查筒体焊缝",
                    "控制矿浆液位在正常范围",
                ],
                "severity": "low",
                "urgency": "安排时间处理",
            },
        ],
        "monitoring_parameters": [
            {"name": "主轴承温度", "normal_range": "≤65℃", "alarm_threshold": "70℃", "shutdown_threshold": "75℃"},
            {"name": "齿轮箱温度", "normal_range": "≤60℃", "alarm_threshold": "65℃", "shutdown_threshold": "70℃"},
            {"name": "润滑油温度", "normal_range": "≤50℃", "alarm_threshold": "55℃", "shutdown_threshold": "60℃"},
            {"name": "振动速度", "normal_range": "≤4.5mm/s", "alarm_threshold": "7.1mm/s", "shutdown_threshold": "11.2mm/s"},
            {"name": "电机电流", "normal_range": "额定电流±10%", "alarm_threshold": "额定电流+15%", "shutdown_threshold": "额定电流+20%"},
        ],
    },
    "高压釜": {
        "common_faults": [
            {
                "fault": "钛衬里腐蚀泄漏",
                "symptoms": ["釜体表面有积液", "保温层潮湿", "压力下降", "温度异常"],
                "causes": [
                    "钛衬里焊接缺陷：未焊透、气孔、裂纹",
                    "钛衬里机械损伤：安装时划伤、碰撞",
                    "介质冲刷腐蚀：流速过高、含固体颗粒",
                    "电偶腐蚀：与其他金属接触",
                    "氢脆：吸氢导致脆性",
                    "温度过高导致腐蚀加速",
                ],
                "solutions": [
                    "停车泄压，进行电火花检测定位泄漏点",
                    "对泄漏点进行补焊修复，焊后重新检测",
                    "严重腐蚀时更换钛衬里",
                    "检查介质成分和流速，调整工艺参数",
                    "消除电偶腐蚀源，隔离不同金属接触",
                    "控制操作温度在设计范围内",
                ],
                "prevention": [
                    "定期进行钛衬里电火花检测",
                    "安装时保护钛衬里，避免机械损伤",
                    "严格控制介质成分和流速",
                    "定期检查保温层，发现潮湿及时处理",
                    "严格控制操作温度和压力",
                ],
                "severity": "high",
                "urgency": "立即停车检查",
            },
            {
                "fault": "机械密封泄漏",
                "symptoms": ["搅拌轴处有液体泄漏", "密封腔压力下降", "润滑油乳化", "轴套磨损"],
                "causes": [
                    "密封面磨损：密封面研磨不良、介质含颗粒",
                    "弹簧失效：弹簧腐蚀、疲劳、断裂",
                    "冷却水中断：密封面温度过高",
                    "安装不正：密封面与轴不垂直",
                    "介质腐蚀：密封材料不耐腐蚀",
                    "压力波动大：密封面受力不均",
                ],
                "solutions": [
                    "停车更换机械密封",
                    "检查密封面磨损情况，研磨或更换",
                    "更换弹簧，检查弹簧力",
                    "恢复冷却水供应，检查冷却管路",
                    "重新安装机械密封，保证安装精度",
                    "更换耐腐蚀性密封材料",
                    "稳定操作压力，减少波动",
                ],
                "prevention": [
                    "定期检查机械密封泄漏情况",
                    "保证冷却水供应正常",
                    "严格控制介质清洁度",
                    "安装时保证安装精度",
                    "定期更换机械密封（按使用寿命）",
                ],
                "severity": "medium",
                "urgency": "尽快处理",
            },
            {
                "fault": "搅拌轴振动大",
                "symptoms": ["搅拌轴振动明显", "减速机振动增大", "轴承温度升高", "密封泄漏"],
                "causes": [
                    "轴承磨损：轴承间隙过大、保持架损坏",
                    "轴弯曲：轴变形、同轴度超差",
                    "叶轮不平衡：叶轮磨损不均、结垢",
                    "安装不正：减速机与釜体不同心",
                    "负荷过大：介质密度大、液位高",
                    "叶轮松动：叶轮固定螺栓松动",
                ],
                "solutions": [
                    "更换轴承，调整轴承间隙",
                    "校直或更换搅拌轴",
                    "清理叶轮结垢，做动平衡",
                    "重新找正减速机与釜体同轴度",
                    "调整负荷，降低介质密度或液位",
                    "紧固叶轮固定螺栓",
                ],
                "prevention": [
                    "定期检测搅拌轴振动",
                    "定期检查轴承温度和磨损情况",
                    "定期清理叶轮结垢",
                    "安装时严格控制同轴度",
                    "定期紧固叶轮螺栓",
                ],
                "severity": "medium",
                "urgency": "尽快检查处理",
            },
            {
                "fault": "安全阀起跳",
                "symptoms": ["安全阀泄漏", "釜内压力骤降", "有异常声响", "介质喷出"],
                "causes": [
                    "超压：进料过多、加热过快、反应剧烈",
                    "安全阀整定压力漂移",
                    "安全阀阀芯卡死或损坏",
                    "出口管路堵塞",
                    "压力控制系统失灵",
                    "操作失误",
                ],
                "solutions": [
                    "立即停止加热和进料，开启泄压",
                    "检查超压原因，调整工艺参数",
                    "重新校验安全阀，整定压力",
                    "检修或更换安全阀",
                    "清理出口管路",
                    "检查压力控制系统，修复失灵部件",
                    "加强操作培训，避免误操作",
                ],
                "prevention": [
                    "严格控制操作压力在设计范围内",
                    "定期校验安全阀（每年至少一次）",
                    "定期检查压力控制系统",
                    "安装超压报警和联锁装置",
                    "加强操作人员培训",
                ],
                "severity": "high",
                "urgency": "立即处理",
            },
        ],
        "monitoring_parameters": [
            {"name": "釜内压力", "normal_range": "≤设计压力", "alarm_threshold": "设计压力90%", "shutdown_threshold": "设计压力95%"},
            {"name": "釜内温度", "normal_range": "≤设计温度", "alarm_threshold": "设计温度95%", "shutdown_threshold": "设计温度"},
            {"name": "搅拌轴振动", "normal_range": "≤4.5mm/s", "alarm_threshold": "7.1mm/s", "shutdown_threshold": "11.2mm/s"},
            {"name": "机械密封泄漏", "normal_range": "≤5滴/分", "alarm_threshold": "10滴/分", "shutdown_threshold": "连续泄漏"},
            {"name": "搅拌电机电流", "normal_range": "额定电流±10%", "alarm_threshold": "额定电流+15%", "shutdown_threshold": "额定电流+20%"},
        ],
    },
}


# 通用故障诊断逻辑
def diagnose_fault(
    equipment_name: str,
    symptoms: list,
    fault_description: str = "",
) -> dict:
    """
    基于症状进行故障诊断。
    
    Args:
        equipment_name: 设备名称
        symptoms: 故障症状列表
        fault_description: 故障描述
    
    Returns:
        诊断结果
    """
    # 获取设备故障库
    equipment_faults = FAULT_DATABASE.get(equipment_name, {})
    
    if not equipment_faults:
        # 尝试从mining_equipment_detail获取常见故障
        try:
            from . import mining_equipment_detail as _med
            detail_result = _med.get_equipment_detail(equipment_name)
            if detail_result.get("ok"):
                common_faults = detail_result["detail"].get("common_faults", [])
                return {
                    "ok": True,
                    "equipment": equipment_name,
                    "diagnosis_method": "知识库匹配",
                    "input_symptoms": symptoms,
                    "possible_faults": common_faults,
                    "suggestion": "根据设备常见故障库，建议对照上述故障进行排查",
                    "note": "该设备暂无详细故障诊断库，使用通用常见故障库",
                }
        except Exception:
            pass
        
        return {
            "ok": False,
            "error": f"未找到设备故障诊断库: {equipment_name}",
            "available_equipment": list(FAULT_DATABASE.keys()),
        }
    
    common_faults = equipment_faults.get("common_faults", [])
    
    # 匹配症状
    matched_faults = []
    for fault in common_faults:
        fault_symptoms = fault.get("symptoms", [])
        match_count = 0
        matched_symptoms = []
        for symptom in symptoms:
            for fs in fault_symptoms:
                if symptom in fs or fs in symptom:
                    match_count += 1
                    matched_symptoms.append(fs)
                    break
        
        if match_count > 0:
            match_rate = round(match_count / len(fault_symptoms) * 100, 1)
            matched_faults.append({
                "fault": fault["fault"],
                "match_count": match_count,
                "match_rate": match_rate,
                "matched_symptoms": matched_symptoms,
                "severity": fault.get("severity", "medium"),
                "urgency": fault.get("urgency", ""),
                "causes": fault.get("causes", []),
                "solutions": fault.get("solutions", []),
                "prevention": fault.get("prevention", []),
            })
    
    # 按匹配度排序
    matched_faults.sort(key=lambda x: x["match_rate"], reverse=True)
    
    # 生成诊断建议
    if matched_faults:
        top_fault = matched_faults[0]
        suggestion = f"根据症状匹配，最可能的故障是「{top_fault['fault']}」（匹配度{top_fault['match_rate']}%）。建议：{top_fault['urgency']}。"
        if top_fault["solutions"]:
            suggestion += f" 处理方法：{top_fault['solutions'][0]}"
    else:
        suggestion = "未能匹配到具体故障，建议进行全面检查，或提供更详细的故障症状描述。"
    
    return {
        "ok": True,
        "equipment": equipment_name,
        "diagnosis_method": "症状匹配",
        "input_symptoms": symptoms,
        "fault_description": fault_description,
        "possible_faults": matched_faults,
        "total_matched": len(matched_faults),
        "most_likely_fault": matched_faults[0]["fault"] if matched_faults else "",
        "suggestion": suggestion,
        "monitoring_parameters": equipment_faults.get("monitoring_parameters", []),
        "diagnosed_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_equipment_faults(equipment_name: str) -> dict:
    """获取设备常见故障列表。"""
    equipment_faults = FAULT_DATABASE.get(equipment_name, {})
    
    if not equipment_faults:
        # 尝试从mining_equipment_detail获取
        try:
            from . import mining_equipment_detail as _med
            detail_result = _med.get_equipment_detail(equipment_name)
            if detail_result.get("ok"):
                return {
                    "ok": True,
                    "equipment": equipment_name,
                    "common_faults": detail_result["detail"].get("common_faults", []),
                    "monitoring_parameters": [],
                    "note": "使用通用常见故障库",
                }
        except Exception:
            pass
        
        return {
            "ok": False,
            "error": f"未找到设备故障库: {equipment_name}",
            "available_equipment": list(FAULT_DATABASE.keys()),
        }
    
    return {
        "ok": True,
        "equipment": equipment_name,
        "common_faults": equipment_faults.get("common_faults", []),
        "monitoring_parameters": equipment_faults.get("monitoring_parameters", []),
        "total_faults": len(equipment_faults.get("common_faults", [])),
    }


def get_fault_detail(equipment_name: str, fault_name: str) -> dict:
    """获取故障详细信息。"""
    equipment_faults = FAULT_DATABASE.get(equipment_name, {})
    
    if not equipment_faults:
        return {"ok": False, "error": f"未找到设备故障库: {equipment_name}"}
    
    for fault in equipment_faults.get("common_faults", []):
        if fault["fault"] == fault_name or fault_name in fault["fault"]:
            return {
                "ok": True,
                "equipment": equipment_name,
                "fault_detail": fault,
            }
    
    return {"ok": False, "error": f"未找到故障: {fault_name}"}


def get_monitoring_parameters(equipment_name: str) -> dict:
    """获取设备监测参数。"""
    equipment_faults = FAULT_DATABASE.get(equipment_name, {})
    
    if not equipment_faults:
        return {
            "ok": True,
            "equipment": equipment_name,
            "monitoring_parameters": [],
            "note": "该设备暂无监测参数库",
        }
    
    return {
        "ok": True,
        "equipment": equipment_name,
        "monitoring_parameters": equipment_faults.get("monitoring_parameters", []),
        "total_parameters": len(equipment_faults.get("monitoring_parameters", [])),
    }


def get_fault_diagnosis_stats() -> dict:
    """获取故障诊断库统计。"""
    total_equipment = len(FAULT_DATABASE)
    total_faults = sum(len(eq.get("common_faults", [])) for eq in FAULT_DATABASE.values())
    total_monitoring = sum(len(eq.get("monitoring_parameters", [])) for eq in FAULT_DATABASE.values())
    
    equipment_stats = []
    for name, data in FAULT_DATABASE.items():
        equipment_stats.append({
            "equipment": name,
            "faults_count": len(data.get("common_faults", [])),
            "monitoring_count": len(data.get("monitoring_parameters", [])),
        })
    
    return {
        "ok": True,
        "total_equipment": total_equipment,
        "total_faults": total_faults,
        "total_monitoring_parameters": total_monitoring,
        "equipment_stats": equipment_stats,
    }


def generate_fault_diagnosis_prompt(
    equipment_name: str,
    symptoms: list,
    fault_description: str = "",
) -> dict:
    """
    生成故障诊断AI提示词。
    
    Args:
        equipment_name: 设备名称
        symptoms: 故障症状
        fault_description: 故障描述
    
    Returns:
        AI提示词
    """
    system_prompt = f"""你是一位资深的矿山设备故障诊断专家，精通{equipment_name}的结构、原理、运行维护和故障诊断。

你的任务：
1. 根据用户提供的故障症状和描述，分析可能的故障原因
2. 给出详细的排查步骤和处理建议
3. 提供预防措施和维护建议
4. 提醒安全注意事项

回答要求：
- 先给出最可能的故障判断
- 列出可能的原因（按可能性排序）
- 给出具体的排查步骤
- 提供处理方法和注意事项
- 给出预防措施
- 涉及安全的必须强调安全注意事项
"""
    
    user_prompt = f"""设备：{equipment_name}

故障症状：
{chr(10).join(['- ' + s for s in symptoms])}

故障描述：{fault_description or '用户未提供详细描述'}

请进行故障诊断，给出可能的原因、排查步骤、处理建议和预防措施。"""
    
    return {
        "ok": True,
        "equipment": equipment_name,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "full_prompt": system_prompt + "\n\n" + user_prompt,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
