"""
v0.1.91：矿山设备现场记录自动生成（针对矿山设备特点优化现场记录模板）

针对矿山/选矿/冶炼设备特点，优化现场记录模板，支持施工日志、开箱记录、
隐蔽记录、验收记录、安全检查等多种现场记录类型，针对不同设备类型生成
专用现场记录，自动从数据库获取设备信息填充记录。
"""

import os
import json
import datetime
from typing import Optional


# ============================================================
# 矿山设备现场记录模板定义
# ============================================================

FIELD_RECORD_TYPES = {
    "construction_log": {
        "name": "施工日志",
        "description": "记录每日施工情况，包括施工内容、人员、机具、进度、质量、安全等",
        "icon": "📋",
        "fields": [
            {"key": "date", "label": "日期", "type": "date", "required": True},
            {"key": "weather", "label": "天气", "type": "text", "required": True},
            {"key": "temperature", "label": "气温", "type": "text", "required": False},
            {"key": "workshop", "label": "施工区域/车间", "type": "text", "required": True},
            {"key": "construction_content", "label": "施工内容", "type": "textarea", "required": True},
            {"key": "equipment_used", "label": "使用设备/机具", "type": "textarea", "required": False},
            {"key": "personnel", "label": "施工人员", "type": "textarea", "required": True},
            {"key": "progress", "label": "进度情况", "type": "textarea", "required": True},
            {"key": "quality", "label": "质量情况", "type": "textarea", "required": True},
            {"key": "safety", "label": "安全情况", "type": "textarea", "required": True},
            {"key": "problems", "label": "存在问题及处理", "type": "textarea", "required": False},
            {"key": "next_plan", "label": "明日计划", "type": "textarea", "required": False},
            {"key": "recorder", "label": "记录人", "type": "text", "required": True},
        ],
    },
    "unboxing_record": {
        "name": "设备开箱检验记录",
        "description": "记录设备开箱检验情况，包括设备外观、零部件、随机文件、缺损情况等",
        "icon": "📦",
        "fields": [
            {"key": "date", "label": "开箱日期", "type": "date", "required": True},
            {"key": "workshop", "label": "施工区域/车间", "type": "text", "required": True},
            {"key": "equipment_name", "label": "设备名称", "type": "text", "required": True},
            {"key": "equipment_model", "label": "设备型号规格", "type": "text", "required": True},
            {"key": "equipment_tag", "label": "设备位号", "type": "text", "required": False},
            {"key": "manufacturer", "label": "制造厂家", "type": "text", "required": True},
            {"key": "contract_no", "label": "合同号/装箱单号", "type": "text", "required": False},
            {"key": "packing_condition", "label": "包装情况", "type": "textarea", "required": True},
            {"key": "appearance", "label": "设备外观检查", "type": "textarea", "required": True},
            {"key": "parts_check", "label": "零部件清点", "type": "textarea", "required": True},
            {"key": "documents", "label": "随机文件（合格证/说明书/图纸）", "type": "textarea", "required": True},
            {"key": "defects", "label": "缺损/锈蚀/变形情况", "type": "textarea", "required": False},
            {"key": "conclusion", "label": "检验结论", "type": "select", "options": ["合格", "基本合格（有缺损待处理）", "不合格"], "required": True},
            {"key": "handover_person", "label": "移交人", "type": "text", "required": True},
            {"key": "receiver", "label": "接收人", "type": "text", "required": True},
            {"key": "supervisor", "label": "监理/见证", "type": "text", "required": False},
        ],
    },
    "concealment_record": {
        "name": "隐蔽工程验收记录",
        "description": "记录隐蔽工程验收情况，包括隐蔽部位、施工内容、质量检查、验收结论等",
        "icon": "🔍",
        "fields": [
            {"key": "date", "label": "验收日期", "type": "date", "required": True},
            {"key": "workshop", "label": "施工区域/车间", "type": "text", "required": True},
            {"key": "equipment_name", "label": "设备名称", "type": "text", "required": False},
            {"key": "equipment_tag", "label": "设备位号", "type": "text", "required": False},
            {"key": "concealment_part", "label": "隐蔽部位", "type": "textarea", "required": True},
            {"key": "construction_content", "label": "施工内容及依据", "type": "textarea", "required": True},
            {"key": "material", "label": "主要材料规格及质量证明", "type": "textarea", "required": True},
            {"key": "quality_check", "label": "质量检查情况", "type": "textarea", "required": True},
            {"key": "test_results", "label": "试验/检测结果", "type": "textarea", "required": False},
            {"key": "conclusion", "label": "验收结论", "type": "select", "options": ["合格，同意隐蔽", "基本合格，整改后同意隐蔽", "不合格，需返工"], "required": True},
            {"key": "construction_unit", "label": "施工单位", "type": "text", "required": True},
            {"key": "constructor", "label": "施工负责人", "type": "text", "required": True},
            {"key": "quality_inspector", "label": "质量检查员", "type": "text", "required": True},
            {"key": "supervisor", "label": "监理工程师", "type": "text", "required": False},
            {"key": "owner_rep", "label": "建设单位代表", "type": "text", "required": False},
        ],
    },
    "installation_record": {
        "name": "设备安装记录",
        "description": "记录设备安装情况，包括安装位置、标高、水平度、垂直度、间隙等",
        "icon": "🔧",
        "fields": [
            {"key": "date", "label": "安装日期", "type": "date", "required": True},
            {"key": "workshop", "label": "施工区域/车间", "type": "text", "required": True},
            {"key": "equipment_name", "label": "设备名称", "type": "text", "required": True},
            {"key": "equipment_model", "label": "设备型号规格", "type": "text", "required": True},
            {"key": "equipment_tag", "label": "设备位号", "type": "text", "required": False},
            {"key": "location", "label": "安装位置（轴线/标高）", "type": "text", "required": True},
            {"key": "elevation", "label": "设备标高", "type": "text", "required": True},
            {"key": "levelness", "label": "水平度", "type": "text", "required": True},
            {"key": "verticality", "label": "垂直度", "type": "text", "required": False},
            {"key": "alignment", "label": "同轴度/对中", "type": "text", "required": False},
            {"key": "clearance", "label": "关键间隙", "type": "textarea", "required": False},
            {"key": "bolt_torque", "label": "地脚螺栓紧固力矩", "type": "textarea", "required": False},
            {"key": "grouting", "label": "二次灌浆情况", "type": "textarea", "required": False},
            {"key": "quality_standard", "label": "执行质量标准", "type": "text", "required": True},
            {"key": "conclusion", "label": "安装结论", "type": "select", "options": ["合格", "基本合格（需整改）", "不合格"], "required": True},
            {"key": "constructor", "label": "施工负责人", "type": "text", "required": True},
            {"key": "quality_inspector", "label": "质量检查员", "type": "text", "required": True},
        ],
    },
    "trial_run_record": {
        "name": "设备试运转记录",
        "description": "记录设备试运转情况，包括空载/负载试运转、运行参数、异常情况等",
        "icon": "⚙️",
        "fields": [
            {"key": "date", "label": "试运转日期", "type": "date", "required": True},
            {"key": "workshop", "label": "施工区域/车间", "type": "text", "required": True},
            {"key": "equipment_name", "label": "设备名称", "type": "text", "required": True},
            {"key": "equipment_model", "label": "设备型号规格", "type": "text", "required": True},
            {"key": "equipment_tag", "label": "设备位号", "type": "text", "required": False},
            {"key": "trial_type", "label": "试运转类型", "type": "select", "options": ["空载试运转", "负载试运转", "联动试运转"], "required": True},
            {"key": "duration", "label": "试运转时长", "type": "text", "required": True},
            {"key": "current", "label": "电流（A）", "type": "text", "required": False},
            {"key": "voltage", "label": "电压（V）", "type": "text", "required": False},
            {"key": "temperature", "label": "轴承温度（℃）", "type": "text", "required": True},
            {"key": "vibration", "label": "振动值（mm/s）", "type": "text", "required": False},
            {"key": "noise", "label": "噪声（dB）", "type": "text", "required": False},
            {"key": "pressure", "label": "压力（MPa）", "type": "text", "required": False},
            {"key": "flow", "label": "流量（m³/h）", "type": "text", "required": False},
            {"key": "lubrication", "label": "润滑系统情况", "type": "textarea", "required": True},
            {"key": "sealing", "label": "密封情况", "type": "textarea", "required": False},
            {"key": "abnormal", "label": "异常情况及处理", "type": "textarea", "required": False},
            {"key": "conclusion", "label": "试运转结论", "type": "select", "options": ["合格", "基本合格（有异常待处理）", "不合格"], "required": True},
            {"key": "operator", "label": "操作人", "type": "text", "required": True},
            {"key": "recorder", "label": "记录人", "type": "text", "required": True},
            {"key": "supervisor", "label": "监护人", "type": "text", "required": False},
        ],
    },
    "safety_check": {
        "name": "安全检查记录",
        "description": "记录施工现场安全检查情况，包括危险源、安全措施、隐患整改等",
        "icon": "⚠️",
        "fields": [
            {"key": "date", "label": "检查日期", "type": "date", "required": True},
            {"key": "workshop", "label": "检查区域/车间", "type": "text", "required": True},
            {"key": "check_type", "label": "检查类型", "type": "select", "options": ["日常检查", "周检查", "专项检查", "节前检查", "季节性检查"], "required": True},
            {"key": "check_content", "label": "检查内容", "type": "textarea", "required": True},
            {"key": "high_place", "label": "高处作业安全", "type": "textarea", "required": False},
            {"key": "lifting", "label": "起重吊装安全", "type": "textarea", "required": False},
            {"key": "hot_work", "label": "动火作业安全", "type": "textarea", "required": False},
            {"key": "confined_space", "label": "受限空间作业安全", "type": "textarea", "required": False},
            {"key": "electricity", "label": "临时用电安全", "type": "textarea", "required": False},
            {"key": "machinery", "label": "机械设备安全", "type": "textarea", "required": False},
            {"key": "ppe", "label": "个人防护用品佩戴", "type": "textarea", "required": True},
            {"key": "hazards", "label": "发现隐患", "type": "textarea", "required": False},
            {"key": "rectification", "label": "整改措施及期限", "type": "textarea", "required": False},
            {"key": "rectification_person", "label": "整改责任人", "type": "text", "required": False},
            {"key": "inspector", "label": "检查人", "type": "text", "required": True},
            {"key": "checked_person", "label": "被检查单位负责人", "type": "text", "required": False},
        ],
    },
    "lifting_record": {
        "name": "吊装作业记录",
        "description": "记录大型设备吊装作业情况，包括吊车、吊点、索具、吊装过程等",
        "icon": "🏗️",
        "fields": [
            {"key": "date", "label": "吊装日期", "type": "date", "required": True},
            {"key": "workshop", "label": "吊装区域/车间", "type": "text", "required": True},
            {"key": "equipment_name", "label": "吊装设备名称", "type": "text", "required": True},
            {"key": "equipment_weight", "label": "设备重量（t）", "type": "text", "required": True},
            {"key": "equipment_size", "label": "设备尺寸（m）", "type": "text", "required": False},
            {"key": "lifting_height", "label": "吊装高度（m）", "type": "text", "required": True},
            {"key": "crane_type", "label": "吊车类型及吨位", "type": "text", "required": True},
            {"key": "crane_working_radius", "label": "作业半径（m）", "type": "text", "required": True},
            {"key": "lifting_method", "label": "吊装方法", "type": "select", "options": ["单机吊装", "双机抬吊", "滑移法", "旋转法", "桅杆吊装"], "required": True},
            {"key": "lifting_points", "label": "吊点设置", "type": "textarea", "required": True},
            {"key": "slings", "label": "索具配置（钢丝绳/吊带/卸扣）", "type": "textarea", "required": True},
            {"key": "safety_factor", "label": "安全系数", "type": "text", "required": True},
            {"key": "wind_speed", "label": "当时风速（m/s）", "type": "text", "required": False},
            {"key": "trial_lift", "label": "试吊情况", "type": "textarea", "required": True},
            {"key": "lifting_process", "label": "吊装过程", "type": "textarea", "required": True},
            {"key": "positioning", "label": "就位情况", "type": "textarea", "required": True},
            {"key": "abnormal", "label": "异常情况及处理", "type": "textarea", "required": False},
            {"key": "conclusion", "label": "吊装结论", "type": "select", "options": ["顺利完成", "基本完成（有异常）", "未完成"], "required": True},
            {"key": "commander", "label": "吊装指挥", "type": "text", "required": True},
            {"key": "crane_operator", "label": "吊车司机", "type": "text", "required": True},
            {"key": "signalman", "label": "信号工", "type": "text", "required": True},
            {"key": "safety_officer", "label": "安全员", "type": "text", "required": True},
        ],
    },
    "welding_record": {
        "name": "焊接记录",
        "description": "记录焊接作业情况，包括焊接工艺、焊材、焊接参数、无损检测等",
        "icon": "🔥",
        "fields": [
            {"key": "date", "label": "焊接日期", "type": "date", "required": True},
            {"key": "workshop", "label": "施工区域/车间", "type": "text", "required": True},
            {"key": "welding_part", "label": "焊接部位", "type": "textarea", "required": True},
            {"key": "material", "label": "母材材质及规格", "type": "text", "required": True},
            {"key": "welding_process", "label": "焊接方法", "type": "select", "options": ["手工电弧焊(SMAW)", "氩弧焊(TIG)", "二氧化碳气体保护焊(MAG)", "埋弧焊(SAW)", "氩电联焊"], "required": True},
            {"key": "welding_material", "label": "焊材牌号及规格", "type": "text", "required": True},
            {"key": "welding_material_batch", "label": "焊材质保书号", "type": "text", "required": False},
            {"key": "preheat_temp", "label": "预热温度（℃）", "type": "text", "required": False},
            {"key": "interpass_temp", "label": "层间温度（℃）", "type": "text", "required": False},
            {"key": "current", "label": "焊接电流（A）", "type": "text", "required": True},
            {"key": "voltage", "label": "焊接电压（V）", "type": "text", "required": True},
            {"key": "welding_speed", "label": "焊接速度（cm/min）", "type": "text", "required": False},
            {"key": "welding_layers", "label": "焊接层数/道数", "type": "text", "required": True},
            {"key": "post_weld_heat", "label": "焊后热处理", "type": "textarea", "required": False},
            {"key": "appearance_check", "label": "外观检查", "type": "textarea", "required": True},
            {"key": "ndt", "label": "无损检测（RT/UT/MT/PT）", "type": "textarea", "required": False},
            {"key": "ndt_result", "label": "检测结果", "type": "select", "options": ["合格", "不合格（需返修）", "待检测"], "required": True},
            {"key": "welder", "label": "焊工（钢印号）", "type": "text", "required": True},
            {"key": "inspector", "label": "焊接检查员", "type": "text", "required": True},
        ],
    },
}


# ============================================================
# 矿山设备专用现场记录要点
# ============================================================

EQUIPMENT_SPECIFIC_RECORD_POINTS = {
    "球磨机": {
        "unboxing": ["主轴承轴瓦外观检查", "筒体椭圆度检查", "大齿圈齿面检查", "端盖法兰面检查", "衬板数量清点", "高低压润滑系统部件清点"],
        "installation": ["主轴承轴瓦刮研接触角60-90°", "筒体吊装双机抬吊", "大齿圈端面跳动≤0.5mm/m", "大齿圈径向跳动≤0.5mm/m", "齿轮啮合侧隙0.5-1.5mm", "齿轮接触率沿齿高≥40%沿齿长≥50%", "衬板螺栓紧固力矩", "高低压润滑系统调试"],
        "concealment": ["基础螺栓预埋", "二次灌浆", "主轴承底座灌浆", "润滑管道预埋"],
        "trial_run": ["空载4-8小时", "负载24-72小时", "轴承温升≤40℃", "振动值≤4.5mm/s", "齿轮啮合声音", "润滑系统油压油温", "衬板螺栓检查"],
    },
    "半自磨机": {
        "unboxing": ["筒体分段外观检查", "环形电机定子检查", "主轴承静压轴承检查", "波形衬板清点", "给矿器/圆筒筛检查"],
        "installation": ["筒体翻身专用工装", "环形电机气隙≤±5%", "定子圆度检查", "静压轴承高压油膜建立", "波形衬板/提升条安装", "给矿端/排矿端安装", "变频启动系统调试"],
        "concealment": ["基础螺栓预埋（大直径）", "二次灌浆（高强度）", "环形电机基础灌浆"],
        "trial_run": ["变频启动测试", "大惯性设备启动转矩", "静压轴承油压", "环形电机气隙监测", "振动值监测", "衬板螺栓检查"],
    },
    "颚式破碎机": {
        "unboxing": ["机架焊缝检查", "动颚外观检查", "肘板/肘板座检查", "调整装置检查", "飞轮/皮带轮检查"],
        "installation": ["机架水平度≤0.2mm/m", "动颚轴承间隙调整", "肘板接触面接触率≥70%", "排矿口调整（垫片/楔块）", "飞轮键连接", "干油润滑/集中润滑"],
        "concealment": ["基础螺栓预埋", "二次灌浆", "机架底座灌浆"],
        "trial_run": ["空载2小时", "负载8小时", "轴承温升≤30℃", "振动值监测", "排矿口稳定性", "肘板工作情况"],
    },
    "高压釜": {
        "unboxing": ["压力容器质量证明书核对", "钛衬里外观检查", "内件清点", "搅拌装置检查", "机械密封检查", "安全阀/压力表检定证书核对"],
        "installation": ["固定端/滑动端支座安装", "膨胀间隙计算", "内件安装（搅拌桨/挡板/加热盘管）", "搅拌装置同轴度", "机械密封静压试验", "钛衬里电火花检测", "耐酸砖衬里检查", "耐压试验1.25倍设计压力", "气密试验"],
        "concealment": ["基础螺栓预埋", "二次灌浆", "支座滑动面处理", "工艺管道预埋"],
        "trial_run": ["水压试验", "气密试验", "搅拌装置试运行", "机械密封泄漏检查", "温度/压力控制系统调试", "安全阀起跳校验"],
    },
    "闪速炉": {
        "unboxing": ["反应塔分段检查", "铜水套水压试验", "沉淀池炉壳检查", "上升烟道检查", "燃烧器/喷枪检查", "耐火材料质量证明核对"],
        "installation": ["反应塔垂直度≤1/1000", "铜水套水压试验", "铜水套接触面接触率", "沉淀池安装", "上升烟道安装", "燃烧器/喷枪定位精度", "炉壳焊接无损检测（RT/UT）", "耐火砌筑（镁铬砖/浇注料）", "膨胀缝检查", "烘炉曲线执行"],
        "concealment": ["基础螺栓预埋", "二次灌浆", "冷却壁水管预埋", "炉底耐火砌筑"],
        "trial_run": ["烘炉（按烘炉曲线）", "烘炉温度记录", "冷却壁水温差监测", "炉壳温度监测", "燃烧系统调试", "烟气系统调试"],
    },
    "浮选机": {
        "unboxing": ["槽体防腐衬里检查", "搅拌轴/叶轮检查", "定子检查", "三角带/皮带轮检查", "充气系统部件检查", "液位调节机构检查"],
        "installation": ["搅拌轴垂直度≤0.5mm/m", "叶轮与槽底间隙", "叶轮与定子间隙", "三角带张紧力", "皮带轮平行度", "充气系统调试", "液位调节机构调试", "槽体渗漏试验", "防腐衬里电火花检测"],
        "concealment": ["基础螺栓预埋", "二次灌浆", "槽体底座灌浆", "工艺管道预埋"],
        "trial_run": ["带水试运转", "带矿试运转", "轴承温升", "搅拌轴振动", "充气量测试", "液面稳定性", "电机电流"],
    },
    "浓缩机": {
        "unboxing": ["桥架检查", "中心传动机构检查", "耙架检查", "耙齿检查", "提升机构检查"],
        "installation": ["桥架水平度", "中心传动机构安装", "耙架安装", "耙架与池底间隙", "提升机构调试", "传动机构润滑", "过载保护调试"],
        "concealment": ["中心支座基础", "二次灌浆", "池底防腐"],
        "trial_run": ["空载试运行", "带水试运行", "耙架旋转平稳性", "提升机构动作", "传动机构温升", "过载保护测试"],
    },
    "压滤机": {
        "unboxing": ["机架检查", "滤板检查", "液压系统检查", "拉板机构检查", "滤布检查"],
        "installation": ["机架水平度", "滤板安装", "滤板对齐", "液压系统调试", "拉板机构调试", "滤布安装", "管路连接"],
        "concealment": ["基础螺栓预埋", "二次灌浆", "液压管路预埋"],
        "trial_run": ["液压系统试压", "滤板压紧测试", "拉板机构测试", "水压试验", "滤饼成型测试", "液压系统泄漏检查"],
    },
}


def get_record_types() -> dict:
    """获取所有现场记录类型列表。"""
    types = []
    for key, rtype in FIELD_RECORD_TYPES.items():
        types.append({
            "key": key,
            "name": rtype["name"],
            "description": rtype["description"],
            "icon": rtype["icon"],
            "field_count": len(rtype["fields"]),
        })
    return {
        "ok": True,
        "types": types,
        "total": len(types),
    }


def get_record_template(record_type: str) -> dict:
    """获取指定类型的现场记录模板。"""
    if record_type not in FIELD_RECORD_TYPES:
        return {"ok": False, "error": f"未找到记录类型: {record_type}"}
    
    rtype = FIELD_RECORD_TYPES[record_type]
    return {
        "ok": True,
        "type": record_type,
        "name": rtype["name"],
        "description": rtype["description"],
        "icon": rtype["icon"],
        "fields": rtype["fields"],
    }


def generate_field_record(
    record_type: str,
    device_type: str = "",
    device_tag: str = "",
    workshop: str = "",
    date: str = "",
    recorder: str = "",
    extra_data: dict = None,
) -> dict:
    """
    生成现场记录（自动填充设备信息和专用要点）。
    
    Args:
        record_type: 记录类型
        device_type: 设备类型（可选，用于获取专用要点）
        device_tag: 设备位号（可选）
        workshop: 车间（可选）
        date: 日期（可选，默认今天）
        recorder: 记录人（可选）
        extra_data: 额外数据（可选）
    
    Returns:
        生成的现场记录
    """
    if record_type not in FIELD_RECORD_TYPES:
        return {"ok": False, "error": f"未找到记录类型: {record_type}"}
    
    rtype = FIELD_RECORD_TYPES[record_type]
    
    if not date:
        date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # 构建记录数据
    record_data = {
        "date": date,
        "workshop": workshop or "待填写",
        "recorder": recorder or "待填写",
    }
    
    # 设备相关字段
    if device_type:
        record_data["equipment_name"] = device_type
    if device_tag:
        record_data["equipment_tag"] = device_tag
    
    # 合并额外数据
    if extra_data:
        record_data.update(extra_data)
    
    # 获取设备专用要点
    equipment_points = []
    if device_type and device_type in EQUIPMENT_SPECIFIC_RECORD_POINTS:
        dev_points = EQUIPMENT_SPECIFIC_RECORD_POINTS[device_type]
        # 根据记录类型获取对应要点
        point_key_map = {
            "unboxing_record": "unboxing",
            "installation_record": "installation",
            "concealment_record": "concealment",
            "trial_run_record": "trial_run",
        }
        point_key = point_key_map.get(record_type)
        if point_key and point_key in dev_points:
            equipment_points = dev_points[point_key]
    
    # 生成填写提示
    fill_hints = []
    for field in rtype["fields"]:
        if field["key"] in record_data and record_data[field["key"]] != "待填写":
            continue
        if field["required"]:
            fill_hints.append(f"请填写：{field['label']}")
    
    return {
        "ok": True,
        "type": record_type,
        "type_name": rtype["name"],
        "icon": rtype["icon"],
        "device_type": device_type,
        "device_tag": device_tag,
        "workshop": workshop,
        "date": date,
        "recorder": recorder,
        "fields": rtype["fields"],
        "record_data": record_data,
        "equipment_specific_points": equipment_points,
        "fill_hints": fill_hints,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_equipment_record_points(device_type: str) -> dict:
    """获取指定设备类型的专用现场记录要点。"""
    if device_type not in EQUIPMENT_SPECIFIC_RECORD_POINTS:
        return {"ok": False, "error": f"未找到设备类型: {device_type}"}
    
    return {
        "ok": True,
        "device_type": device_type,
        "points": EQUIPMENT_SPECIFIC_RECORD_POINTS[device_type],
    }


def get_all_equipment_with_record_points() -> dict:
    """获取所有有专用记录要点的设备类型列表。"""
    return {
        "ok": True,
        "equipment_types": list(EQUIPMENT_SPECIFIC_RECORD_POINTS.keys()),
        "total": len(EQUIPMENT_SPECIFIC_RECORD_POINTS),
    }
