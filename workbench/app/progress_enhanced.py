"""
v0.1.82：设备安装位置与施工进度联动增强

关键路径分析、施工进度预警、设备状态与位置联动、施工顺序优化。
"""

import os
import json
import datetime
from typing import Optional, List, Dict


_PROGRESS_FILE = os.path.join("data", "progress_enhanced.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_progress() -> dict:
    if os.path.exists(_PROGRESS_FILE):
        try:
            with open(_PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {"analysis": {}, "warnings": [], "optimization": {}}


def _save_progress(progress: dict):
    _ensure_dirs()
    with open(_PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def _get_all_devices_with_position() -> List[dict]:
    """获取所有带位置信息的设备。"""
    from . import relations as _rel
    from . import installation_plan as _ip
    
    g = _rel.load_relations()
    devices = g.get("devices", [])
    
    result = []
    for device in devices:
        tag = device.get("tag", "")
        spatial = _ip.get_device_spatial_info(tag)
        if "error" not in spatial:
            device_info = dict(device)
            device_info.update({
                "workshop": spatial.get("workshop", ""),
                "elevation": spatial.get("z"),
                "x": spatial.get("x"),
                "y": spatial.get("y"),
                "adjacent_devices": spatial.get("adjacent_devices", []),
                "has_position": spatial.get("has_position", False),
            })
            result.append(device_info)
    
    return result


def _get_device_status(tag: str) -> dict:
    """获取设备施工状态。"""
    from . import construction_schedule as _cs
    try:
        result = _cs.get_device_status(tag)
        # get_device_status(tag) 直接返回 {ok, tag, status, notes, updated_at}
        if result.get("ok") and "status" in result:
            return {
                "status": result.get("status", "pending"),
                "notes": result.get("notes", ""),
                "updated_at": result.get("updated_at", ""),
            }
        # 兼容无tag时返回 {ok, devices: {tag: {...}}}
        devices = result.get("devices", {})
        if tag in devices:
            return devices[tag]
    except Exception:
        pass
    return {"status": "pending", "notes": "", "updated_at": ""}


def analyze_critical_path() -> dict:
    """v0.1.82：关键路径分析。
    
    根据设备位置（车间、标高、坐标）和施工状态，分析关键路径。
    关键路径：影响整体工期的设备序列。
    """
    devices = _get_all_devices_with_position()
    
    if not devices:
        return {"error": "无设备数据", "critical_path": [], "total_devices": 0}
    
    # 按车间分组
    by_workshop = {}
    for device in devices:
        ws = device.get("workshop", "未分配")
        if ws not in by_workshop:
            by_workshop[ws] = []
        by_workshop[ws].append(device)
    
    # 关键路径设备（未安装且位置关键的设备）
    critical_devices = []
    
    for ws, ws_devices in by_workshop.items():
        # 按标高排序（从低到高）
        ws_devices_sorted = sorted(ws_devices, key=lambda d: (d.get("elevation") or 0, d.get("x") or 0))
        
        for i, device in enumerate(ws_devices_sorted):
            tag = device.get("tag", "")
            status_info = _get_device_status(tag)
            status = status_info.get("status", "pending")
            
            # 关键设备判定：
            # 1. 标高最低的设备（基础设备，影响后续安装）
            # 2. 相邻设备多的设备（影响面广）
            # 3. 状态为pending或in_progress的设备
            is_critical = False
            critical_reasons = []
            
            if i == 0 and len(ws_devices_sorted) > 1:
                is_critical = True
                critical_reasons.append(f"{ws}最低标高设备，影响后续安装")
            
            if len(device.get("adjacent_devices", [])) >= 3:
                is_critical = True
                critical_reasons.append(f"相邻{len(device['adjacent_devices'])}台设备，影响面广")
            
            if status in ["pending", "in_progress"]:
                if is_critical:
                    critical_reasons.append(f"当前状态：{status}")
            
            if is_critical:
                critical_devices.append({
                    "tag": tag,
                    "name": device.get("name", ""),
                    "type": device.get("type", ""),
                    "workshop": ws,
                    "elevation": device.get("elevation"),
                    "status": status,
                    "critical_reasons": critical_reasons,
                    "priority": len(critical_reasons),
                })
    
    # 按优先级排序
    critical_devices.sort(key=lambda d: d["priority"], reverse=True)
    
    # 关键路径（按车间→标高排序的关键设备序列）
    critical_path = []
    for ws in sorted(by_workshop.keys()):
        ws_critical = [d for d in critical_devices if d["workshop"] == ws]
        ws_critical.sort(key=lambda d: (d.get("elevation") or 0))
        critical_path.extend(ws_critical)
    
    result = {
        "ok": True,
        "total_devices": len(devices),
        "critical_devices_count": len(critical_devices),
        "critical_path": critical_path[:20],  # 最多返回20个
        "by_workshop": {ws: len(devs) for ws, devs in by_workshop.items()},
        "analysis_time": datetime.datetime.now().isoformat(),
    }
    
    # 保存分析结果
    progress = _load_progress()
    progress["analysis"] = result
    _save_progress(progress)
    
    return result


def check_progress_warnings() -> dict:
    """v0.1.82：施工进度预警。
    
    检查延期设备、关键设备延期影响、状态异常等。
    """
    devices = _get_all_devices_with_position()
    
    if not devices:
        return {"error": "无设备数据", "warnings": [], "total_devices": 0}
    
    warnings = []
    
    # 统计各状态设备数
    status_count = {"pending": 0, "in_progress": 0, "completed": 0, "accepted": 0, "unknown": 0}
    
    for device in devices:
        tag = device.get("tag", "")
        status_info = _get_device_status(tag)
        status = status_info.get("status", "pending")
        notes = status_info.get("notes", "")
        updated_at = status_info.get("updated_at", "")
        
        if status in status_count:
            status_count[status] += 1
        else:
            status_count["unknown"] += 1
        
        # 预警1：关键设备状态为pending且无更新
        if status == "pending" and not updated_at:
            if len(device.get("adjacent_devices", [])) >= 2:
                warnings.append({
                    "type": "critical_pending",
                    "severity": "high",
                    "tag": tag,
                    "name": device.get("name", ""),
                    "workshop": device.get("workshop", ""),
                    "message": f"关键设备{tag}（{device.get('name','')}）尚未开始安装，相邻{len(device['adjacent_devices'])}台设备受影响",
                })
        
        # 预警2：设备状态为in_progress但长时间未更新
        if status == "in_progress" and updated_at:
            try:
                update_time = datetime.datetime.fromisoformat(updated_at)
                days_since_update = (datetime.datetime.now() - update_time).days
                if days_since_update > 7:
                    warnings.append({
                        "type": "long_in_progress",
                        "severity": "medium",
                        "tag": tag,
                        "name": device.get("name", ""),
                        "workshop": device.get("workshop", ""),
                        "message": f"设备{tag}（{device.get('name','')}）安装中已{days_since_update}天未更新状态",
                        "days_since_update": days_since_update,
                    })
            except Exception:
                pass
        
        # 预警3：高位设备（标高>5m）状态为pending
        elevation = device.get("elevation")
        if elevation is not None and elevation > 5 and status == "pending":
            warnings.append({
                "type": "high_elevation_pending",
                "severity": "medium",
                "tag": tag,
                "name": device.get("name", ""),
                "workshop": device.get("workshop", ""),
                "message": f"高位设备{tag}（标高{elevation}m）尚未开始安装，需提前准备吊装方案",
                "elevation": elevation,
            })
        
        # 预警4：地下设备（标高<0）状态为pending
        if elevation is not None and elevation < 0 and status == "pending":
            warnings.append({
                "type": "underground_pending",
                "severity": "medium",
                "tag": tag,
                "name": device.get("name", ""),
                "workshop": device.get("workshop", ""),
                "message": f"地下设备{tag}（标高{elevation}m）尚未开始安装，需提前完成基础施工",
                "elevation": elevation,
            })
    
    # 按严重程度排序
    severity_order = {"high": 0, "medium": 1, "low": 2}
    warnings.sort(key=lambda w: severity_order.get(w.get("severity", "low"), 2))
    
    result = {
        "ok": True,
        "total_devices": len(devices),
        "status_count": status_count,
        "warnings_count": len(warnings),
        "high_severity": len([w for w in warnings if w.get("severity") == "high"]),
        "medium_severity": len([w for w in warnings if w.get("severity") == "medium"]),
        "warnings": warnings[:30],  # 最多返回30个
        "check_time": datetime.datetime.now().isoformat(),
    }
    
    # 保存预警结果
    progress = _load_progress()
    progress["warnings"] = warnings
    _save_progress(progress)
    
    return result


def optimize_installation_order() -> dict:
    """v0.1.82：施工顺序优化。
    
    根据设备位置（车间、标高、坐标）优化安装顺序。
    原则：先地下后地上、先低后高、先关键后一般、先大后小。
    """
    devices = _get_all_devices_with_position()
    
    if not devices:
        return {"error": "无设备数据", "optimized_order": [], "total_devices": 0}
    
    # 按车间分组
    by_workshop = {}
    for device in devices:
        ws = device.get("workshop", "未分配")
        if ws not in by_workshop:
            by_workshop[ws] = []
        by_workshop[ws].append(device)
    
    optimized_order = []
    phase = 1
    
    for ws in sorted(by_workshop.keys()):
        ws_devices = by_workshop[ws]
        
        # 分组：地下设备（标高<0）、低位设备（0-3m）、中位设备（3-8m）、高位设备（>8m）
        underground = []
        low = []
        medium = []
        high = []
        
        for device in ws_devices:
            elevation = device.get("elevation")
            if elevation is None:
                low.append(device)  # 无标高信息归入低位
            elif elevation < 0:
                underground.append(device)
            elif elevation <= 3:
                low.append(device)
            elif elevation <= 8:
                medium.append(device)
            else:
                high.append(device)
        
        # 每组内按x坐标排序（从左到右）
        for group in [underground, low, medium, high]:
            group.sort(key=lambda d: (d.get("x") or 0, d.get("y") or 0))
        
        # 按阶段加入优化顺序
        for group_name, group in [("地下设备", underground), ("低位设备", low),
                                    ("中位设备", medium), ("高位设备", high)]:
            for device in group:
                tag = device.get("tag", "")
                status_info = _get_device_status(tag)
                status = status_info.get("status", "pending")
                
                # 计算优先级分数
                priority_score = 0
                if len(device.get("adjacent_devices", [])) >= 3:
                    priority_score += 3  # 相邻设备多，优先级高
                if device.get("type") in ["塔器", "储罐", "压缩机"]:
                    priority_score += 2  # 大型设备，优先级高
                if status == "completed":
                    priority_score = -1  # 已完成，不参与排序
                
                optimized_order.append({
                    "phase": phase,
                    "workshop": ws,
                    "elevation_group": group_name,
                    "tag": tag,
                    "name": device.get("name", ""),
                    "type": device.get("type", ""),
                    "elevation": device.get("elevation"),
                    "x": device.get("x"),
                    "y": device.get("y"),
                    "status": status,
                    "priority_score": priority_score,
                    "adjacent_count": len(device.get("adjacent_devices", [])),
                })
            phase += 1
    
    # 未完成设备按优先级排序
    pending_devices = [d for d in optimized_order if d["priority_score"] >= 0]
    pending_devices.sort(key=lambda d: (-d["priority_score"], d["phase"], d.get("elevation") or 0))
    
    result = {
        "ok": True,
        "total_devices": len(devices),
        "total_phases": phase - 1,
        "by_workshop": {ws: len(devs) for ws, devs in by_workshop.items()},
        "optimized_order": pending_devices[:50],  # 最多返回50个
        "completed_count": len([d for d in optimized_order if d["status"] == "completed"]),
        "pending_count": len([d for d in optimized_order if d["status"] == "pending"]),
        "in_progress_count": len([d for d in optimized_order if d["status"] == "in_progress"]),
        "optimization_time": datetime.datetime.now().isoformat(),
    }
    
    # 保存优化结果
    progress = _load_progress()
    progress["optimization"] = result
    _save_progress(progress)
    
    return result


def get_progress_dashboard() -> dict:
    """v0.1.82：获取施工进度总览。"""
    devices = _get_all_devices_with_position()
    
    if not devices:
        return {"error": "无设备数据"}
    
    # 统计各状态
    status_count = {"pending": 0, "in_progress": 0, "completed": 0, "accepted": 0, "unknown": 0}
    by_workshop_status = {}
    
    for device in devices:
        tag = device.get("tag", "")
        ws = device.get("workshop", "未分配")
        status_info = _get_device_status(tag)
        status = status_info.get("status", "pending")
        
        if status in status_count:
            status_count[status] += 1
        else:
            status_count["unknown"] += 1
        
        if ws not in by_workshop_status:
            by_workshop_status[ws] = {"pending": 0, "in_progress": 0, "completed": 0, "accepted": 0, "total": 0}
        if status in by_workshop_status[ws]:
            by_workshop_status[ws][status] += 1
        by_workshop_status[ws]["total"] += 1
    
    # 计算完成率
    total = len(devices)
    completed = status_count.get("completed", 0) + status_count.get("accepted", 0)
    completion_rate = round(completed / total * 100, 1) if total > 0 else 0
    
    return {
        "ok": True,
        "total_devices": total,
        "status_count": status_count,
        "completion_rate": completion_rate,
        "by_workshop": by_workshop_status,
        "dashboard_time": datetime.datetime.now().isoformat(),
    }


def update_device_status_with_position(tag: str, status: str, notes: str = "") -> dict:
    """v0.1.82：更新设备状态（带位置信息联动）。"""
    from . import construction_schedule as _cs
    
    # 验证设备存在且有位置信息
    devices = _get_all_devices_with_position()
    device = next((d for d in devices if d["tag"] == tag), None)
    
    if not device:
        return {"error": f"设备{tag}不存在或无位置信息", "tag": tag}
    
    # 更新状态
    result = _cs.update_device_status(tag, status, notes)
    
    if result.get("ok"):
        # 检查是否影响相邻设备
        adjacent = device.get("adjacent_devices", [])
        affected_devices = []
        for adj_tag in adjacent:
            adj_status = _get_device_status(adj_tag)
            if adj_status.get("status") == "pending":
                affected_devices.append({
                    "tag": adj_tag,
                    "status": adj_status.get("status", "pending"),
                    "message": f"设备{tag}状态更新为{status}，相邻设备{adj_tag}可能受影响",
                })
        
        return {
            "ok": True,
            "tag": tag,
            "status": status,
            "notes": notes,
            "workshop": device.get("workshop", ""),
            "elevation": device.get("elevation"),
            "affected_devices": affected_devices,
            "updated_at": datetime.datetime.now().isoformat(),
        }
    
    return result
