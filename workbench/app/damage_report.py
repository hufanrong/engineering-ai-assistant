"""
v0.1.77：设备安装位置与货损报告联动

根据设备位置（车间、标高、坐标、相邻设备）自动生成货损报告要点，
包括报告编号、报告日期、设备信息、货损情况、损坏部位、损坏程度、
原因分析、处理措施、责任认定、索赔要求、参加人员等完整要素。
"""

import os
import json
import datetime
from typing import Optional


_REPORT_FILE = os.path.join("data", "damage_reports.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_reports() -> dict:
    if os.path.exists(_REPORT_FILE):
        try:
            with open(_REPORT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_reports(reports: dict):
    _ensure_dirs()
    with open(_REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)


# 设备类型货损要点
DEVICE_DAMAGE_POINTS = {
    "泵": {
        "common_damage_parts": [
            "泵壳（铸造缺陷、运输磕碰、裂纹）",
            "叶轮（变形、裂纹、叶片损坏）",
            "泵轴（弯曲、变形、轴颈磨损）",
            "机械密封（密封面损坏、弹簧变形）",
            "联轴器（弹性元件损坏、螺栓变形）",
            "轴承（保持架损坏、滚动体锈蚀）",
            "进出口法兰（密封面磕碰、螺栓孔变形）",
            "底座（变形、焊缝开裂、地脚螺栓孔损坏）",
        ],
        "damage_causes": [
            "运输过程中振动、碰撞导致设备部件损坏",
            "吊装过程中吊点选择不当导致设备变形",
            "装卸过程中操作不当导致设备磕碰",
            "包装防护不到位导致设备受潮、锈蚀",
            "运输车辆急刹车导致设备移位碰撞",
            "堆场存放不当导致设备受压变形",
        ],
        "handling_measures": [
            "对损坏部位进行拍照、录像记录，保留证据",
            "联系厂家技术人员现场鉴定损坏程度",
            "轻微损坏可现场修复的，编制修复方案经审批后实施",
            "严重损坏需返厂修理或更换的，办理退货/换货手续",
            "修复后需重新进行质量检验和试运转",
            "损坏设备隔离存放，避免与合格设备混淆",
        ],
        "claim_requirements": [
            "要求供应商承担设备维修费用",
            "要求供应商承担返厂运输费用",
            "要求供应商赔偿因设备损坏导致的工期延误损失",
            "要求供应商更换损坏的零部件",
            "要求供应商提供修复后的质量保证文件",
        ],
    },
    "压缩机": {
        "common_damage_parts": [
            "压缩机壳体（铸造缺陷、运输磕碰、裂纹）",
            "转子（轴弯曲、叶轮变形、平衡破坏）",
            "轴承（轴瓦磨损、保持架损坏、滚动体锈蚀）",
            "密封组件（密封环损坏、弹簧变形）",
            "联轴器（弹性元件损坏、螺栓变形）",
            "润滑油系统（油管变形、过滤器损坏、油泵损坏）",
            "冷却水系统（水管变形、冷却器损坏）",
            "气阀（阀片损坏、弹簧变形、阀座磕碰）",
            "底座（变形、焊缝开裂、地脚螺栓孔损坏）",
        ],
        "damage_causes": [
            "运输过程中振动、碰撞导致精密部件损坏",
            "吊装过程中吊点选择不当导致转子变形",
            "装卸过程中操作不当导致设备磕碰",
            "包装防护不到位导致精密部件受潮、锈蚀",
            "运输车辆急刹车导致设备移位碰撞",
            "堆场存放不当导致设备受压变形",
            "润滑油系统未充氮保护导致内部锈蚀",
        ],
        "handling_measures": [
            "对损坏部位进行拍照、录像记录，保留证据",
            "联系厂家技术人员现场鉴定损坏程度",
            "转子损坏需进行动平衡试验，确认是否可修复",
            "轴承损坏需更换新轴承，不得继续使用",
            "润滑油系统损坏需清洗、更换部件后重新冲洗",
            "严重损坏需返厂修理或更换的，办理退货/换货手续",
            "修复后需重新进行质量检验和试运转",
            "损坏设备隔离存放，避免与合格设备混淆",
        ],
        "claim_requirements": [
            "要求供应商承担设备维修费用",
            "要求供应商承担返厂运输费用",
            "要求供应商赔偿因设备损坏导致的工期延误损失",
            "要求供应商更换损坏的精密部件",
            "要求供应商提供转子动平衡试验报告",
            "要求供应商提供修复后的质量保证文件",
        ],
    },
    "塔器": {
        "common_damage_parts": [
            "塔体（椭圆度超标、凹陷、焊缝开裂）",
            "塔盘（变形、水平度超标、支撑圈损坏）",
            "填料（破碎、变形、污染）",
            "内件（分布器损坏、除沫器变形、降液管损坏）",
            "人孔（法兰密封面磕碰、螺栓变形）",
            "接管（法兰密封面磕碰、接管变形）",
            "支座（变形、焊缝开裂、地脚螺栓孔损坏）",
            "平台梯子（变形、焊缝开裂、栏杆损坏）",
            "防腐层（划伤、脱落、起泡）",
            "保温层（破损、脱落、受潮）",
        ],
        "damage_causes": [
            "运输过程中振动、碰撞导致塔体椭圆度超标",
            "吊装过程中吊点选择不当导致塔体变形",
            "装卸过程中操作不当导致塔体磕碰",
            "运输过程中塔盘未固定导致塔盘变形",
            "包装防护不到位导致防腐层划伤",
            "运输车辆急刹车导致设备移位碰撞",
            "堆场存放不当导致塔体受压变形",
            "现场倒运过程中操作不当导致接管损坏",
        ],
        "handling_measures": [
            "对损坏部位进行拍照、录像记录，保留证据",
            "联系厂家技术人员现场鉴定损坏程度",
            "塔体椭圆度超标需进行圆度矫正，矫正后重新检测",
            "塔盘变形需更换或矫正，矫正后重新检测水平度",
            "防腐层损坏需按原防腐方案进行修补",
            "焊缝开裂需进行无损检测，确认裂纹深度后制定修复方案",
            "严重损坏需返厂修理或更换的，办理退货/换货手续",
            "修复后需重新进行压力试验和质量检验",
            "损坏设备隔离存放，避免与合格设备混淆",
        ],
        "claim_requirements": [
            "要求供应商承担设备维修费用",
            "要求供应商承担返厂运输费用",
            "要求供应商赔偿因设备损坏导致的工期延误损失",
            "要求供应商更换损坏的内件和塔盘",
            "要求供应商提供修复后的压力试验报告",
            "要求供应商提供修复后的质量保证文件",
        ],
    },
    "换热器": {
        "common_damage_parts": [
            "壳体（凹陷、焊缝开裂、椭圆度超标）",
            "管束（换热管变形、管板损坏、折流板变形）",
            "管箱（法兰密封面磕碰、螺栓变形）",
            "法兰（密封面磕碰、螺栓孔变形）",
            "支座（变形、焊缝开裂、地脚螺栓孔损坏）",
            "防腐层（划伤、脱落）",
            "保温层（破损、脱落、受潮）",
        ],
        "damage_causes": [
            "运输过程中振动、碰撞导致壳体变形",
            "吊装过程中吊点选择不当导致管束变形",
            "装卸过程中操作不当导致设备磕碰",
            "包装防护不到位导致法兰密封面磕碰",
            "运输车辆急刹车导致设备移位碰撞",
            "堆场存放不当导致设备受压变形",
        ],
        "handling_measures": [
            "对损坏部位进行拍照、录像记录，保留证据",
            "联系厂家技术人员现场鉴定损坏程度",
            "换热管变形需进行抽芯检查，确认损坏程度",
            "法兰密封面磕碰需进行修复，修复后重新进行密封面检测",
            "壳体变形需进行圆度矫正，矫正后重新检测",
            "严重损坏需返厂修理或更换的，办理退货/换货手续",
            "修复后需重新进行压力试验和质量检验",
            "损坏设备隔离存放，避免与合格设备混淆",
        ],
        "claim_requirements": [
            "要求供应商承担设备维修费用",
            "要求供应商承担返厂运输费用",
            "要求供应商赔偿因设备损坏导致的工期延误损失",
            "要求供应商更换损坏的管束",
            "要求供应商提供修复后的压力试验报告",
            "要求供应商提供修复后的质量保证文件",
        ],
    },
    "容器": {
        "common_damage_parts": [
            "壳体（凹陷、焊缝开裂、椭圆度超标）",
            "封头（凹陷、变形、焊缝开裂）",
            "接管（法兰密封面磕碰、接管变形）",
            "人孔（法兰密封面磕碰、螺栓变形）",
            "支座（变形、焊缝开裂、地脚螺栓孔损坏）",
            "内件（分布器损坏、挡板变形）",
            "防腐层（划伤、脱落）",
            "保温层（破损、脱落、受潮）",
        ],
        "damage_causes": [
            "运输过程中振动、碰撞导致壳体变形",
            "吊装过程中吊点选择不当导致设备变形",
            "装卸过程中操作不当导致设备磕碰",
            "包装防护不到位导致法兰密封面磕碰",
            "运输车辆急刹车导致设备移位碰撞",
            "堆场存放不当导致设备受压变形",
        ],
        "handling_measures": [
            "对损坏部位进行拍照、录像记录，保留证据",
            "联系厂家技术人员现场鉴定损坏程度",
            "壳体变形需进行圆度矫正，矫正后重新检测",
            "焊缝开裂需进行无损检测，确认裂纹深度后制定修复方案",
            "法兰密封面磕碰需进行修复，修复后重新进行密封面检测",
            "严重损坏需返厂修理或更换的，办理退货/换货手续",
            "修复后需重新进行压力试验和质量检验",
            "损坏设备隔离存放，避免与合格设备混淆",
        ],
        "claim_requirements": [
            "要求供应商承担设备维修费用",
            "要求供应商承担返厂运输费用",
            "要求供应商赔偿因设备损坏导致的工期延误损失",
            "要求供应商更换损坏的内件",
            "要求供应商提供修复后的压力试验报告",
            "要求供应商提供修复后的质量保证文件",
        ],
    },
    "风机": {
        "common_damage_parts": [
            "机壳（凹陷、焊缝开裂、变形）",
            "叶轮（变形、叶片损坏、平衡破坏）",
            "主轴（弯曲、变形、轴颈磨损）",
            "轴承（保持架损坏、滚动体锈蚀）",
            "联轴器（弹性元件损坏、螺栓变形）",
            "减振器（弹簧变形、橡胶老化）",
            "进出口法兰（密封面磕碰、螺栓孔变形）",
            "底座（变形、焊缝开裂、地脚螺栓孔损坏）",
        ],
        "damage_causes": [
            "运输过程中振动、碰撞导致叶轮变形",
            "吊装过程中吊点选择不当导致主轴弯曲",
            "装卸过程中操作不当导致设备磕碰",
            "包装防护不到位导致轴承受潮、锈蚀",
            "运输车辆急刹车导致设备移位碰撞",
            "堆场存放不当导致设备受压变形",
        ],
        "handling_measures": [
            "对损坏部位进行拍照、录像记录，保留证据",
            "联系厂家技术人员现场鉴定损坏程度",
            "叶轮损坏需进行动平衡试验，确认是否可修复",
            "主轴弯曲需进行校直，校直后重新检测弯曲度",
            "轴承损坏需更换新轴承，不得继续使用",
            "减振器损坏需更换新减振器",
            "严重损坏需返厂修理或更换的，办理退货/换货手续",
            "修复后需重新进行质量检验和试运转",
            "损坏设备隔离存放，避免与合格设备混淆",
        ],
        "claim_requirements": [
            "要求供应商承担设备维修费用",
            "要求供应商承担返厂运输费用",
            "要求供应商赔偿因设备损坏导致的工期延误损失",
            "要求供应商更换损坏的叶轮和轴承",
            "要求供应商提供叶轮动平衡试验报告",
            "要求供应商提供修复后的质量保证文件",
        ],
    },
    "电机": {
        "common_damage_parts": [
            "机座（变形、焊缝开裂、地脚螺栓孔损坏）",
            "端盖（变形、轴承室磨损）",
            "转轴（弯曲、变形、轴颈磨损）",
            "定子绕组（绝缘损坏、受潮、短路）",
            "转子（笼条断裂、变形）",
            "轴承（保持架损坏、滚动体锈蚀）",
            "接线盒（变形、接线端子损坏）",
            "风扇（变形、叶片损坏）",
            "冷却器（水管变形、散热片损坏）",
        ],
        "damage_causes": [
            "运输过程中振动、碰撞导致转轴弯曲",
            "吊装过程中吊点选择不当导致机座变形",
            "装卸过程中操作不当导致设备磕碰",
            "包装防护不到位导致绕组受潮、绝缘损坏",
            "运输车辆急刹车导致设备移位碰撞",
            "堆场存放不当导致设备受压变形",
            "运输过程中未充氮保护导致内部锈蚀",
        ],
        "handling_measures": [
            "对损坏部位进行拍照、录像记录，保留证据",
            "联系厂家技术人员现场鉴定损坏程度",
            "绕组受潮需进行干燥处理，干燥后重新检测绝缘电阻",
            "转轴弯曲需进行校直，校直后重新检测弯曲度",
            "轴承损坏需更换新轴承，不得继续使用",
            "绝缘损坏需进行绕组修复或更换",
            "严重损坏需返厂修理或更换的，办理退货/换货手续",
            "修复后需重新进行绝缘测试和试运转",
            "损坏设备隔离存放，避免与合格设备混淆",
        ],
        "claim_requirements": [
            "要求供应商承担设备维修费用",
            "要求供应商承担返厂运输费用",
            "要求供应商赔偿因设备损坏导致的工期延误损失",
            "要求供应商更换损坏的轴承和绕组",
            "要求供应商提供绝缘测试报告",
            "要求供应商提供修复后的质量保证文件",
        ],
    },
    "阀门": {
        "common_damage_parts": [
            "阀体（铸造缺陷、裂纹、磕碰）",
            "阀盖（变形、螺栓孔损坏）",
            "阀杆（弯曲、变形、螺纹损坏）",
            "阀芯（密封面损坏、变形）",
            "阀座（密封面损坏、变形）",
            "法兰（密封面磕碰、螺栓孔变形）",
            "执行机构（气缸损坏、电机损坏、齿轮损坏）",
            "手轮（变形、轮辐损坏）",
        ],
        "damage_causes": [
            "运输过程中振动、碰撞导致密封面损坏",
            "吊装过程中操作不当导致阀杆弯曲",
            "装卸过程中操作不当导致阀门磕碰",
            "包装防护不到位导致密封面磕碰",
            "运输车辆急刹车导致阀门移位碰撞",
            "堆场存放不当导致阀门受压变形",
        ],
        "handling_measures": [
            "对损坏部位进行拍照、录像记录，保留证据",
            "联系厂家技术人员现场鉴定损坏程度",
            "密封面损坏需进行研磨修复，修复后重新进行密封试验",
            "阀杆弯曲需进行校直，校直后重新检测弯曲度",
            "执行机构损坏需进行修复或更换",
            "严重损坏需返厂修理或更换的，办理退货/换货手续",
            "修复后需重新进行强度试验和严密性试验",
            "损坏阀门隔离存放，避免与合格阀门混淆",
        ],
        "claim_requirements": [
            "要求供应商承担阀门维修费用",
            "要求供应商承担返厂运输费用",
            "要求供应商赔偿因阀门损坏导致的工期延误损失",
            "要求供应商更换损坏的阀芯和阀座",
            "要求供应商提供修复后的压力试验报告",
            "要求供应商提供修复后的质量保证文件",
        ],
    },
    "储罐": {
        "common_damage_parts": [
            "底板（变形、焊缝开裂、腐蚀）",
            "壁板（变形、凹陷、焊缝开裂、椭圆度超标）",
            "顶板（变形、凹陷、焊缝开裂）",
            "接管（法兰密封面磕碰、接管变形）",
            "人孔（法兰密封面磕碰、螺栓变形）",
            "附件（液位计损坏、温度计损坏、呼吸阀损坏）",
            "平台梯子（变形、焊缝开裂、栏杆损坏）",
            "防腐层（划伤、脱落、起泡）",
            "保温层（破损、脱落、受潮）",
        ],
        "damage_causes": [
            "运输过程中振动、碰撞导致壁板变形",
            "吊装过程中吊点选择不当导致罐体变形",
            "装卸过程中操作不当导致罐体磕碰",
            "包装防护不到位导致防腐层划伤",
            "运输车辆急刹车导致板材移位碰撞",
            "堆场存放不当导致板材受压变形",
            "现场倒运过程中操作不当导致接管损坏",
        ],
        "handling_measures": [
            "对损坏部位进行拍照、录像记录，保留证据",
            "联系厂家技术人员现场鉴定损坏程度",
            "壁板变形需进行矫正，矫正后重新检测椭圆度",
            "焊缝开裂需进行无损检测，确认裂纹深度后制定修复方案",
            "防腐层损坏需按原防腐方案进行修补",
            "底板变形需进行矫正，矫正后重新进行真空箱试漏",
            "严重损坏需返厂修理或更换的，办理退货/换货手续",
            "修复后需重新进行充水试验和质量检验",
            "损坏材料隔离存放，避免与合格材料混淆",
        ],
        "claim_requirements": [
            "要求供应商承担储罐维修费用",
            "要求供应商承担返厂运输费用",
            "要求供应商赔偿因储罐损坏导致的工期延误损失",
            "要求供应商更换损坏的板材和附件",
            "要求供应商提供修复后的充水试验报告",
            "要求供应商提供修复后的质量保证文件",
        ],
    },
}

DEFAULT_DAMAGE_POINTS = {
    "common_damage_parts": [
        "设备壳体（凹陷、焊缝开裂、变形）",
        "法兰（密封面磕碰、螺栓孔变形）",
        "底座（变形、焊缝开裂、地脚螺栓孔损坏）",
    ],
    "damage_causes": [
        "运输过程中振动、碰撞导致设备损坏",
        "吊装过程中操作不当导致设备变形",
        "装卸过程中操作不当导致设备磕碰",
    ],
    "handling_measures": [
        "对损坏部位进行拍照、录像记录，保留证据",
        "联系厂家技术人员现场鉴定损坏程度",
        "严重损坏需返厂修理或更换的，办理退货/换货手续",
        "修复后需重新进行质量检验",
    ],
    "claim_requirements": [
        "要求供应商承担设备维修费用",
        "要求供应商赔偿因设备损坏导致的工期延误损失",
        "要求供应商提供修复后的质量保证文件",
    ],
}


def get_damage_points(dev_type: str) -> dict:
    """v0.1.77：获取设备类型货损要点。"""
    return DEVICE_DAMAGE_POINTS.get(dev_type, DEFAULT_DAMAGE_POINTS)


def generate_damage_report(tag: str, report_date: str = None,
                            damage_description: str = "") -> dict:
    """v0.1.77：生成设备货损报告。
    
    Args:
        tag: 设备位号
        report_date: 报告日期，默认今天
        damage_description: 货损情况描述
    
    Returns:
        完整的货损报告
    """
    from . import installation_plan as _ip
    from . import equipment_types as _et
    from . import relations as _rel
    
    if report_date is None:
        report_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
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
    
    # 获取货损要点
    points = get_damage_points(dev_type)
    
    # 生成报告编号
    report_number = f"HS-{tag}-{report_date.replace('-', '')}-001"
    
    # 货损位置
    damage_location = f"{spatial_info.get('workshop', '未分配车间')} {tag}存放位置"
    if spatial_info.get("z") is not None:
        damage_location += f"（标高EL{spatial_info['z']}m）"
    
    # 根据位置环境增加原因分析和处理措施
    environment_notes = []
    elevation = spatial_info.get("z")
    if elevation is not None and elevation < 0:
        environment_notes.append(f"设备位于地下{abs(elevation)}m，货损可能与地下潮湿环境有关，需检查防潮措施")
        environment_notes.append("地下设备货损处理需考虑排水、通风条件")
    elif elevation is not None and elevation > 5:
        environment_notes.append(f"设备位于高位{elevation}m，货损可能与高处吊装作业有关，需复核吊装方案")
        environment_notes.append("高位设备货损处理需考虑高处作业安全防护")
    if spatial_info.get("adjacent_devices") and len(spatial_info["adjacent_devices"]) >= 3:
        environment_notes.append("设备周围已安装多台设备，货损处理需考虑对已安装设备的保护和交叉作业影响")
        environment_notes.append("密集区域货损处理需合理安排施工顺序，避免影响其他设备")
    
    # 设备类型特殊注意
    type_special = {
        "塔器": ["塔器货损需重点检查椭圆度和焊缝质量", "塔器货损处理需重新编制吊装方案"],
        "压缩机": ["压缩机货损需重点检查转子动平衡和轴承状况", "压缩机货损处理需重新进行润滑油系统冲洗"],
        "储罐": ["储罐货损需重点检查底板和壁板焊缝质量", "储罐货损处理需重新进行真空箱试漏和充水试验"],
    }
    if dev_type in type_special:
        environment_notes.extend(type_special[dev_type])
    
    report = {
        "report_number": report_number,
        "report_date": report_date,
        "tag": tag,
        "name": spatial_info.get("name", tag),
        "type": dev_type,
        "workshop": spatial_info.get("workshop", ""),
        "elevation": spatial_info.get("z"),
        "damage_location": damage_location,
        "damage_description": damage_description or "待补充",
        "common_damage_parts": points["common_damage_parts"],
        "damage_causes": points["damage_causes"] + environment_notes,
        "handling_measures": points["handling_measures"],
        "claim_requirements": points["claim_requirements"],
        "responsibility": "待认定",  # 待认定/供应商责任/运输方责任/施工方责任/多方责任
        "damage_degree": "待鉴定",  # 待鉴定/轻微/中等/严重/报废
        "participants": [
            {"role": "施工单位", "name": ""},
            {"role": "监理单位", "name": ""},
            {"role": "建设单位", "name": ""},
            {"role": "供应商代表", "name": ""},
        ],
        "generated_at": datetime.datetime.now().isoformat(),
        "adjacent_devices": spatial_info.get("adjacent_devices", []),
    }
    
    # 保存
    reports = _load_reports()
    report_key = f"{tag}_{report_date}"
    reports[report_key] = report
    _save_reports(reports)
    
    return report


def update_damage_report(tag: str, report_date: str, updates: dict) -> dict:
    """v0.1.77：更新货损报告。"""
    reports = _load_reports()
    report_key = f"{tag}_{report_date}"
    
    if report_key not in reports:
        return {"error": "报告不存在", "tag": tag, "date": report_date}
    
    report = reports[report_key]
    report.update(updates)
    report["updated_at"] = datetime.datetime.now().isoformat()
    reports[report_key] = report
    _save_reports(reports)
    
    return {"ok": True, "tag": tag, "date": report_date, "updated_fields": list(updates.keys())}


def list_damage_reports(tag: str = None) -> list:
    """v0.1.77：列出生成的货损报告。"""
    reports = _load_reports()
    result = []
    for key, report in reports.items():
        if tag and report.get("tag") != tag:
            continue
        result.append({
            "key": key,
            "report_number": report.get("report_number", ""),
            "report_date": report.get("report_date", ""),
            "tag": report.get("tag", ""),
            "name": report.get("name", ""),
            "type": report.get("type", ""),
            "workshop": report.get("workshop", ""),
            "damage_degree": report.get("damage_degree", ""),
            "responsibility": report.get("responsibility", ""),
        })
    result.sort(key=lambda x: x.get("report_date", ""), reverse=True)
    return result


def get_damage_report_stats() -> dict:
    """v0.1.77：获取货损报告统计。"""
    reports = _load_reports()
    from . import relations as _rel
    g = _rel.load_relations()
    total_devices = len(g.get("devices", []))
    
    by_degree = {}
    by_responsibility = {}
    by_workshop = {}
    by_type = {}
    
    for report in reports.values():
        degree = report.get("damage_degree", "待鉴定")
        by_degree[degree] = by_degree.get(degree, 0) + 1
        resp = report.get("responsibility", "待认定")
        by_responsibility[resp] = by_responsibility.get(resp, 0) + 1
        ws = report.get("workshop", "未分配")
        by_workshop[ws] = by_workshop.get(ws, 0) + 1
        t = report.get("type", "未知")
        by_type[t] = by_type.get(t, 0) + 1
    
    devices_with_damage = len(set(report.get("tag") for report in reports.values()))
    
    return {
        "total_reports": len(reports),
        "devices_with_damage": devices_with_damage,
        "total_devices": total_devices,
        "damage_rate_percent": round(devices_with_damage / total_devices * 100, 1) if total_devices > 0 else 0,
        "by_degree": by_degree,
        "by_responsibility": by_responsibility,
        "by_workshop": by_workshop,
        "by_type": by_type,
    }
