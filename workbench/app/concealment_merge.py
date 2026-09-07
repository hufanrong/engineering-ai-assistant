"""
v0.1.79：多电脑并库时隐蔽工程验收记录合并

多台电脑解析的隐蔽工程验收记录数据合并到一个完整库，自动去重，记录冲突处理，
合并后写回隐蔽工程验收记录，合并日志，待人工确认，合并统计，完整性检查。
"""

import os
import json
import hashlib
import datetime
from typing import Optional


_MERGE_FILE = os.path.join("data", "concealment_merge.json")


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


def _calculate_record_md5(record: dict) -> str:
    """计算记录内容MD5（用于去重）。"""
    content = json.dumps({
        "concealment_date": record.get("concealment_date", ""),
        "concealment_location": record.get("concealment_location", ""),
        "concealment_parts": record.get("concealment_parts", []),
        "inspection_items": record.get("inspection_items", []),
        "quality_standards": record.get("quality_standards", []),
        "acceptance_basis": record.get("acceptance_basis", []),
        "environment_notes": record.get("environment_notes", []),
        "inspection_result": record.get("inspection_result", ""),
        "inspection_conclusion": record.get("inspection_conclusion", ""),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def load_records_from_file(file_path: str) -> dict:
    """v0.1.79：从JSON文件加载隐蔽工程验收记录数据。"""
    if not os.path.exists(file_path):
        return {"error": "文件不存在", "file": file_path}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"文件解析失败: {str(e)}", "file": file_path}


def _get_current_records() -> dict:
    """v0.1.79：获取当前隐蔽工程验收记录数据。"""
    record_file = os.path.join("data", "concealment_records.json")
    if os.path.exists(record_file):
        try:
            with open(record_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _write_back_records(records: dict):
    """v0.1.79：将合并后的隐蔽工程验收记录写回。"""
    record_file = os.path.join("data", "concealment_records.json")
    os.makedirs("data", exist_ok=True)
    with open(record_file, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def merge_concealment_records(source_records: dict, source_pc: str = "",
                               conflict_strategy: str = "latest") -> dict:
    """v0.1.79：合并源隐蔽工程验收记录数据。
    
    Args:
        source_records: 源隐蔽工程验收记录数据 {key: {tag, concealment_date, ...}}
        source_pc: 来源电脑名
        conflict_strategy: 冲突策略 - latest/keep_existing/manual
    
    Returns:
        合并结果
    """
    merge = _load_merge()
    
    # 获取当前记录
    current = _get_current_records()
    
    # 统计
    total_source = len(source_records)
    merged_records = 0
    skipped_duplicate = 0
    conflicts = 0
    fields_merged = 0
    pending_conflicts = []
    
    for record_key, source_record in source_records.items():
        if not isinstance(source_record, dict):
            continue
        
        tag = source_record.get("tag", "")
        concealment_date = source_record.get("concealment_date", "")
        
        # 生成唯一key
        if not record_key or record_key not in current:
            current_key = f"{tag}_{concealment_date}" if tag and concealment_date else record_key
        else:
            current_key = record_key
        
        # 计算MD5
        source_md5 = _calculate_record_md5(source_record)
        
        # 检查是否已存在相同记录
        is_duplicate = False
        if current_key in current:
            current_record = current[current_key]
            current_md5 = _calculate_record_md5(current_record)
            if source_md5 == current_md5:
                is_duplicate = True
        
        if is_duplicate:
            skipped_duplicate += 1
            continue
        
        # 冲突判断：同一设备同一日期但内容不同
        has_conflict = current_key in current and current_key in source_records and not is_duplicate
        
        if has_conflict:
            conflicts += 1
            
            if conflict_strategy == "manual":
                pending_conflicts.append({
                    "key": current_key,
                    "tag": tag,
                    "concealment_date": concealment_date,
                    "source_pc": source_pc,
                    "source_result": source_record.get("inspection_result", ""),
                    "current_result": current[current_key].get("inspection_result", ""),
                    "source_parts_count": len(source_record.get("concealment_parts", [])),
                    "current_parts_count": len(current[current_key].get("concealment_parts", [])),
                    "source_items_count": len(source_record.get("inspection_items", [])),
                    "current_items_count": len(current[current_key].get("inspection_items", [])),
                    "status": "pending",
                    "created_at": datetime.datetime.now().isoformat(),
                })
                continue
            elif conflict_strategy == "keep_existing":
                skipped_duplicate += 1
                continue
            # latest: 以源数据为准
        
        # 合并记录内容
        if current_key in current:
            current_record = current[current_key]
            # 合并隐蔽部位（去重）
            source_parts = source_record.get("concealment_parts", [])
            current_parts = current_record.get("concealment_parts", [])
            merged_parts = list(current_parts)
            for item in source_parts:
                if item not in merged_parts:
                    merged_parts.append(item)
                    fields_merged += 1
            source_record["concealment_parts"] = merged_parts
            
            # 合并检查项目（去重）
            source_items = source_record.get("inspection_items", [])
            current_items = current_record.get("inspection_items", [])
            merged_items = list(current_items)
            for item in source_items:
                if item not in merged_items:
                    merged_items.append(item)
                    fields_merged += 1
            source_record["inspection_items"] = merged_items
            
            # 合并质量标准（去重）
            source_standards = source_record.get("quality_standards", [])
            current_standards = current_record.get("quality_standards", [])
            merged_standards = list(current_standards)
            for item in source_standards:
                if item not in merged_standards:
                    merged_standards.append(item)
                    fields_merged += 1
            source_record["quality_standards"] = merged_standards
            
            # 合并验收依据（去重）
            source_basis = source_record.get("acceptance_basis", [])
            current_basis = current_record.get("acceptance_basis", [])
            merged_basis = list(current_basis)
            for item in source_basis:
                if item not in merged_basis:
                    merged_basis.append(item)
                    fields_merged += 1
            source_record["acceptance_basis"] = merged_basis
            
            # 合并环境注意事项（去重）
            source_notes = source_record.get("environment_notes", [])
            current_notes = current_record.get("environment_notes", [])
            merged_notes = list(current_notes)
            for item in source_notes:
                if item not in merged_notes:
                    merged_notes.append(item)
                    fields_merged += 1
            source_record["environment_notes"] = merged_notes
            
            merged_records += 1
        else:
            merged_records += 1
        
        # 更新来源信息
        source_record["source_pc"] = source_pc
        source_record["merged_at"] = datetime.datetime.now().isoformat()
        
        current[current_key] = source_record
    
    # 写回隐蔽工程验收记录
    _write_back_records(current)
    
    # 记录合并日志
    log_entry = {
        "source_pc": source_pc,
        "merged_at": datetime.datetime.now().isoformat(),
        "source_records": total_source,
        "merged_records": merged_records,
        "skipped_duplicate": skipped_duplicate,
        "conflicts": conflicts,
        "fields_merged": fields_merged,
        "conflict_strategy": conflict_strategy,
        "total_records_after": len(current),
    }
    merge["log"].insert(0, log_entry)
    if len(merge["log"]) > 100:
        merge["log"] = merge["log"][:100]
    
    if pending_conflicts:
        merge["pending"].extend(pending_conflicts)
    
    stats = merge.get("stats", {})
    stats["total_merge_operations"] = stats.get("total_merge_operations", 0) + 1
    stats["total_records_merged"] = stats.get("total_records_merged", 0) + merged_records
    stats["total_fields_merged"] = stats.get("total_fields_merged", 0) + fields_merged
    stats["total_conflicts"] = stats.get("total_conflicts", 0) + conflicts
    merge["stats"] = stats
    
    _save_merge(merge)
    
    # 合并后自动触发完整性检查
    integrity = check_concealment_integrity()
    
    return {
        "ok": True,
        "log": log_entry,
        "pending_conflicts": pending_conflicts,
        "integrity_after_merge": integrity,
    }


def resolve_pending(index: int, decision: str) -> dict:
    """v0.1.79：处理待人工确认的记录冲突。"""
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
    """v0.1.79：列出待人工确认的记录冲突。"""
    merge = _load_merge()
    return [p for p in merge.get("pending", []) if p.get("status") == "pending"]


def list_merge_log() -> list:
    """v0.1.79：列出合并日志。"""
    merge = _load_merge()
    return merge.get("log", [])


def merge_stats() -> dict:
    """v0.1.79：获取合并统计信息。"""
    merge = _load_merge()
    stats = merge.get("stats", {})
    log = merge.get("log", [])
    pending = merge.get("pending", [])
    
    current = _get_current_records()
    
    # 按日期统计
    by_date = {}
    by_tag = {}
    by_result = {}
    for key, record in current.items():
        date = record.get("concealment_date", "")
        by_date[date] = by_date.get(date, 0) + 1
        tag = record.get("tag", "")
        by_tag[tag] = by_tag.get(tag, 0) + 1
        result = record.get("inspection_result", "待验收")
        by_result[result] = by_result.get(result, 0) + 1
    
    return {
        "total_merge_operations": stats.get("total_merge_operations", 0),
        "total_records_merged": stats.get("total_records_merged", 0),
        "total_fields_merged": stats.get("total_fields_merged", 0),
        "total_conflicts": stats.get("total_conflicts", 0),
        "pending_conflicts": len([p for p in pending if p.get("status") == "pending"]),
        "resolved_conflicts": len([p for p in pending if p.get("status") == "resolved"]),
        "current_total_records": len(current),
        "current_by_date": by_date,
        "current_by_tag": by_tag,
        "current_by_result": by_result,
        "last_merge": log[0] if log else None,
    }


def check_concealment_integrity() -> dict:
    """v0.1.79：检查隐蔽工程验收记录完整性。"""
    from . import relations as _rel
    
    g = _rel.load_relations()
    all_devices = g.get("devices", [])
    current = _get_current_records()
    
    issues = []
    
    # 无隐蔽工程验收记录的设备
    devices_with_records = set(record.get("tag") for record in current.values() if record.get("tag"))
    devices_without_records = [d["tag"] for d in all_devices if d["tag"] not in devices_with_records]
    if devices_without_records:
        issues.append({"type": "devices_without_records", "count": len(devices_without_records),
                       "devices": devices_without_records[:10]})
    
    # 记录内容不完整（缺少关键要素）
    incomplete_records = []
    for key, record in current.items():
        missing = []
        if not record.get("concealment_date"):
            missing.append("隐蔽日期")
        if not record.get("concealment_location"):
            missing.append("隐蔽部位")
        if not record.get("concealment_parts"):
            missing.append("隐蔽内容")
        if not record.get("inspection_items"):
            missing.append("检查项目")
        if not record.get("quality_standards"):
            missing.append("质量标准")
        if not record.get("inspection_result"):
            missing.append("验收结果")
        if missing:
            incomplete_records.append({"key": key, "tag": record.get("tag", ""),
                                        "date": record.get("concealment_date", ""), "missing": missing})
    if incomplete_records:
        issues.append({"type": "incomplete_records", "count": len(incomplete_records),
                       "records": incomplete_records[:5]})
    
    # 待验收的设备
    devices_pending = [record.get("tag") for record in current.values() if record.get("inspection_result") == "待验收"]
    if devices_pending:
        issues.append({"type": "devices_pending", "count": len(devices_pending),
                       "devices": devices_pending[:10]})
    
    # 不合格的设备
    devices_failed = [record.get("tag") for record in current.values() if record.get("inspection_result") == "不合格"]
    if devices_failed:
        issues.append({"type": "devices_failed", "count": len(devices_failed),
                       "devices": devices_failed[:10]})
    
    # 日期跨度检查
    dates = [record.get("concealment_date", "") for record in current.values() if record.get("concealment_date")]
    if dates:
        dates.sort()
        date_span = f"{dates[0]} ~ {dates[-1]}"
    else:
        date_span = "无数据"
    
    # 总体统计
    total = len(all_devices)
    with_records = len(devices_with_records)
    
    return {
        "ok": True,
        "total_devices": total,
        "devices_with_records": with_records,
        "total_records": len(current),
        "date_span": date_span,
        "coverage_percent": round(with_records / total * 100, 1) if total > 0 else 0,
        "devices_pending": len(devices_pending),
        "devices_failed": len(devices_failed),
        "issues_count": len(issues),
        "issues": issues,
    }
