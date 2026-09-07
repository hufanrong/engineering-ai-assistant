"""
v0.1.106：矿山设备竣工资料自动组卷增强（基于详细知识库）

基于设备详细知识库自动生成竣工资料组卷目录，包含设备竣工资料清单、
组卷要求、资料整理规范、移交清单等。
"""

import os
import json
import datetime
from typing import Optional


# 竣工资料组卷标准结构
ARCHIVE_VOLUMES = [
    {
        "volume": "第一卷 综合管理资料",
        "description": "工程综合管理类资料",
        "documents": [
            {"name": "工程开工报告", "required": True, "description": "工程开工申请及批复"},
            {"name": "施工组织设计", "required": True, "description": "项目总体施工组织设计及审批"},
            {"name": "施工方案", "required": True, "description": "各专业专项施工方案及审批"},
            {"name": "技术交底记录", "required": True, "description": "施工技术交底记录"},
            {"name": "安全交底记录", "required": True, "description": "安全技术交底记录"},
            {"name": "图纸会审记录", "required": True, "description": "施工图纸会审记录"},
            {"name": "设计交底记录", "required": True, "description": "设计单位技术交底记录"},
            {"name": "设计变更通知单", "required": False, "description": "设计变更文件（如有）"},
            {"name": "工程联系单", "required": False, "description": "工程联系单（如有）"},
            {"name": "施工日志", "required": True, "description": "每日施工日志"},
            {"name": "会议纪要", "required": False, "description": "工程会议纪要"},
            {"name": "工程竣工报告", "required": True, "description": "工程竣工报告"},
            {"name": "竣工验收证书", "required": True, "description": "竣工验收证书"},
        ],
    },
    {
        "volume": "第二卷 设备技术资料",
        "description": "设备出厂技术文件及开箱检验资料",
        "documents": [
            {"name": "设备清单", "required": True, "description": "设备明细清单（名称、型号、规格、数量、厂家）"},
            {"name": "设备合格证", "required": True, "description": "设备出厂合格证"},
            {"name": "设备质量证明书", "required": True, "description": "设备质量证明文件"},
            {"name": "设备说明书", "required": True, "description": "设备安装使用说明书"},
            {"name": "设备装箱单", "required": True, "description": "设备零部件装箱清单"},
            {"name": "设备图纸", "required": True, "description": "设备总图、部件图、安装图"},
            {"name": "设备开箱检验记录", "required": True, "description": "设备开箱检验记录"},
            {"name": "进口设备商检报告", "required": False, "description": "进口设备商检证明（如适用）"},
            {"name": "特种设备制造许可证", "required": False, "description": "特种设备制造许可证（如适用）"},
            {"name": "压力容器监检证书", "required": False, "description": "压力容器监督检验证书（如适用）"},
        ],
    },
    {
        "volume": "第三卷 安装施工记录",
        "description": "设备安装施工过程记录",
        "documents": [
            {"name": "基础验收记录", "required": True, "description": "设备基础交接验收记录"},
            {"name": "基础复测记录", "required": True, "description": "基础尺寸复测记录"},
            {"name": "设备安装记录", "required": True, "description": "设备安装过程记录"},
            {"name": "设备找平找正记录", "required": True, "description": "设备水平度、垂直度、同轴度检测记录"},
            {"name": "地脚螺栓紧固记录", "required": True, "description": "地脚螺栓紧固力矩记录"},
            {"name": "垫铁布置记录", "required": True, "description": "垫铁布置和隐蔽验收记录"},
            {"name": "二次灌浆记录", "required": True, "description": "设备基础二次灌浆记录"},
            {"name": "混凝土试块报告", "required": False, "description": "基础混凝土强度试验报告（如适用）"},
            {"name": "隐蔽工程验收记录", "required": True, "description": "隐蔽工程验收记录"},
            {"name": "设备吊装记录", "required": True, "description": "设备吊装作业记录"},
            {"name": "焊接记录", "required": False, "description": "设备管道焊接记录（如适用）"},
            {"name": "焊接无损检测报告", "required": False, "description": "焊缝RT/UT/MT/PT检测报告（如适用）"},
        ],
    },
    {
        "volume": "第四卷 管道安装记录",
        "description": "工艺管道安装施工记录",
        "documents": [
            {"name": "管道安装记录", "required": False, "description": "工艺管道安装记录（如适用）"},
            {"name": "管道压力试验记录", "required": False, "description": "管道水压/气压试验记录（如适用）"},
            {"name": "管道吹扫记录", "required": False, "description": "管道吹扫/清洗记录（如适用）"},
            {"name": "阀门试验记录", "required": False, "description": "阀门强度/严密性试验记录（如适用）"},
            {"name": "管道防腐保温记录", "required": False, "description": "管道防腐绝热施工记录（如适用）"},
        ],
    },
    {
        "volume": "第五卷 电气仪表安装记录",
        "description": "电气仪表安装施工记录",
        "documents": [
            {"name": "电气安装记录", "required": True, "description": "电气设备安装记录"},
            {"name": "电缆敷设记录", "required": True, "description": "电缆敷设及标识记录"},
            {"name": "接地电阻测试记录", "required": True, "description": "接地系统电阻测试记录"},
            {"name": "绝缘电阻测试记录", "required": True, "description": "电缆/电机绝缘测试记录"},
            {"name": "电机试运转记录", "required": True, "description": "电机空载/负载试运转记录"},
            {"name": "DCS/PLC调试记录", "required": False, "description": "控制系统调试记录（如适用）"},
            {"name": "仪表校准记录", "required": False, "description": "检测仪表校准记录（如适用）"},
            {"name": "联锁试验记录", "required": True, "description": "安全联锁功能试验记录"},
        ],
    },
    {
        "volume": "第六卷 试运转记录",
        "description": "设备试运转及性能测试记录",
        "documents": [
            {"name": "试运转方案", "required": True, "description": "设备试运转专项方案及审批"},
            {"name": "单机试运转记录", "required": True, "description": "单台设备空载/负载试运转记录"},
            {"name": "联动试运转记录", "required": True, "description": "系统联动试运转记录"},
            {"name": "设备性能测试报告", "required": True, "description": "设备性能参数测试报告"},
            {"name": "润滑系统调试记录", "required": False, "description": "润滑系统调试记录（如适用）"},
            {"name": "液压系统调试记录", "required": False, "description": "液压系统调试记录（如适用）"},
            {"name": "试运转期间施工日志", "required": True, "description": "试运转期间施工日志"},
        ],
    },
    {
        "volume": "第七卷 质量保证资料",
        "description": "质量保证及验收资料",
        "documents": [
            {"name": "材料进场检验记录", "required": True, "description": "材料进场检验记录"},
            {"name": "材料质量证明文件", "required": True, "description": "材料合格证、质量证明书"},
            {"name": "分项工程质量验收记录", "required": True, "description": "各分项工程质量验收记录"},
            {"name": "分部工程质量验收记录", "required": True, "description": "各分部工程质量验收记录"},
            {"name": "单位工程质量验收记录", "required": True, "description": "单位工程质量验收记录"},
            {"name": "质量事故处理记录", "required": False, "description": "质量事故处理记录（如有）"},
        ],
    },
    {
        "volume": "第八卷 竣工图及移交",
        "description": "竣工图纸及工程移交资料",
        "documents": [
            {"name": "竣工图", "required": True, "description": "竣工图纸（加盖竣工图章）"},
            {"name": "工程移交单", "required": True, "description": "工程移交证书"},
            {"name": "备品备件清单", "required": True, "description": "备品备件移交清单"},
            {"name": "专用工具清单", "required": True, "description": "专用工具移交清单"},
            {"name": "竣工资料移交清单", "required": True, "description": "竣工资料移交清单"},
            {"name": "工程保修书", "required": True, "description": "工程质量保修书"},
        ],
    },
]


def generate_completion_archive(
    equipment_name: str,
    project_name: str = "矿山工程项目",
    workshop: str = "",
    construction_unit: str = "",
) -> dict:
    """
    基于设备详细知识库生成竣工资料组卷目录。
    
    Args:
        equipment_name: 设备名称
        project_name: 项目名称
        workshop: 车间
        construction_unit: 施工单位
    
    Returns:
        完整的竣工资料组卷目录
    """
    from . import mining_equipment_detail as _med
    
    # 获取设备详细信息
    detail_result = _med.get_equipment_detail(equipment_name)
    if not detail_result.get("ok"):
        return {
            "ok": False,
            "error": f"未找到设备详细信息: {equipment_name}",
            "available_equipment": detail_result.get("available_equipment", []),
        }
    
    equipment = detail_result["equipment"]
    detail = detail_result["detail"]
    
    # 根据设备类型调整资料清单
    adjusted_volumes = _adjust_volumes_by_equipment(equipment, detail)
    
    # 统计
    total_volumes = len(adjusted_volumes)
    total_documents = sum(len(v["documents"]) for v in adjusted_volumes)
    required_documents = sum(len([d for d in v["documents"] if d["required"]]) for v in adjusted_volumes)
    optional_documents = total_documents - required_documents
    
    # 构建设备专用竣工资料要求
    equipment_specific = _get_equipment_specific_archive(equipment, detail)
    
    return {
        "ok": True,
        "equipment": equipment,
        "project_name": project_name,
        "workshop": workshop,
        "construction_unit": construction_unit,
        "title": f"{equipment}竣工资料组卷目录",
        "volumes": adjusted_volumes,
        "total_volumes": total_volumes,
        "total_documents": total_documents,
        "required_documents": required_documents,
        "optional_documents": optional_documents,
        "equipment_specific_requirements": equipment_specific,
        "archive_requirements": {
            "format": "纸质资料+电子资料（PDF格式）",
            "binding": "按卷装订，每卷不超过200页",
            "numbering": "按卷-册-页编号，建立总目录",
            "signatures": "所有记录必须有编制人、审核人、批准人签字",
            "seals": "竣工图必须加盖竣工图章，验收记录必须加盖公章",
            "retention": "工程移交后保存期限按国家规定执行",
        },
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _adjust_volumes_by_equipment(equipment: str, detail: dict) -> list:
    """根据设备类型调整资料卷册。"""
    volumes = json.loads(json.dumps(ARCHIVE_VOLUMES))  # 深拷贝
    
    # 管道安装记录：无管道的设备标记为不适用
    has_piping = any("管道" in str(c) for c in detail.get("main_components", []))
    if not has_piping:
        for vol in volumes:
            if vol["volume"] == "第四卷 管道安装记录":
                vol["applicable"] = False
                vol["note"] = "该设备无工艺管道，本卷不适用"
    
    # 压力容器设备增加专用资料
    if "高压釜" in equipment or "压力容器" in equipment:
        for vol in volumes:
            if vol["volume"] == "第二卷 设备技术资料":
                vol["documents"].extend([
                    {"name": "压力容器产品质量证明书", "required": True, "description": "压力容器产品质量证明书"},
                    {"name": "压力容器强度计算书", "required": True, "description": "压力容器强度计算书"},
                    {"name": "压力容器竣工图", "required": True, "description": "压力容器制造竣工图"},
                ])
            if vol["volume"] == "第三卷 安装施工记录":
                vol["documents"].extend([
                    {"name": "耐压试验记录", "required": True, "description": "压力容器水压试验记录（1.25倍设计压力）"},
                    {"name": "气密性试验记录", "required": True, "description": "压力容器气密性试验记录"},
                    {"name": "安全阀校验记录", "required": True, "description": "安全阀校验记录及铅封"},
                    {"name": "压力表校验记录", "required": True, "description": "压力表校验记录"},
                ])
    
    # 磨机设备增加专用资料
    if "磨机" in equipment:
        for vol in volumes:
            if vol["volume"] == "第三卷 安装施工记录":
                vol["documents"].extend([
                    {"name": "主轴承轴瓦刮研记录", "required": True, "description": "主轴承轴瓦刮研接触点记录（≥2点/cm²）"},
                    {"name": "大齿圈安装检测记录", "required": True, "description": "大齿圈端面/径向跳动检测记录"},
                    {"name": "齿轮啮合检测记录", "required": True, "description": "齿轮啮合间隙/接触率检测记录"},
                    {"name": "衬板安装记录", "required": True, "description": "筒体衬板安装紧固力矩记录"},
                ])
    
    # 炉类设备增加专用资料
    if "炉" in equipment:
        for vol in volumes:
            if vol["volume"] == "第三卷 安装施工记录":
                vol["documents"].extend([
                    {"name": "炉壳焊接无损检测记录", "required": True, "description": "炉壳焊缝RT/UT检测记录"},
                    {"name": "铜水套水压试验记录", "required": True, "description": "铜水套逐块水压试验记录"},
                    {"name": "耐火砌筑记录", "required": True, "description": "耐火砖/浇注料砌筑记录"},
                ])
            if vol["volume"] == "第六卷 试运转记录":
                vol["documents"].extend([
                    {"name": "烘炉记录", "required": True, "description": "按烘炉曲线升温记录"},
                    {"name": "烘炉曲线记录", "required": True, "description": "烘炉温度曲线记录"},
                ])
    
    return volumes


def _get_equipment_specific_archive(equipment: str, detail: dict) -> list:
    """获取设备专用竣工资料要求。"""
    requirements = []
    
    # 从设备验收项目生成
    acceptance_items = detail.get("acceptance_items", [])
    for item in acceptance_items:
        requirements.append({
            "item": item,
            "requirement": f"{item}必须有完整的施工记录和验收记录，记录数据真实、准确、完整，签字齐全",
            "records_needed": [f"{item}施工记录", f"{item}验收记录"],
        })
    
    # 从施工要点生成
    key_points = detail.get("construction_key_points", [])
    for point in key_points[:5]:  # 只取前5条
        requirements.append({
            "item": point[:20] + "..." if len(point) > 20 else point,
            "requirement": point,
            "records_needed": ["施工记录", "检测记录"],
        })
    
    return requirements


def get_archive_template() -> dict:
    """获取竣工资料组卷模板。"""
    return {
        "ok": True,
        "volumes": ARCHIVE_VOLUMES,
        "total_volumes": len(ARCHIVE_VOLUMES),
        "total_documents": sum(len(v["documents"]) for v in ARCHIVE_VOLUMES),
    }


def check_archive_completeness(
    equipment_name: str,
    existing_documents: list,
) -> dict:
    """
    检查竣工资料完整性。
    
    Args:
        equipment_name: 设备名称
        existing_documents: 已有资料列表
    
    Returns:
        资料完整性检查结果
    """
    # 生成竣工资料目录
    archive_result = generate_completion_archive(equipment_name)
    if not archive_result.get("ok"):
        return archive_result
    
    volumes = archive_result["volumes"]
    
    # 检查每卷资料完整性
    volume_results = []
    total_required = 0
    total_existing = 0
    missing_required = []
    
    for vol in volumes:
        if vol.get("applicable") is False:
            continue
        
        vol_required = 0
        vol_existing = 0
        vol_missing = []
        
        for doc in vol["documents"]:
            if doc["required"]:
                vol_required += 1
                total_required += 1
                if _doc_exists(doc["name"], existing_documents):
                    vol_existing += 1
                    total_existing += 1
                else:
                    vol_missing.append(doc)
                    missing_required.append({"volume": vol["volume"], "document": doc})
        
        completion_rate = round(vol_existing / max(vol_required, 1) * 100, 1)
        volume_results.append({
            "volume": vol["volume"],
            "description": vol["description"],
            "required": vol_required,
            "existing": vol_existing,
            "missing": len(vol_missing),
            "completion_rate": completion_rate,
            "missing_documents": vol_missing,
        })
    
    overall_completion = round(total_existing / max(total_required, 1) * 100, 1)
    
    return {
        "ok": True,
        "equipment": equipment_name,
        "total_required": total_required,
        "total_existing": total_existing,
        "missing_count": len(missing_required),
        "overall_completion_rate": overall_completion,
        "can_archive": overall_completion >= 95,
        "volume_results": volume_results,
        "missing_required_documents": missing_required,
        "suggestion": "资料齐全，可以组卷归档" if overall_completion >= 95 else f"资料不完整，缺少{len(missing_required)}项必备资料，建议补充完善后再组卷",
        "checked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _doc_exists(doc_name: str, existing_docs: list) -> bool:
    """检查资料是否已存在（模糊匹配）。"""
    doc_name_lower = doc_name.lower()
    for existing in existing_docs:
        existing_lower = existing.lower()
        if doc_name_lower == existing_lower:
            return True
        if doc_name_lower in existing_lower or existing_lower in doc_name_lower:
            return True
    return False


def generate_transmittal(
    equipment_name: str,
    project_name: str = "矿山工程项目",
    workshop: str = "",
    construction_unit: str = "",
    receiver_unit: str = "",
) -> dict:
    """
    生成竣工资料移交单。
    
    Args:
        equipment_name: 设备名称
        project_name: 项目名称
        workshop: 车间
        construction_unit: 施工单位
        receiver_unit: 接收单位
    
    Returns:
        竣工资料移交单
    """
    archive_result = generate_completion_archive(equipment_name, project_name, workshop, construction_unit)
    if not archive_result.get("ok"):
        return archive_result
    
    return {
        "ok": True,
        "title": f"{equipment_name}竣工资料移交单",
        "project_name": project_name,
        "workshop": workshop,
        "equipment": equipment_name,
        "construction_unit": construction_unit,
        "receiver_unit": receiver_unit,
        "transfer_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "archive_summary": {
            "total_volumes": archive_result["total_volumes"],
            "total_documents": archive_result["total_documents"],
            "required_documents": archive_result["required_documents"],
            "optional_documents": archive_result["optional_documents"],
        },
        "volume_list": [{"volume": v["volume"], "document_count": len(v["documents"])} for v in archive_result["volumes"]],
        "transfer_items": [
            {"item": "纸质竣工资料", "quantity": f"{archive_result['total_volumes']}卷", "unit": "卷"},
            {"item": "电子竣工资料（PDF）", "quantity": "1套", "unit": "套"},
            {"item": "竣工图", "quantity": "1套", "unit": "套"},
            {"item": "备品备件", "quantity": "按清单", "unit": "批"},
            {"item": "专用工具", "quantity": "按清单", "unit": "批"},
        ],
        "signatures": [
            {"role": "移交单位（施工单位）", "name": construction_unit, "signature": "", "date": ""},
            {"role": "接收单位（建设单位）", "name": receiver_unit, "signature": "", "date": ""},
            {"role": "监理单位", "name": "", "signature": "", "date": ""},
            {"role": "见证人", "name": "", "signature": "", "date": ""},
        ],
        "notes": "本移交单一式四份，移交单位、接收单位、监理单位、档案室各存一份。移交资料必须完整、准确、系统，符合国家档案管理规定。",
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
