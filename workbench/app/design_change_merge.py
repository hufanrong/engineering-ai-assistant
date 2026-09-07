"""
v0.1.80：多电脑并库时设计变更合并

多台电脑解析的设计变更数据合并到一个完整库，自动去重，变更冲突处理，
合并后写回设计变更，合并日志，待人工确认，合并统计，完整性检查。
"""

import os
import json
import hashlib
import datetime
from typing import Optional


_MERGE_FILE = os.path.join("data", "design_change_merge.json")


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


def _calculate_change_md5(change: dict) -> str:
    """计算变更内容MD5（用于去重）。"""
    content = json.dumps({
        "change_date": change.get("change_date", ""),
        "change_location": change.get("change_location", ""),
        "change_reason": change.get("change_reason", ""),
        "common_changes": change.get("common_changes", []),
        "impact_analysis": change.get("impact_analysis", []),
        "handling_measures": change.get("handling_measures", []),
        "acceptance_requirements": change.get("acceptance_requirements", []),
        "change_status": change.get("change_status", ""),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def load_changes_from_file(file_path: str) -> dict:
    """v0.1.80：从JSON文件加载设计变更数据。"""
    if not os.path.exists(file_path):
        return {"error": "文件不存在", "file": file_path}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"文件解析失败: {str(e)}", "file": file_path}


def _get_current_changes() -> dict:
    """v0.1.80：获取当前设计变更数据。"""
    change_file = os.path.join("data", "design_changes.json")
    if os.path.exists(change_file):
        try:
            with open(change_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _write_back_changes(changes: dict):
    """v0.1.80：将合并后的设计变更写回。"""
    change_file = os.path.join("data", "design_changes.json")
    os.makedirs("data", exist_ok=True)
    with open(change_file, "w", encoding="utf-8") as f:
        json.dump(changes, f, ensure_ascii=False, indent=2)


def merge_design_changes(source_changes: dict, source_pc: str = "",
                          conflict_strategy: str = "latest") -> dict:
    """v0.1.80：合并源设计变更数据。
    
    Args:
        source_changes: 源设计变更数据 {key: {tag, change_date, ...}}
        source_pc: 来源电脑名
        conflict_strategy: 冲突策略 - latest/keep_existing/manual
    
    Returns:
        合并结果
    """
    merge = _load_merge()
    
    # 获取当前变更
    current = _get_current_changes()
    
    # 统计
    total_source = len(source_changes)
    merged_changes = 0
    skipped_duplicate = 0
    conflicts = 0
    fields_merged = 0
    pending_conflicts = []
    
    for change_key, source_change in source_changes.items():
        if not isinstance(source_change, dict):
            continue
        
        tag = source_change.get("tag", "")
        change_date = source_change.get("change_date", "")
        
        # 生成唯一key
        if not change_key or change_key not in current:
            current_key = f"{tag}_{change_date}" if tag and change_date else change_key
        else:
            current_key = change_key
        
        # 计算MD5
        source_md5 = _calculate_change_md5(source_change)
        
        # 检查是否已存在相同变更
        is_duplicate = False
        if current_key in current:
            current_change = current[current_key]
            current_md5 = _calculate_change_md5(current_change)
            if source_md5 == current_md5:
                is_duplicate = True
        
        if is_duplicate:
            skipped_duplicate += 1
            continue
        
        # 冲突判断：同一设备同一日期但内容不同
        has_conflict = current_key in current and current_key in source_changes and not is_duplicate
        
        if has_conflict:
            conflicts += 1
            
            if conflict_strategy == "manual":
                pending_conflicts.append({
                    "key": current_key,
                    "tag": tag,
                    "change_date": change_date,
                    "source_pc": source_pc,
                    "source_status": source_change.get("change_status", ""),
                    "current_status": current[current_key].get("change_status", ""),
                    "source_reason": source_change.get("change_reason", ""),
                    "current_reason": current[current_key].get("change_reason", ""),
                    "source_changes_count": len(source_change.get("common_changes", [])),
                    "current_changes_count": len(current[current_key].get("common_changes", [])),
                    "source_impact_count": len(source_change.get("impact_analysis", [])),
                    "current_impact_count": len(current[current_key].get("impact_analysis", [])),
                    "status": "pending",
                    "created_at": datetime.datetime.now().isoformat(),
                })
                continue
            elif conflict_strategy == "keep_existing":
                skipped_duplicate += 1
                continue
            # latest: 以源数据为准
        
        # 合并变更内容
        if current_key in current:
            current_change = current[current_key]
            # 合并常见变更类型（去重）
            source_common = source_change.get("common_changes", [])
            current_common = current_change.get("common_changes", [])
            merged_common = list(current_common)
            for item in source_common:
                if item not in merged_common:
                    merged_common.append(item)
                    fields_merged += 1
            source_change["common_changes"] = merged_common
            
            # 合并影响分析（去重）
            source_impact = source_change.get("impact_analysis", [])
            current_impact = current_change.get("impact_analysis", [])
            merged_impact = list(current_impact)
            for item in source_impact:
                if item not in merged_impact:
                    merged_impact.append(item)
                    fields_merged += 1
            source_change["impact_analysis"] = merged_impact
            
            # 合并处理措施（去重）
            source_measures = source_change.get("handling_measures", [])
            current_measures = current_change.get("handling_measures", [])
            merged_measures = list(current_measures)
            for item in source_measures:
                if item not in merged_measures:
                    merged_measures.append(item)
                    fields_merged += 1
            source_change["handling_measures"] = merged_measures
            
            # 合并验收要求（去重）
            source_req = source_change.get("acceptance_requirements", [])
            current_req = current_change.get("acceptance_requirements", [])
            merged_req = list(current_req)
            for item in source_req:
                if item not in merged_req:
                    merged_req.append(item)
                    fields_merged += 1
            source_change["acceptance_requirements"] = merged_req
            
            merged_changes += 1
        else:
            merged_changes += 1
        
        # 更新来源信息
        source_change["source_pc"] = source_pc
        source_change["merged_at"] = datetime.datetime.now().isoformat()
        
        current[current_key] = source_change
    
    # 写回设计变更
    _write_back_changes(current)
    
    # 记录合并日志
    log_entry = {
        "source_pc": source_pc,
        "merged_at": datetime.datetime.now().isoformat(),
        "source_changes": total_source,
        "merged_changes": merged_changes,
        "skipped_duplicate": skipped_duplicate,
        "conflicts": conflicts,
        "fields_merged": fields_merged,
        "conflict_strategy": conflict_strategy,
        "total_changes_after": len(current),
    }
    merge["log"].insert(0, log_entry)
    if len(merge["log"]) > 100:
        merge["log"] = merge["log"][:100]
    
    if pending_conflicts:
        merge["pending"].extend(pending_conflicts)
    
    stats = merge.get("stats", {})
    stats["total_merge_operations"] = stats.get("total_merge_operations", 0) + 1
    stats["total_changes_merged"] = stats.get("total_changes_merged", 0) + merged_changes
    stats["total_fields_merged"] = stats.get("total_fields_merged", 0) + fields_merged
    stats["total_conflicts"] = stats.get("total_conflicts", 0) + conflicts
    merge["stats"] = stats
    
    _save_merge(merge)
    
    # 合并后自动触发完整性检查
    integrity = check_design_change_integrity()
    
    return {
        "ok": True,
        "log": log_entry,
        "pending_conflicts": pending_conflicts,
        "integrity_after_merge": integrity,
    }


def resolve_pending(index: int, decision: str) -> dict:
    """v0.1.80：处理待人工确认的变更冲突。"""
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
    """v0.1.80：列出待人工确认的变更冲突。"""
    merge = _load_merge()
    return [p for p in merge.get("pending", []) if p.get("status") == "pending"]


def list_merge_log() -> list:
    """v0.1.80：列出合并日志。"""
    merge = _load_merge()
    return merge.get("log", [])


def merge_stats() -> dict:
    """v0.1.80：获取合并统计信息。"""
    merge = _load_merge()
    stats = merge.get("stats", {})
    log = merge.get("log", [])
    pending = merge.get("pending", [])
    
    current = _get_current_changes()
    
    # 按日期统计
    by_date = {}
    by_tag = {}
    by_status = {}
    for key, change in current.items():
        date = change.get("change_date", "")
        by_date[date] = by_date.get(date, 0) + 1
        tag = change.get("tag", "")
        by_tag[tag] = by_tag.get(tag, 0) + 1
        status = change.get("change_status", "待审批")
        by_status[status] = by_status.get(status, 0) + 1
    
    return {
        "total_merge_operations": stats.get("total_merge_operations", 0),
        "total_changes_merged": stats.get("total_changes_merged", 0),
        "total_fields_merged": stats.get("total_fields_merged", 0),
        "total_conflicts": stats.get("total_conflicts", 0),
        "pending_conflicts": len([p for p in pending if p.get("status") == "pending"]),
        "resolved_conflicts": len([p for p in pending if p.get("status") == "resolved"]),
        "current_total_changes": len(current),
        "current_by_date": by_date,
        "current_by_tag": by_tag,
        "current_by_status": by_status,
        "last_merge": log[0] if log else None,
    }


def check_design_change_integrity() -> dict:
    """v0.1.80：检查设计变更完整性。"""
    from . import relations as _rel
    
    g = _rel.load_relations()
    all_devices = g.get("devices", [])
    current = _get_current_changes()
    
    issues = []
    
    # 无设计变更的设备
    devices_with_changes = set(change.get("tag") for change in current.values() if change.get("tag"))
    devices_without_changes = [d["tag"] for d in all_devices if d["tag"] not in devices_with_changes]
    if devices_without_changes:
        issues.append({"type": "devices_without_changes", "count": len(devices_without_changes),
                       "devices": devices_without_changes[:10]})
    
    # 变更内容不完整（缺少关键要素）
    incomplete_changes = []
    for key, change in current.items():
        missing = []
        if not change.get("change_date"):
            missing.append("变更日期")
        if not change.get("change_reason") or change.get("change_reason") == "待补充":
            missing.append("变更原因")
        if not change.get("common_changes"):
            missing.append("常见变更类型")
        if not change.get("impact_analysis"):
            missing.append("影响分析")
        if not change.get("handling_measures"):
            missing.append("处理措施")
        if not change.get("change_status"):
            missing.append("变更状态")
        if missing:
            incomplete_changes.append({"key": key, "tag": change.get("tag", ""),
                                        "date": change.get("change_date", ""), "missing": missing})
    if incomplete_changes:
        issues.append({"type": "incomplete_changes", "count": len(incomplete_changes),
                       "changes": incomplete_changes[:5]})
    
    # 待审批的变更
    changes_pending = [change.get("tag") for change in current.values() if change.get("change_status") == "待审批"]
    if changes_pending:
        issues.append({"type": "changes_pending", "count": len(changes_pending),
                       "changes": changes_pending[:10]})
    
    # 施工中的变更
    changes_in_progress = [change.get("tag") for change in current.values() if change.get("change_status") == "施工中"]
    if changes_in_progress:
        issues.append({"type": "changes_in_progress", "count": len(changes_in_progress),
                       "changes": changes_in_progress[:10]})
    
    # 日期跨度检查
    dates = [change.get("change_date", "") for change in current.values() if change.get("change_date")]
    if dates:
        dates.sort()
        date_span = f"{dates[0]} ~ {dates[-1]}"
    else:
        date_span = "无数据"
    
    # 总体统计
    total = len(all_devices)
    with_changes = len(devices_with_changes)
    
    return {
        "ok": True,
        "total_devices": total,
        "devices_with_changes": with_changes,
        "total_changes": len(current),
        "date_span": date_span,
        "coverage_percent": round(with_changes / total * 100, 1) if total > 0 else 0,
        "changes_pending": len(changes_pending),
        "changes_in_progress": len(changes_in_progress),
        "issues_count": len(issues),
        "issues": issues,
    }
