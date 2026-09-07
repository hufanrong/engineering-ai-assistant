"""
v0.1.86：矿山设备竣工资料组卷优化（按工艺流程组卷）

按矿山工艺流程（破碎→磨矿→选别→脱水→冶炼）组织竣工资料卷册，
每个工艺流程作为一个卷册，卷册内按设备组织，设备内按资料阶段组织。
"""

import os
import json
import datetime
from typing import Optional


# ============================================================
# 矿山工艺流程定义
# ============================================================

MINING_PROCESS_FLOW = {
    "1. 破碎系统": {
        "order": 1,
        "description": "粗碎→中碎→细碎→筛分，将原矿破碎至合格粒度",
        "equipment_types": [
            "颚式破碎机", "圆锥破碎机", "反击式破碎机", "锤式破碎机", "辊式破碎机",
            "振动筛", "圆振动筛", "直线振动筛", "高频筛", "弛张筛",
            "给料机", "板式给料机", "振动给料机", "螺旋给料机", "圆盘给料机",
            "皮带输送机", "胶带输送机", "矿仓", "卸料器",
        ],
        "key_equipment": ["颚式破碎机", "圆锥破碎机", "振动筛"],
        "archive_volume_name": "第一卷 破碎系统竣工资料",
    },
    "2. 磨矿系统": {
        "order": 2,
        "description": "一段磨矿→二段磨矿→分级，将破碎产品磨至选别粒度",
        "equipment_types": [
            "球磨机", "棒磨机", "自磨机", "半自磨机", "砾磨机",
            "螺旋分级机", "水力旋流器", "高频细筛",
            "矿浆泵", "渣浆泵", "隔膜泵", "柱塞泵",
            "搅拌槽", "矿浆搅拌槽",
            "皮带输送机", "螺旋输送机", "斗式提升机",
        ],
        "key_equipment": ["球磨机", "半自磨机", "螺旋分级机", "水力旋流器"],
        "archive_volume_name": "第二卷 磨矿系统竣工资料",
    },
    "3. 选别系统": {
        "order": 3,
        "description": "浮选→磁选→重选，根据矿石类型选择选别方法，提高精矿品位",
        "equipment_types": [
            "浮选机", "机械搅拌浮选机", "充气式浮选机", "浮选柱",
            "磁选机", "湿式磁选机", "干式磁选机", "高梯度磁选机", "强磁选机",
            "跳汰机", "摇床", "螺旋溜槽", "离心选矿机", "重介质旋流器",
            "搅拌槽", "搅拌桶", "药剂搅拌槽",
            "加药机", "药剂添加系统",
            "矿浆泵", "隔膜泵",
            "自动取样机", "在线分析仪",
        ],
        "key_equipment": ["浮选机", "磁选机", "加药机"],
        "archive_volume_name": "第三卷 选别系统竣工资料",
    },
    "4. 脱水系统": {
        "order": 4,
        "description": "浓缩→过滤→干燥，将精矿脱水至合格水分",
        "equipment_types": [
            "浓缩机", "高效浓缩机", "深锥浓缩机", "斜板浓密机",
            "压滤机", "板框压滤机", "厢式压滤机", "隔膜压滤机",
            "真空过滤机", "陶瓷过滤机", "带式过滤机", "圆盘过滤机",
            "回转干燥机", "喷雾干燥机", "流化床干燥机",
            "矿浆泵", "离心泵",
            "皮带输送机", "螺旋输送机",
            "冷却塔", "循环水泵",
        ],
        "key_equipment": ["浓缩机", "压滤机", "陶瓷过滤机"],
        "archive_volume_name": "第四卷 脱水系统竣工资料",
    },
    "5. 火法冶炼系统": {
        "order": 5,
        "description": "熔炼→吹炼→精炼→制酸，将精矿冶炼成金属",
        "equipment_types": [
            "闪速炉", "熔池熔炼炉", "艾萨炉", "奥斯麦特炉", "诺兰达炉",
            "回转窑", "鼓风炉", "矿热电炉", "熔炼电炉", "贫化电炉",
            "转炉", "PS转炉", "顶吹转炉", "底吹转炉",
            "阳极炉", "精炼炉", "回转式精炼炉", "倾动式精炼炉",
            "沉降炉", "保温炉", "混合炉", "静置炉",
            "余热锅炉", "废热锅炉", "辐射废热锅炉", "对流废热锅炉",
            "转化器", "干吸塔", "干燥塔", "吸收塔", "电除雾器",
            "电除尘器", "布袋除尘器", "旋风除尘器", "湿式除尘器",
            "高温风机", "引风机", "鼓风机", "罗茨风机",
            "冶金起重机", "铸造起重机", "加料起重机", "阳极炉起重机",
            "阳极浇铸机", "圆盘浇铸机", "阴极剥片机组", "永久阴极机组",
            "捞渣机", "出渣机", "水淬渣设备", "粒化设备",
            "铜包", "钢包", "中间包", "铁水包", "渣包",
            "燃烧器", "燃烧系统", "重油燃烧器", "煤气燃烧器", "天然气燃烧器",
            "制氧设备", "空分设备", "氧枪", "喷枪",
            "加料系统", "配料系统", "定量给料系统",
        ],
        "key_equipment": ["闪速炉", "转炉", "阳极炉", "余热锅炉"],
        "archive_volume_name": "第五卷 火法冶炼系统竣工资料",
    },
    "6. 湿法冶炼系统": {
        "order": 6,
        "description": "浸出→萃取→电积，将精矿湿法冶炼成金属",
        "equipment_types": [
            "浸出槽", "搅拌浸出槽", "空气搅拌浸出槽", "渗滤浸出槽",
            "高压釜", "压力浸出釜", "钛钢复合高压釜",
            "萃取箱", "混合澄清槽", "萃取柱", "离心萃取机",
            "电积槽", "电解槽", "电沉积槽", "电解精炼槽",
            "离子交换柱", "树脂塔", "吸附柱",
            "中和槽", "中和反应槽", "石灰乳制备槽",
            "沉淀槽", "反应沉淀槽", "硫化沉淀槽",
            "溶液储槽", "储液罐", "酸储槽", "碱储槽",
            "酸泵", "碱泵", "耐腐蚀泵", "氟塑料泵",
            "换热器", "加热器", "冷却器", "石墨换热器", "钛换热器",
            "蒸发器", "多效蒸发器", "MVR蒸发器", "强制循环蒸发器",
            "结晶器", "结晶槽", "奥斯陆结晶器",
            "离心机", "卧式螺旋离心机", "活塞推料离心机",
            "净化槽", "净化除杂槽", "锌粉置换槽",
            "阳极泥处理设备", "贵金属回收设备",
            "压滤机", "板框压滤机", "厢式压滤机",
            "浓缩机", "高效浓缩机",
        ],
        "key_equipment": ["高压釜", "萃取箱", "电积槽", "蒸发器"],
        "archive_volume_name": "第六卷 湿法冶炼系统竣工资料",
    },
    "7. 公用辅助系统": {
        "order": 7,
        "description": "通风、压气、供水、供电、仪表、自动化等公用辅助系统",
        "equipment_types": [
            "矿用通风机", "通风机", "引风机", "鼓风机",
            "矿用空压机", "空压机", "螺杆空压机", "离心空压机",
            "矿用排水泵", "排水泵", "离心泵", "多级泵",
            "冷却塔", "凉水塔", "循环水泵",
            "矿用变压器", "变压器", "高压开关柜", "低压开关柜",
            "DCS系统", "PLC系统", "仪表柜", "操作站",
            "皮带输送机", "胶带输送机", "斗式提升机", "螺旋输送机", "埋刮板输送机",
            "矿井提升机", "绞车", "卷扬机",
            "装载机", "铲运机", "挖掘机", "矿用自卸车",
            "取样机", "自动取样机", "在线分析仪",
            "药剂制备系统", "加药系统",
            "水处理系统", "污水处理系统",
            "消防系统", "消防泵", "消防水池",
        ],
        "key_equipment": ["空压机", "通风机", "变压器"],
        "archive_volume_name": "第七卷 公用辅助系统竣工资料",
    },
}


# 资料阶段定义
ARCHIVE_STAGES = {
    "开箱": ["设备开箱检验记录", "设备质量证明文件", "设备说明书", "设备装箱单"],
    "基础": ["设备基础验收记录", "基础隐蔽工程验收记录", "二次灌浆记录"],
    "安装": ["设备安装记录", "设备找平找正记录", "地脚螺栓紧固记录", "衬板安装记录", "内件安装记录"],
    "隐蔽": ["隐蔽工程验收记录", "管道隐蔽工程验收记录", "电气隐蔽工程验收记录"],
    "配管": ["管道安装记录", "管道压力试验记录", "管道吹扫记录", "阀门试验记录"],
    "电气": ["电气安装记录", "电缆敷设记录", "接地电阻测试记录", "绝缘电阻测试记录", "电机试运转记录"],
    "仪表": ["仪表安装记录", "仪表校验记录", "DCS/PLC调试记录", "联锁试验记录"],
    "试运转": ["单机试运转记录", "联动试运转记录", "空载试运转记录", "负载试运转记录", "轴承温升记录", "振动测试记录"],
    "试验": ["耐压试验记录", "气密性试验记录", "烘炉记录", "煮炉记录", "衬里检测记录"],
    "资料": ["设备竣工图", "竣工报告", "竣工验收证书", "工程移交证书"],
}


def get_process_flow() -> dict:
    """获取矿山工艺流程定义。"""
    return MINING_PROCESS_FLOW


def get_equipment_process(dev_type: str) -> str:
    """获取设备所属工艺流程。"""
    for process, info in MINING_PROCESS_FLOW.items():
        if dev_type in info.get("equipment_types", []):
            return process
    return "7. 公用辅助系统"


def organize_by_process_flow(devices: list = None) -> dict:
    """
    按工艺流程组卷竣工资料。
    
    Args:
        devices: 设备列表，每个设备含 tag, name, type, workshop, status 等
    
    Returns:
        按工艺流程组织的卷册结构
    """
    if devices is None:
        # 从 relations 中获取设备列表
        try:
            from . import relations as _rel
            g = _rel.load_relations()
            devices = []
            for tag, dev in g.get("devices", {}).items():
                devices.append({
                    "tag": tag,
                    "name": dev.get("name", ""),
                    "type": dev.get("type", ""),
                    "workshop": dev.get("workshop", ""),
                    "status": dev.get("status", "pending"),
                    "elevation": dev.get("elevation"),
                })
        except Exception:
            devices = []
    
    # 按工艺流程分组
    volumes = {}
    for process, info in MINING_PROCESS_FLOW.items():
        volumes[process] = {
            "volume_name": info["archive_volume_name"],
            "order": info["order"],
            "description": info["description"],
            "equipment_types": info.get("equipment_types", []),
            "key_equipment": info.get("key_equipment", []),
            "devices": [],
            "device_count": 0,
            "total_docs": 0,
            "completed_docs": 0,
            "stages": {},
        }
    
    # 未分类设备
    uncategorized = []
    
    for dev in devices:
        dev_type = dev.get("type", "")
        process = get_equipment_process(dev_type)
        
        if process in volumes:
            volumes[process]["devices"].append(dev)
            volumes[process]["device_count"] += 1
            
            # 统计资料阶段
            dev_status = dev.get("status", "pending")
            for stage, docs in ARCHIVE_STAGES.items():
                if stage not in volumes[process]["stages"]:
                    volumes[process]["stages"][stage] = {
                        "doc_count": 0,
                        "completed_count": 0,
                        "docs": [],
                    }
                volumes[process]["stages"][stage]["doc_count"] += len(docs)
                volumes[process]["total_docs"] += len(docs)
                
                # 根据设备状态判断资料完成情况
                if dev_status in ["completed", "accepted"]:
                    volumes[process]["stages"][stage]["completed_count"] += len(docs)
                    volumes[process]["completed_docs"] += len(docs)
                elif dev_status == "in_progress":
                    # 进行中的设备，开箱和基础阶段资料应已完成
                    if stage in ["开箱", "基础"]:
                        volumes[process]["stages"][stage]["completed_count"] += len(docs)
                        volumes[process]["completed_docs"] += len(docs)
        else:
            uncategorized.append(dev)
    
    # 排序卷册
    sorted_volumes = sorted(volumes.items(), key=lambda x: x[1]["order"])
    
    result = {
        "ok": True,
        "total_volumes": len([v for v in volumes.values() if v["device_count"] > 0]),
        "total_devices": len(devices),
        "total_docs": sum(v["total_docs"] for v in volumes.values()),
        "completed_docs": sum(v["completed_docs"] for v in volumes.values()),
        "completion_rate": round(
            sum(v["completed_docs"] for v in volumes.values()) / 
            max(sum(v["total_docs"] for v in volumes.values()), 1) * 100, 1
        ),
        "uncategorized_count": len(uncategorized),
        "uncategorized": uncategorized[:20],  # 最多显示20个
        "volumes": [
            {
                "process": process,
                "volume_name": info["volume_name"],
                "order": info["order"],
                "description": info["description"],
                "device_count": info["device_count"],
                "total_docs": info["total_docs"],
                "completed_docs": info["completed_docs"],
                "completion_rate": round(
                    info["completed_docs"] / max(info["total_docs"], 1) * 100, 1
                ),
                "key_equipment": info["key_equipment"],
                "devices": info["devices"][:50],  # 每卷最多显示50个设备
                "stages": info["stages"],
            }
            for process, info in sorted_volumes
            if info["device_count"] > 0  # 只显示有设备的卷册
        ],
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    return result


def get_volume_catalog() -> dict:
    """获取竣工资料卷册目录（按工艺流程）。"""
    volumes = []
    for process, info in sorted(MINING_PROCESS_FLOW.items(), key=lambda x: x[1]["order"]):
        volumes.append({
            "volume_number": f"第{info['order']}卷",
            "volume_name": info["archive_volume_name"],
            "process": process,
            "description": info["description"],
            "key_equipment": info["key_equipment"],
            "equipment_count": len(info["equipment_types"]),
        })
    
    return {
        "ok": True,
        "total_volumes": len(volumes),
        "volumes": volumes,
        "stages": list(ARCHIVE_STAGES.keys()),
    }


def get_process_equipment_list(process: str) -> dict:
    """获取指定工艺流程的设备清单。"""
    if process not in MINING_PROCESS_FLOW:
        return {"ok": False, "error": f"未找到工艺流程: {process}"}
    
    info = MINING_PROCESS_FLOW[process]
    return {
        "ok": True,
        "process": process,
        "volume_name": info["archive_volume_name"],
        "description": info["description"],
        "key_equipment": info["key_equipment"],
        "equipment_types": info["equipment_types"],
        "equipment_count": len(info["equipment_types"]),
    }


def generate_archive_transmittal(volume_name: str = "", process: str = "") -> dict:
    """生成竣工资料移交单。"""
    volume_info = None
    if process and process in MINING_PROCESS_FLOW:
        volume_info = MINING_PROCESS_FLOW[process]
    elif volume_name:
        for p, info in MINING_PROCESS_FLOW.items():
            if volume_name in info["archive_volume_name"]:
                volume_info = info
                process = p
                break
    
    if not volume_info:
        return {"ok": False, "error": "未找到指定卷册"}
    
    transmittal = {
        "ok": True,
        "transmittal_title": f"{volume_info['archive_volume_name']} 移交单",
        "volume_name": volume_info["archive_volume_name"],
        "process": process,
        "description": volume_info["description"],
        "key_equipment": volume_info["key_equipment"],
        "stages": list(ARCHIVE_STAGES.keys()),
        "transmittal_items": [
            {"item": "设备开箱检验记录", "count": "按设备数量", "remarks": "每台设备一份"},
            {"item": "设备安装记录", "count": "按设备数量", "remarks": "每台设备一份"},
            {"item": "设备找平找正记录", "count": "按设备数量", "remarks": "每台设备一份"},
            {"item": "隐蔽工程验收记录", "count": "按隐蔽部位", "remarks": "每个隐蔽部位一份"},
            {"item": "单机试运转记录", "count": "按设备数量", "remarks": "每台设备一份"},
            {"item": "联动试运转记录", "count": "按系统", "remarks": "每个系统一份"},
            {"item": "设备竣工图", "count": "按设备数量", "remarks": "每台设备一份"},
            {"item": "设备质量证明文件", "count": "按设备数量", "remarks": "每台设备一份"},
            {"item": "设备说明书", "count": "按设备数量", "remarks": "每台设备一份"},
        ],
        "transmittal_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "transmitter": "",  # 移交人
        "receiver": "",     # 接收人
        "remarks": "本移交单一式三份，移交单位、接收单位、存档各一份",
    }
    
    return transmittal
