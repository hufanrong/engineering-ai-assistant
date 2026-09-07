"""
v0.1.87：多电脑并库时矿山设备数据合并

专门针对矿山设备特点的多电脑并库合并：
- 基于矿山设备知识库的设备类型识别
- 设计院编号与厂家编号映射合并
- 跨车间设备合并
- 设备空间位置合并
- 设备状态合并
- 自动去重（位号精确匹配 > 设计院编号匹配 > 厂家编号匹配 > 名称+型号相似）
- 三种冲突策略（latest/keep_existing/manual）
- 合并日志
- 待人工确认
- 完整性检查
"""

import os
import json
import datetime
import hashlib
from typing import Optional


_MERGE_LOG_FILE = os.path.join("data", "mining_equipment_merge_log.json")
_PENDING_FILE = os.path.join("data", "mining_equipment_merge_pending.json")


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
    # 保留最近100条
    log = log[-100:]
    with open(_MERGE_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def _add_merge_log(action: str, details: dict, source_node: str = "unknown"):
    log = _load_merge_log()
    log.append({
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "source_node": source_node,
        "details": details,
    })
    _save_merge_log(log)


def _load_pending() -> list:
    if os.path.exists(_PENDING_FILE):
        try:
            with open(_PENDING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_pending(pending: list):
    _ensure_dirs()
    with open(_PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)


def _calculate_device_md5(device: dict) -> str:
    """计算设备数据的MD5用于去重。"""
    # 只比较关键字段
    key_fields = {
        "tag": device.get("tag", ""),
        "name": device.get("name", ""),
        "type": device.get("type", ""),
        "model": device.get("model", ""),
        "workshop": device.get("workshop", ""),
        "x": device.get("x"),
        "y": device.get("y"),
        "z": device.get("z"),
        "elevation": device.get("elevation"),
        "status": device.get("status", ""),
        "design_tag": device.get("design_tag", ""),
        "vendor_tag": device.get("vendor_tag", ""),
    }
    content = json.dumps(key_fields, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def _match_devices(dev1: dict, dev2: dict) -> tuple:
    """
    匹配两台设备，返回 (match_level, confidence)。
    
    match_level:
    - exact: 位号精确匹配
    - design_tag: 设计院编号匹配
    - vendor_tag: 厂家编号匹配
    - name_model: 名称+型号相似
    - name_similar: 名称高度相似（候选）
    - none: 不匹配
    """
    tag1 = dev1.get("tag", "").strip().upper()
    tag2 = dev2.get("tag", "").strip().upper()
    
    # 1. 位号精确匹配
    if tag1 and tag1 == tag2:
        return ("exact", 0.95)
    
    # 2. 设计院编号匹配
    design1 = dev1.get("design_tag", "").strip().upper()
    design2 = dev2.get("design_tag", "").strip().upper()
    if design1 and design1 == design2:
        return ("design_tag", 0.90)
    
    # 3. 厂家编号匹配
    vendor1 = dev1.get("vendor_tag", "").strip().upper()
    vendor2 = dev2.get("vendor_tag", "").strip().upper()
    if vendor1 and vendor1 == vendor2:
        return ("vendor_tag", 0.85)
    
    # 4. 位号与设计院/厂家编号交叉匹配
    if tag1 and (tag1 == design2 or tag1 == vendor2):
        return ("cross_match", 0.80)
    if tag2 and (tag2 == design1 or tag2 == vendor1):
        return ("cross_match", 0.80)
    
    # 5. 名称+型号相似
    name1 = dev1.get("name", "").strip()
    name2 = dev2.get("name", "").strip()
    model1 = dev1.get("model", "").strip().upper()
    model2 = dev2.get("model", "").strip().upper()
    
    if name1 and name2 and model1 and model1 == model2:
        # 名称相似性简单判断
        if name1 == name2:
            return ("name_model", 0.75)
        # 名称包含关系
        if name1 in name2 or name2 in name1:
            return ("name_model", 0.70)
    
    # 6. 名称高度相似（候选，需人工确认）
    if name1 and name2:
        # 简单的相似性判断
        shorter = min(name1, name2, key=len)
        longer = max(name1, name2, key=len)
        if shorter and shorter in longer:
            return ("name_similar", 0.55)
    
    return ("none", 0.0)


def _merge_device_fields(existing: dict, incoming: dict, strategy: str = "latest") -> dict:
    """
    合并两台设备的字段。
    
    strategy:
    - latest: 以最新版为准（incoming覆盖existing）
    - keep_existing: 保留现有版本（existing覆盖incoming）
    - manual: 冲突字段留待人工确认
    """
    merged = existing.copy()
    
    # 需要合并的字段
    fields_to_merge = [
        "name", "type", "model", "manufacturer", "workshop",
        "x", "y", "z", "elevation", "status", "weight",
        "design_tag", "vendor_tag", "sources", "notes",
    ]
    
    conflict_fields = []
    
    for field in fields_to_merge:
        existing_val = existing.get(field)
        incoming_val = incoming.get(field)
        
        if incoming_val is None or incoming_val == "":
            continue
        
        if existing_val is None or existing_val == "":
            merged[field] = incoming_val
            continue
        
        # 字段有冲突
        if existing_val != incoming_val:
            if strategy == "latest":
                merged[field] = incoming_val
            elif strategy == "keep_existing":
                pass  # 保留existing
            elif strategy == "manual":
                conflict_fields.append({
                    "field": field,
                    "existing_value": existing_val,
                    "incoming_value": incoming_val,
                })
                # manual策略下保留existing，但记录冲突
            else:
                merged[field] = incoming_val
    
    # 合并sources（取并集）
    existing_sources = existing.get("sources", {})
    incoming_sources = incoming.get("sources", {})
    merged_sources = {}
    for key in set(list(existing_sources.keys()) + list(incoming_sources.keys())):
        merged_sources[key] = max(
            existing_sources.get(key, 0),
            incoming_sources.get(key, 0)
        )
    merged["sources"] = merged_sources
    
    # 更新时间
    merged["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    merged["merge_source"] = incoming.get("source_node", "unknown")
    
    if conflict_fields:
        merged["conflict_fields"] = conflict_fields
    
    return merged


def merge_mining_equipment(
    existing_devices: list,
    incoming_devices: list,
    strategy: str = "latest",
    source_node: str = "unknown",
    auto_confirm_threshold: float = 0.75,
) -> dict:
    """
    合并矿山设备数据。
    
    Args:
        existing_devices: 现有设备列表
        incoming_devices: 待合并设备列表
        strategy: 冲突策略 latest/keep_existing/manual
        source_node: 来源节点名称
        auto_confirm_threshold: 自动确认阈值（置信度≥此值自动合并）
    
    Returns:
        合并结果
    """
    merged_devices = existing_devices.copy()
    pending_confirmation = []
    merge_stats = {
        "total_incoming": len(incoming_devices),
        "exact_match": 0,
        "design_tag_match": 0,
        "vendor_tag_match": 0,
        "cross_match": 0,
        "name_model_match": 0,
        "name_similar_candidate": 0,
        "new_devices": 0,
        "auto_merged": 0,
        "pending_confirmation": 0,
        "conflicts": 0,
    }
    
    # 计算现有设备的MD5用于去重
    existing_md5s = {}
    for i, dev in enumerate(merged_devices):
        md5 = _calculate_device_md5(dev)
        existing_md5s[md5] = i
    
    for incoming in incoming_devices:
        incoming_md5 = _calculate_device_md5(incoming)
        
        # 1. 完全相同的设备，跳过
        if incoming_md5 in existing_md5s:
            continue
        
        # 2. 查找匹配的设备
        best_match = None
        best_match_level = "none"
        best_confidence = 0.0
        best_index = -1
        
        for i, existing in enumerate(merged_devices):
            match_level, confidence = _match_devices(existing, incoming)
            if confidence > best_confidence:
                best_match = existing
                best_match_level = match_level
                best_confidence = confidence
                best_index = i
        
        # 3. 根据匹配置信度处理
        if best_match_level == "none":
            # 新设备
            incoming["source_node"] = source_node
            incoming["added_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            merged_devices.append(incoming)
            merge_stats["new_devices"] += 1
            _add_merge_log("new_device", {"tag": incoming.get("tag"), "name": incoming.get("name")}, source_node)
        
        elif best_confidence >= auto_confirm_threshold:
            # 高置信度匹配，自动合并
            merged = _merge_device_fields(best_match, incoming, strategy)
            merged_devices[best_index] = merged
            merge_stats["auto_merged"] += 1
            merge_stats[best_match_level + "_match"] = merge_stats.get(best_match_level + "_match", 0) + 1
            
            if merged.get("conflict_fields"):
                merge_stats["conflicts"] += len(merged["conflict_fields"])
            
            _add_merge_log("auto_merge", {
                "tag": incoming.get("tag"),
                "match_level": best_match_level,
                "confidence": best_confidence,
                "strategy": strategy,
            }, source_node)
        
        else:
            # 低置信度匹配，待人工确认
            pending_item = {
                "id": hashlib.md5((incoming.get("tag", "") + datetime.datetime.now().isoformat()).encode()).hexdigest()[:12],
                "incoming_device": incoming,
                "matched_device": best_match,
                "match_level": best_match_level,
                "confidence": best_confidence,
                "source_node": source_node,
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "pending",
            }
            pending_confirmation.append(pending_item)
            merge_stats["pending_confirmation"] += 1
            merge_stats[best_match_level + "_match"] = merge_stats.get(best_match_level + "_match", 0) + 1
            
            _add_merge_log("pending_confirmation", {
                "tag": incoming.get("tag"),
                "match_level": best_match_level,
                "confidence": best_confidence,
            }, source_node)
    
    # 保存待确认列表
    if pending_confirmation:
        existing_pending = _load_pending()
        existing_pending.extend(pending_confirmation)
        _save_pending(existing_pending)
    
    result = {
        "ok": True,
        "merged_devices": merged_devices,
        "pending_count": len(pending_confirmation),
        "stats": merge_stats,
        "merged_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_node": source_node,
        "strategy": strategy,
    }
    
    _add_merge_log("merge_complete", merge_stats, source_node)
    
    return result


def merge_mining_equipment_file(
    file_path: str,
    strategy: str = "latest",
    source_node: str = "unknown",
) -> dict:
    """
    从文件合并矿山设备数据。
    
    文件格式：JSON，包含 devices 列表
    """
    if not os.path.exists(file_path):
        return {"ok": False, "error": f"文件不存在: {file_path}"}
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"ok": False, "error": f"文件解析失败: {str(e)}"}
    
    incoming_devices = data.get("devices", [])
    if not incoming_devices:
        return {"ok": False, "error": "文件中没有设备数据"}
    
    # 从relations中获取现有设备
    try:
        from . import relations as _rel
        g = _rel.load_relations()
        existing_devices = []
        for tag, dev in g.get("devices", {}).items():
            dev_dict = dev.copy()
            dev_dict["tag"] = tag
            existing_devices.append(dev_dict)
    except Exception:
        existing_devices = []
    
    return merge_mining_equipment(existing_devices, incoming_devices, strategy, source_node)


def list_pending() -> list:
    """列出待人工确认的合并项。"""
    return _load_pending()


def resolve_pending(
    pending_id: str,
    action: str,
    strategy: str = "latest",
) -> dict:
    """
    处理待人工确认的合并项。
    
    action:
    - confirm: 确认合并
    - reject: 拒绝合并（作为新设备）
    - keep_existing: 保留现有设备，忽略新设备
    """
    pending = _load_pending()
    item = None
    item_index = -1
    
    for i, p in enumerate(pending):
        if p.get("id") == pending_id:
            item = p
            item_index = i
            break
    
    if not item:
        return {"ok": False, "error": f"未找到待确认项: {pending_id}"}
    
    if action == "confirm":
        # 确认合并
        incoming = item["incoming_device"]
        matched = item["matched_device"]
        merged = _merge_device_fields(matched, incoming, strategy)
        
        # 更新relations中的设备
        try:
            from . import relations as _rel
            g = _rel.load_relations()
            tag = matched.get("tag", "")
            if tag in g.get("devices", {}):
                for key, val in merged.items():
                    if key != "tag":
                        g["devices"][tag][key] = val
                _rel.save_relations(g)
        except Exception:
            pass
        
        pending.pop(item_index)
        _save_pending(pending)
        _add_merge_log("confirm_merge", {"id": pending_id, "tag": incoming.get("tag")}, item.get("source_node", "unknown"))
        
        return {"ok": True, "action": "confirm", "merged_device": merged}
    
    elif action == "reject":
        # 拒绝合并，作为新设备
        incoming = item["incoming_device"]
        try:
            from . import relations as _rel
            g = _rel.load_relations()
            tag = incoming.get("tag", "")
            if tag and tag not in g.get("devices", {}):
                g["devices"][tag] = incoming
                _rel.save_relations(g)
        except Exception:
            pass
        
        pending.pop(item_index)
        _save_pending(pending)
        _add_merge_log("reject_merge_as_new", {"id": pending_id, "tag": incoming.get("tag")}, item.get("source_node", "unknown"))
        
        return {"ok": True, "action": "reject", "new_device": incoming}
    
    elif action == "keep_existing":
        # 保留现有设备，忽略新设备
        pending.pop(item_index)
        _save_pending(pending)
        _add_merge_log("keep_existing_ignore", {"id": pending_id}, item.get("source_node", "unknown"))
        
        return {"ok": True, "action": "keep_existing"}
    
    else:
        return {"ok": False, "error": f"未知操作: {action}"}


def get_merge_log(limit: int = 50) -> list:
    """获取合并日志。"""
    log = _load_merge_log()
    return log[-limit:]


def get_merge_stats() -> dict:
    """获取合并统计。"""
    log = _load_merge_log()
    pending = _load_pending()
    
    stats = {
        "total_merges": 0,
        "new_devices": 0,
        "auto_merged": 0,
        "pending_confirmation": len(pending),
        "total_conflicts": 0,
        "source_nodes": set(),
    }
    
    for entry in log:
        action = entry.get("action", "")
        details = entry.get("details", {})
        
        if action == "merge_complete":
            stats["total_merges"] += 1
            stats["new_devices"] += details.get("new_devices", 0)
            stats["auto_merged"] += details.get("auto_merged", 0)
            stats["total_conflicts"] += details.get("conflicts", 0)
        
        if entry.get("source_node"):
            stats["source_nodes"].add(entry["source_node"])
    
    stats["source_nodes"] = list(stats["source_nodes"])
    
    return stats


def check_mining_equipment_integrity(devices: list = None) -> dict:
    """
    检查矿山设备数据完整性。
    
    检查项：
    - 设备位号是否唯一
    - 设备类型是否在矿山设备知识库中
    - 设备空间位置是否完整
    - 设备车间是否分配
    - 设计院编号与厂家编号是否冲突
    """
    if devices is None:
        try:
            from . import relations as _rel
            g = _rel.load_relations()
            devices = []
            for tag, dev in g.get("devices", {}).items():
                dev_dict = dev.copy()
                dev_dict["tag"] = tag
                devices.append(dev_dict)
        except Exception:
            devices = []
    
    # 加载矿山设备知识库
    try:
        from . import mining_equipment as _me
        all_types = set(_me.ALL_MINING_EQUIPMENT)
    except Exception:
        all_types = set()
    
    issues = []
    tags_seen = {}
    design_tags_seen = {}
    vendor_tags_seen = {}
    
    for dev in devices:
        tag = dev.get("tag", "")
        dev_type = dev.get("type", "")
        workshop = dev.get("workshop", "")
        x = dev.get("x")
        y = dev.get("y")
        z = dev.get("z")
        elevation = dev.get("elevation")
        design_tag = dev.get("design_tag", "")
        vendor_tag = dev.get("vendor_tag", "")
        
        # 1. 位号唯一性
        if tag:
            if tag in tags_seen:
                issues.append({
                    "severity": "high",
                    "type": "duplicate_tag",
                    "tag": tag,
                    "message": f"设备位号重复: {tag}",
                })
            tags_seen[tag] = True
        
        # 2. 设备类型检查
        if dev_type and all_types and dev_type not in all_types:
            issues.append({
                "severity": "medium",
                "type": "unknown_type",
                "tag": tag,
                "type": dev_type,
                "message": f"设备类型不在矿山设备知识库中: {dev_type}",
            })
        
        # 3. 空间位置完整性
        if x is None or y is None:
            issues.append({
                "severity": "low",
                "type": "missing_position",
                "tag": tag,
                "message": f"设备缺少空间坐标(x,y): {tag}",
            })
        
        # 4. 车间分配
        if not workshop:
            issues.append({
                "severity": "medium",
                "type": "missing_workshop",
                "tag": tag,
                "message": f"设备未分配车间: {tag}",
            })
        
        # 5. 设计院编号冲突
        if design_tag:
            if design_tag in design_tags_seen:
                issues.append({
                    "severity": "high",
                    "type": "duplicate_design_tag",
                    "tag": tag,
                    "design_tag": design_tag,
                    "message": f"设计院编号重复: {design_tag}",
                })
            design_tags_seen[design_tag] = tag
        
        # 6. 厂家编号冲突
        if vendor_tag:
            if vendor_tag in vendor_tags_seen:
                issues.append({
                    "severity": "medium",
                    "type": "duplicate_vendor_tag",
                    "tag": tag,
                    "vendor_tag": vendor_tag,
                    "message": f"厂家编号重复: {vendor_tag}",
                })
            vendor_tags_seen[vendor_tag] = tag
    
    # 按严重程度排序
    severity_order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 3))
    
    result = {
        "ok": True,
        "total_devices": len(devices),
        "total_issues": len(issues),
        "high_severity": len([i for i in issues if i["severity"] == "high"]),
        "medium_severity": len([i for i in issues if i["severity"] == "medium"]),
        "low_severity": len([i for i in issues if i["severity"] == "low"]),
        "issues": issues[:50],  # 最多显示50个
        "checked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    return result
