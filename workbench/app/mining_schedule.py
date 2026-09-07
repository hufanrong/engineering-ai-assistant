"""
v0.1.88：矿山设备施工进度计划自动生成（按工艺流程排程）

按矿山工艺流程（破碎→磨矿→选别→脱水→冶炼）自动生成施工进度计划，
考虑设备依赖关系、施工周期、关键路径，生成甘特图。
"""

import os
import json
import datetime
from typing import Optional


# ============================================================
# 工艺流程与施工顺序
# ============================================================

# 工艺流程顺序（数字越小越先施工）
PROCESS_ORDER = {
    "1. 破碎系统": 1,
    "2. 磨矿系统": 2,
    "3. 选别系统": 3,
    "4. 脱水系统": 4,
    "5. 火法冶炼系统": 5,
    "6. 湿法冶炼系统": 5,  # 火法和湿法可并行
    "7. 公用辅助系统": 0,  # 公用辅助最先开始，贯穿全程
}

# 各系统内的施工阶段
PROCESS_PHASES = {
    "1. 破碎系统": [
        {"phase": "基础施工", "duration": 15, "depends": []},
        {"phase": "粗碎设备安装", "duration": 10, "depends": ["基础施工"]},
        {"phase": "中碎设备安装", "duration": 8, "depends": ["粗碎设备安装"]},
        {"phase": "细碎设备安装", "duration": 8, "depends": ["中碎设备安装"]},
        {"phase": "筛分设备安装", "duration": 5, "depends": ["细碎设备安装"]},
        {"phase": "皮带输送机安装", "duration": 10, "depends": ["粗碎设备安装"]},
        {"phase": "给料设备安装", "duration": 3, "depends": ["基础施工"]},
        {"phase": "管道及电气安装", "duration": 7, "depends": ["筛分设备安装", "皮带输送机安装"]},
        {"phase": "单机试运转", "duration": 5, "depends": ["管道及电气安装"]},
        {"phase": "联动试运转", "duration": 3, "depends": ["单机试运转"]},
    ],
    "2. 磨矿系统": [
        {"phase": "基础施工", "duration": 20, "depends": []},
        {"phase": "主轴承安装", "duration": 7, "depends": ["基础施工"]},
        {"phase": "球磨机/半自磨机筒体吊装", "duration": 5, "depends": ["主轴承安装"]},
        {"phase": "端盖及大齿圈安装", "duration": 5, "depends": ["球磨机/半自磨机筒体吊装"]},
        {"phase": "传动装置安装", "duration": 5, "depends": ["端盖及大齿圈安装"]},
        {"phase": "分级机安装", "duration": 5, "depends": ["基础施工"]},
        {"phase": "旋流器安装", "duration": 3, "depends": ["基础施工"]},
        {"phase": "衬板安装", "duration": 7, "depends": ["传动装置安装"]},
        {"phase": "润滑系统安装", "duration": 4, "depends": ["主轴承安装"]},
        {"phase": "管道及电气安装", "duration": 8, "depends": ["衬板安装", "分级机安装", "旋流器安装"]},
        {"phase": "单机试运转", "duration": 7, "depends": ["管道及电气安装", "润滑系统安装"]},
        {"phase": "联动试运转", "duration": 5, "depends": ["单机试运转"]},
    ],
    "3. 选别系统": [
        {"phase": "基础施工", "duration": 12, "depends": []},
        {"phase": "浮选机安装", "duration": 10, "depends": ["基础施工"]},
        {"phase": "磁选机安装", "duration": 5, "depends": ["基础施工"]},
        {"phase": "重选设备安装", "duration": 5, "depends": ["基础施工"]},
        {"phase": "搅拌槽安装", "duration": 3, "depends": ["基础施工"]},
        {"phase": "加药系统安装", "duration": 5, "depends": ["搅拌槽安装"]},
        {"phase": "管道及电气安装", "duration": 8, "depends": ["浮选机安装", "磁选机安装", "重选设备安装"]},
        {"phase": "单机试运转", "duration": 5, "depends": ["管道及电气安装", "加药系统安装"]},
        {"phase": "联动试运转", "duration": 3, "depends": ["单机试运转"]},
    ],
    "4. 脱水系统": [
        {"phase": "基础施工", "duration": 10, "depends": []},
        {"phase": "浓缩机安装", "duration": 7, "depends": ["基础施工"]},
        {"phase": "过滤机安装", "duration": 7, "depends": ["基础施工"]},
        {"phase": "压滤机安装", "duration": 5, "depends": ["基础施工"]},
        {"phase": "干燥机安装", "duration": 8, "depends": ["基础施工"]},
        {"phase": "管道及电气安装", "duration": 7, "depends": ["浓缩机安装", "过滤机安装", "压滤机安装", "干燥机安装"]},
        {"phase": "单机试运转", "duration": 4, "depends": ["管道及电气安装"]},
        {"phase": "联动试运转", "duration": 3, "depends": ["单机试运转"]},
    ],
    "5. 火法冶炼系统": [
        {"phase": "基础施工", "duration": 30, "depends": []},
        {"phase": "炉壳安装", "duration": 15, "depends": ["基础施工"]},
        {"phase": "冷却壁/水套安装", "duration": 10, "depends": ["炉壳安装"]},
        {"phase": "炉顶安装", "duration": 7, "depends": ["冷却壁/水套安装"]},
        {"phase": "反应塔/沉淀池安装", "duration": 10, "depends": ["炉壳安装"]},
        {"phase": "上升烟道安装", "duration": 5, "depends": ["炉顶安装"]},
        {"phase": "余热锅炉安装", "duration": 20, "depends": ["上升烟道安装"]},
        {"phase": "除尘系统安装", "duration": 10, "depends": ["余热锅炉安装"]},
        {"phase": "制酸系统安装", "duration": 15, "depends": ["除尘系统安装"]},
        {"phase": "燃烧器/喷枪安装", "duration": 5, "depends": ["炉顶安装"]},
        {"phase": "耐火材料砌筑", "duration": 20, "depends": ["冷却壁/水套安装", "反应塔/沉淀池安装"]},
        {"phase": "管道及电气安装", "duration": 15, "depends": ["制酸系统安装", "燃烧器/喷枪安装"]},
        {"phase": "烘炉", "duration": 10, "depends": ["耐火材料砌筑", "管道及电气安装"]},
        {"phase": "单机试运转", "duration": 7, "depends": ["烘炉"]},
        {"phase": "联动试运转", "duration": 5, "depends": ["单机试运转"]},
    ],
    "6. 湿法冶炼系统": [
        {"phase": "基础施工", "duration": 20, "depends": []},
        {"phase": "浸出槽安装", "duration": 10, "depends": ["基础施工"]},
        {"phase": "高压釜安装", "duration": 15, "depends": ["基础施工"]},
        {"phase": "萃取箱安装", "duration": 8, "depends": ["基础施工"]},
        {"phase": "电积槽安装", "duration": 10, "depends": ["基础施工"]},
        {"phase": "离子交换柱安装", "duration": 5, "depends": ["基础施工"]},
        {"phase": "蒸发器/结晶器安装", "duration": 10, "depends": ["基础施工"]},
        {"phase": "溶液储槽安装", "duration": 5, "depends": ["基础施工"]},
        {"phase": "管道及电气安装", "duration": 15, "depends": ["浸出槽安装", "高压釜安装", "萃取箱安装", "电积槽安装", "离子交换柱安装", "蒸发器/结晶器安装", "溶液储槽安装"]},
        {"phase": "耐压/气密性试验", "duration": 5, "depends": ["管道及电气安装"]},
        {"phase": "单机试运转", "duration": 7, "depends": ["耐压/气密性试验"]},
        {"phase": "联动试运转", "duration": 5, "depends": ["单机试运转"]},
    ],
    "7. 公用辅助系统": [
        {"phase": "基础施工", "duration": 10, "depends": []},
        {"phase": "空压机安装", "duration": 5, "depends": ["基础施工"]},
        {"phase": "通风机安装", "duration": 3, "depends": ["基础施工"]},
        {"phase": "水泵安装", "duration": 3, "depends": ["基础施工"]},
        {"phase": "冷却塔安装", "duration": 5, "depends": ["基础施工"]},
        {"phase": "变压器/配电柜安装", "duration": 5, "depends": ["基础施工"]},
        {"phase": "DCS/PLC安装", "duration": 7, "depends": ["变压器/配电柜安装"]},
        {"phase": "管道及电气安装", "duration": 10, "depends": ["空压机安装", "通风机安装", "水泵安装", "冷却塔安装"]},
        {"phase": "单机试运转", "duration": 3, "depends": ["管道及电气安装", "DCS/PLC安装"]},
        {"phase": "联动试运转", "duration": 2, "depends": ["单机试运转"]},
    ],
}

# 设备类型到施工阶段的映射（用于根据设备清单调整工期）
EQUIPMENT_PHASE_MAP = {
    "颚式破碎机": "粗碎设备安装",
    "圆锥破碎机": "中碎设备安装",
    "反击式破碎机": "细碎设备安装",
    "锤式破碎机": "细碎设备安装",
    "振动筛": "筛分设备安装",
    "圆振动筛": "筛分设备安装",
    "给料机": "给料设备安装",
    "板式给料机": "给料设备安装",
    "皮带输送机": "皮带输送机安装",
    "胶带输送机": "皮带输送机安装",
    "球磨机": "球磨机/半自磨机筒体吊装",
    "棒磨机": "球磨机/半自磨机筒体吊装",
    "自磨机": "球磨机/半自磨机筒体吊装",
    "半自磨机": "球磨机/半自磨机筒体吊装",
    "螺旋分级机": "分级机安装",
    "水力旋流器": "旋流器安装",
    "浮选机": "浮选机安装",
    "机械搅拌浮选机": "浮选机安装",
    "充气式浮选机": "浮选机安装",
    "浮选柱": "浮选机安装",
    "磁选机": "磁选机安装",
    "湿式磁选机": "磁选机安装",
    "干式磁选机": "磁选机安装",
    "跳汰机": "重选设备安装",
    "摇床": "重选设备安装",
    "螺旋溜槽": "重选设备安装",
    "浓缩机": "浓缩机安装",
    "高效浓缩机": "浓缩机安装",
    "深锥浓缩机": "浓缩机安装",
    "压滤机": "压滤机安装",
    "板框压滤机": "压滤机安装",
    "厢式压滤机": "压滤机安装",
    "真空过滤机": "过滤机安装",
    "陶瓷过滤机": "过滤机安装",
    "带式过滤机": "过滤机安装",
    "回转干燥机": "干燥机安装",
    "喷雾干燥机": "干燥机安装",
    "闪速炉": "炉壳安装",
    "熔池熔炼炉": "炉壳安装",
    "艾萨炉": "炉壳安装",
    "奥斯麦特炉": "炉壳安装",
    "转炉": "炉壳安装",
    "PS转炉": "炉壳安装",
    "阳极炉": "炉壳安装",
    "精炼炉": "炉壳安装",
    "余热锅炉": "余热锅炉安装",
    "废热锅炉": "余热锅炉安装",
    "电除尘器": "除尘系统安装",
    "布袋除尘器": "除尘系统安装",
    "转化器": "制酸系统安装",
    "干吸塔": "制酸系统安装",
    "浸出槽": "浸出槽安装",
    "搅拌浸出槽": "浸出槽安装",
    "高压釜": "高压釜安装",
    "压力浸出釜": "高压釜安装",
    "萃取箱": "萃取箱安装",
    "混合澄清槽": "萃取箱安装",
    "萃取柱": "萃取箱安装",
    "电积槽": "电积槽安装",
    "电解槽": "电积槽安装",
    "离子交换柱": "离子交换柱安装",
    "蒸发器": "蒸发器/结晶器安装",
    "多效蒸发器": "蒸发器/结晶器安装",
    "MVR蒸发器": "蒸发器/结晶器安装",
    "结晶器": "蒸发器/结晶器安装",
    "空压机": "空压机安装",
    "矿用空压机": "空压机安装",
    "通风机": "通风机安装",
    "矿用通风机": "通风机安装",
    "排水泵": "水泵安装",
    "矿用排水泵": "水泵安装",
    "冷却塔": "冷却塔安装",
    "凉水塔": "冷却塔安装",
}


# 设备类型到工艺流程的直接映射
EQUIPMENT_PROCESS_MAP = {
    # 破碎系统
    "颚式破碎机": "1. 破碎系统", "圆锥破碎机": "1. 破碎系统",
    "反击式破碎机": "1. 破碎系统", "锤式破碎机": "1. 破碎系统",
    "辊式破碎机": "1. 破碎系统", "振动筛": "1. 破碎系统",
    "圆振动筛": "1. 破碎系统", "直线振动筛": "1. 破碎系统",
    "高频筛": "1. 破碎系统", "弛张筛": "1. 破碎系统",
    "给料机": "1. 破碎系统", "板式给料机": "1. 破碎系统",
    "振动给料机": "1. 破碎系统", "螺旋给料机": "1. 破碎系统",
    "圆盘给料机": "1. 破碎系统",
    # 磨矿系统
    "球磨机": "2. 磨矿系统", "棒磨机": "2. 磨矿系统",
    "自磨机": "2. 磨矿系统", "半自磨机": "2. 磨矿系统",
    "砾磨机": "2. 磨矿系统", "螺旋分级机": "2. 磨矿系统",
    "水力旋流器": "2. 磨矿系统", "高频细筛": "2. 磨矿系统",
    # 选别系统
    "浮选机": "3. 选别系统", "机械搅拌浮选机": "3. 选别系统",
    "充气式浮选机": "3. 选别系统", "浮选柱": "3. 选别系统",
    "磁选机": "3. 选别系统", "湿式磁选机": "3. 选别系统",
    "干式磁选机": "3. 选别系统", "高梯度磁选机": "3. 选别系统",
    "强磁选机": "3. 选别系统", "跳汰机": "3. 选别系统",
    "摇床": "3. 选别系统", "螺旋溜槽": "3. 选别系统",
    "离心选矿机": "3. 选别系统", "重介质旋流器": "3. 选别系统",
    "搅拌槽": "3. 选别系统", "搅拌桶": "3. 选别系统",
    "药剂搅拌槽": "3. 选别系统", "加药机": "3. 选别系统",
    "药剂添加系统": "3. 选别系统",
    # 脱水系统
    "浓缩机": "4. 脱水系统", "高效浓缩机": "4. 脱水系统",
    "深锥浓缩机": "4. 脱水系统", "斜板浓密机": "4. 脱水系统",
    "压滤机": "4. 脱水系统", "板框压滤机": "4. 脱水系统",
    "厢式压滤机": "4. 脱水系统", "隔膜压滤机": "4. 脱水系统",
    "真空过滤机": "4. 脱水系统", "陶瓷过滤机": "4. 脱水系统",
    "带式过滤机": "4. 脱水系统", "圆盘过滤机": "4. 脱水系统",
    "回转干燥机": "4. 脱水系统", "喷雾干燥机": "4. 脱水系统",
    "流化床干燥机": "4. 脱水系统",
    # 火法冶炼系统
    "闪速炉": "5. 火法冶炼系统", "熔池熔炼炉": "5. 火法冶炼系统",
    "艾萨炉": "5. 火法冶炼系统", "奥斯麦特炉": "5. 火法冶炼系统",
    "诺兰达炉": "5. 火法冶炼系统", "回转窑": "5. 火法冶炼系统",
    "鼓风炉": "5. 火法冶炼系统", "矿热电炉": "5. 火法冶炼系统",
    "熔炼电炉": "5. 火法冶炼系统", "贫化电炉": "5. 火法冶炼系统",
    "转炉": "5. 火法冶炼系统", "PS转炉": "5. 火法冶炼系统",
    "顶吹转炉": "5. 火法冶炼系统", "底吹转炉": "5. 火法冶炼系统",
    "阳极炉": "5. 火法冶炼系统", "精炼炉": "5. 火法冶炼系统",
    "回转式精炼炉": "5. 火法冶炼系统", "倾动式精炼炉": "5. 火法冶炼系统",
    "余热锅炉": "5. 火法冶炼系统", "废热锅炉": "5. 火法冶炼系统",
    "转化器": "5. 火法冶炼系统", "干吸塔": "5. 火法冶炼系统",
    "电除尘器": "5. 火法冶炼系统", "布袋除尘器": "5. 火法冶炼系统",
    # 湿法冶炼系统
    "浸出槽": "6. 湿法冶炼系统", "搅拌浸出槽": "6. 湿法冶炼系统",
    "空气搅拌浸出槽": "6. 湿法冶炼系统", "高压釜": "6. 湿法冶炼系统",
    "压力浸出釜": "6. 湿法冶炼系统", "萃取箱": "6. 湿法冶炼系统",
    "混合澄清槽": "6. 湿法冶炼系统", "萃取柱": "6. 湿法冶炼系统",
    "电积槽": "6. 湿法冶炼系统", "电解槽": "6. 湿法冶炼系统",
    "离子交换柱": "6. 湿法冶炼系统", "蒸发器": "6. 湿法冶炼系统",
    "多效蒸发器": "6. 湿法冶炼系统", "MVR蒸发器": "6. 湿法冶炼系统",
    "结晶器": "6. 湿法冶炼系统",
    # 公用辅助系统
    "空压机": "7. 公用辅助系统", "矿用空压机": "7. 公用辅助系统",
    "通风机": "7. 公用辅助系统", "矿用通风机": "7. 公用辅助系统",
    "排水泵": "7. 公用辅助系统", "矿用排水泵": "7. 公用辅助系统",
    "冷却塔": "7. 公用辅助系统", "凉水塔": "7. 公用辅助系统",
    "皮带输送机": "7. 公用辅助系统", "胶带输送机": "7. 公用辅助系统",
}


def _get_process_for_equipment(dev_type: str) -> str:
    """获取设备所属工艺流程。"""
    return EQUIPMENT_PROCESS_MAP.get(dev_type, "7. 公用辅助系统")


def generate_mining_schedule(
    devices: list = None,
    start_date: str = None,
    work_days_per_week: int = 6,
) -> dict:
    """
    生成矿山设备施工进度计划。
    
    Args:
        devices: 设备列表，用于根据实际设备调整工期
        start_date: 开工日期 (YYYY-MM-DD)，默认今天
        work_days_per_week: 每周工作天数
    
    Returns:
        施工进度计划
    """
    if start_date is None:
        start_date = datetime.date.today().strftime("%Y-%m-%d")
    
    # 确定需要排程的工艺流程
    if devices:
        processes_needed = set()
        for dev in devices:
            dev_type = dev.get("type", "")
            process = _get_process_for_equipment(dev_type)
            processes_needed.add(process)
        # 公用辅助系统总是需要
        processes_needed.add("7. 公用辅助系统")
    else:
        processes_needed = set(PROCESS_ORDER.keys())
    
    # 按工艺流程顺序排序
    sorted_processes = sorted(processes_needed, key=lambda p: PROCESS_ORDER.get(p, 99))
    
    # 计算每个工艺流程的工期
    process_schedules = {}
    current_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    overall_start = current_date
    overall_end = current_date
    
    for process in sorted_processes:
        phases = PROCESS_PHASES.get(process, [])
        if not phases:
            continue
        
        # 根据设备清单调整工期（如果有对应设备，使用标准工期；没有则跳过该阶段）
        active_phases = []
        if devices:
            device_types = set(dev.get("type", "") for dev in devices)
            for phase in phases:
                phase_name = phase["phase"]
                # 检查是否有设备对应此阶段
                phase_needed = False
                for dev_type in device_types:
                    if EQUIPMENT_PHASE_MAP.get(dev_type) == phase_name:
                        phase_needed = True
                        break
                # 基础施工、管道电气、试运转等通用阶段总是需要
                if phase_name in ["基础施工", "管道及电气安装", "单机试运转", "联动试运转", "烘炉", "耐压/气密性试验", "耐火材料砌筑"]:
                    phase_needed = True
                if phase_needed:
                    active_phases.append(phase)
        else:
            active_phases = phases
        
        # 计算各阶段的开始和结束日期（考虑依赖关系）
        phase_dates = {}
        for phase in active_phases:
            phase_name = phase["phase"]
            duration = phase["duration"]
            depends = phase.get("depends", [])
            
            # 计算最早开始日期
            earliest_start = current_date
            for dep in depends:
                if dep in phase_dates:
                    dep_end = phase_dates[dep]["end"]
                    if dep_end > earliest_start:
                        earliest_start = dep_end
            
            # 计算结束日期（考虑工作日）
            start = earliest_start
            end = _add_workdays(start, duration, work_days_per_week)
            
            phase_dates[phase_name] = {
                "phase": phase_name,
                "start": start,
                "end": end,
                "duration": duration,
                "depends": depends,
            }
            
            if end > overall_end:
                overall_end = end
        
        # 计算该流程的总工期
        process_start = min(pd["start"] for pd in phase_dates.values()) if phase_dates else current_date.strftime("%Y-%m-%d")
        process_end = max(pd["end"] for pd in phase_dates.values()) if phase_dates else current_date.strftime("%Y-%m-%d")
        process_start_date = process_start if isinstance(process_start, datetime.date) else datetime.datetime.strptime(process_start, "%Y-%m-%d").date()
        process_end_date = process_end if isinstance(process_end, datetime.date) else datetime.datetime.strptime(process_end, "%Y-%m-%d").date()
        process_duration = _workday_diff(process_start_date, process_end_date, work_days_per_week)
        
        # 将日期转字符串
        phases_out = []
        for pd in phase_dates.values():
            phases_out.append({
                "phase": pd["phase"],
                "start": pd["start"].strftime("%Y-%m-%d"),
                "end": pd["end"].strftime("%Y-%m-%d"),
                "duration": pd["duration"],
                "depends": pd["depends"],
            })
        
        process_schedules[process] = {
            "process": process,
            "order": PROCESS_ORDER.get(process, 99),
            "start": process_start if isinstance(process_start, str) else process_start.strftime("%Y-%m-%d"),
            "end": process_end if isinstance(process_end, str) else process_end.strftime("%Y-%m-%d"),
            "duration_days": process_duration,
            "phases": phases_out,
            "phase_count": len(phase_dates),
        }
        
        # 下一个流程从当前流程的基础施工完成后开始（允许部分并行）
        # 实际上，后续流程可以在前一流程开始后并行，但为了简化，按顺序排程
        # 公用辅助系统与其他系统并行
        if process != "7. 公用辅助系统":
            # 后续流程从当前流程开始后30天开始（允许并行）
            parallel_start = _add_workdays(current_date, 30, work_days_per_week)
            if parallel_start > current_date:
                current_date = parallel_start
    
    # 关键路径分析
    critical_path = _calculate_critical_path(process_schedules)
    
    # 施工进度预警
    warnings = _check_schedule_warnings(process_schedules, devices)
    
    result = {
        "ok": True,
        "start_date": start_date,
        "end_date": overall_end.strftime("%Y-%m-%d"),
        "total_duration_days": _workday_diff(
            datetime.datetime.strptime(start_date, "%Y-%m-%d").date(),
            overall_end,
            work_days_per_week
        ),
        "process_count": len(process_schedules),
        "total_phases": sum(ps["phase_count"] for ps in process_schedules.values()),
        "processes": sorted(process_schedules.values(), key=lambda x: x["order"]),
        "critical_path": critical_path,
        "warnings": warnings,
        "work_days_per_week": work_days_per_week,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    return result


def _add_workdays(start_date: datetime.date, days: int, work_days_per_week: int = 6) -> datetime.date:
    """添加工作日。"""
    current = start_date
    added = 0
    while added < days:
        current += datetime.timedelta(days=1)
        weekday = current.weekday()  # 0=Monday, 6=Sunday
        if work_days_per_week == 7:
            added += 1
        elif work_days_per_week == 6:
            if weekday < 6:  # Monday-Saturday
                added += 1
        elif work_days_per_week == 5:
            if weekday < 5:  # Monday-Friday
                added += 1
        else:
            if weekday < work_days_per_week:
                added += 1
    return current


def _workday_diff(start_date: datetime.date, end_date: datetime.date, work_days_per_week: int = 6) -> int:
    """计算工作日差。"""
    current = start_date
    days = 0
    while current < end_date:
        current += datetime.timedelta(days=1)
        weekday = current.weekday()
        if work_days_per_week == 7:
            days += 1
        elif work_days_per_week == 6:
            if weekday < 6:
                days += 1
        elif work_days_per_week == 5:
            if weekday < 5:
                days += 1
        else:
            if weekday < work_days_per_week:
                days += 1
    return days


def _calculate_critical_path(process_schedules: dict) -> list:
    """计算关键路径。"""
    # 关键路径是工期最长的流程链
    # 简化：按流程顺序，取每个流程中工期最长的阶段链
    critical_path = []
    
    sorted_processes = sorted(process_schedules.values(), key=lambda x: x["order"])
    
    for ps in sorted_processes:
        # 找到该流程中工期最长的阶段链（简化：取最后阶段）
        if ps["phases"]:
            last_phase = ps["phases"][-1]
            critical_path.append({
                "process": ps["process"],
                "phase": last_phase["phase"],
                "start": last_phase["start"],
                "end": last_phase["end"],
                "duration": last_phase["duration"],
            })
    
    return critical_path


def _check_schedule_warnings(process_schedules: dict, devices: list = None) -> list:
    """检查施工进度预警。"""
    warnings = []
    
    for ps in process_schedules.values():
        # 工期过长预警
        if ps["duration_days"] > 120:
            warnings.append({
                "severity": "medium",
                "type": "long_duration",
                "process": ps["process"],
                "message": f"{ps['process']}工期较长（{ps['duration_days']}天），建议增加施工队伍或优化施工顺序",
            })
        
        # 火法冶炼系统特殊预警
        if "火法" in ps["process"]:
            warnings.append({
                "severity": "high",
                "type": "high_risk",
                "process": ps["process"],
                "message": f"{ps['process']}涉及高温熔融金属和压力容器，需编制专项施工方案和安全预案",
            })
        
        # 湿法冶炼系统特殊预警
        if "湿法" in ps["process"]:
            warnings.append({
                "severity": "medium",
                "type": "corrosion_risk",
                "process": ps["process"],
                "message": f"{ps['process']}涉及腐蚀性介质，需注意设备衬里保护和管道材质确认",
            })
    
    # 总工期预警
    total_days = max(ps["duration_days"] for ps in process_schedules.values()) if process_schedules else 0
    if total_days > 180:
        warnings.append({
            "severity": "low",
            "type": "total_duration",
            "message": f"总工期较长（约{total_days}天），建议合理安排各系统并行施工",
        })
    
    return warnings


def generate_gantt_svg(schedule: dict, width: int = 1200, height: int = 600) -> str:
    """生成甘特图SVG。"""
    if not schedule.get("ok"):
        return "<svg>无法生成甘特图</svg>"
    
    processes = schedule.get("processes", [])
    if not processes:
        return "<svg>无进度数据</svg>"
    
    # 计算时间范围
    all_starts = []
    all_ends = []
    for ps in processes:
        for phase in ps["phases"]:
            all_starts.append(datetime.datetime.strptime(phase["start"], "%Y-%m-%d").date())
            all_ends.append(datetime.datetime.strptime(phase["end"], "%Y-%m-%d").date())
    
    if not all_starts or not all_ends:
        return "<svg>无阶段数据</svg>"
    
    min_date = min(all_starts)
    max_date = max(all_ends)
    total_days = (max_date - min_date).days + 1
    
    # SVG布局
    margin_left = 180
    margin_right = 20
    margin_top = 60
    margin_bottom = 40
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom
    
    # 计算每个阶段的位置
    row_height = chart_height / max(sum(len(ps["phases"]) for ps in processes), 1)
    bar_height = min(row_height * 0.7, 20)
    
    # 颜色
    colors = ["#1E5AA8", "#FF7A00", "#52C41A", "#FAAD14", "#9B59B6", "#1ABC9C", "#E74C3C"]
    
    svg_parts = []
    svg_parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    svg_parts.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')
    
    # 标题
    svg_parts.append(f'<text x="{width/2}" y="30" text-anchor="middle" font-size="16" font-weight="bold" fill="#1A1B1C">矿山设备施工进度计划甘特图</text>')
    svg_parts.append(f'<text x="{width/2}" y="50" text-anchor="middle" font-size="12" fill="#6B7280">开工: {schedule["start_date"]} | 竣工: {schedule["end_date"]} | 总工期: {schedule["total_duration_days"]}天</text>')
    
    # 时间轴
    month_positions = []
    current = min_date.replace(day=1)
    while current <= max_date:
        x = margin_left + ((current - min_date).days / total_days) * chart_width
        month_positions.append((x, current.strftime("%Y-%m")))
        # 垂直线
        svg_parts.append(f'<line x1="{x}" y1="{margin_top}" x2="{x}" y2="{height-margin_bottom}" stroke="#E4E3DD" stroke-width="0.5"/>')
        # 月份标签
        svg_parts.append(f'<text x="{x+5}" y="{margin_top-10}" font-size="10" fill="#6B7280">{current.strftime("%Y-%m")}</text>')
        # 下个月
        if current.month == 12:
            current = current.replace(year=current.year+1, month=1)
        else:
            current = current.replace(month=current.month+1)
    
    # 绘制各流程阶段
    y = margin_top
    process_index = 0
    for ps in processes:
        color = colors[process_index % len(colors)]
        process_index += 1
        
        # 流程标签
        first_phase = ps["phases"][0] if ps["phases"] else None
        if first_phase:
            svg_parts.append(f'<text x="{margin_left-10}" y="{y + len(ps["phases"])*row_height/2}" text-anchor="end" font-size="11" font-weight="bold" fill="{color}">{ps["process"]}</text>')
        
        for phase in ps["phases"]:
            phase_start = datetime.datetime.strptime(phase["start"], "%Y-%m-%d").date()
            phase_end = datetime.datetime.strptime(phase["end"], "%Y-%m-%d").date()
            phase_duration = (phase_end - phase_start).days + 1
            
            x = margin_left + ((phase_start - min_date).days / total_days) * chart_width
            bar_width = max((phase_duration / total_days) * chart_width, 2)
            bar_y = y + (row_height - bar_height) / 2
            
            # 条形
            svg_parts.append(f'<rect x="{x}" y="{bar_y}" width="{bar_width}" height="{bar_height}" fill="{color}" opacity="0.8" rx="2"/>')
            
            # 阶段名称（如果条形足够宽）
            if bar_width > 60:
                svg_parts.append(f'<text x="{x+bar_width/2}" y="{bar_y+bar_height/2+4}" text-anchor="middle" font-size="9" fill="#ffffff">{phase["phase"]}</text>')
            else:
                # 标签在条形右侧
                svg_parts.append(f'<text x="{x+bar_width+3}" y="{bar_y+bar_height/2+4}" font-size="9" fill="#6B7280">{phase["phase"]}</text>')
            
            y += row_height
        
        # 流程分隔线
        svg_parts.append(f'<line x1="{margin_left}" y1="{y}" x2="{width-margin_right}" y2="{y}" stroke="#E4E3DD" stroke-width="0.5"/>')
    
    # 图例
    legend_y = height - margin_bottom + 15
    legend_x = margin_left
    for i, ps in enumerate(processes[:7]):
        color = colors[i % len(colors)]
        svg_parts.append(f'<rect x="{legend_x + i*150}" y="{legend_y-10}" width="12" height="12" fill="{color}" rx="2"/>')
        svg_parts.append(f'<text x="{legend_x + i*150 + 18}" y="{legend_y}" font-size="10" fill="#6B7280">{ps["process"]}</text>')
    
    svg_parts.append('</svg>')
    
    return '\n'.join(svg_parts)


def get_schedule_stats(schedule: dict) -> dict:
    """获取进度计划统计。"""
    if not schedule.get("ok"):
        return {"ok": False, "error": "无效的进度计划"}
    
    processes = schedule.get("processes", [])
    total_phases = sum(ps["phase_count"] for ps in processes)
    avg_duration = sum(ps["duration_days"] for ps in processes) / max(len(processes), 1)
    longest_process = max(processes, key=lambda x: x["duration_days"]) if processes else None
    
    return {
        "ok": True,
        "process_count": len(processes),
        "total_phases": total_phases,
        "total_duration_days": schedule.get("total_duration_days", 0),
        "avg_process_duration": round(avg_duration, 1),
        "longest_process": longest_process["process"] if longest_process else "",
        "longest_process_duration": longest_process["duration_days"] if longest_process else 0,
        "critical_path_length": len(schedule.get("critical_path", [])),
        "warning_count": len(schedule.get("warnings", [])),
    }
