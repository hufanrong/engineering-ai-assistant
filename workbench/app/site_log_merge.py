"""
v0.1.75：多电脑并库时施工日志合并

多台电脑解析的施工日志数据合并到一个完整库，自动去重，日志冲突处理，
合并后写回施工日志，合并日志，待人工确认，合并统计，完整性检查。
"""

import os
import json
import hashlib
import datetime
from typing import Optional


_MERGE_FILE = os.path.join("data", "site_log_merge.json")


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


def _calculate_log_md5(log: dict) -> str:
    """计算日志内容MD5（用于去重）。"""
    content = json.dumps({
        "construction_content": log.get("construction_content", []),
        "personnel": log.get("personnel", []),
        "equipment": log.get("equipment", []),
        "materials": log.get("materials", []),
        "quality_results": log.get("quality_results", []),
        "safety_situation": log.get("safety_situation", []),
        "issues": log.get("issues", []),
        "tomorrow_plan": log.get("tomorrow_plan", []),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def load_logs_from_file(file_path: str) -> dict:
    """v0.1.75：从JSON文件加载施工日志数据。"""
    if not os.path.exists(file_path):
        return {"error": "文件不存在", "file": file_path}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"文件解析失败: {str(e)}", "file": file_path}


def _get_current_logs() -> dict:
    """v0.1.75：获取当前施工日志数据。"""
    log_file = os.path.join("data", "site_logs.json")
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _write_back_logs(logs: dict):
    """v0.1.75：将合并后的施工日志写回。"""
    log_file = os.path.join("data", "site_logs.json")
    os.makedirs("data", exist_ok=True)
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def merge_site_logs(source_logs: dict, source_pc: str = "",
                     conflict_strategy: str = "latest") -> dict:
    """v0.1.75：合并源施工日志数据。
    
    Args:
        source_logs: 源施工日志数据 {key: {tag, log_date, construction_content, ...}}
        source_pc: 来源电脑名
        conflict_strategy: 冲突策略 - latest/keep_existing/manual
    
    Returns:
        合并结果
    """
    merge = _load_merge()
    
    # 获取当前日志
    current = _get_current_logs()
    
    # 统计
    total_source = len(source_logs)
    merged_logs = 0
    skipped_duplicate = 0
    conflicts = 0
    content_merged = 0
    pending_conflicts = []
    
    for log_key, source_log in source_logs.items():
        if not isinstance(source_log, dict):
            continue
        
        tag = source_log.get("tag", "")
        log_date = source_log.get("log_date", "")
        
        # 生成唯一key
        if not log_key or log_key not in current:
            current_key = f"{tag}_{log_date}" if tag and log_date else log_key
        else:
            current_key = log_key
        
        # 计算MD5
        source_md5 = _calculate_log_md5(source_log)
        
        # 检查是否已存在相同日志
        is_duplicate = False
        if current_key in current:
            current_log = current[current_key]
            current_md5 = _calculate_log_md5(current_log)
            if source_md5 == current_md5:
                is_duplicate = True
        
        if is_duplicate:
            skipped_duplicate += 1
            continue
        
        # 冲突判断：同一设备同一日期但内容不同
        has_conflict = current_key in current and current_key in source_logs and not is_duplicate
        
        if has_conflict:
            conflicts += 1
            
            if conflict_strategy == "manual":
                pending_conflicts.append({
                    "key": current_key,
                    "tag": tag,
                    "log_date": log_date,
                    "source_pc": source_pc,
                    "source_content_count": len(source_log.get("construction_content", [])),
                    "source_personnel_count": len(source_log.get("personnel", [])),
                    "current_content_count": len(current[current_key].get("construction_content", [])),
                    "current_personnel_count": len(current[current_key].get("personnel", [])),
                    "status": "pending",
                    "created_at": datetime.datetime.now().isoformat(),
                })
                continue
            elif conflict_strategy == "keep_existing":
                skipped_duplicate += 1
                continue
            # latest: 以源数据为准
        
        # 合并日志内容
        if current_key in current:
            current_log = current[current_key]
            # 合并施工内容（去重）
            source_content = source_log.get("construction_content", [])
            current_content = current_log.get("construction_content", [])
            merged_content = list(current_content)
            for item in source_content:
                if item not in merged_content:
                    merged_content.append(item)
                    content_merged += 1
            source_log["construction_content"] = merged_content
            
            # 合并人员配置（去重）
            source_personnel = source_log.get("personnel", [])
            current_personnel = current_log.get("personnel", [])
            merged_personnel = list(current_personnel)
            for item in source_personnel:
                if item not in merged_personnel:
                    merged_personnel.append(item)
            source_log["personnel"] = merged_personnel
            
            # 合并机具设备（去重）
            source_equipment = source_log.get("equipment", [])
            current_equipment = current_log.get("equipment", [])
            merged_equipment = list(current_equipment)
            for item in source_equipment:
                if item not in merged_equipment:
                    merged_equipment.append(item)
            source_log["equipment"] = merged_equipment
            
            # 合并材料使用（去重）
            source_materials = source_log.get("materials", [])
            current_materials = current_log.get("materials", [])
            merged_materials = list(current_materials)
            for item in source_materials:
                if item not in merged_materials:
                    merged_materials.append(item)
            source_log["materials"] = merged_materials
            
            # 合并问题及处理（去重）
            source_issues = source_log.get("issues", [])
            current_issues = current_log.get("issues", [])
            merged_issues = list(current_issues)
            for item in source_issues:
                if item not in merged_issues:
                    merged_issues.append(item)
            source_log["issues"] = merged_issues
            
            # 合并明日计划（去重）
            source_tomorrow = source_log.get("tomorrow_plan", [])
            current_tomorrow = current_log.get("tomorrow_plan", [])
            merged_tomorrow = list(current_tomorrow)
            for item in source_tomorrow:
                if item not in merged_tomorrow:
                    merged_tomorrow.append(item)
            source_log["tomorrow_plan"] = merged_tomorrow
            
            merged_logs += 1
        else:
            merged_logs += 1
        
        # 更新来源信息
        source_log["source_pc"] = source_pc
        source_log["merged_at"] = datetime.datetime.now().isoformat()
        
        current[current_key] = source_log
    
    # 写回施工日志
    _write_back_logs(current)
    
    # 记录合并日志
    log_entry = {
        "source_pc": source_pc,
        "merged_at": datetime.datetime.now().isoformat(),
        "source_logs": total_source,
        "merged_logs": merged_logs,
        "skipped_duplicate": skipped_duplicate,
        "conflicts": conflicts,
        "content_merged": content_merged,
        "conflict_strategy": conflict_strategy,
        "total_logs_after": len(current),
    }
    merge["log"].insert(0, log_entry)
    if len(merge["log"]) > 100:
        merge["log"] = merge["log"][:100]
    
    if pending_conflicts:
        merge["pending"].extend(pending_conflicts)
    
    stats = merge.get("stats", {})
    stats["total_merge_operations"] = stats.get("total_merge_operations", 0) + 1
    stats["total_logs_merged"] = stats.get("total_logs_merged", 0) + merged_logs
    stats["total_content_merged"] = stats.get("total_content_merged", 0) + content_merged
    stats["total_conflicts"] = stats.get("total_conflicts", 0) + conflicts
    merge["stats"] = stats
    
    _save_merge(merge)
    
    # 合并后自动触发完整性检查
    integrity = check_log_integrity()
    
    return {
        "ok": True,
        "log": log_entry,
        "pending_conflicts": pending_conflicts,
        "integrity_after_merge": integrity,
    }


def resolve_pending(index: int, decision: str) -> dict:
    """v0.1.75：处理待人工确认的日志冲突。"""
    merge = _load_merge()
    pending = merge.get("pending", [])
    
    if index < 0 or index >= len(pending):
        return {"error": "索引超出范围", "index": index}
    
    item = pending[index]
    if item.get("status") != "pending":
        return {"error": "该冲突已处理", "index": index}
    
    item["status"] = "resolved"
    item["decision"] = decision
    item["resolved_at"] = datetime.datetime.now().isoformat()
    
    _save_merge(merge)
    
    return {"ok": True, "index": index, "key": item.get("key", ""), "decision": decision}


def list_pending() -> list:
    """v0.1.75：列出待人工确认的日志冲突。"""
    merge = _load_merge()
    return [p for p in merge.get("pending", []) if p.get("status") == "pending"]


def list_merge_log() -> list:
    """v0.1.75：列出合并日志。"""
    merge = _load_merge()
    return merge.get("log", [])


def merge_stats() -> dict:
    """v0.1.75：获取合并统计信息。"""
    merge = _load_merge()
    stats = merge.get("stats", {})
    log = merge.get("log", [])
    pending = merge.get("pending", [])
    
    current = _get_current_logs()
    
    # 按日期统计
    by_date = {}
    by_tag = {}
    for key, log_entry in current.items():
        date = log_entry.get("log_date", "")
        by_date[date] = by_date.get(date, 0) + 1
        tag = log_entry.get("tag", "")
        by_tag[tag] = by_tag.get(tag, 0) + 1
    
    return {
        "total_merge_operations": stats.get("total_merge_operations", 0),
        "total_logs_merged": stats.get("total_logs_merged", 0),
        "total_content_merged": stats.get("total_content_merged", 0),
        "total_conflicts": stats.get("total_conflicts", 0),
        "pending_conflicts": len([p for p in pending if p.get("status") == "pending"]),
        "resolved_conflicts": len([p for p in pending if p.get("status") == "resolved"]),
        "current_total_logs": len(current),
        "current_by_date": by_date,
        "current_by_tag": by_tag,
        "last_merge": log[0] if log else None,
    }


def check_log_integrity() -> dict:
    """v0.1.75：检查施工日志完整性。"""
    from . import relations as _rel
    from . import construction_schedule as _cs
    
    g = _rel.load_relations()
    all_devices = g.get("devices", [])
    current = _get_current_logs()
    
    issues = []
    
    # 无施工日志的设备
    devices_with_logs = set(log.get("tag") for log in current.values() if log.get("tag"))
    devices_without_logs = [d["tag"] for d in all_devices if d["tag"] not in devices_with_logs]
    if devices_without_logs:
        issues.append({"type": "devices_without_logs", "count": len(devices_without_logs),
                       "devices": devices_without_logs[:10]})
    
    # 日志内容不完整（缺少关键要素）
    incomplete_logs = []
    for key, log_entry in current.items():
        missing = []
        if not log_entry.get("construction_content"):
            missing.append("施工内容")
        if not log_entry.get("personnel"):
            missing.append("人员配置")
        if not log_entry.get("quality_results"):
            missing.append("质量检查")
        if not log_entry.get("safety_situation"):
            missing.append("安全情况")
        if missing:
            incomplete_logs.append({"key": key, "tag": log_entry.get("tag", ""),
                                     "date": log_entry.get("log_date", ""), "missing": missing})
    if incomplete_logs:
        issues.append({"type": "incomplete_logs", "count": len(incomplete_logs),
                       "logs": incomplete_logs[:5]})
    
    # 日期跨度检查
    dates = [log.get("log_date", "") for log in current.values() if log.get("log_date")]
    if dates:
        dates.sort()
        date_span = f"{dates[0]} ~ {dates[-1]}"
    else:
        date_span = "无数据"
    
    # 总体统计
    total = len(all_devices)
    with_logs = len(devices_with_logs)
    
    return {
        "ok": True,
        "total_devices": total,
        "devices_with_logs": with_logs,
        "total_logs": len(current),
        "date_span": date_span,
        "coverage_percent": round(with_logs / total * 100, 1) if total > 0 else 0,
        "issues_count": len(issues),
        "issues": issues,
    }
