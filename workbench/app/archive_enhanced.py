"""
v0.1.83：设备安装位置与竣工资料联动增强

竣工资料清单自动生成、完整性检查、组卷优化、与设备状态联动。
"""

import os
import json
import datetime
from typing import Optional, List, Dict


_ARCHIVE_FILE = os.path.join("data", "archive_enhanced.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_archive() -> dict:
    if os.path.exists(_ARCHIVE_FILE):
        try:
            with open(_ARCHIVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {"checklist": {}, "integrity": {}, "organization": {}}


def _save_archive(archive: dict):
    _ensure_dirs()
    with open(_ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)


# 设备类型竣工资料要求清单
DEVICE_ARCHIVE_REQUIREMENTS = {
    "泵": [
        {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
        {"doc_type": "设备基础验收记录", "required": True, "stage": "基础"},
        {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
        {"doc_type": "设备找平找正记录", "required": True, "stage": "安装"},
        {"doc_type": "联轴器对中记录", "required": True, "stage": "安装"},
        {"doc_type": "管道连接记录", "required": False, "stage": "配管"},
        {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "隐蔽"},
        {"doc_type": "设备试运转记录", "required": True, "stage": "试运转"},
        {"doc_type": "设备单机试运转方案", "required": True, "stage": "试运转"},
        {"doc_type": "设备质量证明文件", "required": True, "stage": "资料"},
        {"doc_type": "设备说明书", "required": True, "stage": "资料"},
        {"doc_type": "设备竣工图", "required": True, "stage": "资料"},
    ],
    "压缩机": [
        {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
        {"doc_type": "设备基础验收记录", "required": True, "stage": "基础"},
        {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
        {"doc_type": "设备找平找正记录", "required": True, "stage": "安装"},
        {"doc_type": "联轴器对中记录", "required": True, "stage": "安装"},
        {"doc_type": "润滑油系统冲洗记录", "required": True, "stage": "安装"},
        {"doc_type": "冷却水系统压力试验记录", "required": False, "stage": "配管"},
        {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "隐蔽"},
        {"doc_type": "设备试运转记录", "required": True, "stage": "试运转"},
        {"doc_type": "设备单机试运转方案", "required": True, "stage": "试运转"},
        {"doc_type": "压缩机性能测试报告", "required": True, "stage": "试运转"},
        {"doc_type": "设备质量证明文件", "required": True, "stage": "资料"},
        {"doc_type": "设备说明书", "required": True, "stage": "资料"},
        {"doc_type": "设备竣工图", "required": True, "stage": "资料"},
    ],
    "塔器": [
        {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
        {"doc_type": "设备基础验收记录", "required": True, "stage": "基础"},
        {"doc_type": "塔器吊装方案", "required": True, "stage": "吊装"},
        {"doc_type": "塔器吊装记录", "required": True, "stage": "吊装"},
        {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
        {"doc_type": "塔器垂直度检测记录", "required": True, "stage": "安装"},
        {"doc_type": "塔器内件安装记录", "required": True, "stage": "安装"},
        {"doc_type": "塔盘水平度检测记录", "required": False, "stage": "安装"},
        {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "隐蔽"},
        {"doc_type": "塔器压力试验记录", "required": True, "stage": "试验"},
        {"doc_type": "塔器气密性试验记录", "required": False, "stage": "试验"},
        {"doc_type": "设备质量证明文件", "required": True, "stage": "资料"},
        {"doc_type": "设备说明书", "required": True, "stage": "资料"},
        {"doc_type": "设备竣工图", "required": True, "stage": "资料"},
    ],
    "换热器": [
        {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
        {"doc_type": "设备基础验收记录", "required": True, "stage": "基础"},
        {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
        {"doc_type": "设备找平找正记录", "required": True, "stage": "安装"},
        {"doc_type": "换热器抽芯检查记录", "required": False, "stage": "安装"},
        {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "隐蔽"},
        {"doc_type": "换热器压力试验记录", "required": True, "stage": "试验"},
        {"doc_type": "换热器气密性试验记录", "required": False, "stage": "试验"},
        {"doc_type": "设备质量证明文件", "required": True, "stage": "资料"},
        {"doc_type": "设备说明书", "required": True, "stage": "资料"},
        {"doc_type": "设备竣工图", "required": True, "stage": "资料"},
    ],
    "容器": [
        {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
        {"doc_type": "设备基础验收记录", "required": True, "stage": "基础"},
        {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
        {"doc_type": "设备找平找正记录", "required": True, "stage": "安装"},
        {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "隐蔽"},
        {"doc_type": "容器压力试验记录", "required": True, "stage": "试验"},
        {"doc_type": "容器气密性试验记录", "required": False, "stage": "试验"},
        {"doc_type": "设备质量证明文件", "required": True, "stage": "资料"},
        {"doc_type": "设备说明书", "required": True, "stage": "资料"},
        {"doc_type": "设备竣工图", "required": True, "stage": "资料"},
    ],
    "风机": [
        {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
        {"doc_type": "设备基础验收记录", "required": True, "stage": "基础"},
        {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
        {"doc_type": "设备找平找正记录", "required": True, "stage": "安装"},
        {"doc_type": "联轴器对中记录", "required": True, "stage": "安装"},
        {"doc_type": "减振器安装记录", "required": False, "stage": "安装"},
        {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "隐蔽"},
        {"doc_type": "设备试运转记录", "required": True, "stage": "试运转"},
        {"doc_type": "设备单机试运转方案", "required": True, "stage": "试运转"},
        {"doc_type": "设备质量证明文件", "required": True, "stage": "资料"},
        {"doc_type": "设备说明书", "required": True, "stage": "资料"},
        {"doc_type": "设备竣工图", "required": True, "stage": "资料"},
    ],
    "电机": [
        {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
        {"doc_type": "设备基础验收记录", "required": True, "stage": "基础"},
        {"doc_type": "电机安装记录", "required": True, "stage": "安装"},
        {"doc_type": "电机找平找正记录", "required": True, "stage": "安装"},
        {"doc_type": "电机绝缘测试记录", "required": True, "stage": "安装"},
        {"doc_type": "电机直流电阻测试记录", "required": False, "stage": "安装"},
        {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "隐蔽"},
        {"doc_type": "电机试运转记录", "required": True, "stage": "试运转"},
        {"doc_type": "电机单机试运转方案", "required": True, "stage": "试运转"},
        {"doc_type": "设备质量证明文件", "required": True, "stage": "资料"},
        {"doc_type": "设备说明书", "required": True, "stage": "资料"},
        {"doc_type": "设备竣工图", "required": True, "stage": "资料"},
    ],
    "阀门": [
        {"doc_type": "阀门开箱检验记录", "required": True, "stage": "开箱"},
        {"doc_type": "阀门强度试验记录", "required": True, "stage": "试验"},
        {"doc_type": "阀门严密性试验记录", "required": True, "stage": "试验"},
        {"doc_type": "阀门安装记录", "required": True, "stage": "安装"},
        {"doc_type": "阀门调试记录", "required": False, "stage": "调试"},
        {"doc_type": "设备质量证明文件", "required": True, "stage": "资料"},
        {"doc_type": "阀门合格证", "required": True, "stage": "资料"},
    ],
    "储罐": [
        {"doc_type": "材料进场检验记录", "required": True, "stage": "材料"},
        {"doc_type": "储罐基础验收记录", "required": True, "stage": "基础"},
        {"doc_type": "储罐底板铺设记录", "required": True, "stage": "安装"},
        {"doc_type": "储罐壁板安装记录", "required": True, "stage": "安装"},
        {"doc_type": "储罐顶板安装记录", "required": True, "stage": "安装"},
        {"doc_type": "储罐焊缝无损检测报告", "required": True, "stage": "检测"},
        {"doc_type": "储罐真空箱试漏记录", "required": True, "stage": "试验"},
        {"doc_type": "储罐充水试验记录", "required": True, "stage": "试验"},
        {"doc_type": "储罐沉降观测记录", "required": True, "stage": "试验"},
        {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "隐蔽"},
        {"doc_type": "储罐防腐施工记录", "required": False, "stage": "防腐"},
        {"doc_type": "储罐保温施工记录", "required": False, "stage": "保温"},
        {"doc_type": "材料质量证明文件", "required": True, "stage": "资料"},
        {"doc_type": "储罐竣工图", "required": True, "stage": "资料"},
    ],
}

DEFAULT_ARCHIVE_REQUIREMENTS = [
    {"doc_type": "设备开箱检验记录", "required": True, "stage": "开箱"},
    {"doc_type": "设备基础验收记录", "required": True, "stage": "基础"},
    {"doc_type": "设备安装记录", "required": True, "stage": "安装"},
    {"doc_type": "隐蔽工程验收记录", "required": True, "stage": "隐蔽"},
    {"doc_type": "设备质量证明文件", "required": True, "stage": "资料"},
    {"doc_type": "设备说明书", "required": True, "stage": "资料"},
    {"doc_type": "设备竣工图", "required": True, "stage": "资料"},
]


def get_archive_requirements(dev_type: str) -> list:
    """v0.1.83：获取设备类型竣工资料要求。"""
    return DEVICE_ARCHIVE_REQUIREMENTS.get(dev_type, DEFAULT_ARCHIVE_REQUIREMENTS)


def _get_all_devices_with_position() -> List[dict]:
    """获取所有带位置信息的设备。"""
    from . import relations as _rel
    from . import installation_plan as _ip
    
    g = _rel.load_relations()
    devices = g.get("devices", [])
    
    result = []
    for device in devices:
        tag = device.get("tag", "")
        spatial = _ip.get_device_spatial_info(tag)
        if "error" not in spatial:
            device_info = dict(device)
            device_info.update({
                "workshop": spatial.get("workshop", ""),
                "elevation": spatial.get("z"),
                "x": spatial.get("x"),
                "y": spatial.get("y"),
                "adjacent_devices": spatial.get("adjacent_devices", []),
            })
            result.append(device_info)
    
    return result


def _get_device_status(tag: str) -> dict:
    """获取设备施工状态。"""
    from . import construction_schedule as _cs
    try:
        result = _cs.get_device_status(tag)
        if result.get("ok") and "status" in result:
            return {
                "status": result.get("status", "pending"),
                "notes": result.get("notes", ""),
                "updated_at": result.get("updated_at", ""),
            }
    except Exception:
        pass
    return {"status": "pending", "notes": "", "updated_at": ""}


def generate_archive_checklist() -> dict:
    """v0.1.83：生成竣工资料清单。
    
    根据设备位置（车间、标高）和设备类型，自动生成竣工资料清单。
    按车间→设备→资料类型组织。
    """
    devices = _get_all_devices_with_position()
    
    if not devices:
        return {"error": "无设备数据", "checklist": {}, "total_devices": 0}
    
    checklist = {}
    total_required = 0
    total_optional = 0
    
    for device in devices:
        tag = device.get("tag", "")
        dev_type = device.get("type", "")
        ws = device.get("workshop", "未分配")
        elevation = device.get("elevation")
        status_info = _get_device_status(tag)
        status = status_info.get("status", "pending")
        
        # 获取该设备类型的竣工资料要求
        requirements = get_archive_requirements(dev_type)
        
        device_docs = []
        for req in requirements:
            doc_info = dict(req)
            doc_info["status"] = "pending"  # pending/complete/missing
            doc_info["completed_at"] = None
            doc_info["file_path"] = None
            
            # 根据设备状态判断资料是否应该已完成
            if status == "completed" or status == "accepted":
                if req["stage"] in ["开箱", "基础", "安装", "隐蔽", "资料"]:
                    doc_info["expected_status"] = "should_complete"
                else:
                    doc_info["expected_status"] = "pending"
            elif status == "in_progress":
                if req["stage"] in ["开箱", "基础"]:
                    doc_info["expected_status"] = "should_complete"
                else:
                    doc_info["expected_status"] = "pending"
            else:
                doc_info["expected_status"] = "pending"
            
            device_docs.append(doc_info)
            
            if req["required"]:
                total_required += 1
            else:
                total_optional += 1
        
        if ws not in checklist:
            checklist[ws] = {}
        
        checklist[ws][tag] = {
            "name": device.get("name", ""),
            "type": dev_type,
            "elevation": elevation,
            "status": status,
            "total_docs": len(device_docs),
            "required_docs": len([d for d in device_docs if d["required"]]),
            "optional_docs": len([d for d in device_docs if not d["required"]]),
            "completed_docs": 0,
            "pending_docs": len(device_docs),
            "docs": device_docs,
        }
    
    result = {
        "ok": True,
        "total_devices": len(devices),
        "total_workshops": len(checklist),
        "total_required_docs": total_required,
        "total_optional_docs": total_optional,
        "total_docs": total_required + total_optional,
        "checklist": checklist,
        "generated_at": datetime.datetime.now().isoformat(),
    }
    
    # 保存清单
    archive = _load_archive()
    archive["checklist"] = result
    _save_archive(archive)
    
    return result


def check_archive_integrity() -> dict:
    """v0.1.83：竣工资料完整性检查。
    
    检查每台设备的竣工资料是否完整，标记缺失的资料。
    """
    checklist_data = generate_archive_checklist()
    
    if "error" in checklist_data:
        return checklist_data
    
    checklist = checklist_data.get("checklist", {})
    
    issues = []
    total_missing_required = 0
    total_missing_optional = 0
    devices_complete = 0
    devices_incomplete = 0
    
    for ws, ws_devices in checklist.items():
        for tag, device_info in ws_devices.items():
            docs = device_info.get("docs", [])
            missing_required = []
            missing_optional = []
            
            for doc in docs:
                if doc["status"] != "complete":
                    if doc["required"]:
                        missing_required.append(doc["doc_type"])
                    else:
                        missing_optional.append(doc["doc_type"])
            
            if missing_required:
                total_missing_required += len(missing_required)
                devices_incomplete += 1
                issues.append({
                    "type": "missing_required",
                    "severity": "high",
                    "tag": tag,
                    "name": device_info.get("name", ""),
                    "workshop": ws,
                    "missing_count": len(missing_required),
                    "missing_docs": missing_required,
                    "message": f"设备{tag}（{device_info.get('name','')}）缺少{len(missing_required)}项必备竣工资料：{', '.join(missing_required[:5])}",
                })
            else:
                devices_complete += 1
            
            if missing_optional:
                total_missing_optional += len(missing_optional)
                issues.append({
                    "type": "missing_optional",
                    "severity": "medium",
                    "tag": tag,
                    "name": device_info.get("name", ""),
                    "workshop": ws,
                    "missing_count": len(missing_optional),
                    "missing_docs": missing_optional,
                    "message": f"设备{tag}（{device_info.get('name','')}）缺少{len(missing_optional)}项可选竣工资料",
                })
            
            # 检查设备状态与资料完成度的匹配
            status = device_info.get("status", "pending")
            if status in ["completed", "accepted"] and missing_required:
                issues.append({
                    "type": "status_mismatch",
                    "severity": "high",
                    "tag": tag,
                    "name": device_info.get("name", ""),
                    "workshop": ws,
                    "message": f"设备{tag}状态为{status}，但仍缺少{len(missing_required)}项必备竣工资料",
                })
    
    # 按严重程度排序
    severity_order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: severity_order.get(i.get("severity", "low"), 2))
    
    result = {
        "ok": True,
        "total_devices": checklist_data.get("total_devices", 0),
        "devices_complete": devices_complete,
        "devices_incomplete": devices_incomplete,
        "completion_rate": round(devices_complete / checklist_data.get("total_devices", 1) * 100, 1),
        "total_missing_required": total_missing_required,
        "total_missing_optional": total_missing_optional,
        "issues_count": len(issues),
        "high_severity": len([i for i in issues if i.get("severity") == "high"]),
        "medium_severity": len([i for i in issues if i.get("severity") == "medium"]),
        "issues": issues[:50],
        "check_time": datetime.datetime.now().isoformat(),
    }
    
    # 保存检查结果
    archive = _load_archive()
    archive["integrity"] = result
    _save_archive(archive)
    
    return result


def organize_archive_volumes() -> dict:
    """v0.1.83：竣工资料组卷优化。
    
    按车间→设备→资料类型组卷，生成卷册目录。
    """
    checklist_data = generate_archive_checklist()
    
    if "error" in checklist_data:
        return checklist_data
    
    checklist = checklist_data.get("checklist", {})
    
    volumes = []
    volume_index = 1
    
    for ws in sorted(checklist.keys()):
        ws_devices = checklist[ws]
        
        # 每个车间一个卷册
        volume_docs = []
        total_docs_in_volume = 0
        
        for tag in sorted(ws_devices.keys()):
            device_info = ws_devices[tag]
            docs = device_info.get("docs", [])
            
            # 按阶段分组
            by_stage = {}
            for doc in docs:
                stage = doc.get("stage", "其他")
                if stage not in by_stage:
                    by_stage[stage] = []
                by_stage[stage].append(doc)
            
            device_volume_entry = {
                "tag": tag,
                "name": device_info.get("name", ""),
                "type": device_info.get("type", ""),
                "elevation": device_info.get("elevation"),
                "status": device_info.get("status", ""),
                "total_docs": len(docs),
                "by_stage": by_stage,
            }
            volume_docs.append(device_volume_entry)
            total_docs_in_volume += len(docs)
        
        volume = {
            "volume_number": f"第{volume_index}卷",
            "workshop": ws,
            "device_count": len(ws_devices),
            "total_docs": total_docs_in_volume,
            "devices": volume_docs,
        }
        volumes.append(volume)
        volume_index += 1
    
    result = {
        "ok": True,
        "total_volumes": len(volumes),
        "total_devices": checklist_data.get("total_devices", 0),
        "total_docs": checklist_data.get("total_docs", 0),
        "volumes": volumes,
        "organized_at": datetime.datetime.now().isoformat(),
    }
    
    # 保存组卷结果
    archive = _load_archive()
    archive["organization"] = result
    _save_archive(archive)
    
    return result


def update_archive_doc_status(tag: str, doc_type: str, status: str,
                                file_path: str = None) -> dict:
    """v0.1.83：更新竣工资料状态。"""
    archive = _load_archive()
    checklist = archive.get("checklist", {}).get("checklist", {})
    
    if not checklist:
        # 如果没有清单，先生成
        checklist_data = generate_archive_checklist()
        checklist = checklist_data.get("checklist", {})
        archive = _load_archive()
    
    found = False
    for ws, ws_devices in checklist.items():
        if tag in ws_devices:
            device_info = ws_devices[tag]
            for doc in device_info.get("docs", []):
                if doc["doc_type"] == doc_type:
                    doc["status"] = status
                    if status == "complete":
                        doc["completed_at"] = datetime.datetime.now().isoformat()
                    if file_path:
                        doc["file_path"] = file_path
                    found = True
                    
                    # 更新设备统计
                    device_info["completed_docs"] = len([d for d in device_info["docs"] if d["status"] == "complete"])
                    device_info["pending_docs"] = len([d for d in device_info["docs"] if d["status"] != "complete"])
                    break
            break
    
    if not found:
        return {"error": f"未找到设备{tag}的资料{doc_type}", "tag": tag, "doc_type": doc_type}
    
    # 保存
    archive["checklist"]["checklist"] = checklist
    archive["checklist"]["updated_at"] = datetime.datetime.now().isoformat()
    _save_archive(archive)
    
    return {
        "ok": True,
        "tag": tag,
        "doc_type": doc_type,
        "status": status,
        "file_path": file_path,
        "updated_at": datetime.datetime.now().isoformat(),
    }


def get_archive_summary() -> dict:
    """v0.1.83：获取竣工资料总览。"""
    checklist_data = generate_archive_checklist()
    integrity_data = check_archive_integrity()
    
    if "error" in checklist_data:
        return checklist_data
    
    checklist = checklist_data.get("checklist", {})
    
    # 按车间统计
    by_workshop = {}
    for ws, ws_devices in checklist.items():
        total = 0
        completed = 0
        required = 0
        for tag, device_info in ws_devices.items():
            total += device_info.get("total_docs", 0)
            completed += device_info.get("completed_docs", 0)
            required += device_info.get("required_docs", 0)
        by_workshop[ws] = {
            "device_count": len(ws_devices),
            "total_docs": total,
            "completed_docs": completed,
            "required_docs": required,
            "completion_rate": round(completed / total * 100, 1) if total > 0 else 0,
        }
    
    # 按资料类型统计
    by_doc_type = {}
    for ws, ws_devices in checklist.items():
        for tag, device_info in ws_devices.items():
            for doc in device_info.get("docs", []):
                dtype = doc["doc_type"]
                if dtype not in by_doc_type:
                    by_doc_type[dtype] = {"total": 0, "completed": 0, "required": 0}
                by_doc_type[dtype]["total"] += 1
                if doc["status"] == "complete":
                    by_doc_type[dtype]["completed"] += 1
                if doc["required"]:
                    by_doc_type[dtype]["required"] += 1
    
    return {
        "ok": True,
        "total_devices": checklist_data.get("total_devices", 0),
        "total_workshops": checklist_data.get("total_workshops", 0),
        "total_docs": checklist_data.get("total_docs", 0),
        "total_required_docs": checklist_data.get("total_required_docs", 0),
        "total_optional_docs": checklist_data.get("total_optional_docs", 0),
        "devices_complete": integrity_data.get("devices_complete", 0),
        "devices_incomplete": integrity_data.get("devices_incomplete", 0),
        "device_completion_rate": integrity_data.get("completion_rate", 0),
        "total_missing_required": integrity_data.get("total_missing_required", 0),
        "total_missing_optional": integrity_data.get("total_missing_optional", 0),
        "by_workshop": by_workshop,
        "by_doc_type": dict(sorted(by_doc_type.items(), key=lambda x: x[1]["total"], reverse=True)[:20]),
        "summary_time": datetime.datetime.now().isoformat(),
    }
