"""
v0.1.76：设备安装位置与设计变更联动

根据设备位置（车间、标高、坐标、相邻设备）自动生成设计变更要点，
包括变更编号、变更日期、变更原因、变更内容、影响范围、处理措施、
验收要求、参加人员等完整要素。
"""

import os
import json
import datetime
from typing import Optional


_CHANGE_FILE = os.path.join("data", "design_changes.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_changes() -> dict:
    if os.path.exists(_CHANGE_FILE):
        try:
            with open(_CHANGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_changes(changes: dict):
    _ensure_dirs()
    with open(_CHANGE_FILE, "w", encoding="utf-8") as f:
        json.dump(changes, f, ensure_ascii=False, indent=2)


# 设备类型设计变更要点
DEVICE_CHANGE_POINTS = {
    "泵": {
        "common_changes": [
            "泵基础尺寸或标高调整",
            "泵进出口管道走向或管径变更",
            "泵型号或参数变更",
            "泵安装位置调整",
            "泵联轴器形式变更",
            "泵密封形式变更",
        ],
        "impact_analysis": [
            "对基础施工的影响：需复核基础尺寸、标高、地脚螺栓位置",
            "对管道安装的影响：需重新计算管道应力，调整支吊架位置",
            "对电气安装的影响：需复核电机功率、电缆截面、开关容量",
            "对仪表安装的影响：需复核仪表量程、安装位置",
            "对试运转的影响：需调整试运转方案，复核试运转参数",
        ],
        "handling_measures": [
            "按变更后的图纸重新施工",
            "已施工部分按变更要求进行修改或返工",
            "修改部分需重新进行质量检验",
            "变更涉及的管道需重新进行压力试验",
            "变更涉及的电气需重新进行绝缘测试",
        ],
    },
    "压缩机": {
        "common_changes": [
            "压缩机基础尺寸或标高调整",
            "压缩机进出口管道走向或管径变更",
            "压缩机型号或参数变更",
            "压缩机安装位置调整",
            "润滑油系统管道变更",
            "冷却水系统管道变更",
            "压缩机厂房尺寸或布局变更",
        ],
        "impact_analysis": [
            "对基础施工的影响：需复核基础尺寸、标高、承载力、地脚螺栓位置",
            "对管道安装的影响：需重新计算管道应力，调整支吊架位置，润滑油管道需重新冲洗",
            "对电气安装的影响：需复核电机功率、电缆截面、开关容量、接地系统",
            "对仪表安装的影响：需复核仪表量程、安装位置、联锁逻辑",
            "对厂房建筑的影响：需复核厂房尺寸、吊车吨位、通风系统",
            "对试运转的影响：需调整试运转方案，复核试运转参数、润滑油规格",
        ],
        "handling_measures": [
            "按变更后的图纸重新施工",
            "已施工部分按变更要求进行修改或返工",
            "修改部分需重新进行质量检验",
            "变更涉及的管道需重新进行压力试验和冲洗",
            "变更涉及的电气需重新进行绝缘测试和接地电阻测试",
            "变更涉及的仪表需重新进行校验和联锁试验",
        ],
    },
    "塔器": {
        "common_changes": [
            "塔器基础尺寸或标高调整",
            "塔器高度或直径变更",
            "塔器安装位置调整",
            "塔器内件形式或数量变更",
            "塔器进出口管道位置变更",
            "塔器附件（人孔、平台、梯子）位置变更",
            "塔器吊装方案变更",
        ],
        "impact_analysis": [
            "对基础施工的影响：需复核基础尺寸、标高、承载力、沉降观测点",
            "对塔器制造的影响：需复核塔器高度、直径、壁厚、内件位置",
            "对管道安装的影响：需重新计算管道应力，调整支吊架位置",
            "对平台梯子的影响：需复核平台尺寸、梯子位置、荷载",
            "对吊装方案的影响：需重新计算吊装重量、吊装高度、吊车吨位、吊装半径",
            "对电气仪表的影响：需复核仪表安装位置、电缆长度、照明位置",
            "对防腐保温的影响：需复核防腐面积、保温厚度、保温面积",
        ],
        "handling_measures": [
            "按变更后的图纸重新施工",
            "已施工部分按变更要求进行修改或返工",
            "修改部分需重新进行质量检验",
            "变更涉及的塔器需重新进行压力试验",
            "变更涉及的吊装需重新编制吊装方案并审批",
            "变更涉及的内件需重新进行安装质量检查",
            "塔器垂直度需重新进行检测",
        ],
    },
    "换热器": {
        "common_changes": [
            "换热器基础尺寸或标高调整",
            "换热器型号或参数变更",
            "换热器安装位置调整",
            "换热器进出口管道位置变更",
            "换热器固定端/滑动端支座变更",
            "换热器抽芯空间变更",
        ],
        "impact_analysis": [
            "对基础施工的影响：需复核基础尺寸、标高、固定端/滑动端位置",
            "对管道安装的影响：需重新计算管道应力，调整支吊架位置，预留热膨胀量",
            "对检修空间的影响：需复核抽芯空间、检修通道",
            "对电气仪表的影响：需复核仪表安装位置、电缆长度",
            "对防腐保温的影响：需复核保温厚度、保温面积",
        ],
        "handling_measures": [
            "按变更后的图纸重新施工",
            "已施工部分按变更要求进行修改或返工",
            "修改部分需重新进行质量检验",
            "变更涉及的换热器需重新进行压力试验",
            "变更涉及的管道需重新进行压力试验",
            "滑动端支座间隙需重新进行检查和调整",
        ],
    },
    "容器": {
        "common_changes": [
            "容器基础尺寸或标高调整",
            "容器型号或参数变更",
            "容器安装位置调整",
            "容器进出口管道位置变更",
            "容器附件位置变更",
        ],
        "impact_analysis": [
            "对基础施工的影响：需复核基础尺寸、标高、地脚螺栓位置",
            "对管道安装的影响：需重新计算管道应力，调整支吊架位置",
            "对电气仪表的影响：需复核仪表安装位置、电缆长度",
            "对防腐保温的影响：需复核防腐面积、保温厚度、保温面积",
        ],
        "handling_measures": [
            "按变更后的图纸重新施工",
            "已施工部分按变更要求进行修改或返工",
            "修改部分需重新进行质量检验",
            "变更涉及的容器需重新进行压力试验",
            "立式容器垂直度或卧式容器水平度需重新进行检测",
        ],
    },
    "风机": {
        "common_changes": [
            "风机基础尺寸或标高调整",
            "风机型号或参数变更",
            "风机安装位置调整",
            "风机进出口管道走向变更",
            "风机减振器形式变更",
        ],
        "impact_analysis": [
            "对基础施工的影响：需复核基础尺寸、标高、地脚螺栓位置",
            "对管道安装的影响：需重新计算管道应力，调整支吊架位置，柔性接头位置",
            "对电气安装的影响：需复核电机功率、电缆截面、开关容量",
            "对减振的影响：需复核减振器型号、数量、压缩量",
            "对试运转的影响：需调整试运转方案，复核试运转参数",
        ],
        "handling_measures": [
            "按变更后的图纸重新施工",
            "已施工部分按变更要求进行修改或返工",
            "修改部分需重新进行质量检验",
            "变更涉及的减振器需重新进行压缩量检查",
            "变更涉及的风机需重新进行试运转",
        ],
    },
    "电机": {
        "common_changes": [
            "电机基础尺寸或标高调整",
            "电机型号或参数变更",
            "电机安装位置调整",
            "电机电缆路径变更",
            "电机接地方式变更",
        ],
        "impact_analysis": [
            "对基础施工的影响：需复核基础尺寸、标高、地脚螺栓位置",
            "对电气安装的影响：需复核电机功率、电缆截面、开关容量、保护定值",
            "对电缆敷设的影响：需复核电缆长度、电缆路径、电缆桥架尺寸",
            "对接地系统的影响：需复核接地电阻、接地线截面",
            "对仪表联锁的影响：需复核联锁逻辑、信号电缆",
        ],
        "handling_measures": [
            "按变更后的图纸重新施工",
            "已施工部分按变更要求进行修改或返工",
            "修改部分需重新进行质量检验",
            "变更涉及的电机需重新进行绝缘测试和直流电阻测试",
            "变更涉及的电缆需重新进行绝缘测试",
            "变更涉及的保护定值需重新进行整定和校验",
        ],
    },
    "阀门": {
        "common_changes": [
            "阀门型号或参数变更",
            "阀门安装位置调整",
            "阀门操作方式变更（手动/电动/气动）",
            "阀门管道管径变更",
        ],
        "impact_analysis": [
            "对管道安装的影响：需复核管道尺寸、法兰规格、螺栓规格",
            "对操作空间的影响：需复核阀门操作空间、检修空间",
            "对电气仪表的影响：电动/气动阀门需复核电源、气源、控制信号",
            "对管道试验的影响：需重新进行管道压力试验",
        ],
        "handling_measures": [
            "按变更后的图纸重新施工",
            "已施工部分按变更要求进行修改或返工",
            "修改部分需重新进行质量检验",
            "变更涉及的阀门需重新进行强度和严密性试验",
            "变更涉及的管道需重新进行压力试验",
            "电动/气动阀门需重新进行调试和联锁试验",
        ],
    },
    "储罐": {
        "common_changes": [
            "储罐基础尺寸或标高调整",
            "储罐容积或直径变更",
            "储罐安装位置调整",
            "储罐进出口管道位置变更",
            "储罐附件位置变更",
            "储罐防腐保温方案变更",
            "储罐施工方法变更（正装/倒装）",
        ],
        "impact_analysis": [
            "对基础施工的影响：需复核基础尺寸、标高、承载力、环墙尺寸、砂垫层厚度",
            "对储罐制造的影响：需复核储罐直径、高度、壁厚、底板排版、壁板排版",
            "对管道安装的影响：需重新计算管道应力，调整支吊架位置",
            "对平台梯子的影响：需复核平台尺寸、梯子位置、荷载",
            "对防腐保温的影响：需复核防腐面积、保温厚度、保温面积",
            "对施工方案的影响：需重新编制施工方案，复核吊装重量、提升装置",
            "对充水试验的影响：需复核充水高度、沉降观测点、排水方案",
        ],
        "handling_measures": [
            "按变更后的图纸重新施工",
            "已施工部分按变更要求进行修改或返工",
            "修改部分需重新进行质量检验",
            "变更涉及的储罐需重新进行真空箱试漏和充水试验",
            "变更涉及的焊缝需重新进行无损检测",
            "变更涉及的防腐保温需重新进行施工和质量检查",
            "基础沉降需重新进行观测和记录",
        ],
    },
}

DEFAULT_CHANGE_POINTS = {
    "common_changes": [
        "设备基础尺寸或标高调整",
        "设备型号或参数变更",
        "设备安装位置调整",
        "设备进出口管道位置变更",
    ],
    "impact_analysis": [
        "对基础施工的影响：需复核基础尺寸、标高、地脚螺栓位置",
        "对管道安装的影响：需重新计算管道应力，调整支吊架位置",
        "对电气仪表的影响：需复核仪表安装位置、电缆长度",
    ],
    "handling_measures": [
        "按变更后的图纸重新施工",
        "已施工部分按变更要求进行修改或返工",
        "修改部分需重新进行质量检验",
    ],
}


def get_change_points(dev_type: str) -> dict:
    """v0.1.76：获取设备类型设计变更要点。"""
    return DEVICE_CHANGE_POINTS.get(dev_type, DEFAULT_CHANGE_POINTS)


def generate_design_change(tag: str, change_date: str = None,
                            change_reason: str = "") -> dict:
    """v0.1.76：生成设备设计变更。
    
    Args:
        tag: 设备位号
        change_date: 变更日期，默认今天
        change_reason: 变更原因
    
    Returns:
        完整的设计变更
    """
    from . import installation_plan as _ip
    from . import equipment_types as _et
    from . import relations as _rel
    
    if change_date is None:
        change_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # 获取设备空间信息
    spatial_info = _ip.get_device_spatial_info(tag)
    if "error" in spatial_info:
        return spatial_info
    
    # 多源检测设备类型
    dev_type = spatial_info.get("type", "")
    if not dev_type:
        g = _rel.load_relations()
        devices = g.get("devices", [])
        device = next((d for d in devices if d["tag"] == tag), None)
        if device:
            dev_type = _et.get_equipment_type_from_devices([device])
    
    # 获取变更要点
    points = get_change_points(dev_type)
    
    # 生成变更编号
    change_number = f"GC-{tag}-{change_date.replace('-', '')}-001"
    
    # 变更位置
    change_location = f"{spatial_info.get('workshop', '未分配车间')} {tag}安装位置"
    if spatial_info.get("z") is not None:
        change_location += f"（标高EL{spatial_info['z']}m）"
    
    # 根据位置环境增加影响分析
    environment_impact = []
    elevation = spatial_info.get("z")
    if elevation is not None and elevation < 0:
        environment_impact.append(f"设备位于地下{abs(elevation)}m，变更需考虑防水、防潮、排水系统的影响")
        environment_impact.append("地下设备变更需复核地下结构承载力和防水措施")
    elif elevation is not None and elevation > 5:
        environment_impact.append(f"设备位于高位{elevation}m，变更需考虑高处作业安全防护和吊装方案")
        environment_impact.append("高位设备变更需复核操作平台、安全通道、吊装设施")
    if spatial_info.get("adjacent_devices") and len(spatial_info["adjacent_devices"]) >= 3:
        environment_impact.append("设备周围已安装多台设备，变更需考虑对已安装设备的保护和交叉作业影响")
        environment_impact.append("密集区域变更需合理安排施工顺序，避免影响其他设备安装")
    
    # 设备类型特殊影响
    type_special = {
        "塔器": ["塔器变更需重新编制吊装方案，复核吊车吨位和吊装半径", "塔器变更需复核内件安装位置和塔盘水平度"],
        "压缩机": ["压缩机变更需复核润滑油系统冲洗方案和油质要求", "压缩机变更需复核试运转方案和参数"],
        "储罐": ["储罐变更需重新编制施工方案，复核正装/倒装方法", "储罐变更需复核充水试验方案和沉降观测要求"],
    }
    if dev_type in type_special:
        environment_impact.extend(type_special[dev_type])
    
    change = {
        "change_number": change_number,
        "change_date": change_date,
        "tag": tag,
        "name": spatial_info.get("name", tag),
        "type": dev_type,
        "workshop": spatial_info.get("workshop", ""),
        "elevation": spatial_info.get("z"),
        "change_location": change_location,
        "change_reason": change_reason or "待补充",
        "common_changes": points["common_changes"],
        "impact_analysis": points["impact_analysis"] + environment_impact,
        "handling_measures": points["handling_measures"],
        "acceptance_requirements": [
            "按变更后的图纸和规范进行施工质量验收",
            "变更涉及的隐蔽工程需进行隐蔽验收",
            "变更涉及的压力试验需重新进行并记录",
            "变更涉及的无损检测需按规范要求进行",
            "变更涉及的试运转需按方案进行并记录参数",
            "所有变更内容需形成完整的施工记录和验收资料",
        ],
        "change_status": "待审批",  # 待审批/已审批/施工中/已完成
        "participants": [
            {"role": "设计单位", "name": ""},
            {"role": "建设单位", "name": ""},
            {"role": "监理单位", "name": ""},
            {"role": "施工单位", "name": ""},
        ],
        "generated_at": datetime.datetime.now().isoformat(),
        "adjacent_devices": spatial_info.get("adjacent_devices", []),
    }
    
    # 保存
    changes = _load_changes()
    change_key = f"{tag}_{change_date}"
    changes[change_key] = change
    _save_changes(changes)
    
    return change


def update_design_change(tag: str, change_date: str, updates: dict) -> dict:
    """v0.1.76：更新设计变更。"""
    changes = _load_changes()
    change_key = f"{tag}_{change_date}"
    
    if change_key not in changes:
        return {"error": "变更不存在", "tag": tag, "date": change_date}
    
    change = changes[change_key]
    change.update(updates)
    change["updated_at"] = datetime.datetime.now().isoformat()
    changes[change_key] = change
    _save_changes(changes)
    
    return {"ok": True, "tag": tag, "date": change_date, "updated_fields": list(updates.keys())}


def list_design_changes(tag: str = None) -> list:
    """v0.1.76：列出生成的设计变更。"""
    changes = _load_changes()
    result = []
    for key, change in changes.items():
        if tag and change.get("tag") != tag:
            continue
        result.append({
            "key": key,
            "change_number": change.get("change_number", ""),
            "change_date": change.get("change_date", ""),
            "tag": change.get("tag", ""),
            "name": change.get("name", ""),
            "type": change.get("type", ""),
            "workshop": change.get("workshop", ""),
            "change_status": change.get("change_status", ""),
        })
    result.sort(key=lambda x: x.get("change_date", ""), reverse=True)
    return result


def get_design_change_stats() -> dict:
    """v0.1.76：获取设计变更统计。"""
    changes = _load_changes()
    from . import relations as _rel
    g = _rel.load_relations()
    total_devices = len(g.get("devices", []))
    
    by_status = {}
    by_workshop = {}
    by_type = {}
    
    for change in changes.values():
        status = change.get("change_status", "待审批")
        by_status[status] = by_status.get(status, 0) + 1
        ws = change.get("workshop", "未分配")
        by_workshop[ws] = by_workshop.get(ws, 0) + 1
        t = change.get("type", "未知")
        by_type[t] = by_type.get(t, 0) + 1
    
    devices_with_changes = len(set(change.get("tag") for change in changes.values()))
    
    return {
        "total_changes": len(changes),
        "devices_with_changes": devices_with_changes,
        "total_devices": total_devices,
        "coverage_percent": round(devices_with_changes / total_devices * 100, 1) if total_devices > 0 else 0,
        "by_status": by_status,
        "by_workshop": by_workshop,
        "by_type": by_type,
    }
