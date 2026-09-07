"""
v0.1.105：矿山设备安全交底自动生成

基于设备详细知识库和故障诊断库自动生成安全交底记录，包含工程概况、
危险源辨识、安全技术措施、应急预案、安全操作规程等。
"""

import os
import json
import datetime
from typing import Optional


# 安全交底模板结构
SAFETY_DISCLOSURE_STRUCTURE = [
    {"section": "工程概况", "key": "overview"},
    {"section": "危险源辨识与风险评估", "key": "hazards"},
    {"section": "安全技术措施", "key": "safety_measures"},
    {"section": "安全操作规程", "key": "operation_rules"},
    {"section": "个人防护要求", "key": "ppe"},
    {"section": "应急预案", "key": "emergency"},
    {"section": "安全检查要求", "key": "inspection"},
    {"section": "交底签字", "key": "signatures"},
]


# 通用危险源库
GENERAL_HAZARDS = [
    {"hazard": "高处坠落", "location": "2m以上高处作业", "risk_level": "高", "consequence": "人员伤亡", "control_measure": "系安全带、设安全网、作业平台牢固、设防护栏杆"},
    {"hazard": "起重伤害", "location": "起重吊装作业", "risk_level": "高", "consequence": "人员伤亡、设备损坏", "control_measure": "专人指挥、索具检查合格、吊物下方严禁站人、严禁超载"},
    {"hazard": "物体打击", "location": "高处作业下方、交叉作业", "risk_level": "中", "consequence": "人员伤亡", "control_measure": "戴安全帽、工具入袋、严禁抛掷、设隔离区"},
    {"hazard": "触电", "location": "电气作业、施工用电", "risk_level": "中", "consequence": "人员伤亡", "control_measure": "三级配电两级保护、漏电保护器有效、电缆无破损、持证操作"},
    {"hazard": "机械伤害", "location": "设备运转、转动部位", "risk_level": "中", "consequence": "人员伤亡", "control_measure": "防护罩齐全、运转时严禁靠近、停机检修、挂牌上锁"},
    {"hazard": "火灾", "location": "焊接作业、易燃物存放", "risk_level": "中", "consequence": "财产损失、人员伤亡", "control_measure": "办理动火证、配备灭火器、清理易燃物、专人监护"},
    {"hazard": "中毒窒息", "location": "密闭空间、有限空间作业", "risk_level": "高", "consequence": "人员伤亡", "control_measure": "通风检测、专人监护、佩戴防护用品、应急救援准备"},
    {"hazard": "灼烫", "location": "高温设备、焊接作业", "risk_level": "中", "consequence": "人员伤害", "control_measure": "穿戴防烫用品、设警示标志、保持安全距离"},
    {"hazard": "车辆伤害", "location": "场内运输、吊车行走", "risk_level": "中", "consequence": "人员伤亡", "control_measure": "限速行驶、专人指挥、设警示标志、严禁人货混装"},
    {"hazard": "坍塌", "location": "基础开挖、临时设施", "risk_level": "高", "consequence": "人员伤亡、财产损失", "control_measure": "按方案施工、设支护、定期检查、严禁超挖"},
]


# 个人防护用品库
PPE_REQUIREMENTS = [
    {"ppe": "安全帽", "requirement": "进入施工现场必须佩戴，符合GB2811标准", "inspection": "每日检查，有裂纹、破损立即更换"},
    {"ppe": "安全带", "requirement": "2m以上高处作业必须佩戴，高挂低用", "inspection": "每次使用前检查，定期检验"},
    {"ppe": "防护眼镜", "requirement": "焊接、切割、打磨作业必须佩戴", "inspection": "镜片无裂纹、破损"},
    {"ppe": "防护手套", "requirement": "焊接、搬运、接触化学品时佩戴", "inspection": "无破损、渗漏"},
    {"ppe": "防护鞋", "requirement": "防砸、防穿刺、绝缘（根据作业类型）", "inspection": "鞋底无磨损、钢包头无变形"},
    {"ppe": "防尘口罩", "requirement": "粉尘作业环境佩戴", "inspection": "滤棉定期更换"},
    {"ppe": "防毒面具", "requirement": "有毒有害气体环境佩戴", "inspection": "滤毒罐定期更换"},
    {"ppe": "耳塞/耳罩", "requirement": "噪声超过85dB环境佩戴", "inspection": "定期更换"},
    {"ppe": "工作服", "requirement": "统一着装，袖口、下摆扎紧", "inspection": "无破损、油污"},
    {"ppe": "反光背心", "requirement": "夜间作业、场内运输时佩戴", "inspection": "反光条无脱落"},
]


def generate_safety_disclosure(
    equipment_name: str,
    project_name: str = "矿山工程项目",
    workshop: str = "",
    construction_unit: str = "",
    disclosure_person: str = "",
    disclosure_date: str = "",
) -> dict:
    """
    基于设备详细知识库生成安全交底记录。
    
    Args:
        equipment_name: 设备名称
        project_name: 项目名称
        workshop: 车间
        construction_unit: 施工单位
        disclosure_person: 交底人
        disclosure_date: 交底日期
    
    Returns:
        完整的安全交底记录
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
    
    # 获取设备专用危险源
    equipment_hazards = _get_equipment_hazards(equipment)
    
    # 获取设备专用安全措施
    equipment_safety = _get_equipment_safety(equipment)
    
    # 获取设备安全操作规程
    operation_rules = _get_operation_rules(equipment)
    
    # 构建安全交底
    disclosure = {
        "title": f"{equipment}安装安全交底记录",
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
            "workshop": workshop or "待定",
            "typical_models": detail.get("typical_models", []),
            "key_parameters": detail.get("key_parameters", {}),
            "disclosure_scope": f"本安全交底适用于{project_name}{workshop + '' if workshop else ''}{equipment}的安装施工全过程的安全管理，包括设备开箱检验、基础验收、设备吊装、安装调试、试运转等各工序的安全要求。",
        },
    })
    
    # 2. 危险源辨识与风险评估
    all_hazards = GENERAL_HAZARDS + equipment_hazards
    high_risks = [h for h in all_hazards if h["risk_level"] == "高"]
    medium_risks = [h for h in all_hazards if h["risk_level"] == "中"]
    low_risks = [h for h in all_hazards if h["risk_level"] == "低"]
    
    disclosure["sections"].append({
        "section": "危险源辨识与风险评估",
        "content": {
            "total_hazards": len(all_hazards),
            "high_risk_count": len(high_risks),
            "medium_risk_count": len(medium_risks),
            "low_risk_count": len(low_risks),
            "high_risks": high_risks,
            "medium_risks": medium_risks,
            "low_risks": low_risks,
            "risk_assessment_method": "采用LEC法（作业条件危险性评价法）进行风险评估，L-事故发生可能性，E-暴露于危险环境频率，C-事故后果严重程度，D=L×E×C危险性分值",
        },
    })
    
    # 3. 安全技术措施
    disclosure["sections"].append({
        "section": "安全技术措施",
        "content": {
            "general_measures": [
                "建立健全安全生产责任制，明确各级人员安全职责",
                "施工前进行安全技术交底，所有参与人员签字确认",
                "特种作业人员必须持证上岗，严禁无证操作",
                "施工现场设置明显的安全警示标志，危险区域设置防护栏杆",
                "施工用电必须符合三级配电两级保护要求，配电箱上锁",
                "起重作业时，吊物下方严禁站人，设专人指挥",
                "高处作业时，工具必须放入工具袋，严禁抛掷工具和材料",
                "氧气瓶和乙炔瓶间距不小于5m，距明火不小于10m",
                "施工现场配备足够的消防器材，定期检查有效性",
                "每日施工前进行安全检查，每周进行安全大检查",
                "遇有六级及以上大风、大雨、大雾等恶劣天气，停止高处和起重作业",
            ],
            "equipment_specific_measures": equipment_safety,
            "high_risk_control": [
                "高处作业：必须系安全带，设置安全网，作业平台牢固，设防护栏杆，专人监护",
                "起重吊装：必须专人指挥，索具检查合格，严禁超载，吊物下方严禁站人，设警戒区",
                "触电：必须三级配电两级保护，漏电保护器有效，电缆无破损，持证操作，挂牌上锁",
                "中毒窒息：必须通风检测合格，专人监护，佩戴防护用品，应急救援准备到位",
            ],
        },
    })
    
    # 4. 安全操作规程
    disclosure["sections"].append({
        "section": "安全操作规程",
        "content": {
            "general_rules": [
                "作业前必须检查作业环境和设备状况，确认安全后方可作业",
                "作业时必须严格按照操作规程操作，严禁违章作业",
                "作业中发现异常情况，立即停止作业，报告负责人",
                "作业完毕后，清理现场，关闭电源，确认无安全隐患后方可离开",
                "严禁酒后上岗、疲劳作业、带病作业",
                "严禁擅自拆除安全防护设施和警示标志",
            ],
            "equipment_specific_rules": operation_rules,
        },
    })
    
    # 5. 个人防护要求
    disclosure["sections"].append({
        "section": "个人防护要求",
        "content": {
            "ppe_requirements": PPE_REQUIREMENTS,
            "total_ppe": len(PPE_REQUIREMENTS),
            "ppe_management": [
                "个人防护用品必须符合国家标准，有合格证书",
                "防护用品必须正确佩戴和使用，不得随意丢弃",
                "防护用品定期检查，损坏或过期立即更换",
                "项目部统一采购和发放防护用品，建立发放台账",
                "施工人员必须妥善保管防护用品，遗失或损坏照价赔偿",
            ],
        },
    })
    
    # 6. 应急预案
    disclosure["sections"].append({
        "section": "应急预案",
        "content": {
            "emergency_types": [
                {"type": "高处坠落", "response": "立即停止作业，拨打120，保护现场，对伤者进行初步急救（止血、固定），等待专业救援，严禁随意搬动伤者"},
                {"type": "起重伤害", "response": "立即停止起重作业，疏散人员，评估险情，拨打120，对伤者进行急救，专业人员处理设备，严禁盲目救援"},
                {"type": "物体打击", "response": "立即停止作业，查看伤者情况，轻微伤害现场处理，严重伤害送医治疗，保护现场，查明原因"},
                {"type": "触电事故", "response": "立即切断电源，用绝缘物体将伤者与电源分离，进行心肺复苏，拨打120，保护现场，查明原因"},
                {"type": "火灾事故", "response": "立即停止作业，使用灭火器灭火，拨打119，疏散人员，切断电源和气源，保护重要物资"},
                {"type": "机械伤害", "response": "立即停止设备运行，切断电源，对伤者进行急救，严重伤害送医治疗，保护现场，查明原因"},
                {"type": "中毒窒息", "response": "立即将伤者转移至通风良好处，保持呼吸道通畅，进行人工呼吸，拨打120，严禁盲目进入施救"},
            ],
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
                "防毒面具和空气呼吸器",
            ],
        },
    })
    
    # 7. 安全检查要求
    disclosure["sections"].append({
        "section": "安全检查要求",
        "content": {
            "daily_inspection": [
                "每日施工前进行班前安全检查，确认作业环境安全",
                "检查个人防护用品佩戴情况",
                "检查施工用电和设备安全状况",
                "检查安全防护设施和警示标志",
                "检查消防器材配备情况",
            ],
            "weekly_inspection": [
                "每周进行一次安全大检查，由项目负责人组织",
                "检查安全生产责任制落实情况",
                "检查安全技术交底执行情况",
                "检查隐患整改落实情况",
                "检查特种作业人员持证上岗情况",
            ],
            "special_inspection": [
                "起重吊装作业前进行专项安全检查",
                "高处作业前进行专项安全检查",
                "临时用电进行专项安全检查",
                "节假日前后进行安全大检查",
                "恶劣天气后进行安全检查",
            ],
            "hazard_rectification": [
                "检查发现的安全隐患必须立即整改",
                "重大隐患必须停工整改，整改合格后方可复工",
                "隐患整改实行闭环管理，有检查、有整改、有复查",
                "建立隐患整改台账，记录隐患内容、整改措施、责任人、完成时间",
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
                {"role": "安全员", "name": "", "signature": "", "date": ""},
                {"role": "班组长", "name": "", "signature": "", "date": ""},
                {"role": "施工人员", "name": "", "signature": "", "date": ""},
            ],
            "disclosure_notes": "本安全交底一式三份，交底人、施工班组、项目部各存一份。施工人员必须认真学习并严格执行安全操作规程，有权拒绝违章指挥和强令冒险作业。",
        },
    })
    
    # 计算完成度
    total_sections = len(SAFETY_DISCLOSURE_STRUCTURE)
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


def _get_equipment_hazards(equipment: str) -> list:
    """获取设备专用危险源。"""
    hazards = []
    
    if "磨机" in equipment:
        hazards = [
            {"hazard": "筒体吊装伤害", "location": "磨机筒体吊装和翻身", "risk_level": "高", "consequence": "人员伤亡、设备损坏", "control_measure": "使用专用吊具，专人指挥，设警戒区，严禁站人"},
            {"hazard": "轴瓦刮研伤害", "location": "主轴承轴瓦刮研", "risk_level": "中", "consequence": "人员伤害", "control_measure": "轴瓦固定牢固，佩戴防护手套，工具摆放整齐"},
            {"hazard": "大齿圈安装伤害", "location": "大齿圈吊装和安装", "risk_level": "高", "consequence": "人员伤亡", "control_measure": "齿圈下方严禁站人，使用专用工具，专人指挥"},
            {"hazard": "试运转伤害", "location": "磨机试运转", "risk_level": "高", "consequence": "人员伤亡", "control_measure": "筒体两侧严禁站人，设防护罩，专人监护"},
        ]
    elif "高压釜" in equipment:
        hazards = [
            {"hazard": "压力容器爆炸", "location": "高压釜耐压试验和运行", "risk_level": "高", "consequence": "人员伤亡、设备损坏", "control_measure": "严禁超压，定期校验安全阀，设警戒区，专人监护"},
            {"hazard": "钛衬里焊接火灾", "location": "钛衬里焊接作业", "risk_level": "中", "consequence": "火灾、人员伤害", "control_measure": "办理动火证，配备灭火器，清理易燃物，专人监护"},
            {"hazard": "机械密封伤害", "location": "机械密封安装和调试", "risk_level": "中", "consequence": "人员伤害", "control_measure": "停机检修，挂牌上锁，佩戴防护用品"},
            {"hazard": "中毒窒息", "location": "高压釜内部检修", "risk_level": "高", "consequence": "人员伤亡", "control_measure": "通风检测合格，专人监护，佩戴防护用品，应急救援准备"},
        ]
    elif "炉" in equipment:
        hazards = [
            {"hazard": "高温灼烫", "location": "炉体安装和烘炉", "risk_level": "高", "consequence": "人员伤害", "control_measure": "穿戴防烫用品，设警示标志，保持安全距离，专人监护"},
            {"hazard": "炉内作业窒息", "location": "炉内砌筑和检修", "risk_level": "高", "consequence": "人员伤亡", "control_measure": "通风检测合格，专人监护，佩戴防护用品，应急救援准备"},
            {"hazard": "炉壳吊装伤害", "location": "炉壳吊装", "risk_level": "高", "consequence": "人员伤亡、设备损坏", "control_measure": "使用专用吊具，专人指挥，设警戒区，严禁站人"},
            {"hazard": "烘炉火灾", "location": "烘炉期间", "risk_level": "中", "consequence": "火灾、设备损坏", "control_measure": "24小时值班，配备灭火器，监控炉温，清理易燃物"},
        ]
    elif "破碎" in equipment:
        hazards = [
            {"hazard": "飞轮伤害", "location": "破碎机飞轮和皮带轮", "risk_level": "高", "consequence": "人员伤亡", "control_measure": "安装防护罩，运转时严禁打开，停机检修"},
            {"hazard": "进料口坠落", "location": "破碎机进料口", "risk_level": "高", "consequence": "人员伤亡", "control_measure": "设防护栏，加盖板，严禁靠近，专人监护"},
            {"hazard": "检修伤害", "location": "破碎机检修", "risk_level": "中", "consequence": "人员伤害", "control_measure": "切断电源，挂牌上锁，专人监护，佩戴防护用品"},
        ]
    
    return hazards


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
            "高压釜耐压试验时，严禁超压，试验区域设置警戒线，无关人员不得进入",
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


def _get_operation_rules(equipment: str) -> list:
    """获取设备安全操作规程。"""
    rules = []
    
    if "磨机" in equipment:
        rules = [
            "磨机启动前必须检查润滑系统、冷却系统、传动系统是否正常",
            "磨机启动时必须先启动润滑系统，再启动主电机",
            "磨机运转时严禁靠近筒体和传动部位，严禁打开防护罩",
            "磨机停机时必须先停止给矿，待筒体内物料排空后再停机",
            "磨机检修时必须切断电源，挂牌上锁，专人监护",
        ]
    elif "高压釜" in equipment:
        rules = [
            "高压釜使用前必须检查安全阀、压力表、温度计是否完好有效",
            "高压釜进料前必须检查釜内是否清洁，有无异物",
            "高压釜升温升压必须缓慢进行，严禁快速升温升压",
            "高压釜运行时必须密切监控温度和压力，严禁超温超压",
            "高压釜检修时必须泄压降温至常温常压后方可进入",
        ]
    elif "破碎" in equipment:
        rules = [
            "破碎机启动前必须检查破碎腔内有无异物，防护罩是否完好",
            "破碎机必须空载启动，运转正常后方可给矿",
            "破碎机运转时严禁靠近进料口，严禁用手或工具清理破碎腔",
            "破碎机停机时必须先停止给矿，待破碎腔内物料排空后再停机",
            "破碎机检修时必须切断电源，挂牌上锁，专人监护",
        ]
    
    if not rules:
        rules = [
            "设备启动前必须进行全面检查，确认安全后方可启动",
            "设备运转时严禁靠近转动部位，严禁打开防护罩",
            "设备检修时必须切断电源，挂牌上锁，专人监护",
            "严格按照设备说明书操作规程操作，严禁违章作业",
        ]
    
    return rules


def get_safety_disclosure_template() -> dict:
    """获取安全交底模板结构。"""
    return {
        "ok": True,
        "structure": SAFETY_DISCLOSURE_STRUCTURE,
        "total_sections": len(SAFETY_DISCLOSURE_STRUCTURE),
    }


def get_general_hazards() -> dict:
    """获取通用危险源库。"""
    return {
        "ok": True,
        "hazards": GENERAL_HAZARDS,
        "total": len(GENERAL_HAZARDS),
    }
