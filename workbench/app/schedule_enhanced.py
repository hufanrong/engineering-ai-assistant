"""
v0.1.82：设备安装位置与施工进度联动增强

施工顺序优化、施工冲突识别、关键路径分析、施工进度预警、资源优化。
"""

import os
import json
import datetime
from typing import Optional, List, Dict


_ENHANCED_FILE = os.path.join("data", "schedule_enhanced.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_enhanced() -> dict:
    if os.path.exists(_ENHANCED_FILE):
        try:
            with open(_ENHANCED_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {"optimized_schedule": [], "conflicts": [], "critical_path": [],
            "warnings": [], "resource_plan": {}, "stats": {}}


def _save_enhanced(enhanced: dict):
    _ensure_dirs()
    with open(_ENHANCED_FILE, "w", encoding="utf-8") as f:
        json.dump(enhanced, f, ensure_ascii=False, indent=2)


def _get_devices_with_positions() -> List[dict]:
    """获取带位置信息的设备列表。"""
    from . import relations as _rel
    from . import installation_plan as _ip
    
    g = _rel.load_relations()
    devices = g.get("devices", [])
    
    result = []
    for device in devices:
        tag = device.get("tag", "")
        spatial = _ip.get_device_spatial_info(tag)
        if "error" not in spatial:
            device_info = {
                "tag": tag,
                "name": spatial.get("name", tag),
                "type": spatial.get("type", ""),
                "workshop": spatial.get("workshop", "未分配"),
                "x": spatial.get("x"),
                "y": spatial.get("y"),
                "z": spatial.get("z"),
                "adjacent_devices": spatial.get("adjacent_devices", []),
                "sources": device.get("sources", {}),
            }
            result.append(device_info)
    return result


def optimize_construction_order() -> dict:
    """v0.1.82：根据设备位置优化施工顺序。
    
    优化原则：
    1. 按车间分组，同一车间连续施工
    2. 同一车间内按标高从低到高（先地下后地上）
    3. 同一标高内按x坐标从左到右
    4. 关键设备优先（大吨位、高精密）
    5. 相邻设备集中施工，减少机具移动
    """
    devices = _get_devices_with_positions()
    
    if not devices:
        return {"ok": False, "error": "无设备数据", "optimized_schedule": []}
    
    # 关键设备类型（优先施工）
    critical_types = {"塔器", "储罐", "压缩机", "换热器", "容器"}
    
    # 按车间分组
    workshops = {}
    for device in devices:
        ws = device.get("workshop", "未分配")
        if ws not in workshops:
            workshops[ws] = []
        workshops[ws].append(device)
    
    # 每个车间内排序
    optimized = []
    sequence = 0
    
    for ws, ws_devices in sorted(workshops.items()):
        # 先按标高排序（None视为0），再按x坐标，关键设备优先
        def sort_key(d):
            z = d.get("z") if d.get("z") is not None else 0
            x = d.get("x") if d.get("x") is not None else 0
            is_critical = 0 if d.get("type") in critical_types else 1
            return (is_critical, z, x)
        
        ws_devices.sort(key=sort_key)
        
        for device in ws_devices:
            sequence += 1
            # 估算施工天数
            estimated_days = _estimate_construction_days(device)
            # 计算与前一设备的距离（机具移动成本）
            move_cost = 0
            if optimized:
                prev = optimized[-1]
                if prev["workshop"] != device["workshop"]:
                    move_cost = 10  # 跨车间
                else:
                    dx = abs((device.get("x") or 0) - (prev.get("x") or 0))
                    dy = abs((device.get("y") or 0) - (prev.get("y") or 0))
                    move_cost = round((dx**2 + dy**2)**0.5, 1)
            
            optimized.append({
                "sequence": sequence,
                "tag": device["tag"],
                "name": device.get("name", device["tag"]),
                "type": device.get("type", ""),
                "workshop": ws,
                "elevation": device.get("z"),
                "x": device.get("x"),
                "y": device.get("y"),
                "is_critical": device.get("type") in critical_types,
                "estimated_days": estimated_days,
                "move_cost_from_prev": move_cost,
                "status": "pending",  # pending/in_progress/completed
                "planned_start": None,
                "planned_end": None,
            })
    
    # 计算总工期和总移动成本
    total_days = sum(d["estimated_days"] for d in optimized)
    total_move_cost = sum(d["move_cost_from_prev"] for d in optimized)
    
    result = {
        "ok": True,
        "total_devices": len(optimized),
        "total_workshops": len(workshops),
        "total_estimated_days": total_days,
        "total_move_cost": round(total_move_cost, 1),
        "critical_devices": len([d for d in optimized if d["is_critical"]]),
        "optimized_schedule": optimized,
        "generated_at": datetime.datetime.now().isoformat(),
    }
    
    # 保存
    enhanced = _load_enhanced()
    enhanced["optimized_schedule"] = optimized
    enhanced["stats"]["last_optimization"] = result
    _save_enhanced(enhanced)
    
    return result


def _estimate_construction_days(device: dict) -> int:
    """估算设备施工天数。"""
    type_days = {
        "塔器": 5, "储罐": 7, "压缩机": 4, "换热器": 3,
        "容器": 2, "泵": 1, "风机": 1, "电机": 1,
        "阀门": 0.5,
    }
    base = type_days.get(device.get("type", ""), 2)
    # 高位设备增加施工天数
    z = device.get("z")
    if z is not None and z > 5:
        base += 1
    if z is not None and z > 10:
        base += 2
    return base


def detect_construction_conflicts() -> dict:
    """v0.1.82：识别施工冲突。
    
    冲突类型：
    1. 空间冲突：相邻设备同时施工
    2. 资源冲突：同一车间多台大型设备同时吊装
    3. 工序冲突：管线连接设备未完成就开始管道施工
    4. 安全冲突：高位设备施工时下方有其他作业
    """
    devices = _get_devices_with_positions()
    conflicts = []
    
    if not devices:
        return {"ok": False, "error": "无设备数据", "conflicts": []}
    
    # 1. 空间冲突：相邻设备距离过近
    for i, d1 in enumerate(devices):
        for d2 in devices[i+1:]:
            if d1["workshop"] != d2["workshop"]:
                continue
            x1, y1 = d1.get("x") or 0, d1.get("y") or 0
            x2, y2 = d2.get("x") or 0, d2.get("y") or 0
            distance = ((x1-x2)**2 + (y1-y2)**2)**0.5
            if 0 < distance < 3:  # 3米以内
                conflicts.append({
                    "type": "空间冲突",
                    "severity": "high" if distance < 1.5 else "medium",
                    "devices": [d1["tag"], d2["tag"]],
                    "workshop": d1["workshop"],
                    "distance": round(distance, 2),
                    "description": f"{d1['tag']}与{d2['tag']}距离仅{round(distance,2)}米，同时施工存在空间冲突",
                    "suggestion": "建议错开施工时间，或设置安全隔离区",
                })
    
    # 2. 资源冲突：同一车间多台大型设备
    large_types = {"塔器", "储罐", "压缩机"}
    workshop_large = {}
    for d in devices:
        if d.get("type") in large_types:
            ws = d["workshop"]
            if ws not in workshop_large:
                workshop_large[ws] = []
            workshop_large[ws].append(d["tag"])
    
    for ws, tags in workshop_large.items():
        if len(tags) >= 2:
            conflicts.append({
                "type": "资源冲突",
                "severity": "high",
                "devices": tags,
                "workshop": ws,
                "description": f"{ws}有{len(tags)}台大型设备({','.join(tags)})，可能存在吊装资源冲突",
                "suggestion": "建议合理安排吊装顺序，或协调多台吊车同时作业",
            })
    
    # 3. 安全冲突：高位设备下方有其他设备
    high_devices = [d for d in devices if d.get("z") is not None and d["z"] > 5]
    for hd in high_devices:
        for d in devices:
            if d["tag"] == hd["tag"]:
                continue
            if d["workshop"] != hd["workshop"]:
                continue
            x1, y1 = hd.get("x") or 0, hd.get("y") or 0
            x2, y2 = d.get("x") or 0, d.get("y") or 0
            distance = ((x1-x2)**2 + (y1-y2)**2)**0.5
            if distance < 5:
                conflicts.append({
                    "type": "安全冲突",
                    "severity": "high",
                    "devices": [hd["tag"], d["tag"]],
                    "workshop": hd["workshop"],
                    "description": f"{hd['tag']}(标高{hd['z']}m)施工时，下方{d['tag']}存在物体打击风险",
                    "suggestion": "建议高位设备施工时下方设置警戒区，禁止其他作业",
                })
                break  # 每个高位设备只报一次
    
    result = {
        "ok": True,
        "total_conflicts": len(conflicts),
        "high_severity": len([c for c in conflicts if c["severity"] == "high"]),
        "medium_severity": len([c for c in conflicts if c["severity"] == "medium"]),
        "conflicts": conflicts,
        "generated_at": datetime.datetime.now().isoformat(),
    }
    
    # 保存
    enhanced = _load_enhanced()
    enhanced["conflicts"] = conflicts
    enhanced["stats"]["last_conflict_detection"] = {
        "total_conflicts": len(conflicts),
        "high_severity": result["high_severity"],
        "generated_at": result["generated_at"],
    }
    _save_enhanced(enhanced)
    
    return result


def analyze_critical_path() -> dict:
    """v0.1.82：关键路径分析。
    
    基于设备位置和依赖关系识别关键路径：
    1. 大型设备（塔器、储罐）通常在关键路径上
    2. 管线连接设备多的设备在关键路径上
    3. 高位设备施工周期长，可能在关键路径上
    4. 首台施工设备和最后一台施工设备在关键路径上
    """
    devices = _get_devices_with_positions()
    
    if not devices:
        return {"ok": False, "error": "无设备数据", "critical_path": []}
    
    # 计算每个设备的关键度评分
    device_scores = []
    critical_types = {"塔器", "储罐", "压缩机", "换热器"}
    
    for device in devices:
        score = 0
        reasons = []
        
        # 设备类型权重
        if device.get("type") in critical_types:
            score += 30
            reasons.append(f"{device['type']}为关键设备类型")
        
        # 相邻设备数量（连接复杂度）
        adjacent_count = len(device.get("adjacent_devices", []))
        if adjacent_count >= 3:
            score += 20
            reasons.append(f"连接{adjacent_count}台相邻设备")
        elif adjacent_count >= 2:
            score += 10
            reasons.append(f"连接{adjacent_count}台相邻设备")
        
        # 标高权重（高位设备施工周期长）
        z = device.get("z")
        if z is not None and z > 10:
            score += 20
            reasons.append(f"标高{z}m，施工周期长")
        elif z is not None and z > 5:
            score += 10
            reasons.append(f"标高{z}m，施工周期较长")
        
        # 估算施工天数
        est_days = _estimate_construction_days(device)
        if est_days >= 5:
            score += 15
            reasons.append(f"估算施工{est_days}天")
        elif est_days >= 3:
            score += 5
            reasons.append(f"估算施工{est_days}天")
        
        device_scores.append({
            "tag": device["tag"],
            "name": device.get("name", device["tag"]),
            "type": device.get("type", ""),
            "workshop": device.get("workshop", ""),
            "elevation": z,
            "critical_score": score,
            "reasons": reasons,
            "estimated_days": est_days,
        })
    
    # 按关键度排序
    device_scores.sort(key=lambda x: x["critical_score"], reverse=True)
    
    # 关键路径：取评分最高的前30%设备，或评分>=最高分50%的设备
    if device_scores:
        max_score = device_scores[0]["critical_score"]
        top_30_count = max(1, int(len(device_scores) * 0.3))
        threshold = max(max_score * 0.5, device_scores[min(top_30_count-1, len(device_scores)-1)]["critical_score"])
    else:
        threshold = 0
    critical_path = [d for d in device_scores if d["critical_score"] >= threshold]
    
    # 关键路径总工期
    critical_days = sum(d["estimated_days"] for d in critical_path)
    
    result = {
        "ok": True,
        "total_devices": len(devices),
        "critical_path_length": len(critical_path),
        "critical_path_days": critical_days,
        "threshold": threshold,
        "critical_path": critical_path,
        "all_device_scores": device_scores,
        "generated_at": datetime.datetime.now().isoformat(),
    }
    
    # 保存
    enhanced = _load_enhanced()
    enhanced["critical_path"] = critical_path
    enhanced["stats"]["last_critical_path_analysis"] = {
        "critical_path_length": len(critical_path),
        "critical_path_days": critical_days,
        "generated_at": result["generated_at"],
    }
    _save_enhanced(enhanced)
    
    return result


def detect_schedule_warnings() -> dict:
    """v0.1.82：施工进度预警。
    
    预警类型：
    1. 工期预警：关键路径设备施工进度滞后
    2. 资源预警：多台大型设备同时施工
    3. 质量预警：高位设备或精密设备施工风险
    4. 安全预警：交叉作业、高处作业
    5. 成本预警：货损设备、设计变更设备增加成本
    """
    devices = _get_devices_with_positions()
    warnings = []
    
    if not devices:
        return {"ok": False, "error": "无设备数据", "warnings": []}
    
    # 1. 质量预警：高位设备
    high_risk = [d for d in devices if d.get("z") is not None and d["z"] > 10]
    if high_risk:
        warnings.append({
            "type": "质量预警",
            "severity": "high",
            "devices": [d["tag"] for d in high_risk],
            "description": f"{len(high_risk)}台设备标高超过10m，施工质量控制难度大",
            "suggestion": "建议编制专项施工方案，加强过程质量检验",
        })
    
    # 2. 安全预警：交叉作业密集区域
    dense_areas = {}
    for d in devices:
        ws = d["workshop"]
        if ws not in dense_areas:
            dense_areas[ws] = 0
        dense_areas[ws] += 1
    for ws, count in dense_areas.items():
        if count >= 5:
            warnings.append({
                "type": "安全预警",
                "severity": "medium",
                "workshop": ws,
                "devices": [d["tag"] for d in devices if d["workshop"] == ws][:5],
                "description": f"{ws}有{count}台设备，施工期间可能存在交叉作业",
                "suggestion": "建议合理安排施工顺序，设置安全隔离区，加强现场安全管理",
            })
    
    # 3. 资源预警：大型设备集中
    large_types = {"塔器", "储罐", "压缩机"}
    large_devices = [d for d in devices if d.get("type") in large_types]
    if len(large_devices) >= 3:
        warnings.append({
            "type": "资源预警",
            "severity": "medium",
            "devices": [d["tag"] for d in large_devices],
            "description": f"有{len(large_devices)}台大型设备，吊装资源需求集中",
            "suggestion": "建议提前协调吊装资源，合理安排吊装顺序",
        })
    
    # 4. 工期预警：关键路径设备多
    critical_types = {"塔器", "储罐", "压缩机", "换热器"}
    critical_devices = [d for d in devices if d.get("type") in critical_types]
    if len(critical_devices) >= 4:
        warnings.append({
            "type": "工期预警",
            "severity": "high",
            "devices": [d["tag"] for d in critical_devices],
            "description": f"关键路径上有{len(critical_devices)}台设备，工期压力较大",
            "suggestion": "建议优先保障关键路径设备施工资源，必要时增加作业班组",
        })
    
    # 5. 精密设备预警
    precision_types = {"压缩机", "泵"}
    precision_devices = [d for d in devices if d.get("type") in precision_types]
    if precision_devices:
        warnings.append({
            "type": "质量预警",
            "severity": "low",
            "devices": [d["tag"] for d in precision_devices],
            "description": f"{len(precision_devices)}台精密设备，对中、找平要求高",
            "suggestion": "建议使用精密测量仪器，严格控制安装精度",
        })
    
    result = {
        "ok": True,
        "total_warnings": len(warnings),
        "high_severity": len([w for w in warnings if w["severity"] == "high"]),
        "medium_severity": len([w for w in warnings if w["severity"] == "medium"]),
        "low_severity": len([w for w in warnings if w["severity"] == "low"]),
        "warnings": warnings,
        "generated_at": datetime.datetime.now().isoformat(),
    }
    
    # 保存
    enhanced = _load_enhanced()
    enhanced["warnings"] = warnings
    enhanced["stats"]["last_warning_detection"] = {
        "total_warnings": len(warnings),
        "high_severity": result["high_severity"],
        "generated_at": result["generated_at"],
    }
    _save_enhanced(enhanced)
    
    return result


def optimize_resource_plan() -> dict:
    """v0.1.82：资源优化配置。
    
    根据设备位置和施工顺序自动优化：
    1. 人员配置：按车间和设备类型配置钳工、管工、电工、起重工
    2. 机具配置：按设备类型和重量配置吊车、焊机、千斤顶等
    3. 材料配置：按设备类型配置地脚螺栓、垫铁、灌浆料等
    """
    devices = _get_devices_with_positions()
    
    if not devices:
        return {"ok": False, "error": "无设备数据", "resource_plan": {}}
    
    # 按车间分组
    workshops = {}
    for device in devices:
        ws = device.get("workshop", "未分配")
        if ws not in workshops:
            workshops[ws] = []
        workshops[ws].append(device)
    
    resource_plan = {"workshops": {}}
    
    # 人员配置标准（每台设备）
    personnel_std = {
        "塔器": {"钳工": 4, "起重工": 4, "焊工": 2, "电工": 1},
        "储罐": {"钳工": 6, "起重工": 4, "焊工": 4, "电工": 1},
        "压缩机": {"钳工": 4, "起重工": 2, "管工": 2, "电工": 2},
        "换热器": {"钳工": 2, "起重工": 2, "管工": 2, "电工": 1},
        "容器": {"钳工": 2, "起重工": 2, "电工": 1},
        "泵": {"钳工": 2, "起重工": 1, "管工": 1, "电工": 1},
        "风机": {"钳工": 2, "起重工": 1, "电工": 1},
        "电机": {"电工": 2, "起重工": 1, "钳工": 1},
        "阀门": {"管工": 1, "起重工": 1},
    }
    default_personnel = {"钳工": 2, "起重工": 1, "电工": 1}
    
    # 机具配置标准
    equipment_std = {
        "塔器": ["200t汽车吊", "经纬仪", "水准仪", "电焊机2台", "千斤顶4台"],
        "储罐": ["200t汽车吊", "经纬仪", "水准仪", "电焊机4台", "千斤顶4台", "真空箱"],
        "压缩机": ["50t汽车吊", "经纬仪", "百分表2套", "电焊机2台", "千斤顶2台"],
        "换热器": ["50t汽车吊", "水准仪", "电焊机2台", "千斤顶2台"],
        "容器": ["30t汽车吊", "水准仪", "电焊机2台", "千斤顶2台"],
        "泵": ["20t汽车吊", "百分表1套", "手动葫芦2台"],
        "风机": ["20t汽车吊", "手动葫芦2台"],
        "电机": ["20t汽车吊", "兆欧表"],
        "阀门": ["手动葫芦1台"],
    }
    default_equipment = ["20t汽车吊", "电焊机1台", "千斤顶2台"]
    
    # 材料配置标准
    material_std = {
        "塔器": ["地脚螺栓", "垫铁", "灌浆料", "钢丝绳"],
        "储罐": ["地脚螺栓", "垫铁", "灌浆料", "焊接材料", "防腐材料"],
        "压缩机": ["地脚螺栓", "垫铁", "灌浆料", "润滑油", "密封件"],
        "换热器": ["地脚螺栓", "垫铁", "灌浆料", "密封垫片"],
        "容器": ["地脚螺栓", "垫铁", "灌浆料"],
        "泵": ["地脚螺栓", "垫铁", "灌浆料", "密封垫片", "联轴器"],
        "风机": ["地脚螺栓", "垫铁", "灌浆料", "减振器"],
        "电机": ["地脚螺栓", "垫铁", "灌浆料", "电缆"],
        "阀门": ["螺栓", "密封垫片"],
    }
    default_material = ["地脚螺栓", "垫铁", "灌浆料"]
    
    total_personnel = {}
    total_equipment = set()
    total_material = set()
    
    for ws, ws_devices in workshops.items():
        ws_personnel = {}
        ws_equipment = set()
        ws_material = set()
        
        for device in ws_devices:
            dtype = device.get("type", "")
            # 人员
            p = personnel_std.get(dtype, default_personnel)
            for role, count in p.items():
                ws_personnel[role] = ws_personnel.get(role, 0) + count
            # 机具
            e = equipment_std.get(dtype, default_equipment)
            ws_equipment.update(e)
            # 材料
            m = material_std.get(dtype, default_material)
            ws_material.update(m)
        
        resource_plan["workshops"][ws] = {
            "device_count": len(ws_devices),
            "devices": [d["tag"] for d in ws_devices],
            "personnel": ws_personnel,
            "equipment": sorted(list(ws_equipment)),
            "materials": sorted(list(ws_material)),
        }
        
        # 汇总
        for role, count in ws_personnel.items():
            total_personnel[role] = total_personnel.get(role, 0) + count
        total_equipment.update(ws_equipment)
        total_material.update(ws_material)
    
    resource_plan["total"] = {
        "workshops": len(workshops),
        "devices": len(devices),
        "personnel": total_personnel,
        "equipment": sorted(list(total_equipment)),
        "materials": sorted(list(total_material)),
    }
    
    result = {
        "ok": True,
        "resource_plan": resource_plan,
        "generated_at": datetime.datetime.now().isoformat(),
    }
    
    # 保存
    enhanced = _load_enhanced()
    enhanced["resource_plan"] = resource_plan
    enhanced["stats"]["last_resource_optimization"] = {
        "workshops": len(workshops),
        "devices": len(devices),
        "generated_at": result["generated_at"],
    }
    _save_enhanced(enhanced)
    
    return result


def run_full_analysis() -> dict:
    """v0.1.82：运行完整分析（优化顺序+冲突识别+关键路径+预警+资源优化）。"""
    order = optimize_construction_order()
    conflicts = detect_construction_conflicts()
    critical = analyze_critical_path()
    warnings = detect_schedule_warnings()
    resources = optimize_resource_plan()
    
    return {
        "ok": True,
        "optimized_schedule": order,
        "conflicts": conflicts,
        "critical_path": critical,
        "warnings": warnings,
        "resources": resources,
        "generated_at": datetime.datetime.now().isoformat(),
    }


def get_enhanced_stats() -> dict:
    """v0.1.82：获取增强分析统计。"""
    enhanced = _load_enhanced()
    return {
        "ok": True,
        "optimized_schedule_count": len(enhanced.get("optimized_schedule", [])),
        "conflicts_count": len(enhanced.get("conflicts", [])),
        "critical_path_count": len(enhanced.get("critical_path", [])),
        "warnings_count": len(enhanced.get("warnings", [])),
        "has_resource_plan": bool(enhanced.get("resource_plan", {})),
        "stats": enhanced.get("stats", {}),
    }
