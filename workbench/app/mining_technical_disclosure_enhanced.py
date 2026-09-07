"""
v0.1.104：矿山设备技术交底自动生成

基于设备详细知识库自动生成技术交底记录，包含工程概况、施工准备、
施工工艺、技术要求、质量标准、安全注意事项、验收标准等。
"""

import os
import json
import datetime
from typing import Optional


# 技术交底模板结构
DISCLOSURE_STRUCTURE = [
    {"section": "工程概况", "key": "overview"},
    {"section": "施工准备", "key": "preparation"},
    {"section": "施工工艺流程", "key": "process"},
    {"section": "施工方法及技术要求", "key": "methods"},
    {"section": "质量标准及验收要求", "key": "quality"},
    {"section": "安全注意事项", "key": "safety"},
    {"section": "文明施工及环保要求", "key": "environment"},
    {"section": "交底签字", "key": "signatures"},
]


def generate_technical_disclosure(
    equipment_name: str,
    project_name: str = "矿山工程项目",
    workshop: str = "",
    construction_unit: str = "",
    disclosure_person: str = "",
    disclosure_date: str = "",
) -> dict:
    """
    基于设备详细知识库生成技术交底记录。
    
    Args:
        equipment_name: 设备名称
        project_name: 项目名称
        workshop: 车间
        construction_unit: 施工单位
        disclosure_person: 交底人
        disclosure_date: 交底日期
    
    Returns:
        完整的技术交底记录
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
    
    if not disclosure_date:
        disclosure_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # 构建技术交底
    disclosure = {
        "title": f"{equipment}安装技术交底记录",
        "project_name": project_name,
        "workshop": workshop,
        "equipment": equipment,
        "construction_unit": construction_unit,
        "disclosure_person": disclosure_person,
        "disclosure_date": disclosure_date,
        "version": "v1.0",
        "sections": [],
    }
    
    # 1. 工程概况
    disclosure["sections"].append({
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
            "disclosure_scope": f"本技术交底适用于{project_name}{workshop + '' if workshop else ''}{equipment}的安装施工，包括设备开箱检验、基础验收、设备安装、管道连接、电气接线、调试及试运转等全过程的技术要求。",
        },
    })
    
    # 2. 施工准备
    disclosure["sections"].append({
        "section": "施工准备",
        "content": {
            "technical_preparation": [
                "熟悉施工图纸和设备说明书，进行图纸会审",
                "编制施工方案并进行技术交底",
                "准备施工记录表格和验收表格",
                "对施工人员进行技术培训和安全交底",
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
            "site_preparation": [
                "清理施工现场，确保道路畅通",
                "设备基础验收合格，混凝土强度达到设计要求",
                "施工用电、用水接通",
                "设置材料堆放区和设备临时存放区",
            ],
        },
    })
    
    # 3. 施工工艺流程
    disclosure["sections"].append({
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
    })
    
    # 4. 施工方法及技术要求
    phase_points = _get_phase_points(equipment)
    disclosure["sections"].append({
        "section": "施工方法及技术要求",
        "content": {
            "key_points": detail.get("construction_key_points", []),
            "phase_points": phase_points,
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
    })
    
    # 5. 质量标准及验收要求
    disclosure["sections"].append({
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
            "precision_requirements": [
                "设备水平度偏差：≤0.1mm/m",
                "设备中心线偏差：≤±5mm",
                "设备标高偏差：≤±5mm",
                "联轴器同轴度偏差：≤0.05mm（根据设备要求）",
                "齿轮啮合侧隙：0.8~1.6mm（根据设备要求）",
                "齿轮接触率：沿齿高≥40%，沿齿长≥50%",
            ],
        },
    })
    
    # 6. 安全注意事项
    disclosure["sections"].append({
        "section": "安全注意事项",
        "content": {
            "general_safety": [
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
            ],
            "equipment_specific_safety": _get_equipment_safety(equipment),
            "risk_analysis": [
                {"risk": "高处坠落", "level": "高", "measure": "高处作业系安全带，设置安全网，作业平台牢固"},
                {"risk": "起重伤害", "level": "高", "measure": "起重设备定期检验，索具检查合格，专人指挥，吊物下方严禁站人"},
                {"risk": "物体打击", "level": "中", "measure": "进入现场戴安全帽，高处作业工具入袋，严禁抛掷"},
                {"risk": "触电", "level": "中", "measure": "三级配电两级保护，漏电保护器有效，电缆无破损"},
                {"risk": "机械伤害", "level": "中", "measure": "设备运转时严禁靠近转动部位，防护罩齐全有效"},
            ],
        },
    })
    
    # 7. 文明施工及环保要求
    disclosure["sections"].append({
        "section": "文明施工及环保要求",
        "content": {
            "civilized_construction": [
                "施工现场材料堆放整齐，标识清晰",
                "施工道路畅通，场地平整干净",
                "施工人员统一着装，佩戴胸卡",
                "工完料尽场地清，每日清理施工现场",
                "施工垃圾分类存放，及时清运",
            ],
            "environmental_protection": [
                "施工废水经沉淀处理后排放，不得直接排放",
                "施工垃圾集中堆放，及时清运至指定地点",
                "减少施工噪声，夜间施工办理夜间施工许可证",
                "焊接作业采取防弧光措施，避免影响周边",
                "油品存放采取防泄漏措施，防止污染土壤",
            ],
        },
    })
    
    # 8. 交底签字
    disclosure["sections"].append({
        "section": "交底签字",
        "content": {
            "disclosure_person": disclosure_person or "（交底人签字）",
            "disclosure_date": disclosure_date,
            "recipients": [
                {"role": "施工负责人", "name": "", "signature": "", "date": ""},
                {"role": "技术负责人", "name": "", "signature": "", "date": ""},
                {"role": "安全员", "name": "", "signature": "", "date": ""},
                {"role": "班组长", "name": "", "signature": "", "date": ""},
                {"role": "施工人员", "name": "", "signature": "", "date": ""},
            ],
            "disclosure_notes": "本技术交底一式三份，交底人、施工班组、项目部各存一份。施工人员必须认真学习并严格执行，如有疑问及时向交底人提出。",
        },
    })
    
    # 计算完成度
    total_sections = len(DISCLOSURE_STRUCTURE)
    completed_sections = len(disclosure["sections"])
    completion_rate = round(completed_sections / total_sections * 100, 1)
    
    return {
        "ok": True,
        "equipment": equipment,
        "title": disclosure["title"],
        "disclosure": disclosure,
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


def _get_equipment_safety(equipment: str) -> list:
    """获取设备专用安全措施。"""
    measures = []
    
    if "磨机" in equipment:
        measures.extend([
            "磨机筒体吊装必须使用专用吊耳，严禁捆绑筒体衬板螺栓孔",
            "磨机筒体翻身必须使用专用翻身吊具，设专人指挥",
            "磨机主轴承轴瓦刮研时，轴瓦必须固定牢固，防止滑动伤人",
            "磨机大齿圈安装时，齿圈下方严禁站人",
            "磨机试运转时，筒体两侧严禁站人，防止衬板螺栓飞出",
        ])
    elif "高压釜" in equipment:
        measures.extend([
            "高压釜吊装必须使用专用吊耳，严禁捆绑接管和法兰",
            "高压釜耐压试验时，严禁超压，试验区域设置警戒线",
            "高压釜气密性试验时，严禁用明火检漏，使用肥皂水或专用检漏仪",
            "高压釜钛衬里焊接时，必须做好防火措施，配备灭火器",
            "高压釜安全阀必须经校验合格后安装，铅封完好",
        ])
    elif "炉" in equipment:
        measures.extend([
            "炉壳吊装必须使用专用吊具，设专人指挥",
            "炉内砌筑作业时，必须保持通风良好，设置专人监护",
            "烘炉期间，必须24小时值班，密切监控炉温变化",
            "炉区作业时，必须穿戴防烫劳保用品，防止烫伤",
        ])
    elif "破碎" in equipment:
        measures.extend([
            "破碎机飞轮和皮带轮必须安装防护罩，运转时严禁打开",
            "破碎机进料口必须设置防护栏，防止人员误入",
            "破碎机检修时，必须切断电源，悬挂'禁止合闸'警示牌",
        ])
    elif "浮选" in equipment:
        measures.extend([
            "浮选机槽体盛水试验时，必须监控槽体变形情况",
            "浮选机搅拌装置安装时，叶轮下方严禁站人",
            "浮选药剂添加时，必须佩戴防护用品，防止药剂接触皮肤",
        ])
    
    if not measures:
        measures.append("按照设备说明书和规范要求，制定设备专用安全措施")
    
    return measures


def get_disclosure_template() -> dict:
    """获取技术交底模板结构。"""
    return {
        "ok": True,
        "structure": DISCLOSURE_STRUCTURE,
        "total_sections": len(DISCLOSURE_STRUCTURE),
    }
