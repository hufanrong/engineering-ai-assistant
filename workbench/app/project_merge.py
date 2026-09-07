"""
v0.1.110：项目间设备数据对比与合并

支持选择两个项目，对比设备列表，显示相同设备、不同设备、冲突设备，
并支持将一个项目的设备数据合并到另一个项目。
"""

import os
import json
import datetime
from typing import Optional, Dict, List, Tuple


def _load_project_devices(project_id: str) -> Tuple[Dict, Dict]:
    """
    加载项目的设备数据和索引。
    
    Returns:
        (devices_dict, index_dict)
    """
    from . import project_manager as _pm
    
    project_dir = _pm.get_project_data_dir(project_id)
    idx_path = os.path.join(project_dir, "index.json")
    
    devices = {}
    idx = {}
    
    if os.path.isfile(idx_path):
        try:
            with open(idx_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
            devices = idx.get("devices", {})
        except Exception:
            pass
    
    return devices, idx


def _normalize_device_name(name: str) -> str:
    """标准化设备名称用于对比。"""
    if not name:
        return ""
    # 去除空格、特殊字符，转小写
    import re
    normalized = re.sub(r'[\s_\-（）()【】\[\]]', '', name).lower()
    return normalized


def compare_projects(project_a_id: str, project_b_id: str) -> Dict:
    """
    对比两个项目的设备数据。
    
    Args:
        project_a_id: 项目A ID
        project_b_id: 项目B ID
    
    Returns:
        对比结果
    """
    from . import project_manager as _pm
    
    project_a = _pm.get_project(project_a_id)
    project_b = _pm.get_project(project_b_id)
    
    if not project_a:
        return {"ok": False, "error": f"项目A不存在：{project_a_id}"}
    if not project_b:
        return {"ok": False, "error": f"项目B不存在：{project_b_id}"}
    
    devices_a, idx_a = _load_project_devices(project_a_id)
    devices_b, idx_b = _load_project_devices(project_b_id)
    
    # 构建设备名称到位号的映射
    name_to_tag_a = {}
    for tag, dev in devices_a.items():
        name = dev.get("name", tag)
        normalized = _normalize_device_name(name)
        if normalized:
            name_to_tag_a[normalized] = tag
    
    name_to_tag_b = {}
    for tag, dev in devices_b.items():
        name = dev.get("name", tag)
        normalized = _normalize_device_name(name)
        if normalized:
            name_to_tag_b[normalized] = tag
    
    # 分类
    same_devices = []      # 两个项目都有的设备
    only_in_a = []         # 仅在项目A的设备
    only_in_b = []         # 仅在项目B的设备
    conflicts = []         # 同名但数据冲突的设备
    
    # 检查项目A的设备
    for tag, dev in devices_a.items():
        name = dev.get("name", tag)
        normalized = _normalize_device_name(name)
        
        if normalized in name_to_tag_b:
            # 两个项目都有
            tag_b = name_to_tag_b[normalized]
            dev_b = devices_b[tag_b]
            
            # 检查数据是否冲突
            conflict_fields = _compare_device_data(dev, dev_b)
            
            same_info = {
                "name": name,
                "tag_a": tag,
                "tag_b": tag_b,
                "workshop_a": dev.get("workshop", ""),
                "workshop_b": dev_b.get("workshop", ""),
                "manufacturer_a": dev.get("manufacturer", ""),
                "manufacturer_b": dev_b.get("manufacturer", ""),
            }
            
            if conflict_fields:
                same_info["conflict_fields"] = conflict_fields
                conflicts.append(same_info)
            else:
                same_devices.append(same_info)
        else:
            only_in_a.append({
                "name": name,
                "tag": tag,
                "workshop": dev.get("workshop", ""),
                "manufacturer": dev.get("manufacturer", ""),
            })
    
    # 检查项目B中独有的设备
    for tag, dev in devices_b.items():
        name = dev.get("name", tag)
        normalized = _normalize_device_name(name)
        if normalized not in name_to_tag_a:
            only_in_b.append({
                "name": name,
                "tag": tag,
                "workshop": dev.get("workshop", ""),
                "manufacturer": dev.get("manufacturer", ""),
            })
    
    return {
        "ok": True,
        "project_a": {"id": project_a_id, "name": project_a["name"], "device_count": len(devices_a)},
        "project_b": {"id": project_b_id, "name": project_b["name"], "device_count": len(devices_b)},
        "summary": {
            "same_count": len(same_devices),
            "conflict_count": len(conflicts),
            "only_in_a_count": len(only_in_a),
            "only_in_b_count": len(only_in_b),
        },
        "same_devices": same_devices,
        "conflicts": conflicts,
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
    }


def _compare_device_data(dev_a: Dict, dev_b: Dict) -> List[Dict]:
    """对比两个设备的数据，返回冲突字段。"""
    conflict_fields = []
    compare_keys = ["workshop", "manufacturer", "model", "location", "elevation", "status"]
    
    for key in compare_keys:
        val_a = dev_a.get(key, "")
        val_b = dev_b.get(key, "")
        if val_a and val_b and str(val_a).strip() != str(val_b).strip():
            conflict_fields.append({
                "field": key,
                "value_a": val_a,
                "value_b": val_b,
            })
    
    return conflict_fields


def merge_devices(source_project_id: str, target_project_id: str,
                  device_tags: List[str] = None, conflict_strategy: str = "manual") -> Dict:
    """
    将源项目的设备数据合并到目标项目。
    
    Args:
        source_project_id: 源项目ID
        target_project_id: 目标项目ID
        device_tags: 要合并的设备位号列表，为None时合并所有
        conflict_strategy: 冲突处理策略
            - "source": 以源项目为准
            - "target": 以目标项目为准
            - "manual": 冲突设备留待人工确认（默认）
    
    Returns:
        合并结果
    """
    from . import project_manager as _pm
    
    source = _pm.get_project(source_project_id)
    target = _pm.get_project(target_project_id)
    
    if not source:
        return {"ok": False, "error": f"源项目不存在：{source_project_id}"}
    if not target:
        return {"ok": False, "error": f"目标项目不存在：{target_project_id}"}
    if source_project_id == target_project_id:
        return {"ok": False, "error": "源项目和目标项目不能相同"}
    
    devices_source, idx_source = _load_project_devices(source_project_id)
    devices_target, idx_target = _load_project_devices(target_project_id)
    
    # 确定要合并的设备
    if device_tags:
        to_merge = {tag: dev for tag, dev in devices_source.items() if tag in device_tags}
    else:
        to_merge = devices_source
    
    merged_count = 0
    skipped_count = 0
    conflict_count = 0
    pending_manual = []
    
    # 构建目标项目设备名称映射
    name_to_tag_target = {}
    for tag, dev in devices_target.items():
        name = dev.get("name", tag)
        normalized = _normalize_device_name(name)
        if normalized:
            name_to_tag_target[normalized] = tag
    
    for tag, dev in to_merge.items():
        name = dev.get("name", tag)
        normalized = _normalize_device_name(name)
        
        if normalized in name_to_tag_target:
            # 目标项目已有同名设备
            target_tag = name_to_tag_target[normalized]
            target_dev = devices_target[target_tag]
            conflict_fields = _compare_device_data(dev, target_dev)
            
            if conflict_fields:
                conflict_count += 1
                if conflict_strategy == "source":
                    # 以源为准，覆盖
                    for field in conflict_fields:
                        target_dev[field["field"]] = field["value_a"]
                    merged_count += 1
                elif conflict_strategy == "target":
                    # 以目标为准，跳过
                    skipped_count += 1
                else:
                    # manual: 留待人工确认
                    pending_manual.append({
                        "name": name,
                        "source_tag": tag,
                        "target_tag": target_tag,
                        "conflict_fields": conflict_fields,
                    })
            else:
                # 无冲突，合并补充字段
                for key, val in dev.items():
                    if key not in target_dev or not target_dev[key]:
                        target_dev[key] = val
                merged_count += 1
        else:
            # 目标项目没有此设备，直接添加
            # 生成新的位号（避免冲突）
            new_tag = tag
            if new_tag in devices_target:
                new_tag = f"{tag}_m"
            devices_target[new_tag] = dict(dev)
            merged_count += 1
    
    # 保存目标项目索引
    target_dir = _pm.get_project_data_dir(target_project_id)
    idx_target["devices"] = devices_target
    
    idx_path = os.path.join(target_dir, "index.json")
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(idx_target, f, ensure_ascii=False, indent=2)
    
    # 更新项目统计
    _pm.update_project_stats(
        target_project_id,
        file_count=len(idx_target.get("files", [])) if isinstance(idx_target.get("files"), list) else len(idx_target),
        device_count=len(devices_target),
        workshop_count=len(idx_target.get("workshops", {})),
    )
    
    return {
        "ok": True,
        "source_project": source["name"],
        "target_project": target["name"],
        "merged_count": merged_count,
        "skipped_count": skipped_count,
        "conflict_count": conflict_count,
        "pending_manual_count": len(pending_manual),
        "pending_manual": pending_manual,
        "conflict_strategy": conflict_strategy,
        "message": f"已从「{source['name']}」合并 {merged_count} 个设备到「{target['name']}」" +
                   (f"，{len(pending_manual)} 个冲突设备待人工确认" if pending_manual else ""),
    }


def resolve_manual_conflict(target_project_id: str, device_name: str,
                             choose: str = "source", source_project_id: str = None) -> Dict:
    """
    人工确认解决冲突。
    
    Args:
        target_project_id: 目标项目ID
        device_name: 设备名称
        choose: "source" 以源为准，"target" 以目标为准
        source_project_id: 源项目ID（choose=source时需要）
    
    Returns:
        处理结果
    """
    from . import project_manager as _pm
    
    devices_target, idx_target = _load_project_devices(target_project_id)
    
    # 查找目标设备
    target_tag = None
    for tag, dev in devices_target.items():
        if dev.get("name", "") == device_name or tag == device_name:
            target_tag = tag
            break
    
    if not target_tag:
        return {"ok": False, "error": f"目标项目中未找到设备：{device_name}"}
    
    if choose == "source" and source_project_id:
        devices_source, _ = _load_project_devices(source_project_id)
        source_tag = None
        for tag, dev in devices_source.items():
            if dev.get("name", "") == device_name:
                source_tag = tag
                break
        if source_tag:
            devices_target[target_tag] = dict(devices_source[source_tag])
            message = f"设备「{device_name}」已以源项目数据为准"
        else:
            return {"ok": False, "error": f"源项目中未找到设备：{device_name}"}
    else:
        message = f"设备「{device_name}」已保留目标项目数据"
    
    # 保存
    target_dir = _pm.get_project_data_dir(target_project_id)
    idx_target["devices"] = devices_target
    idx_path = os.path.join(target_dir, "index.json")
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(idx_target, f, ensure_ascii=False, indent=2)
    
    return {"ok": True, "message": message}
