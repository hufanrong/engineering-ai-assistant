"""
v0.1.73：设备安装位置与开箱验收记录联动

根据设备位置（车间、标高、坐标、相邻设备）自动生成开箱验收记录要点，
包括设备基本信息、包装情况、外观检查、附件清单、随机文件、缺件情况、
验收结论、参加人员等完整要素。
"""

import os
import json
import datetime
from typing import Optional


_RECORD_FILE = os.path.join("data", "unboxing_records.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_records() -> dict:
    if os.path.exists(_RECORD_FILE):
        try:
            with open(_RECORD_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_records(records: dict):
    _ensure_dirs()
    with open(_RECORD_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


# 设备类型开箱验收要点
DEVICE_UNBOXING_POINTS = {
    "泵": {
        "inspection_items": [
            "泵体表面无裂纹、砂眼、气孔等铸造缺陷",
            "泵轴无弯曲、锈蚀，转动灵活无卡涩",
            "叶轮无变形、裂纹，与泵壳间隙符合要求",
            "机械密封或填料函完好，无泄漏痕迹",
            "轴承座无损伤，轴承转动灵活，润滑脂无变质",
            "联轴器完好，弹性元件无老化变形",
            "底座无变形，地脚螺栓孔尺寸符合设计",
            "进出口法兰密封面无损伤，法兰面平行度符合要求",
        ],
        "accessories": [
            "地脚螺栓及螺母",
            "联轴器防护罩",
            "机械密封备件",
            "专用工具",
        ],
        "documents": [
            "产品合格证",
            "产品使用说明书",
            "性能试验报告",
            "装箱单",
        ],
    },
    "压缩机": {
        "inspection_items": [
            "压缩机主机外观无损伤，机壳无裂纹变形",
            "转子转动灵活，无摩擦和卡涩现象",
            "轴承完好，润滑系统无泄漏",
            "进出口法兰密封面完好",
            "冷却器无损伤，管束无变形",
            "气液分离器内壁清洁，无锈蚀",
            "仪表盘完好，仪表接头无松动",
            "电机与压缩机对中良好，联轴器完好",
            "润滑油油质清澈，油位正常",
        ],
        "accessories": [
            "地脚螺栓及螺母",
            "联轴器及防护罩",
            "润滑油（首次充注量）",
            "过滤芯备件",
            "专用工具",
            "易损件包",
        ],
        "documents": [
            "产品合格证",
            "产品使用说明书",
            "性能试验报告",
            "装箱单",
            "润滑油规格说明",
        ],
    },
    "塔器": {
        "inspection_items": [
            "塔体表面无裂纹、凹陷、变形，焊缝外观合格",
            "塔体椭圆度、直线度符合规范要求",
            "法兰密封面无损伤，螺栓孔尺寸符合设计",
            "人孔、手孔开闭灵活，密封面完好",
            "接管无变形，法兰面完好",
            "塔盘支撑圈平整，间距符合设计",
            "填料无破损、污染，规格符合设计",
            "内件（分布器、除沫器等）完好无变形",
            "保温支撑圈焊接牢固，间距均匀",
            "铭牌清晰，内容与设计一致",
        ],
        "accessories": [
            "地脚螺栓及螺母",
            "人孔密封垫片",
            "塔盘紧固件",
            "专用工具",
        ],
        "documents": [
            "产品合格证",
            "质量证明书",
            "竣工图",
            "装箱单",
            "无损检测报告",
            "压力试验报告",
        ],
    },
    "换热器": {
        "inspection_items": [
            "壳体表面无裂纹、凹陷，焊缝外观合格",
            "管板密封面无损伤，管孔无毛刺",
            "管束无变形，换热管无弯曲、堵塞",
            "折流板无变形，间距符合设计",
            "管箱、浮头盖密封面完好",
            "法兰密封面无损伤，螺栓孔尺寸符合设计",
            "接管无变形，法兰面完好",
            "铭牌清晰，内容与设计一致",
            "水压试验合格标识清晰",
        ],
        "accessories": [
            "地脚螺栓及螺母",
            "管箱密封垫片",
            "浮头密封垫片",
            "专用工具",
        ],
        "documents": [
            "产品合格证",
            "质量证明书",
            "竣工图",
            "装箱单",
            "水压试验报告",
            "无损检测报告",
        ],
    },
    "容器": {
        "inspection_items": [
            "壳体表面无裂纹、凹陷、变形，焊缝外观合格",
            "法兰密封面无损伤，螺栓孔尺寸符合设计",
            "接管无变形，法兰面完好",
            "人孔、手孔开闭灵活，密封面完好",
            "内部清洁无杂物，内件完好",
            "铭牌清晰，内容与设计一致",
            "压力试验合格标识清晰",
        ],
        "accessories": [
            "地脚螺栓及螺母",
            "人孔密封垫片",
            "专用工具",
        ],
        "documents": [
            "产品合格证",
            "质量证明书",
            "竣工图",
            "装箱单",
            "压力试验报告",
        ],
    },
    "风机": {
        "inspection_items": [
            "机壳无裂纹、变形，内壁清洁",
            "叶轮无变形、裂纹，与机壳间隙均匀",
            "主轴无弯曲、锈蚀，转动灵活",
            "轴承座无损伤，轴承转动灵活",
            "进出口法兰密封面完好",
            "联轴器完好，弹性元件无老化",
            "底座无变形，地脚螺栓孔符合设计",
            "电机完好，绝缘电阻符合要求",
        ],
        "accessories": [
            "地脚螺栓及螺母",
            "联轴器防护罩",
            "轴承备件",
            "专用工具",
        ],
        "documents": [
            "产品合格证",
            "产品使用说明书",
            "性能试验报告",
            "装箱单",
        ],
    },
    "电机": {
        "inspection_items": [
            "电机外壳无损伤，散热片完好",
            "转轴无弯曲，转动灵活无卡涩",
            "接线盒完好，接线端子无松动、锈蚀",
            "风扇及风罩完好，无变形",
            "底座无变形，地脚螺栓孔符合设计",
            "铭牌清晰，电压、功率、转速等参数与设计一致",
            "绝缘电阻测试合格（不低于0.5MΩ）",
            "轴承润滑脂无变质，油位正常",
        ],
        "accessories": [
            "地脚螺栓及螺母",
            "接线盒密封垫片",
            "专用工具",
        ],
        "documents": [
            "产品合格证",
            "产品使用说明书",
            "出厂试验报告",
            "装箱单",
        ],
    },
    "阀门": {
        "inspection_items": [
            "阀体无裂纹、砂眼，表面光洁",
            "阀杆无弯曲、锈蚀，启闭灵活",
            "法兰密封面无损伤，螺栓孔尺寸符合设计",
            "阀芯、阀座密封面无划痕、损伤",
            "填料函完好，压盖螺栓齐全",
            "手轮/执行机构完好，操作灵活",
            "铭牌清晰，压力等级、口径、材质与设计一致",
            "阀门试验合格标识清晰",
        ],
        "accessories": [
            "法兰螺栓及螺母",
            "法兰密封垫片",
            "填料备件",
            "专用工具",
        ],
        "documents": [
            "产品合格证",
            "质量证明书",
            "阀门试验报告",
            "装箱单",
        ],
    },
    "储罐": {
        "inspection_items": [
            "罐底板无变形、裂纹，焊缝外观合格",
            "罐壁板无变形，椭圆度符合规范",
            "罐壁焊缝外观合格，无气孔、夹渣",
            "固定顶/浮顶完好，无变形",
            "接管无变形，法兰面完好",
            "人孔、清扫孔开闭灵活，密封面完好",
            "盘梯、平台栏杆焊接牢固",
            "防腐层完好，无脱落、划伤",
            "铭牌清晰，内容与设计一致",
        ],
        "accessories": [
            "人孔密封垫片",
            "防腐涂料（补口用）",
            "专用工具",
        ],
        "documents": [
            "产品合格证",
            "质量证明书",
            "竣工图",
            "装箱单",
            "焊缝检测报告",
            "基础沉降观测记录",
        ],
    },
    # 矿山/选矿设备
    "破碎机": {
        "check_items": ["设备型号规格核对", "主机外观检查", "颚板/圆锥头/反击板检查", "衬板检查", "传动装置检查", "电机检查", "地脚螺栓检查", "随机技术文件检查", "随机备件检查", "专用工具检查"],
        "tech_docs": ["产品合格证", "使用说明书", "基础图", "易损件图", "装箱单"],
        "key_points": ["破碎机衬板易磨损，需检查磨损情况", "颚式破碎机注意颚板齿形", "圆锥破碎机注意主轴和偏心套", "反击式破碎机注意板锤和反击板", "检查地脚螺栓数量和规格"],
    },
    "磨矿机": {
        "check_items": ["筒体外观检查", "端盖检查", "衬板检查", "钢球/钢棒检查", "大齿轮检查", "主轴承检查", "减速机检查", "电机检查", "润滑站检查", "随机技术文件检查", "随机备件检查"],
        "tech_docs": ["产品合格证", "使用说明书", "基础图", "装配图", "易损件图", "装箱单", "齿轮检测报告"],
        "key_points": ["磨机筒体大，需检查运输变形", "端盖与筒体配合面检查", "衬板数量和规格核对", "大齿轮齿面检查，无碰伤", "主轴承轴瓦检查，合金层无脱落", "钢球/钢棒规格和数量核对"],
    },
    "浮选机": {
        "check_items": ["槽体外观检查", "叶轮检查", "定子检查", "刮板检查", "传动装置检查", "电机检查", "充气装置检查", "随机技术文件检查"],
        "tech_docs": ["产品合格证", "使用说明书", "基础图", "装箱单"],
        "key_points": ["叶轮叶片无变形损坏", "定子间隙均匀", "刮板平直无变形", "多槽浮选机槽体连接面平整"],
    },
    "浓密机": {
        "check_items": ["池体外观检查", "耙架检查", "耙齿检查", "传动装置检查", "提升机构检查", "电机检查", "随机技术文件检查"],
        "tech_docs": ["产品合格证", "使用说明书", "基础图", "装箱单"],
        "key_points": ["池体无变形渗漏", "耙架平直无变形", "耙齿齐全无损坏", "提升机构动作灵活"],
    },
    # 湿法冶炼设备
    "浸出槽": {
        "check_items": ["槽体外观检查", "衬里检查", "搅拌器检查", "加热/冷却盘管检查", "传动装置检查", "电机检查", "随机技术文件检查"],
        "tech_docs": ["产品合格证", "使用说明书", "基础图", "衬里检测报告", "装箱单"],
        "key_points": ["衬胶/衬塑层无破损气泡", "衬里厚度检测", "搅拌器轴平直无变形", "盘管无泄漏", "机械密封件齐全"],
    },
    "电解槽": {
        "check_items": ["槽体外观检查", "衬里检查", "阳极板检查", "阴极板检查", "导电排检查", "绝缘件检查", "随机技术文件检查"],
        "tech_docs": ["产品合格证", "使用说明书", "基础图", "衬里检测报告", "极板材质证明", "装箱单"],
        "key_points": ["槽体衬里完好无破损", "阳极板尺寸和材质核对", "阴极板表面平整", "导电排接触面平整", "绝缘件齐全"],
    },
    "高压釜": {
        "check_items": ["釜体外观检查", "衬里检查", "搅拌器检查", "安全附件检查", "加热/冷却装置检查", "传动装置检查", "电机检查", "压力容器合格证", "随机技术文件检查"],
        "tech_docs": ["压力容器合格证", "产品质量证明书", "使用说明书", "基础图", "装配图", "安全附件校验报告", "装箱单"],
        "key_points": ["高压釜属于压力容器，必须有合格证和质量证明书", "釜体无碰撞变形", "衬里完好", "安全附件齐全（安全阀/爆破片/压力表/温度计）", "搅拌器密封件齐全"],
    },
    # 火法冶炼设备
    "熔炼炉": {
        "check_items": ["炉体钢结构检查", "炉衬材料检查", "铜水套检查", "燃烧器/喷枪检查", "冷却装置检查", "排烟装置检查", "随机技术文件检查"],
        "tech_docs": ["产品合格证", "使用说明书", "基础图", "炉衬砌筑图", "铜水套检测报告", "装箱单"],
        "key_points": ["钢结构无变形", "炉衬材料规格和数量核对", "铜水套无渗漏", "燃烧器/喷枪完好", "冷却管路畅通"],
    },
    "吹炼炉": {
        "check_items": ["炉体检查", "托圈检查", "托轮检查", "传动装置检查", "风口装置检查", "烟罩检查", "电机检查", "随机技术文件检查"],
        "tech_docs": ["产品合格证", "使用说明书", "基础图", "装配图", "齿轮检测报告", "装箱单"],
        "key_points": ["炉体无变形", "托圈与炉体配合面检查", "托轮表面无碰伤", "大齿轮/销齿完好", "风口装置齐全", "烟罩无变形"],
    },
    "回转窑": {
        "check_items": ["窑体分段检查", "轮带检查", "托轮检查", "挡轮检查", "传动装置检查", "密封装置检查", "电机检查", "随机技术文件检查"],
        "tech_docs": ["产品合格证", "使用说明书", "基础图", "装配图", "齿轮检测报告", "焊接检测报告", "装箱单"],
        "key_points": ["窑体分段无变形", "轮带表面无碰伤", "托轮表面无碰伤", "大齿轮完好", "密封件齐全", "窑体焊接质量证明"],
    },
    "余热锅炉": {
        "check_items": ["钢架检查", "汽包检查", "受热面管束检查", "炉墙材料检查", "安全附件检查", "随机技术文件检查"],
        "tech_docs": ["压力容器合格证", "产品质量证明书", "使用说明书", "基础图", "受热面图纸", "安全附件校验报告", "装箱单"],
        "key_points": ["余热锅炉属于压力容器，必须有合格证", "钢架无变形", "汽包无碰撞", "受热面管束无变形泄漏", "安全附件齐全"],
    },
    "冶金起重机": {
        "check_items": ["桥架检查", "大车运行机构检查", "小车运行机构检查", "起升机构检查", "钢丝绳检查", "吊钩检查", "制动器检查", "电气系统检查", "安全装置检查", "随机技术文件检查"],
        "tech_docs": ["特种设备制造许可证", "产品合格证", "使用说明书", "安装图", "电气原理图", "安全装置校验报告", "装箱单"],
        "key_points": ["冶金起重机属于特种设备，必须有制造许可证", "桥架无变形", "钢丝绳规格和长度核对", "吊钩无裂纹变形", "制动器完好", "安全装置齐全（限位/缓冲/防碰撞/超载）"],
    },

}

DEFAULT_UNBOXING_POINTS = {
    "inspection_items": [
        "设备表面无损伤、变形",
        "设备铭牌清晰，参数与设计一致",
        "法兰密封面无损伤",
        "接管无变形",
        "转动部件转动灵活",
    ],
    "accessories": ["地脚螺栓及螺母", "专用工具"],
    "documents": ["产品合格证", "使用说明书", "装箱单"],
}



# v0.1.84：合并矿山设备开箱验收要点
from .mining_equipment import MINING_UNBOXING as _MINING_UNBOX
DEVICE_UNBOXING_POINTS.update(_MINING_UNBOX)

def get_unboxing_points(dev_type: str) -> dict:
    """v0.1.73：获取设备类型开箱验收要点。"""
    return DEVICE_UNBOXING_POINTS.get(dev_type, DEFAULT_UNBOXING_POINTS)


def generate_unboxing_record(tag: str, unboxing_date: str = None,
                               location: str = None) -> dict:
    """v0.1.73：生成设备开箱验收记录。
    
    Args:
        tag: 设备位号
        unboxing_date: 开箱日期，默认今天
        location: 验收地点，默认设备安装位置
    
    Returns:
        完整的开箱验收记录
    """
    from . import installation_plan as _ip
    from . import equipment_types as _et
    from . import relations as _rel
    
    if unboxing_date is None:
        unboxing_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
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
    
    # 获取验收要点
    points = get_unboxing_points(dev_type)
    
    # 验收地点
    if location is None:
        location = f"{spatial_info.get('workshop', '未分配车间')} {tag}安装位置"
        if spatial_info.get("z") is not None:
            location += f"（标高EL{spatial_info['z']}m）"
    
    # 到货日期（默认开箱前7天）
    arrival_date = (datetime.datetime.strptime(unboxing_date, "%Y-%m-%d") - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    
    # 包装情况
    packaging_condition = "木箱包装，包装完好，无破损、受潮现象"
    
    # 根据位置环境增加注意事项
    environment_notes = []
    elevation = spatial_info.get("z")
    if elevation is not None and elevation > 3:
        environment_notes.append(f"设备安装位置标高{elevation}m，开箱后需妥善保管，防止高处坠落损坏")
        environment_notes.append("高位设备开箱后应尽快吊装就位，减少现场存放时间")
    if spatial_info.get("adjacent_devices") and len(spatial_info["adjacent_devices"]) >= 3:
        environment_notes.append("设备周围已安装多台设备，开箱时注意保护已安装设备，避免碰撞")
        environment_notes.append("密集区域开箱后应及时清理包装材料，保持通道畅通")
    
    # 设备类型特殊注意事项
    type_notes = {
        "塔器": ["塔器体积大，开箱前需确认现场存放空间充足", "塔器内件应单独存放，防止变形", "塔器法兰面应加装保护盖，防止损伤"],
        "压缩机": ["压缩机精密部件较多，开箱时注意保护", "压缩机润滑油系统应保持清洁，防止污染", "压缩机电气元件应防潮保护"],
        "储罐": ["储罐体积大，通常现场组装，开箱验收按部件分批进行", "储罐防腐层应重点检查，发现损伤及时修补"],
        "换热器": ["换热器管束应重点检查，防止运输过程中变形", "换热器管板密封面应加装保护盖"],
    }
    if dev_type in type_notes:
        environment_notes.extend(type_notes[dev_type])
    
    record = {
        "tag": tag,
        "name": spatial_info.get("name", tag),
        "type": dev_type,
        "workshop": spatial_info.get("workshop", ""),
        "elevation": spatial_info.get("z"),
        "model_spec": "",  # 待补充
        "manufacturer": "",  # 待补充
        "serial_number": "",  # 待补充
        "manufacture_date": "",  # 待补充
        "arrival_date": arrival_date,
        "unboxing_date": unboxing_date,
        "unboxing_location": location,
        "packaging_condition": packaging_condition,
        "appearance_inspection": points["inspection_items"],
        "accessories_list": points["accessories"],
        "documents_list": points["documents"],
        "missing_items": [],  # 待补充
        "damage_items": [],  # 待补充
        "environment_notes": environment_notes,
        "inspection_conclusion": "待验收",  # 合格/有条件接收/不合格
        "participants": [
            {"role": "施工单位", "name": ""},
            {"role": "监理单位", "name": ""},
            {"role": "建设单位", "name": ""},
            {"role": "供货单位", "name": ""},
        ],
        "generated_at": datetime.datetime.now().isoformat(),
        "adjacent_devices": spatial_info.get("adjacent_devices", []),
    }
    
    # 保存
    records = _load_records()
    record_key = f"{tag}_{unboxing_date}"
    records[record_key] = record
    _save_records(records)
    
    return record


def update_unboxing_record(tag: str, unboxing_date: str, updates: dict) -> dict:
    """v0.1.73：更新开箱验收记录。"""
    records = _load_records()
    record_key = f"{tag}_{unboxing_date}"
    
    if record_key not in records:
        return {"error": "记录不存在", "tag": tag, "date": unboxing_date}
    
    record = records[record_key]
    record.update(updates)
    record["updated_at"] = datetime.datetime.now().isoformat()
    records[record_key] = record
    _save_records(records)
    
    return {"ok": True, "tag": tag, "date": unboxing_date, "updated_fields": list(updates.keys())}


def list_unboxing_records(tag: str = None) -> list:
    """v0.1.73：列出生成的开箱验收记录。"""
    records = _load_records()
    result = []
    for key, record in records.items():
        if tag and record.get("tag") != tag:
            continue
        result.append({
            "key": key,
            "tag": record.get("tag", ""),
            "name": record.get("name", ""),
            "type": record.get("type", ""),
            "workshop": record.get("workshop", ""),
            "unboxing_date": record.get("unboxing_date", ""),
            "inspection_conclusion": record.get("inspection_conclusion", ""),
        })
    result.sort(key=lambda x: x.get("unboxing_date", ""), reverse=True)
    return result


def get_unboxing_stats() -> dict:
    """v0.1.73：获取开箱验收统计。"""
    records = _load_records()
    from . import relations as _rel
    g = _rel.load_relations()
    total_devices = len(g.get("devices", []))
    
    by_conclusion = {}
    by_workshop = {}
    by_type = {}
    
    for record in records.values():
        conclusion = record.get("inspection_conclusion", "待验收")
        by_conclusion[conclusion] = by_conclusion.get(conclusion, 0) + 1
        ws = record.get("workshop", "未分配")
        by_workshop[ws] = by_workshop.get(ws, 0) + 1
        t = record.get("type", "未知")
        by_type[t] = by_type.get(t, 0) + 1
    
    devices_with_records = len(set(record.get("tag") for record in records.values()))
    
    return {
        "total_records": len(records),
        "devices_with_records": devices_with_records,
        "total_devices": total_devices,
        "coverage_percent": round(devices_with_records / total_devices * 100, 1) if total_devices > 0 else 0,
        "by_conclusion": by_conclusion,
        "by_workshop": by_workshop,
        "by_type": by_type,
    }
