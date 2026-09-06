"""
v0.1.69：多电脑并库时施工进度合并

多台电脑解析的施工进度数据合并到一个完整库，自动去重，进度冲突处理，
合并后写回施工进度，合并日志，待人工确认，合并统计，完整性检查。
"""

import os
import json
import datetime
from typing import Optional


_MERGE_FILE = os.path.join("data", "schedule_merge.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_merge() -> dict:
    if os.path.exists(_MERGE_FILE):
        try:
            with open(_MERGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {"pending": [], "log": [], "stats": {}}


def _save_merge(merge: dict):
    _ensure_dirs()
    with open(_MERGE_FILE, "w", encoding="utf-8") as f:
        json.dump(merge, f, ensure_ascii=False, indent=2)


def load_schedule_from_file(file_path: str) -> dict:
    """v0.1.69：从JSON文件加载施工进度数据。"""
    if not os.path.exists(file_path):
        return {"error": "文件不存在", "file": file_path}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"文件解析失败: {str(e)}", "file": file_path}


def _get_current_schedule() -> dict:
    """v0.1.69：获取当前施工进度数据。"""
    from . import construction_schedule as _cs
    try:
        result = _cs.get_device_status()
        # get_device_status返回 {ok: True, devices: {tag: {...}}}
        if isinstance(result, dict) and "devices" in result:
            devices = result["devices"]
            if isinstance(devices, dict):
                return dict(devices)
            elif isinstance(devices, list):
                return {d["tag"]: d for d in devices if isinstance(d, dict) and "tag" in d}
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _write_back_schedule(device_status: dict):
    """v0.1.69：将合并后的进度写回施工进度。"""
    from . import construction_schedule as _cs
    for tag, status_info in device_status.items():
        try:
            notes = status_info.get("notes", "")
            _cs.update_device_status(tag, status_info.get("status", "pending"), notes)
        except Exception:
            pass


def merge_schedule(source_schedule: dict, source_pc: str = "",
                   conflict_strategy: str = "latest") -> dict:
    """v0.1.69：合并源施工进度数据到当前库。
    
    Args:
        source_schedule: 源施工进度数据 {tag: {status, workshop, notes, updated_at, ...}}
        source_pc: 来源电脑名
        conflict_strategy: 冲突策略 - latest以最新版为准/keep_existing保留现有/manual冲突留待人工确认
    
    Returns:
        合并结果
    """
    merge = _load_merge()
    
    # 获取当前进度
    current = _get_current_schedule()
    
    # 统计
    total_source = len(source_schedule)
    merged = 0
    skipped_duplicate = 0
    conflicts = 0
    status_updated = 0
    workshop_updated = 0
    notes_updated = 0
    pending_conflicts = []
    
    # 状态优先级（用于冲突判断）
    STATUS_PRIORITY = {"completed": 4, "in_progress": 3, "pending": 2, "blocked": 1}
    
    for tag, source_info in source_schedule.items():
        if not isinstance(source_info, dict):
            continue
        
        source_status = source_info.get("status", "pending")
        source_workshop = source_info.get("workshop", "")
        source_notes = source_info.get("notes", "")
        source_updated = source_info.get("updated_at", "")
        
        current_info = current.get(tag, {})
        current_status = current_info.get("status", "pending")
        current_workshop = current_info.get("workshop", "")
        current_notes = current_info.get("notes", "")
        current_updated = current_info.get("updated_at", "")
        
        # 去重判断：状态、备注完全一致视为重复（workshop可能不存储在construction_schedule中）
        is_duplicate = (source_status == current_status and 
                        source_notes == current_notes)
        
        if is_duplicate and tag in current:
            skipped_duplicate += 1
            continue
        
        # 冲突判断：状态不一致
        has_conflict = (tag in current and source_status != current_status)
        
        if has_conflict:
            conflicts += 1
            
            if conflict_strategy == "manual":
                # 留待人工确认
                pending_conflicts.append({
                    "tag": tag,
                    "source_pc": source_pc,
                    "source_status": source_status,
                    "source_workshop": source_workshop,
                    "source_notes": source_notes,
                    "source_updated_at": source_updated,
                    "current_status": current_status,
                    "current_workshop": current_workshop,
                    "current_notes": current_notes,
                    "current_updated_at": current_updated,
                    "status": "pending",
                    "created_at": datetime.datetime.now().isoformat(),
                })
                continue
            elif conflict_strategy == "keep_existing":
                # 保留现有
                skipped_duplicate += 1
                continue
            # latest: 以源数据为准（继续往下执行更新）
        
        # 更新当前进度
        if tag not in current:
            merged += 1
        else:
            if source_status != current_status:
                status_updated += 1
            if source_workshop and source_workshop != current_workshop:
                workshop_updated += 1
            if source_notes and source_notes != current_notes:
                notes_updated += 1
        
        current[tag] = {
            "status": source_status,
            "workshop": source_workshop or current_workshop,
            "notes": source_notes or current_notes,
            "updated_at": source_updated or datetime.datetime.now().isoformat(),
            "source_pc": source_pc,
        }
    
    # 写回施工进度
    _write_back_schedule(current)
    
    # 记录合并日志
    log_entry = {
        "source_pc": source_pc,
        "merged_at": datetime.datetime.now().isoformat(),
        "source_devices": total_source,
        "merged_devices": merged,
        "skipped_duplicate": skipped_duplicate,
        "conflicts": conflicts,
        "status_updated": status_updated,
        "workshop_updated": workshop_updated,
        "notes_updated": notes_updated,
        "conflict_strategy": conflict_strategy,
        "total_devices_after": len(current),
    }
    merge["log"].insert(0, log_entry)
    if len(merge["log"]) > 100:
        merge["log"] = merge["log"][:100]
    
    # 保存待处理冲突
    if pending_conflicts:
        merge["pending"].extend(pending_conflicts)
    
    # 更新统计
    stats = merge.get("stats", {})
    stats["total_merge_operations"] = stats.get("total_merge_operations", 0) + 1
    stats["total_devices_merged"] = stats.get("total_devices_merged", 0) + merged
    stats["total_devices_skipped"] = stats.get("total_devices_skipped", 0) + skipped_duplicate
    stats["total_conflicts"] = stats.get("total_conflicts", 0) + conflicts
    stats["total_status_updated"] = stats.get("total_status_updated", 0) + status_updated
    merge["stats"] = stats
    
    _save_merge(merge)
    
    return {
        "ok": True,
        "log": log_entry,
        "pending_conflicts": pending_conflicts,
    }


def resolve_pending(index: int, decision: str) -> dict:
    """v0.1.69：处理待人工确认的进度冲突。
    
    Args:
        index: 冲突索引
        decision: 决策 - use_source用源数据覆盖/keep_existing保留现有/skip跳过
    
    Returns:
        处理结果
    """
    merge = _load_merge()
    pending = merge.get("pending", [])
    
    if index < 0 or index >= len(pending):
        return {"error": "索引超出范围", "index": index}
    
    item = pending[index]
    if item.get("status") != "pending":
        return {"error": "该冲突已处理", "index": index}
    
    tag = item["tag"]
    
    if decision == "use_source":
        # 用源数据覆盖
        current = _get_current_schedule()
        current[tag] = {
            "status": item["source_status"],
            "workshop": item["source_workshop"],
            "notes": item["source_notes"],
            "updated_at": datetime.datetime.now().isoformat(),
            "source_pc": item["source_pc"],
        }
        _write_back_schedule(current)
    elif decision == "keep_existing":
        pass  # 保留现有，不做修改
    elif decision == "skip":
        pass  # 跳过
    else:
        return {"error": "无效的决策", "decision": decision}
    
    item["status"] = "resolved"
    item["decision"] = decision
    item["resolved_at"] = datetime.datetime.now().isoformat()
    
    _save_merge(merge)
    
    return {"ok": True, "index": index, "tag": tag, "decision": decision}


def list_pending() -> list:
    """v0.1.69：列出待人工确认的进度冲突。"""
    merge = _load_merge()
    return [p for p in merge.get("pending", []) if p.get("status") == "pending"]


def list_merge_log() -> list:
    """v0.1.69：列出合并日志。"""
    merge = _load_merge()
    return merge.get("log", [])


def merge_stats() -> dict:
    """v0.1.69：获取合并统计信息。"""
    merge = _load_merge()
    stats = merge.get("stats", {})
    log = merge.get("log", [])
    pending = merge.get("pending", [])
    
    # 当前进度统计
    current = _get_current_schedule()
    status_count = {}
    workshop_count = {}
    for tag, info in current.items():
        status = info.get("status", "pending")
        status_count[status] = status_count.get(status, 0) + 1
        ws = info.get("workshop", "未分配")
        workshop_count[ws] = workshop_count.get(ws, 0) + 1
    
    return {
        "total_merge_operations": stats.get("total_merge_operations", 0),
        "total_devices_merged": stats.get("total_devices_merged", 0),
        "total_devices_skipped": stats.get("total_devices_skipped", 0),
        "total_conflicts": stats.get("total_conflicts", 0),
        "total_status_updated": stats.get("total_status_updated", 0),
        "pending_conflicts": len([p for p in pending if p.get("status") == "pending"]),
        "resolved_conflicts": len([p for p in pending if p.get("status") == "resolved"]),
        "current_total_devices": len(current),
        "current_status_distribution": status_count,
        "current_workshop_distribution": workshop_count,
        "last_merge": log[0] if log else None,
    }


def check_schedule_integrity() -> dict:
    """v0.1.69：检查施工进度完整性。"""
    from . import relations as _rel
    
    g = _rel.load_relations()
    all_devices = g.get("devices", [])
    current = _get_current_schedule()
    
    issues = []
    
    # 无进度状态的设备
    devices_without_status = [d["tag"] for d in all_devices if d["tag"] not in current]
    if devices_without_status:
        issues.append({"type": "devices_without_status", "count": len(devices_without_status),
                       "devices": devices_without_status[:10]})
    
    # 无车间的设备
    devices_without_workshop = [tag for tag, info in current.items() if not info.get("workshop")]
    if devices_without_workshop:
        issues.append({"type": "devices_without_workshop", "count": len(devices_without_workshop),
                       "devices": devices_without_workshop[:10]})
    
    # 状态异常（blocked状态需要关注）
    blocked_devices = [tag for tag, info in current.items() if info.get("status") == "blocked"]
    if blocked_devices:
        issues.append({"type": "blocked_devices", "count": len(blocked_devices),
                       "devices": blocked_devices[:10]})
    
    # 长时间未更新的设备（超过7天）
    stale_devices = []
    now = datetime.datetime.now()
    for tag, info in current.items():
        updated_str = info.get("updated_at", "")
        if updated_str:
            try:
                updated = datetime.datetime.fromisoformat(updated_str)
                if (now - updated).days > 7:
                    stale_devices.append(tag)
            except Exception:
                pass
    if stale_devices:
        issues.append({"type": "stale_devices", "count": len(stale_devices),
                       "devices": stale_devices[:10]})
    
    # 进度统计
    status_count = {}
    for tag, info in current.items():
        status = info.get("status", "pending")
        status_count[status] = status_count.get(status, 0) + 1
    
    completion_percent = round(status_count.get("completed", 0) / len(all_devices) * 100, 1) if all_devices else 0
    
    return {
        "ok": True,
        "total_devices": len(all_devices),
        "devices_with_status": len(current),
        "completed_devices": status_count.get("completed", 0),
        "in_progress_devices": status_count.get("in_progress", 0),
        "pending_devices": status_count.get("pending", 0),
        "completion_percent": completion_percent,
        "issues_count": len(issues),
        "issues": issues,
    }
