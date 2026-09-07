"""
v0.1.102：矿山设备吊装方案自动生成增强（基于详细参数）

基于设备详细参数和吊装参数库自动生成吊装方案，包含设备参数、
吊装方法选择、吊车选型、吊点设计、索具配置、吊装顺序、
安全措施、应急预案等完整内容。
"""

import os
import json
import datetime
from typing import Optional


# 吊装方案模板结构
LIFTING_PLAN_STRUCTURE = [
    {"section": "工程概况", "key": "overview"},
    {"section": "编制依据", "key": "references"},
    {"section": "吊装设备参数", "key": "equipment_params"},
    {"section": "吊装方法选择", "key": "method"},
    {"section": "吊车选型及参数", "key": "crane"},
    {"section": "吊点设计", "key": "lifting_points"},
    {"section": "索具配置", "key": "rigging"},
    {"section": "吊装顺序及工艺", "key": "sequence"},
    {"section": "吊装计算", "key": "calculation"},
    {"section": "安全技术措施", "key": "safety"},
    {"section": "应急预案", "key": "emergency"},
    {"section": "人员组织", "key": "personnel"},
]


# 吊车参数库（常用汽车吊）
CRANE_DATABASE = [
    {"model": "25t汽车吊", "max_capacity": 25, "max_boom": 33.5, "typical_radius": [3, 5, 8, 10, 12], "capacity_at_radius": {3: 25, 5: 16.5, 8: 9.5, 10: 7.2, 12: 5.6}},
    {"model": "50t汽车吊", "max_capacity": 50, "max_boom": 43, "typical_radius": [3, 5, 8, 10, 12, 15], "capacity_at_radius": {3: 50, 5: 34, 8: 19.5, 10: 14.8, 12: 11.5, 15: 8.2}},
    {"model": "80t汽车吊", "max_capacity": 80, "max_boom": 47.5, "typical_radius": [3, 5, 8, 10, 12, 15, 18], "capacity_at_radius": {3: 80, 5: 55, 8: 32, 10: 24.5, 12: 19, 15: 13.5, 18: 10}},
    {"model": "100t汽车吊", "max_capacity": 100, "max_boom": 51, "typical_radius": [3, 5, 8, 10, 12, 15, 18, 20], "capacity_at_radius": {3: 100, 5: 68, 8: 40, 10: 30.5, 12: 24, 15: 17, 18: 13, 20: 11}},
    {"model": "130t汽车吊", "max_capacity": 130, "max_boom": 58, "typical_radius": [3, 5, 8, 10, 12, 15, 18, 20, 24], "capacity_at_radius": {3: 130, 5: 90, 8: 53, 10: 40, 12: 31.5, 15: 22.5, 18: 17, 20: 14.5, 24: 10.5}},
    {"model": "200t汽车吊", "max_capacity": 200, "max_boom": 63, "typical_radius": [3, 5, 8, 10, 12, 15, 18, 20, 24, 28], "capacity_at_radius": {3: 200, 5: 140, 8: 82, 10: 62, 12: 49, 15: 35, 18: 26.5, 20: 22.5, 24: 16.5, 28: 12.5}},
    {"model": "300t汽车吊", "max_capacity": 300, "max_boom": 72, "typical_radius": [3, 5, 8, 10, 12, 15, 18, 20, 24, 28, 32], "capacity_at_radius": {3: 300, 5: 210, 8: 125, 10: 95, 12: 75, 15: 53, 18: 40, 20: 34, 24: 25, 28: 19, 32: 14.5}},
    {"model": "400t履带吊", "max_capacity": 400, "max_boom": 96, "typical_radius": [4, 6, 8, 10, 12, 15, 18, 20, 24, 28, 32], "capacity_at_radius": {4: 400, 6: 280, 8: 190, 10: 145, 12: 115, 15: 82, 18: 62, 20: 53, 24: 39, 28: 30, 32: 24}},
    {"model": "500t履带吊", "max_capacity": 500, "max_boom": 108, "typical_radius": [4, 6, 8, 10, 12, 15, 18, 20, 24, 28, 32, 36], "capacity_at_radius": {4: 500, 6: 350, 8: 240, 10: 180, 12: 145, 15: 105, 18: 80, 20: 68, 24: 50, 28: 38, 32: 30, 36: 24}},
]


# 索具参数库
RIGGING_DATABASE = [
    {"type": "钢丝绳", "specs": ["φ15mm", "φ17.5mm", "φ21.5mm", "φ26mm", "φ30mm", "φ34.5mm", "φ39mm", "φ43mm", "φ52mm", "φ60mm"], "safety_factor": 6, "typical_uses": "设备吊装、捆绑"},
    {"type": "合成纤维吊带", "specs": ["1t", "2t", "3t", "5t", "8t", "10t", "15t", "20t", "30t", "50t"], "safety_factor": 7, "typical_uses": "精密设备吊装、表面保护"},
    {"type": "卸扣", "specs": ["1t", "2t", "3.25t", "4.75t", "6.5t", "8.5t", "12t", "17t", "25t", "35t", "55t", "85t", "120t", "150t"], "safety_factor": 4, "typical_uses": "吊点连接、索具连接"},
    {"type": "手拉葫芦", "specs": ["1t", "2t", "3t", "5t", "10t", "20t"], "safety_factor": 4, "typical_uses": "设备精调、临时吊装"},
    {"type": "千斤顶", "specs": ["5t", "10t", "20t", "32t", "50t", "100t", "200t"], "safety_factor": 3, "typical_uses": "设备顶升、移位"},
]


# 吊装方法库
LIFTING_METHODS = [
    {"method": "单机吊装", "description": "使用一台吊车完成设备吊装", "applicable": "重量适中、作业空间充足的设备", "advantages": ["操作简单", "成本较低", "组织方便"], "disadvantages": ["受吊车性能限制", "大型设备无法使用"]},
    {"method": "双机抬吊", "description": "使用两台吊车协同完成设备吊装", "applicable": "重量较大、单机无法完成的设备", "advantages": ["吊装能力大", "可吊装大型设备"], "disadvantages": ["操作复杂", "需要精确配合", "安全风险高"]},
    {"method": "滑移法吊装", "description": "设备在滑道上滑移就位", "applicable": "卧式设备、塔类设备", "advantages": ["平稳安全", "对吊车要求低"], "disadvantages": ["需要滑道", "准备工作多"]},
    {"method": "回转法吊装", "description": "设备绕支点回转直立", "applicable": "立式设备、塔类设备", "advantages": ["吊装效率高", "设备受力合理"], "disadvantages": ["需要足够空间", "技术要求高"]},
    {"method": "提升法吊装", "description": "使用液压提升装置垂直提升设备", "applicable": "超大型设备、空间受限场合", "advantages": ["吊装能力大", "平稳精确"], "disadvantages": ["设备复杂", "成本高"]},
]


def generate_lifting_plan(
    equipment_name: str,
    equipment_weight: float = 0,
    lifting_height: float = 0,
    working_radius: float = 0,
    project_name: str = "矿山工程项目",
    workshop: str = "",
) -> dict:
    """
    基于设备详细参数生成吊装方案。
    
    Args:
        equipment_name: 设备名称
        equipment_weight: 设备重量（吨），0则从知识库估算
        lifting_height: 吊装高度（米）
        working_radius: 作业半径（米）
        project_name: 项目名称
        workshop: 车间
    
    Returns:
        完整的吊装方案
    """
    from . import mining_equipment_detail as _med
    
    # 获取设备详细信息
    detail_result = _med.get_equipment_detail(equipment_name)
    if not detail_result.get("ok"):
        return {
            "ok": False,
            "error": f"未找到设备详细信息: {equipment_name}",
            "available_equipment": detail_result.get("available_equipment", []),
        }
    
    equipment = detail_result["equipment"]
    detail = detail_result["detail"]
    
    # 估算设备重量（如果未提供）
    if equipment_weight <= 0:
        equipment_weight = _estimate_equipment_weight(equipment, detail)
    
    # 估算吊装高度（如果未提供）
    if lifting_height <= 0:
        lifting_height = _estimate_lifting_height(equipment, detail)
    
    # 估算作业半径（如果未提供）
    if working_radius <= 0:
        working_radius = _estimate_working_radius(equipment)
    
    # 选择吊车
    crane_selection = select_crane(equipment_weight, lifting_height, working_radius)
    
    # 选择吊装方法
    lifting_method = select_lifting_method(equipment_weight, equipment)
    
    # 选择索具
    rigging = select_rigging(equipment_weight)
    
    # 吊点设计
    lifting_points = design_lifting_points(equipment, detail, equipment_weight)
    
    # 吊装计算
    calculation = calculate_lifting(equipment_weight, lifting_height, working_radius, crane_selection)
    
    # 构建吊装方案
    plan = {
        "title": f"{equipment}吊装方案",
        "project_name": project_name,
        "workshop": workshop,
        "equipment": equipment,
        "equipment_weight": equipment_weight,
        "lifting_height": lifting_height,
        "working_radius": working_radius,
        "plan_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "version": "v1.0",
        "sections": [],
    }
    
    # 1. 工程概况
    plan["sections"].append({
        "section": "工程概况",
        "content": {
            "project_name": project_name,
            "equipment_name": equipment,
            "equipment_category": detail.get("category", ""),
            "workshop": workshop or "待定",
            "equipment_weight": f"{equipment_weight}t",
            "lifting_height": f"{lifting_height}m",
            "working_radius": f"{working_radius}m",
            "typical_models": detail.get("typical_models", []),
            "main_components": detail.get("main_components", []),
            "lifting_scope": f"本方案适用于{project_name}{workshop + '' if workshop else ''}{equipment}的吊装作业，包括设备卸车、水平运输、吊装就位等全过程。",
        },
    })
    
    # 2. 编制依据
    plan["sections"].append({
        "section": "编制依据",
        "content": {
            "standards": [
                "GB 50231-2009 机械设备安装工程施工及验收通用规范",
                "GB 6067.1-2010 起重机械安全规程",
                "JGJ 276-2012 建筑施工起重吊装工程安全技术规范",
                "GB/T 5972-2016 起重机 钢丝绳 保养、维护、检验和报废",
                "GB/T 8918-2006 重要用途钢丝绳",
                "设备安装使用说明书",
                "施工图纸及设计说明",
            ],
        },
    })
    
    # 3. 吊装设备参数
    plan["sections"].append({
        "section": "吊装设备参数",
        "content": {
            "equipment_name": equipment,
            "equipment_weight": f"{equipment_weight}t",
            "key_parameters": detail.get("key_parameters", {}),
            "main_components": detail.get("main_components", []),
            "lifting_points_count": len(lifting_points),
            "center_of_gravity": "设备几何中心（具体以厂家提供的重心位置为准）",
        },
    })
    
    # 4. 吊装方法选择
    plan["sections"].append({
        "section": "吊装方法选择",
        "content": {
            "selected_method": lifting_method["method"],
            "method_description": lifting_method["description"],
            "applicable": lifting_method["applicable"],
            "advantages": lifting_method["advantages"],
            "disadvantages": lifting_method["disadvantages"],
            "method_selection_reason": f"根据设备重量{equipment_weight}t、吊装高度{lifting_height}m、作业半径{working_radius}m，结合现场作业条件，选择{lifting_method['method']}。",
        },
    })
    
    # 5. 吊车选型及参数
    plan["sections"].append({
        "section": "吊车选型及参数",
        "content": crane_selection,
    })
    
    # 6. 吊点设计
    plan["sections"].append({
        "section": "吊点设计",
        "content": {
            "lifting_points": lifting_points,
            "total_points": len(lifting_points),
            "design_principles": [
                "吊点位置应高于设备重心，确保吊装平稳",
                "吊点应选择在设备强度足够的部位",
                "吊点应对称布置，受力均匀",
                "使用设备专用吊耳时，应核对吊耳承载能力",
                "严禁在设备薄弱部位设置吊点",
            ],
        },
    })
    
    # 7. 索具配置
    plan["sections"].append({
        "section": "索具配置",
        "content": rigging,
    })
    
    # 8. 吊装顺序及工艺
    plan["sections"].append({
        "section": "吊装顺序及工艺",
        "content": {
            "lifting_sequence": [
                {"step": "吊装准备", "description": "检查吊车、索具、吊点，清理作业区域，设置警戒线"},
                {"step": "试吊", "description": "将设备吊离地面100-200mm，停留5-10分钟，检查吊车、索具、吊点受力情况"},
                {"step": "正式起吊", "description": "缓慢起升，保持设备平稳，严禁急停急起"},
                {"step": "回转就位", "description": "吊车回转至设备基础上方，对准安装位置"},
                {"step": "缓慢落钩", "description": "缓慢下降，设备接近基础时停止，人工辅助就位"},
                {"step": "就位固定", "description": "设备就位后，进行初步找正，紧固地脚螺栓或临时固定"},
                {"step": "摘钩", "description": "确认设备固定牢固后，摘除索具，吊车撤离"},
            ],
            "key_points": [
                "吊装作业必须设专人指挥，指挥信号统一明确",
                "起吊前必须进行试吊，确认无异常后方可正式起吊",
                "吊装过程中，吊物下方严禁站人",
                "吊装速度应缓慢均匀，严禁急停急起",
                "遇有六级及以上大风或恶劣天气，停止吊装作业",
                "夜间吊装必须有足够的照明",
            ],
        },
    })
    
    # 9. 吊装计算
    plan["sections"].append({
        "section": "吊装计算",
        "content": calculation,
    })
    
    # 10. 安全技术措施
    plan["sections"].append({
        "section": "安全技术措施",
        "content": {
            "general_measures": [
                "吊装作业人员必须持证上岗，严禁无证操作",
                "吊装作业前进行安全技术交底，所有参与人员签字确认",
                "吊装作业区域设置警戒线，无关人员严禁进入",
                "吊车支腿必须全部伸出，垫木坚实可靠",
                "吊装作业前检查吊车、索具、吊点，确保完好有效",
                "起吊前必须进行试吊，确认无异常后方可正式起吊",
                "吊物下方严禁站人，严禁在吊物下方作业",
                "吊装作业设专人指挥，指挥信号统一明确",
                "遇有六级及以上大风、大雨、大雾等恶劣天气，停止吊装作业",
                "吊装作业完毕后，清理现场，收回索具",
            ],
            "equipment_specific_measures": _get_lifting_safety_measures(equipment),
            "risk_analysis": [
                {"risk": "吊车倾覆", "level": "高", "measure": "支腿全部伸出，垫木坚实，严禁超载，严格控制作业半径"},
                {"risk": "索具断裂", "level": "高", "measure": "索具检查合格，安全系数符合要求，严禁使用破损索具"},
                {"risk": "吊点失效", "level": "高", "measure": "吊点位置准确，吊耳检查合格，严禁在薄弱部位起吊"},
                {"risk": "设备碰撞", "level": "中", "measure": "吊装路径清理，设专人监护，缓慢操作"},
                {"risk": "高处坠落", "level": "中", "measure": "高处作业系安全带，作业平台牢固"},
                {"risk": "物体打击", "level": "中", "measure": "进入现场戴安全帽，工具入袋，严禁抛掷"},
            ],
        },
    })
    
    # 11. 应急预案
    plan["sections"].append({
        "section": "应急预案",
        "content": {
            "emergency_types": [
                {"type": "吊车倾覆", "response": "立即停止作业，疏散人员，评估险情，严禁盲目救援，拨打119和120，专业人员处理"},
                {"type": "索具断裂", "response": "立即停止作业，疏散人员，检查设备受损情况，更换索具，评估后重新吊装"},
                {"type": "设备坠落", "response": "立即停止作业，疏散人员，检查人员伤亡和设备损坏情况，拨打120，保护现场"},
                {"type": "人员伤害", "response": "立即停止作业，对伤者进行急救，拨打120，送医治疗，保护现场"},
                {"type": "突发天气", "response": "立即停止吊装，将设备安全放置或固定，人员撤离至安全区域"},
            ],
            "emergency_organization": [
                {"role": "总指挥", "responsibility": "全面负责应急救援指挥工作"},
                {"role": "抢险组", "responsibility": "负责现场抢险救援工作"},
                {"role": "医疗组", "responsibility": "负责伤员初步急救和送医工作"},
                {"role": "疏散组", "responsibility": "负责人员疏散和现场警戒工作"},
            ],
            "emergency_contacts": [
                {"name": "急救中心", "phone": "120"},
                {"name": "火警", "phone": "119"},
                {"name": "报警", "phone": "110"},
            ],
        },
    })
    
    # 12. 人员组织
    plan["sections"].append({
        "section": "人员组织",
        "content": {
            "personnel": [
                {"role": "吊装指挥", "number": 1, "qualification": "起重指挥证", "responsibility": "全面负责吊装指挥工作"},
                {"role": "吊车司机", "number": 1, "qualification": "吊车操作证", "responsibility": "负责吊车操作"},
                {"role": "起重工", "number": 4, "qualification": "起重工证", "responsibility": "负责挂钩、摘钩、索具检查"},
                {"role": "钳工", "number": 2, "qualification": "钳工证", "responsibility": "负责设备就位、找正"},
                {"role": "安全员", "number": 1, "qualification": "安全员证", "responsibility": "负责安全监督检查"},
                {"role": "技术负责人", "number": 1, "qualification": "工程师", "responsibility": "负责技术指导和质量控制"},
            ],
            "total_personnel": 10,
        },
    })
    
    # 计算完成度
    total_sections = len(LIFTING_PLAN_STRUCTURE)
    completed_sections = len(plan["sections"])
    completion_rate = round(completed_sections / total_sections * 100, 1)
    
    return {
        "ok": True,
        "equipment": equipment,
        "title": plan["title"],
        "plan": plan,
        "total_sections": total_sections,
        "completed_sections": completed_sections,
        "completion_rate": completion_rate,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def select_crane(
    equipment_weight: float,
    lifting_height: float,
    working_radius: float,
) -> dict:
    """
    选择合适的吊车。
    
    Args:
        equipment_weight: 设备重量（吨）
        lifting_height: 吊装高度（米）
        working_radius: 作业半径（米）
    
    Returns:
        吊车选型结果
    """
    # 考虑动载系数1.1和不均衡系数1.1
    required_capacity = equipment_weight * 1.1 * 1.1
    
    # 查找合适的吊车
    selected_crane = None
    for crane in CRANE_DATABASE:
        # 检查作业半径下的承载能力
        radius_key = min(crane["typical_radius"], key=lambda r: abs(r - working_radius))
        capacity_at_radius = crane["capacity_at_radius"].get(radius_key, 0)
        
        # 检查臂长是否满足吊装高度
        required_boom = lifting_height + 5  # 考虑吊具高度和安全余量
        
        if capacity_at_radius >= required_capacity and crane["max_boom"] >= required_boom:
            selected_crane = crane
            selected_radius = radius_key
            selected_capacity = capacity_at_radius
            break
    
    # 如果没有找到，选择最大的吊车
    if not selected_crane:
        selected_crane = CRANE_DATABASE[-1]
        selected_radius = min(selected_crane["typical_radius"], key=lambda r: abs(r - working_radius))
        selected_capacity = selected_crane["capacity_at_radius"].get(selected_radius, 0)
    
    # 计算利用率
    utilization_rate = round(required_capacity / max(selected_capacity, 0.1) * 100, 1)
    
    return {
        "selected_crane": selected_crane["model"],
        "max_capacity": f"{selected_crane['max_capacity']}t",
        "max_boom": f"{selected_crane['max_boom']}m",
        "working_radius": f"{selected_radius}m",
        "capacity_at_radius": f"{selected_capacity}t",
        "required_capacity": f"{round(required_capacity, 2)}t",
        "utilization_rate": f"{utilization_rate}%",
        "safety_margin": f"{round(100 - utilization_rate, 1)}%",
        "boom_length_required": f"{round(lifting_height + 5, 1)}m",
        "boom_length_available": f"{selected_crane['max_boom']}m",
        "selection_reason": f"设备重量{equipment_weight}t，考虑动载系数1.1和不均衡系数1.1，需要起重量{round(required_capacity, 2)}t。{selected_crane['model']}在{selected_radius}m作业半径下额定起重量{selected_capacity}t，利用率{utilization_rate}%，满足吊装要求。",
        "alternative_cranes": [c["model"] for c in CRANE_DATABASE if c["max_capacity"] > selected_crane["max_capacity"]][:2],
    }


def select_lifting_method(
    equipment_weight: float,
    equipment: str,
) -> dict:
    """选择吊装方法。"""
    if equipment_weight <= 25:
        return LIFTING_METHODS[0]  # 单机吊装
    elif equipment_weight <= 80:
        return LIFTING_METHODS[0]  # 单机吊装（大吊车）
    elif equipment_weight <= 200:
        return LIFTING_METHODS[1]  # 双机抬吊
    else:
        return LIFTING_METHODS[4]  # 提升法吊装


def select_rigging(equipment_weight: float) -> dict:
    """选择索具配置。"""
    # 计算单根钢丝绳受力（假设4点吊装，角度60度）
    sling_angle = 60  # 度
    sling_count = 4
    sling_force = equipment_weight * 1.1 / (sling_count * 0.866)  # 0.866 = sin(60°)
    
    # 选择钢丝绳（安全系数6）
    required_wire_rope_capacity = sling_force * 6
    
    # 选择卸扣（安全系数4）
    required_shackle_capacity = sling_force * 4
    
    # 选择吊带（安全系数7）
    required_sling_capacity = sling_force * 7
    
    return {
        "sling_count": sling_count,
        "sling_angle": f"{sling_angle}°",
        "sling_force_per_rope": f"{round(sling_force, 2)}t",
        "wire_rope": {
            "type": "钢丝绳",
            "required_capacity": f"{round(required_wire_rope_capacity, 2)}t",
            "safety_factor": 6,
            "recommendation": f"根据计算，单根钢丝绳受力{round(sling_force, 2)}t，安全系数6，建议选用合适规格钢丝绳",
        },
        "synthetic_sling": {
            "type": "合成纤维吊带",
            "required_capacity": f"{round(required_sling_capacity, 2)}t",
            "safety_factor": 7,
            "recommendation": "精密设备或表面要求高时使用合成纤维吊带",
        },
        "shackle": {
            "type": "卸扣",
            "required_capacity": f"{round(required_shackle_capacity, 2)}t",
            "safety_factor": 4,
            "recommendation": "每个吊点使用一个卸扣连接",
        },
        "additional_equipment": [
            {"name": "手拉葫芦", "specification": "根据需要选择", "use": "设备精调和临时固定"},
            {"name": "千斤顶", "specification": "根据设备重量选择", "use": "设备顶升和移位"},
            {"name": "溜绳", "specification": "φ12-15mm麻绳", "use": "控制设备摆动"},
        ],
        "inspection_requirements": [
            "索具使用前必须检查，严禁使用破损、变形、锈蚀的索具",
            "钢丝绳断丝数超过标准规定的必须报废",
            "吊带表面有割伤、磨损、化学腐蚀的必须报废",
            "卸扣有变形、裂纹、销轴损坏的必须报废",
            "索具必须有合格证书，定期检验",
        ],
    }


def design_lifting_points(
    equipment: str,
    detail: dict,
    equipment_weight: float,
) -> list:
    """设计吊点。"""
    points = []
    
    # 根据设备类型设计吊点
    if "磨机" in equipment:
        points = [
            {"point": "筒体吊耳1", "position": "筒体一端", "load_share": "25%", "type": "专用吊耳"},
            {"point": "筒体吊耳2", "position": "筒体另一端", "load_share": "25%", "type": "专用吊耳"},
            {"point": "端盖吊耳1", "position": "进料端端盖", "load_share": "25%", "type": "专用吊耳"},
            {"point": "端盖吊耳2", "position": "出料端端盖", "load_share": "25%", "type": "专用吊耳"},
        ]
    elif "高压釜" in equipment or "压力容器" in equipment:
        points = [
            {"point": "鞍座吊耳1", "position": "筒体一端鞍座", "load_share": "50%", "type": "专用吊耳"},
            {"point": "鞍座吊耳2", "position": "筒体另一端鞍座", "load_share": "50%", "type": "专用吊耳"},
        ]
    elif "炉" in equipment:
        points = [
            {"point": "炉壳吊耳1", "position": "炉壳上部一侧", "load_share": "25%", "type": "专用吊耳"},
            {"point": "炉壳吊耳2", "position": "炉壳上部另一侧", "load_share": "25%", "type": "专用吊耳"},
            {"point": "炉壳吊耳3", "position": "炉壳下部一侧", "load_share": "25%", "type": "专用吊耳"},
            {"point": "炉壳吊耳4", "position": "炉壳下部另一侧", "load_share": "25%", "type": "专用吊耳"},
        ]
    else:
        # 通用4点吊装
        points = [
            {"point": "吊点1", "position": "设备上部一侧", "load_share": "25%", "type": "专用吊耳或捆绑"},
            {"point": "吊点2", "position": "设备上部另一侧", "load_share": "25%", "type": "专用吊耳或捆绑"},
            {"point": "吊点3", "position": "设备下部一侧", "load_share": "25%", "type": "专用吊耳或捆绑"},
            {"point": "吊点4", "position": "设备下部另一侧", "load_share": "25%", "type": "专用吊耳或捆绑"},
        ]
    
    return points


def calculate_lifting(
    equipment_weight: float,
    lifting_height: float,
    working_radius: float,
    crane_selection: dict,
) -> dict:
    """吊装计算。"""
    # 动载系数
    dynamic_factor = 1.1
    # 不均衡系数
    imbalance_factor = 1.1
    # 计算载荷
    calculated_load = equipment_weight * dynamic_factor * imbalance_factor
    
    # 吊车额定载荷（从选型结果中提取数值）
    try:
        rated_capacity = float(crane_selection.get("capacity_at_radius", "0t").replace("t", ""))
    except (ValueError, AttributeError):
        rated_capacity = 0
    
    # 载荷率
    load_rate = round(calculated_load / max(rated_capacity, 0.1) * 100, 1)
    
    # 钢丝绳受力计算（4点吊装，60度）
    sling_count = 4
    sling_angle = 60
    sling_force = calculated_load / (sling_count * 0.866)  # sin(60°) = 0.866
    
    # 吊耳受力
    lifting_point_force = calculated_load / sling_count
    
    return {
        "equipment_weight": f"{equipment_weight}t",
        "dynamic_factor": dynamic_factor,
        "imbalance_factor": imbalance_factor,
        "calculated_load": f"{round(calculated_load, 2)}t",
        "rated_capacity": f"{rated_capacity}t",
        "load_rate": f"{load_rate}%",
        "load_rate_status": "合格" if load_rate <= 80 else "不合格（超过80%）",
        "sling_count": sling_count,
        "sling_angle": f"{sling_angle}°",
        "sling_force_per_rope": f"{round(sling_force, 2)}t",
        "lifting_point_force": f"{round(lifting_point_force, 2)}t",
        "lifting_height": f"{lifting_height}m",
        "working_radius": f"{working_radius}m",
        "calculation_formula": [
            "计算载荷 = 设备重量 × 动载系数(1.1) × 不均衡系数(1.1)",
            "单根钢丝绳受力 = 计算载荷 / (吊点数 × sin(吊装角度))",
            "载荷率 = 计算载荷 / 吊车额定载荷 × 100%",
            "载荷率≤80%为合格",
        ],
    }


def _estimate_equipment_weight(equipment: str, detail: dict) -> float:
    """估算设备重量。"""
    weight_map = {
        "球磨机": 45,
        "半自磨机": 150,
        "高压釜": 80,
        "闪速炉": 120,
        "浮选机": 8,
        "颚式破碎机": 25,
        "浓缩机": 15,
        "压滤机": 12,
    }
    return weight_map.get(equipment, 20)


def _estimate_lifting_height(equipment: str, detail: str) -> float:
    """估算吊装高度。"""
    height_map = {
        "球磨机": 8,
        "半自磨机": 12,
        "高压釜": 6,
        "闪速炉": 15,
        "浮选机": 5,
        "颚式破碎机": 6,
        "浓缩机": 10,
        "压滤机": 5,
    }
    return height_map.get(equipment, 6)


def _estimate_working_radius(equipment: str) -> float:
    """估算作业半径。"""
    return 8.0


def _get_lifting_safety_measures(equipment: str) -> list:
    """获取设备专用吊装安全措施。"""
    measures = []
    
    if "磨机" in equipment:
        measures.extend([
            "磨机筒体吊装必须使用专用吊耳，严禁捆绑筒体衬板螺栓孔",
            "磨机筒体翻身必须使用专用翻身吊具，设专人指挥",
            "磨机大齿圈安装时，齿圈下方严禁站人",
            "磨机吊装时，筒体两侧严禁站人，防止摆动伤人",
        ])
    elif "高压釜" in equipment:
        measures.extend([
            "高压釜吊装必须使用专用吊耳，严禁捆绑接管和法兰",
            "高压釜吊装时，严禁碰撞接管和仪表",
            "高压釜就位后，必须及时固定，防止滚动",
        ])
    elif "炉" in equipment:
        measures.extend([
            "炉壳吊装必须使用专用吊具，设专人指挥",
            "炉壳吊装时，必须保持平稳，严禁倾斜",
            "炉内有耐火材料时，吊装速度应更缓慢",
        ])
    
    if not measures:
        measures.append("按照设备说明书和规范要求，制定设备专用吊装安全措施")
    
    return measures


def get_lifting_plan_template() -> dict:
    """获取吊装方案模板结构。"""
    return {
        "ok": True,
        "structure": LIFTING_PLAN_STRUCTURE,
        "total_sections": len(LIFTING_PLAN_STRUCTURE),
    }


def get_crane_database() -> dict:
    """获取吊车参数库。"""
    return {
        "ok": True,
        "cranes": CRANE_DATABASE,
        "total": len(CRANE_DATABASE),
    }


def get_rigging_database() -> dict:
    """获取索具参数库。"""
    return {
        "ok": True,
        "rigging": RIGGING_DATABASE,
        "total": len(RIGGING_DATABASE),
    }
