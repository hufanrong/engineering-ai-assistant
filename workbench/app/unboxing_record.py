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
