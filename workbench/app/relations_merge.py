"""
v0.1.63：多电脑并库时设备关系合并

多台电脑解析的设备关系图谱合并到一个完整库，支持自动去重、关系冲突处理、
设备属性冲突处理、车间冲突处理、合并日志记录、合并后关系完整性检查。
"""

import os
import json
import datetime
from typing import Optional


_MERGE_LOG_FILE = os.path.join("data", "relations_merge_log.json")
_MERGE_PENDING_FILE = os.path.join("data", "relations_merge_pending.json")


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


def load_relations_from_file(filepath: str) -> dict:
    """从JSON文件加载关系图谱。
    
    Args:
        filepath: 关系图谱JSON文件路径
    
    Returns:
        关系图谱字典
    """
    if not os.path.exists(filepath):
        return {"error": "文件不存在", "path": filepath}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"加载失败: {str(e)}", "path": filepath}


def merge_relations(source_relations: dict, node_name: str = "unknown",
                    conflict_strategy: str = "latest") -> dict:
    """合并源关系图谱到本地关系图谱。
    
    Args:
        source_relations: 源关系图谱字典
        node_name: 来源节点名称
        conflict_strategy: 冲突处理策略
            - "latest": 以最新版为准（默认）
            - "keep_existing": 保留现有
            - "manual": 冲突留待人工确认
    
    Returns:
        合并结果
    """
    from . import relations as _rel
    
    _ensure_dirs()
    
    if "error" in source_relations:
        return source_relations
    
    # 加载当前关系图谱
    current = _rel.load_relations()
    
    source_devices = source_relations.get("devices", [])
    current_devices = current.get("devices", [])
    
    # 统计
    merged_devices = 0
    skipped_duplicate = 0
    conflicts = 0
    pending_conflicts = []
    merged_relations = 0
    
    # 构建设备索引
    current_index = {d["tag"]: d for d in current_devices}
    
    # 合并设备
    for sd in source_devices:
        tag = sd["tag"]
        
        if tag in current_index:
            # 设备已存在，检查冲突
            cd = current_index[tag]
            has_conflict = False
            conflict_details = {}
            
            # 检查车间冲突
            source_workshops = sd.get("workshops", [])
            current_workshops = cd.get("workshops", [])
            if source_workshops != current_workshops:
                has_conflict = True
                conflict_details["workshops"] = {
                    "source": source_workshops,
                    "current": current_workshops,
                }
            
            # 检查来源冲突
            source_sources = sd.get("sources", {})
            current_sources = cd.get("sources", {})
            if source_sources != current_sources:
                # 合并来源（取并集，计数相加）
                merged_sources = dict(current_sources)
                for k, v in source_sources.items():
                    merged_sources[k] = merged_sources.get(k, 0) + v
                sd["sources"] = merged_sources
            
            # 检查坐标冲突
            source_positions = sd.get("cad_positions", [])
            current_positions = cd.get("cad_positions", [])
            if source_positions and current_positions:
                # 合并坐标（去重）
                merged_positions = list(current_positions)
                for sp in source_positions:
                    if sp not in merged_positions:
                        merged_positions.append(sp)
                sd["cad_positions"] = merged_positions
            elif source_positions:
                sd["cad_positions"] = source_positions
            
            # 检查文件冲突
            source_files = sd.get("files", [])
            current_files = cd.get("files", [])
            merged_files = list(current_files)
            for sf in source_files:
                if sf not in merged_files:
                    merged_files.append(sf)
            sd["files"] = merged_files
            
            if has_conflict:
                conflicts += 1
                if conflict_strategy == "latest":
                    # 用源设备覆盖现有（保留合并的sources/files/positions）
                    current_index[tag] = sd
                    merged_devices += 1
                elif conflict_strategy == "keep_existing":
                    skipped_duplicate += 1
                elif conflict_strategy == "manual":
                    pending_conflicts.append({
                        "device_tag": tag,
                        "conflict_type": "device_attribute",
                        "details": conflict_details,
                        "source_device": sd,
                        "current_device": cd,
                        "node": node_name,
                        "status": "pending",
                    })
            else:
                # 无冲突，合并属性
                skipped_duplicate += 1
                # 更新来源和文件
                current_index[tag]["sources"] = sd.get("sources", current_sources)
                current_index[tag]["files"] = sd.get("files", current_files)
        else:
            # 新设备，直接添加
            current_index[tag] = sd
            merged_devices += 1
    
    # 合并 human_confirm（候选设备人工确认列表）
    source_human = source_relations.get("human_confirm", [])
    current_human = current.get("human_confirm", [])
    human_index = set()
    for h in current_human:
        key = h.get("tag", "") + str(h.get("name", ""))
        human_index.add(key)
    for h in source_human:
        key = h.get("tag", "") + str(h.get("name", ""))
        if key not in human_index:
            current_human.append(h)
            human_index.add(key)
            merged_relations += 1
    
    # 合并 drawings（图纸列表）
    source_drawings = source_relations.get("drawings", [])
    current_drawings = current.get("drawings", [])
    for d in source_drawings:
        if d not in current_drawings:
            current_drawings.append(d)
    
    # 构建合并后的关系图谱（保持原有结构）
    merged_graph = {
        "stats": current.get("stats", {}),
        "devices": list(current_index.values()),
        "human_confirm": current_human,
        "workshops": list(set(current.get("workshops", []) + source_relations.get("workshops", []))),
        "drawings": current_drawings,
        "metadata": {
            "merged_at": datetime.datetime.now().isoformat(),
            "merged_from": node_name,
            "merge_strategy": conflict_strategy,
        },
    }
    
    # 保存合并后的关系图谱
    _rel.save_relations(merged_graph)
    
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
        "source_human_confirm": len(source_relations.get("human_confirm", [])),
        "merged_devices": merged_devices,
        "skipped_duplicate": skipped_duplicate,
        "conflicts": conflicts,
        "merged_relations": merged_relations,
        "total_devices_after": len(merged_graph["devices"]),
        "total_human_confirm_after": len(merged_graph["human_confirm"]),
    }
    merge_log = _load_merge_log()
    merge_log.append(log_entry)
    _save_merge_log(merge_log[-100:])
    
    return {
        "ok": True,
        "log": log_entry,
        "pending_count": len(_load_pending()),
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
        current = _rel.load_relations()
        current_index = {d["tag"]: d for d in current.get("devices", [])}
        tag = item["device_tag"]
        if tag in current_index and "source_device" in item:
            current_index[tag] = item["source_device"]
            current["devices"] = list(current_index.values())
            _rel.save_relations(current)
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
    total_relations_merged = sum(entry.get("merged_relations", 0) for entry in log)
    
    # 当前关系图谱统计
    from . import relations as _rel
    current = _rel.load_relations()
    
    return {
        "total_merge_operations": len(log),
        "total_devices_merged": total_merged,
        "total_devices_skipped": total_skipped,
        "total_conflicts": total_conflicts,
        "total_relations_merged": total_relations_merged,
        "pending_conflicts": len([p for p in pending if p.get("status") == "pending"]),
        "resolved_conflicts": len([p for p in pending if p.get("status") == "resolved"]),
        "current_total_devices": len(current.get("devices", [])),
        "current_total_human_confirm": len(current.get("human_confirm", [])),
        "current_workshops": len(current.get("workshops", [])),
        "last_merge": log[-1] if log else None,
    }


def check_relations_integrity() -> dict:
    """检查合并后关系图谱的完整性。
    
    Returns:
        完整性检查结果
    """
    from . import relations as _rel
    current = _rel.load_relations()
    
    devices = current.get("devices", [])
    device_tags = {d["tag"] for d in devices}
    
    issues = []
    
    # 检查 human_confirm 中的设备是否已确认
    human_confirm = current.get("human_confirm", [])
    pending_human = [h for h in human_confirm if h.get("status") != "confirmed"]
    if pending_human:
        issues.append({"type": "pending_human_confirm", "count": len(pending_human)})
    
    # 检查设备是否有关联文件
    devices_without_files = [d["tag"] for d in devices if not d.get("files")]
    if devices_without_files:
        issues.append({"type": "devices_without_files", "devices": devices_without_files})
    
    # 检查设备是否有车间
    devices_without_workshop = [d["tag"] for d in devices if not d.get("workshops")]
    if devices_without_workshop:
        issues.append({"type": "devices_without_workshop", "devices": devices_without_workshop})
    
    # 检查孤立设备（没有关联文件和车间）
    isolated_devices = [d["tag"] for d in devices if not d.get("files") and not d.get("workshops")]
    if isolated_devices:
        issues.append({"type": "isolated_devices", "devices": isolated_devices})
    
    return {
        "ok": True,
        "total_devices": len(devices),
        "total_human_confirm": len(human_confirm),
        "issues_count": len(issues),
        "issues": issues[:20],  # 最多返回20个问题
        "devices_without_files": len(devices_without_files),
        "devices_without_workshop": len(devices_without_workshop),
        "isolated_devices": len(isolated_devices),
        "pending_human_confirm": len(pending_human),
    }
