"""
v0.1.101：矿山设备施工方案自动生成增强（基于详细知识库）

基于设备详细知识库（mining_equipment_detail）自动生成施工方案，
包含工程概况、编制依据、施工准备、施工工艺、质量标准、安全措施、
应急预案、施工进度、资源配置等完整内容。
"""

import os
import json
import datetime
from typing import Optional


# 施工方案模板结构
PLAN_STRUCTURE = [
    {"section": "工程概况", "key": "overview"},
    {"section": "编制依据", "key": "references"},
    {"section": "施工准备", "key": "preparation"},
    {"section": "施工工艺流程", "key": "process"},
    {"section": "施工方法及技术要求", "key": "methods"},
    {"section": "质量标准及验收要求", "key": "quality"},
    {"section": "安全技术措施", "key": "safety"},
    {"section": "应急预案", "key": "emergency"},
    {"section": "施工进度计划", "key": "schedule"},
    {"section": "资源配置计划", "key": "resources"},
    {"section": "文明施工及环保措施", "key": "environment"},
]


# 通用安全措施
GENERAL_SAFETY_MEASURES = [
    "进入施工现场必须佩戴安全帽，高处作业必须系安全带",
    "施工现场设置明显的安全警示标志，危险区域设置防护栏杆",
    "施工用电必须符合三级配电两级保护要求，配电箱上锁",
    "起重作业时，吊物下方严禁站人，设专人指挥",
    "高处作业时，工具必须放入工具袋，严禁抛掷工具和材料",
    "夜间施工必须有足够的照明，照明电压不超过36V",
    "氧气瓶和乙炔瓶间距不小于5m，距明火不小于10m",
    "施工现场配备足够的消防器材，定期检查有效性",
    "特种作业人员必须持证上岗，严禁无证操作",
    "每日施工前进行安全交底，每周进行安全检查",
]


# 通用应急预案
GENERAL_EMERGENCY_PLAN = [
    {"type": "高处坠落", "response": "立即停止作业，拨打120，保护现场，对伤者进行初步急救（止血、固定），等待专业救援"},
    {"type": "物体打击", "response": "立即停止作业，查看伤者情况，轻微伤害现场处理，严重伤害送医治疗"},
    {"type": "触电事故", "response": "立即切断电源，用绝缘物体将伤者与电源分离，进行心肺复苏，拨打120"},
    {"type": "火灾事故", "response": "立即停止作业，使用灭火器灭火，拨打119，疏散人员，切断电源和气源"},
    {"type": "机械伤害", "response": "立即停止设备运行，切断电源，对伤者进行急救，严重伤害送医治疗"},
    {"type": "起重事故", "response": "立即停止起重作业，疏散人员，评估险情，专业人员处理，严禁盲目救援"},
]


def generate_construction_plan(
    equipment_name: str,
    project_name: str = "矿山工程项目",
    workshop: str = "",
    construction_unit: str = "",
    plan_date: str = "",
) -> dict:
    """
    基于设备详细知识库生成施工方案。
    
    Args:
        equipment_name: 设备名称
        project_name: 项目名称
        workshop: 车间
        construction_unit: 施工单位
        plan_date: 编制日期
    
    Returns:
        完整的施工方案
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
    
    if not plan_date:
        plan_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # 构建施工方案各部分
    plan = {
        "title": f"{equipment}安装施工方案",
        "project_name": project_name,
        "workshop": workshop,
        "equipment": equipment,
        "construction_unit": construction_unit,
        "plan_date": plan_date,
        "version": "v1.0",
        "sections": [],
    }
    
    # 1. 工程概况
    overview = {
        "section": "工程概况",
        "content": {
            "project_name": project_name,
            "equipment_name": equipment,
            "equipment_category": detail.get("category", ""),
            "equipment_subcategory": detail.get("subcategory", ""),
            "workshop": workshop or "待定",
            "typical_models": detail.get("typical_models", []),
            "key_parameters": detail.get("key_parameters", {}),
            "main_components": detail.get("main_components", []),
            "engineering_scope": f"本方案适用于{project_name}{workshop + '' if workshop else ''}{equipment}的安装施工，包括设备开箱检验、基础验收、设备安装、管道连接、电气接线、调试及试运转等全过程。",
        },
    }
    plan["sections"].append(overview)
    
    # 2. 编制依据
    references = {
        "section": "编制依据",
        "content": {
            "standards": detail.get("quality_standards", []),
            "design_documents": [
                "施工图纸及设计说明",
                "设备安装使用说明书",
                "设备基础图",
                "工艺管道布置图",
                "电气原理图及接线图",
            ],
            "management_documents": [
                "施工组织设计",
                "项目质量计划",
                "职业健康安全管理方案",
                "环境管理方案",
            ],
        },
    }
    plan["sections"].append(references)
    
    # 3. 施工准备
    preparation = {
        "section": "施工准备",
        "content": {
            "technical_preparation": [
                "熟悉施工图纸和设备说明书，进行图纸会审",
                "编制施工方案并进行技术交底",
                "编制设备基础验收方案",
                "准备施工记录表格和验收表格",
            ],
            "material_preparation": [
                "设备开箱检验，核对设备型号、规格、数量",
                "检查设备外观有无损伤、变形",
                "核对随机文件（合格证、说明书、图纸）",
                "准备安装材料（垫铁、螺栓、密封件、润滑油等）",
            ],
            "equipment_preparation": [
                "准备起重设备（吊车、葫芦、索具等）",
                "准备测量工具（水准仪、经纬仪、百分表、塞尺等）",
                "准备焊接设备（电焊机、气割设备等）",
                "准备电动工具（电钻、扳手、磨光机等）",
            ],
            "personnel_preparation": [
                "配备专业施工人员（钳工、管工、电工、焊工、起重工等）",
                "特种作业人员持证上岗",
                "进行施工前安全培训和技术交底",
            ],
            "site_preparation": [
                "清理施工现场，确保道路畅通",
                "设备基础验收合格，混凝土强度达到设计要求",
                "施工用电、用水接通",
                "设置材料堆放区和设备临时存放区",
            ],
        },
    }
    plan["sections"].append(preparation)
    
    # 4. 施工工艺流程
    process = {
        "section": "施工工艺流程",
        "content": {
            "flow": [
                "施工准备",
                "设备开箱检验",
                "基础验收",
                "设备吊装就位",
                "设备找平找正",
                "地脚螺栓紧固",
                "二次灌浆",
                "管道连接",
                "电气接线",
                "润滑系统调试",
                "单机试运转",
                "联动试运转",
                "竣工验收",
            ],
            "flow_description": "施工流程按照先准备后施工、先土建后安装、先设备后管道、先单机后联动的原则进行，各工序之间必须进行交接验收，上道工序不合格不得进入下道工序。",
        },
    }
    plan["sections"].append(process)
    
    # 5. 施工方法及技术要求
    methods = {
        "section": "施工方法及技术要求",
        "content": {
            "key_points": detail.get("construction_key_points", []),
            "phase_points": _get_phase_points(equipment),
            "installation_methods": [
                {"step": "设备开箱检验", "requirement": "核对设备型号、规格、数量与合同一致，检查设备外观有无损伤，核对随机文件齐全"},
                {"step": "基础验收", "requirement": "基础混凝土强度达到设计强度75%以上，基础尺寸偏差符合规范要求，基础表面清理干净"},
                {"step": "设备吊装就位", "requirement": "使用专用吊具，严禁直接捆绑设备加工面，吊装时设专人指挥，平稳就位"},
                {"step": "设备找平找正", "requirement": "使用垫铁调整设备水平度，水平度偏差不大于0.1mm/m，中心线偏差不大于±5mm"},
                {"step": "地脚螺栓紧固", "requirement": "螺栓紧固按对角顺序进行，紧固力矩符合厂家要求，紧固后螺栓露出螺母2-3扣"},
                {"step": "二次灌浆", "requirement": "灌浆前基础表面凿毛并清理干净，灌浆层厚度不小于40mm，灌浆后养护不少于7天"},
                {"step": "管道连接", "requirement": "管道与设备连接时不得强力对口，连接后检查设备水平度变化，管道支架独立设置"},
                {"step": "电气接线", "requirement": "电缆敷设整齐，接线牢固，电机绝缘电阻不小于0.5MΩ，接地可靠"},
            ],
        },
    }
    plan["sections"].append(methods)
    
    # 6. 质量标准及验收要求
    quality = {
        "section": "质量标准及验收要求",
        "content": {
            "standards": detail.get("quality_standards", []),
            "acceptance_items": detail.get("acceptance_items", []),
            "quality_controls": [
                "建立质量管理体系，实行三检制（自检、互检、专检）",
                "关键工序设置质量控制点，必须经监理验收合格后方可进入下道工序",
                "施工记录及时、准确、完整，与施工进度同步",
                "材料进场必须进行检验，不合格材料不得使用",
                "设备安装精度必须符合规范和厂家要求",
                "试运转参数必须符合设计要求，记录完整",
            ],
        },
    }
    plan["sections"].append(quality)
    
    # 7. 安全技术措施
    safety = {
        "section": "安全技术措施",
        "content": {
            "general_measures": GENERAL_SAFETY_MEASURES,
            "equipment_specific_measures": _get_safety_measures(equipment, detail),
            "risk_analysis": [
                {"risk": "高处坠落", "level": "高", "measure": "高处作业系安全带，设置安全网，作业平台牢固"},
                {"risk": "起重伤害", "level": "高", "measure": "起重设备定期检验，索具检查合格，专人指挥，吊物下方严禁站人"},
                {"risk": "物体打击", "level": "中", "measure": "进入现场戴安全帽，高处作业工具入袋，严禁抛掷"},
                {"risk": "触电", "level": "中", "measure": "三级配电两级保护，漏电保护器有效，电缆无破损"},
                {"risk": "机械伤害", "level": "中", "measure": "设备运转时严禁靠近转动部位，防护罩齐全有效"},
                {"risk": "火灾", "level": "低", "measure": "动火作业办理动火证，配备灭火器，清理易燃物"},
            ],
        },
    }
    plan["sections"].append(safety)
    
    # 8. 应急预案
    emergency = {
        "section": "应急预案",
        "content": {
            "emergency_types": GENERAL_EMERGENCY_PLAN,
            "emergency_organization": [
                {"role": "总指挥", "responsibility": "全面负责应急救援指挥工作"},
                {"role": "副总指挥", "responsibility": "协助总指挥工作，总指挥不在时代行职责"},
                {"role": "抢险组", "responsibility": "负责现场抢险救援工作"},
                {"role": "医疗组", "responsibility": "负责伤员初步急救和送医工作"},
                {"role": "疏散组", "responsibility": "负责人员疏散和现场警戒工作"},
                {"role": "后勤组", "responsibility": "负责应急物资和车辆保障工作"},
            ],
            "emergency_contacts": [
                {"name": "急救中心", "phone": "120"},
                {"name": "火警", "phone": "119"},
                {"name": "报警", "phone": "110"},
            ],
            "emergency_equipment": [
                "急救箱（绷带、消毒药品、止血带等）",
                "担架",
                "灭火器（干粉、二氧化碳）",
                "应急照明",
                "对讲机",
                "安全绳和安全带",
            ],
        },
    }
    plan["sections"].append(emergency)
    
    # 9. 施工进度计划
    schedule = {
        "section": "施工进度计划",
        "content": {
            "schedule_items": [
                {"phase": "施工准备", "duration": "3天", "description": "技术准备、材料准备、人员进场、现场准备"},
                {"phase": "设备开箱检验", "duration": "1天", "description": "设备开箱、清点、检验、记录"},
                {"phase": "基础验收", "duration": "1天", "description": "基础尺寸复核、强度检查、交接验收"},
                {"phase": "设备吊装就位", "duration": "1天", "description": "设备吊装、就位、初步找正"},
                {"phase": "设备找平找正", "duration": "2天", "description": "精平、找正、垫铁配置、地脚螺栓紧固"},
                {"phase": "二次灌浆", "duration": "1天+7天养护", "description": "灌浆、养护"},
                {"phase": "管道连接", "duration": "3天", "description": "管道安装、焊接、试压、吹扫"},
                {"phase": "电气接线", "duration": "2天", "description": "电缆敷设、接线、检查、绝缘测试"},
                {"phase": "润滑系统调试", "duration": "1天", "description": "润滑油加注、系统调试、检查"},
                {"phase": "单机试运转", "duration": "2天", "description": "空载试运转、负载试运转、参数记录"},
                {"phase": "联动试运转", "duration": "2天", "description": "系统联动、参数优化、问题处理"},
                {"phase": "竣工验收", "duration": "1天", "description": "资料整理、验收、移交"},
            ],
            "total_duration": "约25天（含养护期）",
            "key_milestones": [
                "设备安装完成",
                "二次灌浆完成",
                "单机试运转合格",
                "联动试运转合格",
                "竣工验收合格",
            ],
        },
    }
    plan["sections"].append(schedule)
    
    # 10. 资源配置计划
    resources = {
        "section": "资源配置计划",
        "content": {
            "personnel": [
                {"role": "施工负责人", "number": 1, "responsibility": "全面负责施工管理"},
                {"role": "技术负责人", "number": 1, "responsibility": "负责技术管理和质量控制"},
                {"role": "安全员", "number": 1, "responsibility": "负责安全管理和监督检查"},
                {"role": "钳工", "number": 4, "responsibility": "负责设备安装和调试"},
                {"role": "管工", "number": 3, "responsibility": "负责管道安装和连接"},
                {"role": "电工", "number": 2, "responsibility": "负责电气安装和接线"},
                {"role": "焊工", "number": 2, "responsibility": "负责焊接作业"},
                {"role": "起重工", "number": 2, "responsibility": "负责起重吊装作业"},
                {"role": "普工", "number": 4, "responsibility": "负责辅助工作"},
            ],
            "equipment": [
                {"name": "汽车吊", "specification": "根据设备重量选择", "number": 1, "use": "设备吊装"},
                {"name": "手拉葫芦", "specification": "5t/10t", "number": 2, "use": "设备精调和吊装"},
                {"name": "电焊机", "specification": "交流/直流", "number": 2, "use": "焊接作业"},
                {"name": "气割设备", "specification": "氧-乙炔", "number": 1, "use": "切割作业"},
                {"name": "水准仪", "specification": "DS3", "number": 1, "use": "标高测量"},
                {"name": "经纬仪", "specification": "DJ2", "number": 1, "use": "中心线测量"},
                {"name": "百分表", "specification": "0-10mm", "number": 2, "use": "精度测量"},
                {"name": "塞尺", "specification": "0.02-1mm", "number": 2, "use": "间隙测量"},
                {"name": "扭矩扳手", "specification": "根据螺栓规格", "number": 2, "use": "螺栓紧固"},
                {"name": "电钻", "specification": "冲击钻", "number": 2, "use": "钻孔作业"},
            ],
            "materials": [
                {"name": "垫铁", "specification": "斜垫铁/平垫铁", "quantity": "根据设备数量"},
                {"name": "地脚螺栓", "specification": "根据设备要求", "quantity": "随机配套"},
                {"name": "二次灌浆料", "specification": "无收缩灌浆料", "quantity": "根据灌浆体积"},
                {"name": "润滑油", "specification": "根据设备要求", "quantity": "根据润滑点数量"},
                {"name": "密封件", "specification": "根据管道规格", "quantity": "根据连接点数量"},
                {"name": "焊接材料", "specification": "根据母材材质", "quantity": "根据焊接量"},
            ],
        },
    }
    plan["sections"].append(resources)
    
    # 11. 文明施工及环保措施
    environment = {
        "section": "文明施工及环保措施",
        "content": {
            "civilized_construction": [
                "施工现场材料堆放整齐，标识清晰",
                "施工道路畅通，场地平整干净",
                "施工人员统一着装，佩戴胸卡",
                "施工现场设置宣传栏和警示牌",
                "工完料尽场地清，每日清理施工现场",
                "施工垃圾分类存放，及时清运",
            ],
            "environmental_protection": [
                "施工废水经沉淀处理后排放，不得直接排放",
                "施工垃圾集中堆放，及时清运至指定地点",
                "减少施工噪声，夜间施工办理夜间施工许可证",
                "焊接作业采取防弧光措施，避免影响周边",
                "油品存放采取防泄漏措施，防止污染土壤",
                "爱护施工现场周边植被，不得随意破坏",
            ],
        },
    }
    plan["sections"].append(environment)
    
    # 计算完成度
    total_sections = len(PLAN_STRUCTURE)
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


def _get_phase_points(equipment: str) -> dict:
    """获取设备分阶段施工要点。"""
    try:
        from . import mining_equipment_detail as _med
        result = _med.get_equipment_phase_points(equipment)
        if result.get("ok"):
            return result.get("phase_data", {})
    except Exception:
        pass
    return {}


def _get_safety_measures(equipment: str, detail: dict) -> list:
    """获取设备专用安全措施。"""
    measures = []
    
    # 根据设备类型添加专用安全措施
    if "磨机" in equipment or "磨矿" in equipment:
        measures.extend([
            "磨机筒体吊装时，必须使用专用吊耳，严禁捆绑筒体衬板螺栓孔",
            "磨机筒体翻身时，必须使用专用翻身吊具，设专人指挥",
            "磨机主轴承轴瓦刮研时，轴瓦必须固定牢固，防止滑动伤人",
            "磨机大齿圈安装时，齿圈下方严禁站人，防止齿圈滑落",
            "磨机试运转时，筒体两侧严禁站人，防止衬板螺栓飞出",
        ])
    elif "高压釜" in equipment or "压力容器" in equipment:
        measures.extend([
            "高压釜吊装时，必须使用专用吊耳，严禁捆绑接管和法兰",
            "高压釜耐压试验时，严禁超压，试验区域设置警戒线，无关人员不得进入",
            "高压釜气密性试验时，严禁用明火检漏，使用肥皂水或专用检漏仪",
            "高压釜钛衬里焊接时，必须做好防火措施，配备灭火器",
            "高压釜安全阀必须经校验合格后安装，铅封完好",
        ])
    elif "炉" in equipment or "冶炼" in equipment:
        measures.extend([
            "炉壳吊装时，必须使用专用吊具，设专人指挥",
            "炉内砌筑作业时，必须保持通风良好，设置专人监护",
            "烘炉期间，必须24小时值班，密切监控炉温变化",
            "炉区作业时，必须穿戴防烫劳保用品，防止烫伤",
            "炉体冷却水系统必须定期检查，防止漏水引发事故",
        ])
    elif "破碎" in equipment:
        measures.extend([
            "破碎机飞轮和皮带轮必须安装防护罩，运转时严禁打开",
            "破碎机进料口必须设置防护栏，防止人员误入",
            "破碎机检修时，必须切断电源，悬挂'禁止合闸'警示牌",
            "破碎机排料口清理时，必须停机进行，严禁运行中清理",
        ])
    elif "浮选" in equipment:
        measures.extend([
            "浮选机槽体盛水试验时，必须监控槽体变形情况",
            "浮选机搅拌装置安装时，叶轮下方严禁站人",
            "浮选机试运转时，必须检查槽体渗漏情况，发现泄漏及时处理",
            "浮选药剂添加时，必须佩戴防护用品，防止药剂接触皮肤",
        ])
    elif "浓缩" in equipment or "压滤" in equipment:
        measures.extend([
            "浓缩机耙架安装时，耙架下方严禁站人",
            "浓缩机中心传动装置调试时，必须监控电流变化，防止过载",
            "压滤机液压系统调试时，严禁超压，高压区域设置警戒线",
            "压滤机拉板装置调试时，手严禁伸入滤板之间",
        ])
    
    if not measures:
        measures.append("按照设备说明书和规范要求，制定设备专用安全措施")
    
    return measures


def get_plan_template() -> dict:
    """获取施工方案模板结构。"""
    return {
        "ok": True,
        "structure": PLAN_STRUCTURE,
        "total_sections": len(PLAN_STRUCTURE),
    }


def get_available_equipment_for_plan() -> dict:
    """获取可生成施工方案的设备列表。"""
    try:
        from . import mining_equipment_detail as _med
        result = _med.get_all_equipment_details()
        if result.get("ok"):
            return {
                "ok": True,
                "equipment_list": result.get("equipment_list", []),
                "total": result.get("total", 0),
            }
    except Exception:
        pass
    return {"ok": False, "error": "获取设备列表失败"}
