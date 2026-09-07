"""
v0.1.74：设备安装位置与隐蔽工程验收记录联动

根据设备位置（车间、标高、坐标、相邻设备）自动生成隐蔽工程验收记录要点，
包括工程名称、隐蔽部位、隐蔽内容、隐蔽日期、验收依据、质量检查、验收结论、参加人员。
"""

import os
import json
import datetime
from typing import Optional


_RECORD_FILE = os.path.join("data", "concealment_records.json")


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


# 设备类型隐蔽工程内容
DEVICE_CONCEALMENT_CONTENT = {
    "泵": {
        "concealment_parts": [
            "设备基础地脚螺栓预埋",
            "设备基础二次灌浆层",
            "泵进出口管道地下埋地部分",
            "泵底座与基础接触层",
            "润滑油系统地下管道",
        ],
        "inspection_items": [
            "地脚螺栓规格、数量、位置符合设计要求",
            "地脚螺栓预埋深度符合设计要求",
            "基础混凝土强度达到设计要求",
            "二次灌浆层密实、无空鼓、无裂缝",
            "埋地管道防腐层完好，无破损",
            "埋地管道坡度符合设计要求",
            "管道焊缝经无损检测合格",
            "底座与基础接触紧密，垫铁布置合理",
        ],
        "quality_standards": [
            "地脚螺栓中心位置偏差不大于2mm",
            "地脚螺栓垂直度偏差不大于1/100",
            "二次灌浆层强度不低于基础混凝土强度",
            "埋地管道防腐层厚度符合设计要求",
            "管道坡度偏差不大于设计值的±10%",
        ],
    },
    "压缩机": {
        "concealment_parts": [
            "压缩机基础地脚螺栓预埋",
            "压缩机基础二次灌浆层",
            "润滑油系统地下管道",
            "冷却水系统地下管道",
            "工艺管道地下埋地部分",
            "电缆桥架地下部分",
        ],
        "inspection_items": [
            "地脚螺栓规格、数量、位置符合设计要求",
            "基础混凝土强度达到设计要求（一般不低于C30）",
            "二次灌浆层密实、无空鼓",
            "润滑油管道冲洗合格，油质化验符合要求",
            "冷却水管道水压试验合格",
            "埋地管道防腐层完好",
            "电缆敷设符合规范，接地可靠",
            "垫铁布置合理，接触面积不小于60%",
        ],
        "quality_standards": [
            "地脚螺栓中心位置偏差不大于2mm",
            "基础混凝土强度不低于设计值",
            "润滑油系统冲洗后油质不低于NAS 8级",
            "冷却水管道试验压力为设计压力的1.5倍",
            "电缆绝缘电阻不低于0.5MΩ",
        ],
    },
    "塔器": {
        "concealment_parts": [
            "塔器基础地脚螺栓预埋",
            "塔器基础二次灌浆层",
            "塔器裙座与基础接触层",
            "塔底管道地下埋地部分",
            "塔基础防腐层",
        ],
        "inspection_items": [
            "地脚螺栓规格、数量、位置符合设计要求",
            "基础混凝土强度达到设计要求",
            "基础沉降观测点设置齐全",
            "二次灌浆层密实、无空鼓、无裂缝",
            "裙座与基础接触紧密，垫铁布置合理",
            "埋地管道防腐层完好，无破损",
            "管道焊缝经无损检测合格",
            "基础防腐层厚度符合设计要求",
            "地脚螺栓紧固力矩符合设计要求",
        ],
        "quality_standards": [
            "地脚螺栓中心位置偏差不大于3mm",
            "基础混凝土强度不低于设计值",
            "二次灌浆层强度不低于基础混凝土强度",
            "塔器垂直度偏差不大于塔高的1/1000",
            "基础沉降均匀，不均匀沉降不大于5mm",
            "埋地管道防腐层厚度符合设计要求",
        ],
    },
    "换热器": {
        "concealment_parts": [
            "换热器基础地脚螺栓预埋",
            "换热器基础二次灌浆层",
            "换热器进出口管道地下埋地部分",
            "换热器底座与基础接触层",
        ],
        "inspection_items": [
            "地脚螺栓规格、数量、位置符合设计要求",
            "基础混凝土强度达到设计要求",
            "二次灌浆层密实、无空鼓",
            "埋地管道防腐层完好",
            "管道焊缝经无损检测合格",
            "换热器滑动端支座间隙符合设计要求",
            "固定端支座紧固可靠",
            "垫铁布置合理，接触紧密",
        ],
        "quality_standards": [
            "地脚螺栓中心位置偏差不大于2mm",
            "二次灌浆层强度不低于基础混凝土强度",
            "滑动端支座间隙符合设计要求（一般5-10mm）",
            "埋地管道防腐层厚度符合设计要求",
            "换热器水平度偏差不大于0.1mm/m",
        ],
    },
    "容器": {
        "concealment_parts": [
            "容器基础地脚螺栓预埋",
            "容器基础二次灌浆层",
            "容器进出口管道地下埋地部分",
            "容器底座与基础接触层",
        ],
        "inspection_items": [
            "地脚螺栓规格、数量、位置符合设计要求",
            "基础混凝土强度达到设计要求",
            "二次灌浆层密实、无空鼓",
            "埋地管道防腐层完好",
            "管道焊缝经无损检测合格",
            "垫铁布置合理，接触紧密",
            "立式容器垂直度符合要求",
            "卧式容器水平度符合要求",
        ],
        "quality_standards": [
            "地脚螺栓中心位置偏差不大于2mm",
            "二次灌浆层强度不低于基础混凝土强度",
            "立式容器垂直度偏差不大于高度的1/1000",
            "卧式容器水平度偏差不大于0.1mm/m",
            "埋地管道防腐层厚度符合设计要求",
        ],
    },
    "风机": {
        "concealment_parts": [
            "风机基础地脚螺栓预埋",
            "风机基础二次灌浆层",
            "风机进出口管道地下埋地部分",
            "风机底座与基础接触层",
            "减振器安装层",
        ],
        "inspection_items": [
            "地脚螺栓规格、数量、位置符合设计要求",
            "基础混凝土强度达到设计要求",
            "二次灌浆层密实、无空鼓",
            "减振器型号、规格符合设计要求",
            "减振器安装水平，受力均匀",
            "埋地管道防腐层完好",
            "管道柔性接头安装正确",
            "垫铁布置合理，接触紧密",
        ],
        "quality_standards": [
            "地脚螺栓中心位置偏差不大于2mm",
            "二次灌浆层强度不低于基础混凝土强度",
            "减振器压缩量符合设计要求",
            "风机水平度偏差不大于0.1mm/m",
            "埋地管道防腐层厚度符合设计要求",
        ],
    },
    "电机": {
        "concealment_parts": [
            "电机基础地脚螺栓预埋",
            "电机基础二次灌浆层",
            "电机电缆地下敷设部分",
            "电机底座与基础接触层",
            "接地线埋设",
        ],
        "inspection_items": [
            "地脚螺栓规格、数量、位置符合设计要求",
            "基础混凝土强度达到设计要求",
            "二次灌浆层密实、无空鼓",
            "电缆敷设符合规范，电缆型号规格符合设计",
            "电缆绝缘电阻测试合格",
            "接地线规格符合设计，接地电阻测试合格",
            "电缆保护管敷设符合规范",
            "垫铁布置合理，接触紧密",
        ],
        "quality_standards": [
            "地脚螺栓中心位置偏差不大于2mm",
            "二次灌浆层强度不低于基础混凝土强度",
            "电缆绝缘电阻不低于0.5MΩ",
            "接地电阻不大于4Ω",
            "电机水平度偏差不大于0.1mm/m",
        ],
    },
    "阀门": {
        "concealment_parts": [
            "阀门井基础",
            "阀门井砌体",
            "阀门进出口管道地下埋地部分",
            "阀门井防水措施",
        ],
        "inspection_items": [
            "阀门井尺寸符合设计要求",
            "阀门井砌体灰缝饱满，无通缝",
            "阀门井防水措施到位，无渗漏",
            "埋地管道防腐层完好",
            "阀门安装方向正确（介质流向）",
            "阀门试验合格标识清晰",
            "管道焊缝经无损检测合格",
            "阀门操作空间满足要求",
        ],
        "quality_standards": [
            "阀门井尺寸偏差不大于设计值的±20mm",
            "砌体灰缝饱满度不低于80%",
            "阀门井无渗漏",
            "埋地管道防腐层厚度符合设计要求",
            "阀门启闭灵活，无卡涩",
        ],
    },
    "储罐": {
        "concealment_parts": [
            "储罐基础环墙",
            "储罐基础砂垫层",
            "储罐基础沥青砂绝缘层",
            "罐底中幅板与边缘板焊接",
            "罐底防腐层",
            "储罐进出管道地下埋地部分",
        ],
        "inspection_items": [
            "基础环墙混凝土强度达到设计要求",
            "砂垫层密实度符合设计要求",
            "沥青砂绝缘层厚度符合设计要求，表面平整",
            "罐底焊接外观合格，无气孔、夹渣、裂纹",
            "罐底真空箱试漏合格",
            "罐底防腐层完好，无破损",
            "基础沉降观测点设置齐全",
            "埋地管道防腐层完好",
            "管道焊缝经无损检测合格",
        ],
        "quality_standards": [
            "基础混凝土强度不低于设计值",
            "砂垫层密实度不低于设计值（一般95%）",
            "沥青砂绝缘层厚度偏差不大于设计值的±5mm",
            "罐底真空箱试漏无渗漏",
            "基础沉降均匀，不均匀沉降不大于50mm",
            "埋地管道防腐层厚度符合设计要求",
        ],
    },
}

DEFAULT_CONCEALMENT_CONTENT = {
    "concealment_parts": [
        "设备基础地脚螺栓预埋",
        "设备基础二次灌浆层",
        "设备进出口管道地下埋地部分",
    ],
    "inspection_items": [
        "地脚螺栓规格、数量、位置符合设计要求",
        "基础混凝土强度达到设计要求",
        "二次灌浆层密实、无空鼓",
        "埋地管道防腐层完好",
        "管道焊缝经无损检测合格",
    ],
    "quality_standards": [
        "地脚螺栓中心位置偏差不大于2mm",
        "二次灌浆层强度不低于基础混凝土强度",
        "埋地管道防腐层厚度符合设计要求",
    ],
}


def get_concealment_content(dev_type: str) -> dict:
    """v0.1.74：获取设备类型隐蔽工程内容。"""
    return DEVICE_CONCEALMENT_CONTENT.get(dev_type, DEFAULT_CONCEALMENT_CONTENT)


def generate_concealment_record(tag: str, concealment_date: str = None,
                                  location: str = None) -> dict:
    """v0.1.74：生成设备隐蔽工程验收记录。
    
    Args:
        tag: 设备位号
        concealment_date: 隐蔽日期，默认今天
        location: 隐蔽部位，默认设备安装位置
    
    Returns:
        完整的隐蔽工程验收记录
    """
    from . import installation_plan as _ip
    from . import equipment_types as _et
    from . import relations as _rel
    
    if concealment_date is None:
        concealment_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
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
    
    # 获取隐蔽工程内容
    content = get_concealment_content(dev_type)
    
    # 隐蔽部位
    if location is None:
        location = f"{spatial_info.get('workshop', '未分配车间')} {tag}安装位置"
        if spatial_info.get("z") is not None:
            location += f"（标高EL{spatial_info['z']}m）"
    
    # 验收依据
    acceptance_basis = [
        "施工图纸及设计变更",
        "设备安装使用说明书",
        "《机械设备安装工程施工及验收通用规范》GB 50231",
        "《现场设备、工业管道焊接工程施工规范》GB 50236",
    ]
    if dev_type == "塔器":
        acceptance_basis.append("《立式圆筒形钢制焊接储罐施工规范》GB 50128")
    elif dev_type == "压缩机":
        acceptance_basis.append("《压缩机、风机、泵安装工程施工及验收规范》GB 50275")
    elif dev_type == "泵":
        acceptance_basis.append("《压缩机、风机、泵安装工程施工及验收规范》GB 50275")
    
    # 根据位置环境增加注意事项
    environment_notes = []
    elevation = spatial_info.get("z")
    if elevation is not None and elevation < 0:
        environment_notes.append(f"设备位于地下{abs(elevation)}m，隐蔽工程需重点检查防水、防潮措施")
        environment_notes.append("地下设备隐蔽前需确认排水系统畅通")
    elif elevation is not None and elevation > 5:
        environment_notes.append(f"设备位于高位{elevation}m，隐蔽工程需检查高处作业安全防护")
    if spatial_info.get("adjacent_devices") and len(spatial_info["adjacent_devices"]) >= 3:
        environment_notes.append("设备周围已安装多台设备，隐蔽工程施工时注意保护已安装设备")
        environment_notes.append("密集区域隐蔽工程需合理安排施工顺序，避免交叉作业影响")
    
    # 设备类型特殊注意事项
    type_notes = {
        "储罐": ["储罐基础隐蔽前需完成基础沉降观测初始值记录", "罐底焊接完成后需进行真空箱试漏，合格后方可隐蔽"],
        "塔器": ["塔器基础隐蔽前需确认基础沉降观测点设置齐全", "塔器地脚螺栓紧固力矩需符合设计要求，做好记录"],
        "压缩机": ["压缩机基础二次灌浆前需确认地脚螺栓紧固完毕", "润滑油系统管道隐蔽前需完成冲洗和油质化验"],
    }
    if dev_type in type_notes:
        environment_notes.extend(type_notes[dev_type])
    
    record = {
        "tag": tag,
        "name": spatial_info.get("name", tag),
        "type": dev_type,
        "workshop": spatial_info.get("workshop", ""),
        "elevation": spatial_info.get("z"),
        "concealment_date": concealment_date,
        "concealment_location": location,
        "concealment_parts": content["concealment_parts"],
        "inspection_items": content["inspection_items"],
        "quality_standards": content["quality_standards"],
        "acceptance_basis": acceptance_basis,
        "environment_notes": environment_notes,
        "inspection_result": "待验收",  # 合格/不合格/有条件合格
        "inspection_conclusion": "",
        "participants": [
            {"role": "施工单位", "name": ""},
            {"role": "监理单位", "name": ""},
            {"role": "建设单位", "name": ""},
            {"role": "设计单位", "name": ""},
        ],
        "generated_at": datetime.datetime.now().isoformat(),
        "adjacent_devices": spatial_info.get("adjacent_devices", []),
    }
    
    # 保存
    records = _load_records()
    record_key = f"{tag}_{concealment_date}"
    records[record_key] = record
    _save_records(records)
    
    return record


def update_concealment_record(tag: str, concealment_date: str, updates: dict) -> dict:
    """v0.1.74：更新隐蔽工程验收记录。"""
    records = _load_records()
    record_key = f"{tag}_{concealment_date}"
    
    if record_key not in records:
        return {"error": "记录不存在", "tag": tag, "date": concealment_date}
    
    record = records[record_key]
    record.update(updates)
    record["updated_at"] = datetime.datetime.now().isoformat()
    records[record_key] = record
    _save_records(records)
    
    return {"ok": True, "tag": tag, "date": concealment_date, "updated_fields": list(updates.keys())}


def list_concealment_records(tag: str = None) -> list:
    """v0.1.74：列出生成的隐蔽工程验收记录。"""
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
            "concealment_date": record.get("concealment_date", ""),
            "inspection_result": record.get("inspection_result", ""),
        })
    result.sort(key=lambda x: x.get("concealment_date", ""), reverse=True)
    return result


def get_concealment_stats() -> dict:
    """v0.1.74：获取隐蔽工程验收统计。"""
    records = _load_records()
    from . import relations as _rel
    g = _rel.load_relations()
    total_devices = len(g.get("devices", []))
    
    by_result = {}
    by_workshop = {}
    by_type = {}
    
    for record in records.values():
        result = record.get("inspection_result", "待验收")
        by_result[result] = by_result.get(result, 0) + 1
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
        "by_result": by_result,
        "by_workshop": by_workshop,
        "by_type": by_type,
    }
