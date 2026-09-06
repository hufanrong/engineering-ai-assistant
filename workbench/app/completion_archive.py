"""
v0.1.67：设备安装位置与竣工资料联动

根据设备位置自动生成竣工资料清单，进行完整性检查，与设备状态联动，
按车间/标高分组，资料缺失提醒。
"""

import os
import json
import datetime
from typing import Optional


_ARCHIVE_FILE = os.path.join("data", "completion_archive.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_archive() -> dict:
    if os.path.exists(_ARCHIVE_FILE):
        try:
            with open(_ARCHIVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_archive(archive: dict):
    _ensure_dirs()
    with open(_ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)


# 每类设备需要的竣工资料清单
DEVICE_ARCHIVE_REQUIREMENTS = {
    "泵": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "联轴器对中记录", "required": True},
        {"type": "管道连接记录", "required": True},
        {"type": "单机试运转记录", "required": True},
        {"type": "隐蔽工程验收记录", "required": False},
        {"type": "设计变更通知单", "required": False},
    ],
    "压缩机": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "联轴器对中记录", "required": True},
        {"type": "润滑油系统冲洗记录", "required": True},
        {"type": "管道连接记录", "required": True},
        {"type": "单机试运转记录", "required": True},
        {"type": "隐蔽工程验收记录", "required": False},
        {"type": "设计变更通知单", "required": False},
    ],
    "塔器": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备吊装记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "垂直度测量记录", "required": True},
        {"type": "内件安装记录", "required": True},
        {"type": "管道连接记录", "required": True},
        {"type": "水压试验记录", "required": False},
        {"type": "隐蔽工程验收记录", "required": False},
        {"type": "设计变更通知单", "required": False},
    ],
    "换热器": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "水压试验记录", "required": True},
        {"type": "管道连接记录", "required": True},
        {"type": "隐蔽工程验收记录", "required": False},
        {"type": "设计变更通知单", "required": False},
    ],
    "容器": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "管道连接记录", "required": True},
        {"type": "隐蔽工程验收记录", "required": False},
        {"type": "设计变更通知单", "required": False},
    ],
    "风机": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "联轴器对中记录", "required": True},
        {"type": "单机试运转记录", "required": True},
        {"type": "设计变更通知单", "required": False},
    ],
    "电机": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "绝缘测试记录", "required": True},
        {"type": "单机试运转记录", "required": True},
        {"type": "设计变更通知单", "required": False},
    ],
    "阀门": [
        {"type": "开箱验收记录", "required": True},
        {"type": "阀门试验记录", "required": True},
        {"type": "安装记录", "required": True},
    ],
    "储罐": [
        {"type": "开箱验收记录", "required": True},
        {"type": "基础验收记录", "required": True},
        {"type": "罐底焊接记录", "required": True},
        {"type": "罐壁焊接记录", "required": True},
        {"type": "真空箱试漏记录", "required": True},
        {"type": "充水试验记录", "required": True},
        {"type": "隐蔽工程验收记录", "required": False},
        {"type": "设计变更通知单", "required": False},
    ],
}

# 默认资料清单（未知设备类型）
DEFAULT_REQUIREMENTS = [
    {"type": "开箱验收记录", "required": True},
    {"type": "设备基础验收记录", "required": True},
    {"type": "设备安装记录", "required": True},
    {"type": "管道连接记录", "required": True},
    {"type": "单机试运转记录", "required": True},
    {"type": "设计变更通知单", "required": False},
]


def get_device_requirements(dev_type: str) -> list:
    """v0.1.67：获取设备类型需要的竣工资料清单。
    
    Args:
        dev_type: 设备类型
    
    Returns:
        资料清单
    """
    return DEVICE_ARCHIVE_REQUIREMENTS.get(dev_type, DEFAULT_REQUIREMENTS)


def generate_device_archive_list(tag: str) -> dict:
    """v0.1.67：生成单台设备的竣工资料清单。
    
    Args:
        tag: 设备位号
    
    Returns:
        设备竣工资料清单
    """
    from . import relations as _rel
    from . import spatial_model as _sm
    from . import construction_schedule as _cs
    
    g = _rel.load_relations()
    spatial = _sm.build_spatial_model(g)
    spatial_devs = {d["tag"]: d for d in spatial.get("devices", [])}
    
    device = None
    for d in g.get("devices", []):
        if d["tag"] == tag:
            device = d
            break
    
    if not device:
        return {"error": "设备不存在", "tag": tag}
    
    sd = spatial_devs.get(tag, {})
    dev_type = sd.get("type", "")
    
    # 获取设备施工状态
    try:
        status_info = _cs.get_device_status(tag)
        construction_status = status_info.get("status", "pending")
    except Exception:
        construction_status = "pending"
    
    # 获取需要的资料清单
    requirements = get_device_requirements(dev_type)
    
    # 检查已有的资料（从generated_docs目录扫描）
    existing_docs = []
    docs_dir = os.path.join("data", "generated_docs")
    if os.path.exists(docs_dir):
        for root, dirs, files in os.walk(docs_dir):
            for f in files:
                if tag in f:
                    existing_docs.append(f)
    
    # 检查资料完整性
    archive_items = []
    missing_required = []
    missing_optional = []
    
    for req in requirements:
        doc_type = req["type"]
        required = req["required"]
        
        # 检查是否已有该类型资料
        has_doc = any(doc_type in doc for doc in existing_docs)
        
        item = {
            "type": doc_type,
            "required": required,
            "status": "completed" if has_doc else "missing",
            "existing_file": next((doc for doc in existing_docs if doc_type in doc), None),
        }
        archive_items.append(item)
        
        if not has_doc:
            if required:
                missing_required.append(doc_type)
            else:
                missing_optional.append(doc_type)
    
    # 完整性评估
    total_required = sum(1 for r in requirements if r["required"])
    completed_required = total_required - len(missing_required)
    completeness_percent = round(completed_required / total_required * 100, 1) if total_required > 0 else 100
    
    result = {
        "tag": tag,
        "name": sd.get("name", tag),
        "type": dev_type,
        "workshop": sd.get("workshop") or (device.get("workshops", [""])[0] if device.get("workshops") else ""),
        "elevation": sd.get("z"),
        "construction_status": construction_status,
        "requirements": archive_items,
        "total_requirements": len(requirements),
        "required_count": total_required,
        "completed_count": len([i for i in archive_items if i["status"] == "completed"]),
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "completeness_percent": completeness_percent,
        "existing_docs": existing_docs,
        "generated_at": datetime.datetime.now().isoformat(),
    }
    
    # 保存到归档
    archive = _load_archive()
    archive[tag] = result
    _save_archive(archive)
    
    return result


def generate_all_devices_archive() -> dict:
    """v0.1.67：生成所有设备的竣工资料清单。
    
    Returns:
        所有设备竣工资料汇总
    """
    from . import relations as _rel
    
    g = _rel.load_relations()
    devices = g.get("devices", [])
    
    all_archives = []
    for d in devices:
        archive = generate_device_archive_list(d["tag"])
        if "error" not in archive:
            all_archives.append(archive)
    
    # 按车间分组
    by_workshop = {}
    for a in all_archives:
        ws = a.get("workshop", "未分配")
        if ws not in by_workshop:
            by_workshop[ws] = []
        by_workshop[ws].append(a)
    
    # 按标高分组
    by_elevation = {}
    for a in all_archives:
        elev = a.get("elevation")
        key = f"EL{elev}m" if elev is not None else "无标高"
        if key not in by_elevation:
            by_elevation[key] = []
        by_elevation[key].append(a)
    
    # 总体统计
    total_devices = len(all_archives)
    complete_devices = sum(1 for a in all_archives if a["completeness_percent"] >= 100)
    incomplete_devices = total_devices - complete_devices
    avg_completeness = round(sum(a["completeness_percent"] for a in all_archives) / total_devices, 1) if total_devices > 0 else 0
    
    # 缺失资料汇总
    all_missing = {}
    for a in all_archives:
        for doc_type in a["missing_required"]:
            if doc_type not in all_missing:
                all_missing[doc_type] = []
            all_missing[doc_type].append(a["tag"])
    
    return {
        "total_devices": total_devices,
        "complete_devices": complete_devices,
        "incomplete_devices": incomplete_devices,
        "avg_completeness_percent": avg_completeness,
        "by_workshop": {ws: len(devs) for ws, devs in by_workshop.items()},
        "by_elevation": {elev: len(devs) for elev, devs in by_elevation.items()},
        "missing_summary": {doc_type: len(tags) for doc_type, tags in all_missing.items()},
        "missing_details": all_missing,
        "devices": all_archives,
        "generated_at": datetime.datetime.now().isoformat(),
    }


def update_device_doc_status(tag: str, doc_type: str, status: str,
                              file_name: str = None) -> dict:
    """v0.1.67：更新设备资料状态。
    
    Args:
        tag: 设备位号
        doc_type: 资料类型
        status: 状态 - completed/missing
        file_name: 文件名（可选）
    
    Returns:
        更新结果
    """
    archive = _load_archive()
    if tag not in archive:
        return {"error": "设备归档不存在", "tag": tag}
    
    device_archive = archive[tag]
    for item in device_archive.get("requirements", []):
        if item["type"] == doc_type:
            item["status"] = status
            if file_name:
                item["existing_file"] = file_name
            break
    
    # 重新计算完整性
    requirements = device_archive.get("requirements", [])
    total_required = sum(1 for r in requirements if r["required"])
    completed_required = sum(1 for r in requirements if r["required"] and r["status"] == "completed")
    device_archive["completeness_percent"] = round(completed_required / total_required * 100, 1) if total_required > 0 else 100
    device_archive["completed_count"] = len([i for i in requirements if i["status"] == "completed"])
    device_archive["missing_required"] = [r["type"] for r in requirements if r["required"] and r["status"] != "completed"]
    device_archive["missing_optional"] = [r["type"] for r in requirements if not r["required"] and r["status"] != "completed"]
    
    archive[tag] = device_archive
    _save_archive(archive)
    
    return {"ok": True, "tag": tag, "doc_type": doc_type, "status": status,
            "completeness_percent": device_archive["completeness_percent"]}


def get_archive_stats() -> dict:
    """v0.1.67：获取竣工资料归档统计。"""
    archive = _load_archive()
    devices = list(archive.values())
    
    if not devices:
        return {"ok": True, "total_devices": 0, "message": "尚未生成竣工资料清单"}
    
    total = len(devices)
    complete = sum(1 for d in devices if d.get("completeness_percent", 0) >= 100)
    avg_completeness = round(sum(d.get("completeness_percent", 0) for d in devices) / total, 1)
    
    # 按车间统计
    by_workshop = {}
    for d in devices:
        ws = d.get("workshop", "未分配")
        if ws not in by_workshop:
            by_workshop[ws] = {"total": 0, "complete": 0}
        by_workshop[ws]["total"] += 1
        if d.get("completeness_percent", 0) >= 100:
            by_workshop[ws]["complete"] += 1
    
    # 按施工状态统计
    by_status = {}
    for d in devices:
        status = d.get("construction_status", "pending")
        by_status[status] = by_status.get(status, 0) + 1
    
    return {
        "ok": True,
        "total_devices": total,
        "complete_devices": complete,
        "incomplete_devices": total - complete,
        "avg_completeness_percent": avg_completeness,
        "by_workshop": by_workshop,
        "by_construction_status": by_status,
    }


def list_missing_docs() -> list:
    """v0.1.67：列出所有缺失的资料。"""
    archive = _load_archive()
    missing = []
    
    for tag, device_archive in archive.items():
        for doc_type in device_archive.get("missing_required", []):
            missing.append({
                "tag": tag,
                "name": device_archive.get("name", tag),
                "workshop": device_archive.get("workshop", ""),
                "doc_type": doc_type,
                "required": True,
            })
        for doc_type in device_archive.get("missing_optional", []):
            missing.append({
                "tag": tag,
                "name": device_archive.get("name", tag),
                "workshop": device_archive.get("workshop", ""),
                "doc_type": doc_type,
                "required": False,
            })
    
    return missing
