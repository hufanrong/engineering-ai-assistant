"""
v0.1.98：矿山设备多电脑并库现场记录合并

多台电脑上传的现场记录合并，记录去重（基于MD5），冲突处理
（latest/keep_existing/manual），合并日志，待人工确认管理，完整性检查。
"""

import os
import json
import hashlib
import datetime
from typing import Optional


# 合并记录存储路径
MERGE_DATA_DIR = "data/mining_field_record_merge"
MERGE_LOG_FILE = os.path.join(MERGE_DATA_DIR, "merge_log.json")
PENDING_FILE = os.path.join(MERGE_DATA_DIR, "pending_confirm.json")
MAIN_RECORDS_FILE = os.path.join(MERGE_DATA_DIR, "main_records.json")


def _ensure_dir():
    """确保数据目录存在。"""
    os.makedirs(MERGE_DATA_DIR, exist_ok=True)


def _calculate_record_md5(record: dict) -> str:
    """计算记录的MD5哈希（用于去重）。"""
    # 排除元数据字段
    record_copy = {k: v for k, v in record.items() 
                   if k not in ["id", "upload_time", "uploader", "node_name", 
                                "merged_at", "merge_source", "status", "md5", "source_node"]}
    record_str = json.dumps(record_copy, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(record_str.encode("utf-8")).hexdigest()


def _load_json(filepath: str, default=None):
    """加载JSON文件。"""
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default if default is not None else []


def _save_json(filepath: str, data):
    """保存JSON文件。"""
    _ensure_dir()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def merge_field_records(
    source_records: list,
    source_node: str = "unknown",
    conflict_strategy: str = "latest",
) -> dict:
    """
    合并现场记录（多电脑并库）。
    
    Args:
        source_records: 源记录列表
        source_node: 源节点名称
        conflict_strategy: 冲突策略（latest/keep_existing/manual）
    
    Returns:
        合并结果
    """
    _ensure_dir()
    
    main_records = _load_json(MAIN_RECORDS_FILE, [])
    merge_log = _load_json(MERGE_LOG_FILE, [])
    pending = _load_json(PENDING_FILE, [])
    
    # 建立主库MD5索引
    main_md5_index = {}
    for i, rec in enumerate(main_records):
        md5 = rec.get("md5", _calculate_record_md5(rec))
        rec["md5"] = md5
        main_md5_index[md5] = i
    
    stats = {
        "total_source": len(source_records),
        "new_added": 0,
        "duplicates_skipped": 0,
        "conflicts": 0,
        "merged_latest": 0,
        "kept_existing": 0,
        "pending_manual": 0,
        "errors": 0,
    }
    
    for record in source_records:
        try:
            record_md5 = _calculate_record_md5(record)
            record["md5"] = record_md5
            record["source_node"] = source_node
            record["merge_source"] = source_node
            
            # 检查是否完全重复
            if record_md5 in main_md5_index:
                stats["duplicates_skipped"] += 1
                continue
            
            # 检查是否有冲突（同一记录类型+设备+日期，但内容不同）
            conflict_index = _find_conflict(main_records, record)
            
            if conflict_index >= 0:
                stats["conflicts"] += 1
                
                if conflict_strategy == "latest":
                    # 用最新记录替换
                    old_record = main_records[conflict_index]
                    record["id"] = old_record.get("id", record.get("id", ""))
                    record["merged_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    main_records[conflict_index] = record
                    main_md5_index[record_md5] = conflict_index
                    stats["merged_latest"] += 1
                    
                    merge_log.append({
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "action": "conflict_replace_latest",
                        "source_node": source_node,
                        "record_type": record.get("record_type", ""),
                        "old_md5": old_record.get("md5", ""),
                        "new_md5": record_md5,
                    })
                    
                elif conflict_strategy == "keep_existing":
                    # 保留现有记录
                    stats["kept_existing"] += 1
                    
                    merge_log.append({
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "action": "conflict_keep_existing",
                        "source_node": source_node,
                        "record_type": record.get("record_type", ""),
                        "existing_md5": main_records[conflict_index].get("md5", ""),
                        "incoming_md5": record_md5,
                    })
                    
                else:  # manual
                    # 待人工确认
                    pending.append({
                        "id": datetime.datetime.now().strftime("%Y%m%d%H%M%S") + "_" + str(len(pending)),
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "source_node": source_node,
                        "incoming_record": record,
                        "existing_record": main_records[conflict_index],
                        "record_type": record.get("record_type", ""),
                        "status": "pending",
                    })
                    stats["pending_manual"] += 1
                    
                    merge_log.append({
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "action": "conflict_pending_manual",
                        "source_node": source_node,
                        "record_type": record.get("record_type", ""),
                        "incoming_md5": record_md5,
                    })
            else:
                # 新记录，直接添加
                if "id" not in record or not record["id"]:
                    record["id"] = datetime.datetime.now().strftime("%Y%m%d%H%M%S") + "_" + str(len(main_records))
                record["merged_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                main_records.append(record)
                main_md5_index[record_md5] = len(main_records) - 1
                stats["new_added"] += 1
                
                merge_log.append({
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "action": "new_added",
                    "source_node": source_node,
                    "record_type": record.get("record_type", ""),
                    "md5": record_md5,
                })
                
        except Exception as e:
            stats["errors"] += 1
            merge_log.append({
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "action": "error",
                "source_node": source_node,
                "error": str(e),
            })
    
    # 限制合并日志保留最近200条
    if len(merge_log) > 200:
        merge_log = merge_log[-200:]
    
    # 保存
    _save_json(MAIN_RECORDS_FILE, main_records)
    _save_json(MERGE_LOG_FILE, merge_log)
    _save_json(PENDING_FILE, pending)
    
    return {
        "ok": True,
        "source_node": source_node,
        "conflict_strategy": conflict_strategy,
        "stats": stats,
        "main_records_count": len(main_records),
        "pending_count": len(pending),
        "merge_log_count": len(merge_log),
        "merged_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _find_conflict(main_records: list, record: dict) -> int:
    """查找冲突记录（同一类型+设备+日期，但内容不同）。"""
    record_type = record.get("record_type", "")
    device = record.get("device_type", "") or record.get("equipment_name", "")
    date = record.get("date", "")
    
    for i, main_rec in enumerate(main_records):
        main_type = main_rec.get("record_type", "")
        main_device = main_rec.get("device_type", "") or main_rec.get("equipment_name", "")
        main_date = main_rec.get("date", "")
        
        # 同一类型+设备+日期视为可能冲突
        if (record_type and main_type == record_type and
            device and main_device == device and
            date and main_date == date):
            return i
    
    return -1


def get_merge_stats() -> dict:
    """获取合并统计信息。"""
    _ensure_dir()
    
    main_records = _load_json(MAIN_RECORDS_FILE, [])
    merge_log = _load_json(MERGE_LOG_FILE, [])
    pending = _load_json(PENDING_FILE, [])
    
    # 按记录类型统计
    by_type = {}
    by_node = {}
    for rec in main_records:
        rt = rec.get("record_type", "未知")
        by_type[rt] = by_type.get(rt, 0) + 1
        node = rec.get("source_node", "未知")
        by_node[node] = by_node.get(node, 0) + 1
    
    # 按操作统计日志
    log_stats = {}
    for log in merge_log:
        action = log.get("action", "unknown")
        log_stats[action] = log_stats.get(action, 0) + 1
    
    return {
        "ok": True,
        "main_records_count": len(main_records),
        "pending_count": len(pending),
        "merge_log_count": len(merge_log),
        "by_type": by_type,
        "by_node": by_node,
        "log_stats": log_stats,
        "stats_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_pending_confirmations() -> dict:
    """获取待人工确认列表。"""
    _ensure_dir()
    pending = _load_json(PENDING_FILE, [])
    
    # 只返回待确认的
    pending_list = [p for p in pending if p.get("status") == "pending"]
    
    return {
        "ok": True,
        "pending_count": len(pending_list),
        "pending_list": pending_list,
    }


def resolve_pending_confirmation(
    pending_id: str,
    action: str,
) -> dict:
    """
    处理待人工确认。
    
    Args:
        pending_id: 待确认ID
        action: 处理动作（accept_incoming/keep_existing/merge_both）
    
    Returns:
        处理结果
    """
    _ensure_dir()
    
    pending = _load_json(PENDING_FILE, [])
    main_records = _load_json(MAIN_RECORDS_FILE, [])
    merge_log = _load_json(MERGE_LOG_FILE, [])
    
    for i, p in enumerate(pending):
        if p.get("id") == pending_id and p.get("status") == "pending":
            incoming = p.get("incoming_record", {})
            existing = p.get("existing_record", {})
            
            if action == "accept_incoming":
                # 用传入记录替换
                for j, rec in enumerate(main_records):
                    if rec.get("md5") == existing.get("md5"):
                        incoming["id"] = rec.get("id", incoming.get("id", ""))
                        incoming["merged_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        main_records[j] = incoming
                        break
                
                p["status"] = "resolved_accept_incoming"
                merge_log.append({
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "action": "manual_accept_incoming",
                    "pending_id": pending_id,
                    "record_type": p.get("record_type", ""),
                })
                
            elif action == "keep_existing":
                # 保留现有
                p["status"] = "resolved_keep_existing"
                merge_log.append({
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "action": "manual_keep_existing",
                    "pending_id": pending_id,
                    "record_type": p.get("record_type", ""),
                })
                
            elif action == "merge_both":
                # 合并两条记录
                merged = {**existing, **incoming}
                merged["md5"] = _calculate_record_md5(merged)
                merged["merged_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                merged["merge_source"] = "manual_merge_both"
                
                for j, rec in enumerate(main_records):
                    if rec.get("md5") == existing.get("md5"):
                        main_records[j] = merged
                        break
                
                p["status"] = "resolved_merge_both"
                merge_log.append({
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "action": "manual_merge_both",
                    "pending_id": pending_id,
                    "record_type": p.get("record_type", ""),
                })
            else:
                return {"ok": False, "error": f"未知动作: {action}"}
            
            # 保存
            _save_json(PENDING_FILE, pending)
            _save_json(MAIN_RECORDS_FILE, main_records)
            if len(merge_log) > 200:
                merge_log = merge_log[-200:]
            _save_json(MERGE_LOG_FILE, merge_log)
            
            return {
                "ok": True,
                "pending_id": pending_id,
                "action": action,
                "status": p["status"],
            }
    
    return {"ok": False, "error": f"未找到待确认记录: {pending_id}"}


def get_merge_log(limit: int = 50) -> dict:
    """获取合并日志。"""
    _ensure_dir()
    merge_log = _load_json(MERGE_LOG_FILE, [])
    
    # 按时间倒序
    merge_log.sort(key=lambda x: x.get("time", ""), reverse=True)
    
    return {
        "ok": True,
        "total": len(merge_log),
        "logs": merge_log[:limit],
        "returned": min(len(merge_log), limit),
    }


def check_field_record_integrity() -> dict:
    """检查现场记录完整性。"""
    _ensure_dir()
    main_records = _load_json(MAIN_RECORDS_FILE, [])
    
    issues = []
    record_types = {}
    
    for rec in main_records:
        rt = rec.get("record_type", "未知")
        record_types[rt] = record_types.get(rt, 0) + 1
        
        # 检查必填字段
        if not rec.get("date"):
            issues.append({"record_id": rec.get("id", ""), "issue": "缺少日期", "record_type": rt})
        if not rec.get("record_type"):
            issues.append({"record_id": rec.get("id", ""), "issue": "缺少记录类型", "record_type": rt})
        
        # 检查MD5
        if not rec.get("md5"):
            rec["md5"] = _calculate_record_md5(rec)
    
    # 保存更新后的MD5
    _save_json(MAIN_RECORDS_FILE, main_records)
    
    return {
        "ok": True,
        "total_records": len(main_records),
        "record_types": record_types,
        "issues_count": len(issues),
        "issues": issues[:50],
        "checked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def clear_merge_data() -> dict:
    """清空合并数据（谨慎使用）。"""
    _ensure_dir()
    
    # 备份
    backup_dir = os.path.join(MERGE_DATA_DIR, "backup_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
    os.makedirs(backup_dir, exist_ok=True)
    
    for f in [MAIN_RECORDS_FILE, MERGE_LOG_FILE, PENDING_FILE]:
        if os.path.exists(f):
            import shutil
            shutil.copy(f, os.path.join(backup_dir, os.path.basename(f)))
    
    # 清空
    _save_json(MAIN_RECORDS_FILE, [])
    _save_json(MERGE_LOG_FILE, [])
    _save_json(PENDING_FILE, [])
    
    return {
        "ok": True,
        "message": "合并数据已清空，备份保存在: " + backup_dir,
        "backup_dir": backup_dir,
    }
