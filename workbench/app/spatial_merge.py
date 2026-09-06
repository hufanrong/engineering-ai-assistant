"""
v0.1.66：多电脑并库时空间模型合并

多台电脑解析的空间模型合并到一个完整库，支持自动去重、坐标冲突处理、
标高冲突处理、车间冲突处理、合并日志记录、合并后空间模型完整性检查。
"""

import os
import json
import datetime
from typing import Optional


_MERGE_LOG_FILE = os.path.join("data", "spatial_merge_log.json")
_MERGE_PENDING_FILE = os.path.join("data", "spatial_merge_pending.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_merge_log() -> list:
    if os.path.exists(_MERGE_LOG_FILE):
        try:
            with open(_MERGE_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_merge_log(log: list):
    _ensure_dirs()
    with open(_MERGE_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def _load_pending() -> list:
    if os.path.exists(_MERGE_PENDING_FILE):
        try:
            with open(_MERGE_PENDING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_pending(pending: list):
    _ensure_dirs()
    with open(_MERGE_PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)


def load_spatial_from_file(filepath: str) -> dict:
    """从JSON文件加载空间模型。
    
    Args:
        filepath: 空间模型JSON文件路径
    
    Returns:
        空间模型字典
    """
    if not os.path.exists(filepath):
        return {"error": "文件不存在", "path": filepath}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"加载失败: {str(e)}", "path": filepath}


def merge_spatial(source_spatial: dict, node_name: str = "unknown",
                  conflict_strategy: str = "latest") -> dict:
    """合并源空间模型到本地空间模型。
    
    Args:
        source_spatial: 源空间模型字典
        node_name: 来源节点名称
        conflict_strategy: 冲突处理策略
            - "latest": 以最新版为准（默认）
            - "keep_existing": 保留现有
            - "manual": 冲突留待人工确认
    
    Returns:
        合并结果
    """
    from . import spatial_model as _sm
    from . import relations as _rel
    
    _ensure_dirs()
    
    if "error" in source_spatial:
        return source_spatial
    
    # 加载当前关系图谱，从cad_positions提取坐标构建设备索引
    g = _rel.load_relations()
    
    source_devices = source_spatial.get("devices", [])
    # 从relations设备中提取坐标（从cad_positions）
    current_devices = []
    for rd in g.get("devices", []):
        dev = {"tag": rd["tag"], "name": rd.get("name", rd["tag"]), "workshop": rd.get("workshops", [""])[0] if rd.get("workshops") else ""}
        if rd.get("cad_positions"):
            cp = rd["cad_positions"][0]
            dev["x"] = cp.get("x")
            dev["y"] = cp.get("y")
            dev["z"] = cp.get("z")
        current_devices.append(dev)
    
    # 统计
    merged_devices = 0
    skipped_duplicate = 0
    conflicts = 0
    pending_conflicts = []
    coord_updated = 0
    elevation_updated = 0
    workshop_updated = 0
    
    # 构建设备索引
    current_index = {d["tag"]: d for d in current_devices}
    
    # 合并设备
    for sd in source_devices:
        tag = sd.get("tag", "")
        if not tag:
            continue
        
        if tag in current_index:
            # 设备已存在，检查冲突
            cd = current_index[tag]
            has_conflict = False
            conflict_details = {}
            
            # 检查坐标冲突
            source_x, source_y = sd.get("x"), sd.get("y")
            current_x, current_y = cd.get("x"), cd.get("y")
            
            if source_x is not None and source_y is not None:
                if current_x is None or current_y is None:
                    # 当前无坐标，用源坐标
                    cd["x"] = source_x
                    cd["y"] = source_y
                    coord_updated += 1
                elif abs(source_x - current_x) > 0.5 or abs(source_y - current_y) > 0.5:
                    # 坐标差异大于0.5米，视为冲突
                    has_conflict = True
                    conflict_details["coordinates"] = {
                        "source": {"x": source_x, "y": source_y},
                        "current": {"x": current_x, "y": current_y},
                        "diff": {"dx": round(source_x - current_x, 2), "dy": round(source_y - current_y, 2)},
                    }
            
            # 检查标高冲突
            source_z = sd.get("z")
            current_z = cd.get("z")
            if source_z is not None:
                if current_z is None:
                    cd["z"] = source_z
                    elevation_updated += 1
                elif abs(source_z - current_z) > 0.1:
                    has_conflict = True
                    conflict_details["elevation"] = {
                        "source": source_z,
                        "current": current_z,
                        "diff": round(source_z - current_z, 2),
                    }
            
            # 检查车间冲突
            source_ws = sd.get("workshop", "")
            current_ws = cd.get("workshop", "")
            if source_ws and current_ws and source_ws != current_ws:
                has_conflict = True
                conflict_details["workshop"] = {
                    "source": source_ws,
                    "current": current_ws,
                }
            elif source_ws and not current_ws:
                cd["workshop"] = source_ws
                workshop_updated += 1
            
            # 合并其他属性
            for key in ["name", "type", "floor", "area"]:
                if sd.get(key) and not cd.get(key):
                    cd[key] = sd[key]
            
            if has_conflict:
                conflicts += 1
                if conflict_strategy == "latest":
                    # 用源数据覆盖
                    if "coordinates" in conflict_details:
                        cd["x"] = source_x
                        cd["y"] = source_y
                    if "elevation" in conflict_details:
                        cd["z"] = source_z
                    if "workshop" in conflict_details:
                        cd["workshop"] = source_ws
                    merged_devices += 1
                elif conflict_strategy == "keep_existing":
                    skipped_duplicate += 1
                elif conflict_strategy == "manual":
                    pending_conflicts.append({
                        "device_tag": tag,
                        "conflict_type": "spatial_conflict",
                        "details": conflict_details,
                        "source_device": sd,
                        "current_device": cd,
                        "node": node_name,
                        "status": "pending",
                    })
            else:
                skipped_duplicate += 1
        else:
            # 新设备，直接添加
            current_index[tag] = sd
            merged_devices += 1
    
    # 构建合并后的空间模型
    all_workshops = set()
    for d in current_index.values():
        if d.get("workshop"):
            all_workshops.add(d["workshop"])
    for ws in source_spatial.get("workshops", []):
        all_workshops.add(ws)
    
    merged_spatial = {
        "devices": list(current_index.values()),
        "workshops": list(all_workshops),
        "stats": {
            "total_devices": len(current_index),
            "devices_with_coords": sum(1 for d in current_index.values() if d.get("x") is not None and d.get("y") is not None),
            "devices_with_elevation": sum(1 for d in current_index.values() if d.get("z") is not None),
        },
        "metadata": {
            "merged_at": datetime.datetime.now().isoformat(),
            "merged_from": node_name,
            "merge_strategy": conflict_strategy,
        },
    }
    
    # 保存合并后的空间模型到关系图谱
    # 将空间坐标写回 relations
    devices_with_coords = {d["tag"]: d for d in merged_spatial["devices"] if d.get("x") is not None}
    for rd in g.get("devices", []):
        tag = rd["tag"]
        if tag in devices_with_coords:
            sd = devices_with_coords[tag]
            # 更新 cad_positions
            if not rd.get("cad_positions"):
                rd["cad_positions"] = []
            # 检查是否已存在相同坐标
            exists = any(abs(p.get("x", 0) - sd["x"]) < 0.01 and abs(p.get("y", 0) - sd["y"]) < 0.01 
                         for p in rd["cad_positions"])
            if not exists:
                rd["cad_positions"].append({
                    "x": sd["x"],
                    "y": sd["y"],
                    "z": sd.get("z"),
                    "source": "spatial_merge",
                })
    _rel.save_relations(g)
    
    # 保存待人工确认的冲突
    if pending_conflicts:
        all_pending = _load_pending()
        all_pending.extend(pending_conflicts)
        _save_pending(all_pending)
    
    # 记录合并日志
    log_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "node_name": node_name,
        "conflict_strategy": conflict_strategy,
        "source_devices": len(source_devices),
        "merged_devices": merged_devices,
        "skipped_duplicate": skipped_duplicate,
        "conflicts": conflicts,
        "coord_updated": coord_updated,
        "elevation_updated": elevation_updated,
        "workshop_updated": workshop_updated,
        "total_devices_after": len(merged_spatial["devices"]),
        "devices_with_coords_after": merged_spatial["stats"]["devices_with_coords"],
        "devices_with_elevation_after": merged_spatial["stats"]["devices_with_elevation"],
    }
    merge_log = _load_merge_log()
    merge_log.append(log_entry)
    _save_merge_log(merge_log[-100:])
    
    return {
        "ok": True,
        "log": log_entry,
        "pending_count": len(_load_pending()),
        "merged_spatial": merged_spatial,
    }


def resolve_pending(index: int, decision: str) -> dict:
    """处理待人工确认的冲突。
    
    Args:
        index: 冲突索引
        decision: 决策 - "use_source"（用源数据）/ "keep_existing"（保留现有）/ "skip"（跳过）
    
    Returns:
        处理结果
    """
    pending = _load_pending()
    if index < 0 or index >= len(pending):
        return {"error": "索引超出范围", "total": len(pending)}
    
    item = pending[index]
    
    if decision == "use_source":
        from . import relations as _rel
        g = _rel.load_relations()
        tag = item["device_tag"]
        if "source_device" in item:
            sd = item["source_device"]
            for rd in g.get("devices", []):
                if rd["tag"] == tag:
                    if sd.get("x") is not None:
                        if not rd.get("cad_positions"):
                            rd["cad_positions"] = []
                        rd["cad_positions"].append({
                            "x": sd["x"], "y": sd["y"], "z": sd.get("z"),
                            "source": "manual_resolve",
                        })
                    break
            _rel.save_relations(g)
        result = "已用源数据覆盖"
    elif decision == "keep_existing":
        result = "已保留现有数据"
    elif decision == "skip":
        result = "已跳过"
    else:
        return {"error": "无效决策", "valid_decisions": ["use_source", "keep_existing", "skip"]}
    
    item["status"] = "resolved"
    item["decision"] = decision
    item["result"] = result
    pending[index] = item
    _save_pending(pending)
    
    return {"ok": True, "result": result, "item": item}


def list_pending() -> list:
    """列出待人工确认的冲突。"""
    return _load_pending()


def list_merge_log(limit: int = 20) -> list:
    """列出合并日志。"""
    log = _load_merge_log()
    return log[-limit:]


def merge_stats() -> dict:
    """获取合并统计信息。"""
    log = _load_merge_log()
    pending = _load_pending()
    
    total_merged = sum(entry.get("merged_devices", 0) for entry in log)
    total_skipped = sum(entry.get("skipped_duplicate", 0) for entry in log)
    total_conflicts = sum(entry.get("conflicts", 0) for entry in log)
    total_coord_updated = sum(entry.get("coord_updated", 0) for entry in log)
    total_elevation_updated = sum(entry.get("elevation_updated", 0) for entry in log)
    
    # 当前空间模型统计（从relations获取）
    from . import relations as _rel
    g = _rel.load_relations()
    current_devices = g.get("devices", [])
    devices_with_coords = sum(1 for d in current_devices if d.get("cad_positions"))
    devices_with_elevation = sum(1 for d in current_devices if d.get("cad_positions") and any(p.get("z") is not None for p in d["cad_positions"]))
    
    return {
        "total_merge_operations": len(log),
        "total_devices_merged": total_merged,
        "total_devices_skipped": total_skipped,
        "total_conflicts": total_conflicts,
        "total_coord_updated": total_coord_updated,
        "total_elevation_updated": total_elevation_updated,
        "pending_conflicts": len([p for p in pending if p.get("status") == "pending"]),
        "resolved_conflicts": len([p for p in pending if p.get("status") == "resolved"]),
        "current_total_devices": len(current_devices),
        "current_devices_with_coords": devices_with_coords,
        "current_devices_with_elevation": devices_with_elevation,
        "last_merge": log[-1] if log else None,
    }


def check_spatial_integrity() -> dict:
    """检查合并后空间模型的完整性。
    
    Returns:
        完整性检查结果
    """
    from . import relations as _rel
    
    g = _rel.load_relations()
    rel_devices = g.get("devices", [])
    
    # 从relations构建设备空间信息
    devices = []
    for rd in rel_devices:
        dev = {"tag": rd["tag"], "workshop": rd.get("workshops", [""])[0] if rd.get("workshops") else ""}
        if rd.get("cad_positions"):
            cp = rd["cad_positions"][0]
            dev["x"] = cp.get("x")
            dev["y"] = cp.get("y")
            dev["z"] = cp.get("z")
        devices.append(dev)
    
    issues = []
    
    # 无坐标设备
    devices_without_coords = [d["tag"] for d in devices if d.get("x") is None or d.get("y") is None]
    if devices_without_coords:
        issues.append({"type": "devices_without_coords", "count": len(devices_without_coords), "devices": devices_without_coords[:10]})
    
    # 无标高设备
    devices_without_elevation = [d["tag"] for d in devices if d.get("z") is None]
    if devices_without_elevation:
        issues.append({"type": "devices_without_elevation", "count": len(devices_without_elevation), "devices": devices_without_elevation[:10]})
    
    # 无车间设备
    devices_without_workshop = [d["tag"] for d in devices if not d.get("workshop")]
    if devices_without_workshop:
        issues.append({"type": "devices_without_workshop", "count": len(devices_without_workshop), "devices": devices_without_workshop[:10]})
    
    # 坐标异常（超出合理范围）
    abnormal_coords = []
    for d in devices:
        if d.get("x") is not None and (d["x"] < -100 or d["x"] > 1000):
            abnormal_coords.append(d["tag"])
        if d.get("y") is not None and (d["y"] < -100 or d["y"] > 1000):
            abnormal_coords.append(d["tag"])
    if abnormal_coords:
        issues.append({"type": "abnormal_coordinates", "count": len(abnormal_coords), "devices": abnormal_coords[:10]})
    
    return {
        "ok": True,
        "total_devices": len(devices),
        "devices_with_coords": len(devices) - len(devices_without_coords),
        "devices_with_elevation": len(devices) - len(devices_without_elevation),
        "devices_with_workshop": len(devices) - len(devices_without_workshop),
        "issues_count": len(issues),
        "issues": issues,
        "coord_coverage_percent": round((len(devices) - len(devices_without_coords)) / len(devices) * 100, 1) if devices else 0,
        "elevation_coverage_percent": round((len(devices) - len(devices_without_elevation)) / len(devices) * 100, 1) if devices else 0,
    }
