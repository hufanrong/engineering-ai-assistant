"""
v0.1.71：设备安装位置与施工日志联动

根据设备位置（车间、标高、坐标、相邻设备）自动生成施工日志要点，
包括日期、天气、施工部位、施工内容、人员配置、机具设备、材料使用、
质量检查、安全情况、问题及处理、明日计划。
"""

import os
import json
import datetime
from typing import Optional


_LOG_FILE = os.path.join("data", "site_logs.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_logs() -> dict:
    if os.path.exists(_LOG_FILE):
        try:
            with open(_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_logs(logs: dict):
    _ensure_dirs()
    with open(_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


# 设备类型施工日志模板
DEVICE_LOG_TEMPLATES = {
    "泵": {
        "typical_work": ["泵设备开箱检验", "泵基础验收与处理", "泵就位与初平", "泵管道连接", "联轴器对中", "泵二次灌浆", "泵精平精正", "泵单机试运转"],
        "personnel": ["钳工2人", "起重工1人", "电工1人", "普工2人"],
        "equipment": ["25t汽车吊1台", "手动葫芦2台", "水平仪1台", "百分表1套", "扭矩扳手1套"],
        "materials": ["地脚螺栓", "斜垫铁", "平垫铁", "灌浆料", "润滑油"],
        "quality_checks": ["泵水平度检查", "联轴器对中检查", "管道法兰平行度检查", "地脚螺栓紧固力矩检查"],
    },
    "压缩机": {
        "typical_work": ["压缩机主机开箱检验", "压缩机基础验收", "主机就位与初平", "辅机安装", "润滑油系统冲洗", "管道连接", "联轴器对中", "压缩机单机试运转"],
        "personnel": ["钳工3人", "起重工2人", "电工2人", "管工2人", "普工3人"],
        "equipment": ["80t汽车吊1台", "手动葫芦2台", "水平仪1台", "百分表2套", "油质化验设备1套"],
        "materials": ["地脚螺栓", "垫铁", "灌浆料", "润滑油", "密封垫片"],
        "quality_checks": ["主机水平度检查", "联轴器对中检查", "润滑油油质化验", "轴承温度检查", "振动值检测"],
    },
    "塔器": {
        "typical_work": ["塔器开箱检验", "塔基础验收", "塔器吊装就位", "塔体初平与垂直度检测", "塔体临时固定", "内件安装", "管道连接", "附件安装", "水压试验"],
        "personnel": ["钳工4人", "起重工4人", "焊工2人", "电工1人", "普工4人", "安全员1人"],
        "equipment": ["200t汽车吊1台", "50t溜尾吊车1台", "经纬仪1台", "手动葫芦4台", "电焊机2台"],
        "materials": ["地脚螺栓", "垫铁", "灌浆料", "塔盘", "填料", "密封垫片"],
        "quality_checks": ["塔体垂直度检测", "塔盘水平度检查", "填料装填高度检查", "水压试验压力检查", "焊缝外观检查"],
    },
    "换热器": {
        "typical_work": ["换热器开箱检验", "基础验收", "换热器就位", "水压试验", "管道连接", "抽芯检查", "附件安装", "保温施工"],
        "personnel": ["钳工2人", "起重工1人", "管工2人", "焊工1人", "普工2人"],
        "equipment": ["50t汽车吊1台", "手动葫芦2台", "水平仪1台", "试压泵1台"],
        "materials": ["地脚螺栓", "垫铁", "灌浆料", "密封垫片", "保温材料"],
        "quality_checks": ["水平度检查", "水压试验检查", "管板密封检查", "法兰连接检查"],
    },
    "容器": {
        "typical_work": ["容器开箱检验", "基础验收", "容器就位", "初平初正", "管道连接", "附件安装", "水压试验", "保温施工"],
        "personnel": ["钳工2人", "起重工1人", "管工1人", "普工2人"],
        "equipment": ["30t汽车吊1台", "手动葫芦2台", "水平仪1台", "试压泵1台"],
        "materials": ["地脚螺栓", "垫铁", "灌浆料", "密封垫片"],
        "quality_checks": ["垂直度/水平度检查", "水压试验检查", "附件安装方向检查"],
    },
    "风机": {
        "typical_work": ["风机开箱检验", "基础验收", "风机就位", "电机就位", "初平初正", "联轴器对中", "管道连接", "单机试运转"],
        "personnel": ["钳工2人", "起重工1人", "电工1人", "管工1人", "普工2人"],
        "equipment": ["25t汽车吊1台", "手动葫芦2台", "水平仪1台", "百分表1套"],
        "materials": ["地脚螺栓", "垫铁", "灌浆料", "柔性接头", "密封垫片"],
        "quality_checks": ["水平度检查", "联轴器对中检查", "轴承温度检查", "振动值检测", "叶轮转向检查"],
    },
    "电机": {
        "typical_work": ["电机开箱检验", "绝缘电阻测试", "基础验收", "电机就位", "初平初正", "电气接线", "联轴器对中", "单机试运转"],
        "personnel": ["电工2人", "钳工1人", "起重工1人", "普工1人"],
        "equipment": ["16t汽车吊1台", "手动葫芦1台", "水平仪1台", "兆欧表1台", "钳形电流表1台"],
        "materials": ["地脚螺栓", "垫铁", "灌浆料", "电缆", "接线端子"],
        "quality_checks": ["绝缘电阻测试", "水平度检查", "联轴器对中检查", "空载电流测试", "轴承温度检查"],
    },
    "阀门": {
        "typical_work": ["阀门检验", "阀门强度试验", "阀门严密性试验", "阀门就位安装", "法兰连接/焊接", "传动装置安装", "阀门调试"],
        "personnel": ["管工2人", "焊工1人", "起重工1人", "普工1人"],
        "equipment": ["试压泵1台", "电焊机1台", "扭矩扳手1套", "手动葫芦1台"],
        "materials": ["阀门", "法兰垫片", "螺栓", "焊条"],
        "quality_checks": ["强度试验检查", "严密性试验检查", "阀门开关灵活性检查", "法兰紧固力矩检查", "焊缝无损检测"],
    },
    "储罐": {
        "typical_work": ["基础验收", "罐底铺设", "罐底焊接", "罐壁安装", "罐壁焊接", "固定顶安装", "附件安装", "充水试验", "防腐保温"],
        "personnel": ["焊工6人", "钳工2人", "起重工2人", "电工1人", "普工6人", "安全员1人"],
        "equipment": ["250t汽车吊1台", "电焊机6台", "真空箱1套", "提升装置1套", "经纬仪1台"],
        "materials": ["钢板", "焊条", "防腐涂料", "保温材料", "密封材料"],
        "quality_checks": ["罐底真空试漏", "罐壁煤油试漏", "垂直度检测", "充水试验沉降观测", "焊缝无损检测", "防腐层厚度检测"],
    },
}

DEFAULT_LOG_TEMPLATE = {
    "typical_work": ["设备开箱检验", "基础验收", "设备就位", "初平初正", "管道连接", "附件安装", "试运转"],
    "personnel": ["钳工2人", "起重工1人", "电工1人", "普工2人"],
    "equipment": ["25t汽车吊1台", "手动葫芦2台", "水平仪1台"],
    "materials": ["地脚螺栓", "垫铁", "灌浆料"],
    "quality_checks": ["水平度检查", "地脚螺栓紧固检查", "试运转参数检查"],
}


def get_log_template(dev_type: str) -> dict:
    """v0.1.71：获取设备类型施工日志模板。"""
    return DEVICE_LOG_TEMPLATES.get(dev_type, DEFAULT_LOG_TEMPLATE)


def generate_site_log(tag: str, log_date: str = None, weather: str = "晴") -> dict:
    """v0.1.71：生成设备施工日志。
    
    Args:
        tag: 设备位号
        log_date: 日志日期（YYYY-MM-DD），默认今天
        weather: 天气情况
    
    Returns:
        完整的施工日志
    """
    from . import installation_plan as _ip
    from . import equipment_types as _et
    from . import relations as _rel
    from . import construction_schedule as _cs
    
    if log_date is None:
        log_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
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
    
    # 获取设备施工状态
    try:
        status_info = _cs.get_device_status(tag)
        construction_status = status_info.get("status", "pending") if isinstance(status_info, dict) else "pending"
    except Exception:
        construction_status = "pending"
    
    # 获取日志模板
    template = get_log_template(dev_type)
    
    # 根据施工状态确定当前施工内容
    status_work_map = {
        "pending": template["typical_work"][:2],  # 开箱检验、基础验收
        "in_progress": template["typical_work"][2:5],  # 就位、初平、管道连接
        "completed": template["typical_work"][-2:],  # 试运转、收尾
    }
    current_work = status_work_map.get(construction_status, template["typical_work"][:3])
    
    # 1. 施工部位
    construction_location = f"{spatial_info.get('workshop', '未分配车间')} {tag} {spatial_info.get('name', tag)}"
    if spatial_info.get("z") is not None:
        construction_location += f"（标高EL{spatial_info['z']}m）"
    if spatial_info.get("x") is not None and spatial_info.get("y") is not None:
        construction_location += f"（坐标X:{spatial_info['x']}m, Y:{spatial_info['y']}m）"
    
    # 2. 施工内容
    construction_content = [
        f"{tag} {dev_type}安装工程",
        f"当前施工状态：{construction_status}",
    ]
    construction_content.extend([f"进行{work}" for work in current_work])
    
    # 根据位置环境增加内容
    elevation = spatial_info.get("z")
    if elevation is not None and elevation > 3:
        construction_content.append(f"高位作业（{elevation}m），搭设操作平台，作业人员系安全带")
    if spatial_info.get("adjacent_devices") and len(spatial_info["adjacent_devices"]) >= 3:
        construction_content.append("设备密集区域作业，对已安装设备采取防护措施")
    
    # 3. 人员配置
    personnel = template["personnel"]
    
    # 4. 机具设备
    equipment = template["equipment"]
    
    # 5. 材料使用
    materials = template["materials"]
    
    # 6. 质量检查
    quality_checks = template["quality_checks"]
    quality_results = [f"{check}：符合要求" for check in quality_checks[:2]]
    quality_results.append(f"{quality_checks[2] if len(quality_checks) > 2 else '其他检查'}：正在进行")
    
    # 7. 安全情况
    safety_situation = [
        "今日施工安全无事故",
        "施工人员正确佩戴劳动防护用品",
        "吊装作业由持证起重工指挥，作业区域设置警戒线",
    ]
    if elevation is not None and elevation > 3:
        safety_situation.append(f"高位作业（{elevation}m）人员佩戴速差自控器，操作平台搭设牢固")
    if dev_type == "塔器":
        safety_situation.append("塔器吊装作业办理一级吊装作业许可，全员安全技术交底")
    
    # 8. 问题及处理
    issues = []
    if construction_status == "in_progress":
        issues.append("暂无重大问题，施工正常进行")
    elif construction_status == "pending":
        issues.append("施工准备阶段，待基础验收合格后开始设备就位")
    else:
        issues.append("施工已完成，资料整理中")
    
    # 9. 明日计划
    tomorrow = (datetime.datetime.strptime(log_date, "%Y-%m-%d") + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    next_work_index = min(template["typical_work"].index(current_work[-1]) + 1, len(template["typical_work"]) - 1) if current_work[-1] in template["typical_work"] else 2
    tomorrow_plan = [
        f"继续进行{template['typical_work'][next_work_index]}",
        "完成当日质量检查记录",
        "整理施工技术资料",
    ]
    
    site_log = {
        "tag": tag,
        "name": spatial_info.get("name", tag),
        "type": dev_type,
        "workshop": spatial_info.get("workshop", ""),
        "elevation": spatial_info.get("z"),
        "log_date": log_date,
        "weather": weather,
        "construction_status": construction_status,
        "construction_location": construction_location,
        "construction_content": construction_content,
        "personnel": personnel,
        "equipment": equipment,
        "materials": materials,
        "quality_checks": quality_checks,
        "quality_results": quality_results,
        "safety_situation": safety_situation,
        "issues": issues,
        "tomorrow_plan": tomorrow_plan,
        "tomorrow_date": tomorrow,
        "generated_at": datetime.datetime.now().isoformat(),
        "adjacent_devices": spatial_info.get("adjacent_devices", []),
    }
    
    # 保存
    logs = _load_logs()
    log_key = f"{tag}_{log_date}"
    logs[log_key] = site_log
    _save_logs(logs)
    
    return site_log


def list_site_logs(tag: str = None) -> list:
    """v0.1.71：列出生成的施工日志。"""
    logs = _load_logs()
    result = []
    for key, log in logs.items():
        if tag and log.get("tag") != tag:
            continue
        result.append({
            "key": key,
            "tag": log.get("tag", ""),
            "name": log.get("name", ""),
            "type": log.get("type", ""),
            "workshop": log.get("workshop", ""),
            "log_date": log.get("log_date", ""),
            "weather": log.get("weather", ""),
            "construction_status": log.get("construction_status", ""),
        })
    result.sort(key=lambda x: x.get("log_date", ""), reverse=True)
    return result


def get_site_log_stats() -> dict:
    """v0.1.71：获取施工日志统计。"""
    logs = _load_logs()
    from . import relations as _rel
    g = _rel.load_relations()
    total_devices = len(g.get("devices", []))
    
    date_count = {}
    workshop_count = {}
    type_count = {}
    status_count = {}
    
    for log in logs.values():
        date = log.get("log_date", "")
        date_count[date] = date_count.get(date, 0) + 1
        ws = log.get("workshop", "未分配")
        workshop_count[ws] = workshop_count.get(ws, 0) + 1
        t = log.get("type", "未知")
        type_count[t] = type_count.get(t, 0) + 1
        status = log.get("construction_status", "pending")
        status_count[status] = status_count.get(status, 0) + 1
    
    devices_with_logs = len(set(log.get("tag") for log in logs.values()))
    
    return {
        "total_logs": len(logs),
        "devices_with_logs": devices_with_logs,
        "total_devices": total_devices,
        "coverage_percent": round(devices_with_logs / total_devices * 100, 1) if total_devices > 0 else 0,
        "date_count": date_count,
        "workshop_count": workshop_count,
        "type_count": type_count,
        "status_count": status_count,
    }
