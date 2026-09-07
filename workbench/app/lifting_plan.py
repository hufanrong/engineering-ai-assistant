"""
v0.1.68：设备安装位置与吊装方案联动

根据设备位置（车间、标高、坐标、相邻设备）自动生成吊装方案要点，
包括吊装环境分析、吊装参数建议、吊装顺序建议、安全注意事项。
"""

import os
import json
import math
import datetime
from typing import Optional


_PLAN_FILE = os.path.join("data", "lifting_plans.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_plans() -> dict:
    if os.path.exists(_PLAN_FILE):
        try:
            with open(_PLAN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_plans(plans: dict):
    _ensure_dirs()
    with open(_PLAN_FILE, "w", encoding="utf-8") as f:
        json.dump(plans, f, ensure_ascii=False, indent=2)


# 设备类型吊装参数参考
DEVICE_LIFTING_PARAMS = {
    "泵": {
        "estimated_weight": 1.5,  # 吨
        "estimated_height": 1.5,  # 米
        "crane_tons": 25,
        "lifting_radius": 6,
        "lifting_method": "单机吊装",
        "special_requirements": [],
    },
    "压缩机": {
        "estimated_weight": 8.0,
        "estimated_height": 2.5,
        "crane_tons": 80,
        "lifting_radius": 8,
        "lifting_method": "单机吊装",
        "special_requirements": ["压缩机对中要求高，吊装时需保持水平", "润滑油系统需在吊装前完成冲洗"],
    },
    "塔器": {
        "estimated_weight": 15.0,
        "estimated_height": 15.0,
        "crane_tons": 200,
        "lifting_radius": 12,
        "lifting_method": "双机抬吊或单机溜尾",
        "special_requirements": ["塔器高度大，需确认吊装路线无障碍物", "塔器垂直度要求高，需使用经纬仪监测", "内件安装需在塔器就位固定后进行"],
    },
    "换热器": {
        "estimated_weight": 5.0,
        "estimated_height": 3.0,
        "crane_tons": 50,
        "lifting_radius": 7,
        "lifting_method": "单机吊装",
        "special_requirements": ["换热器抽芯检查需预留抽芯空间", "水压试验需在管道连接前完成"],
    },
    "容器": {
        "estimated_weight": 3.0,
        "estimated_height": 2.5,
        "crane_tons": 30,
        "lifting_radius": 6,
        "lifting_method": "单机吊装",
        "special_requirements": [],
    },
    "风机": {
        "estimated_weight": 2.0,
        "estimated_height": 2.0,
        "crane_tons": 25,
        "lifting_radius": 6,
        "lifting_method": "单机吊装",
        "special_requirements": ["风机叶轮需做动平衡试验", "进出口管道需设置柔性连接"],
    },
    "电机": {
        "estimated_weight": 1.0,
        "estimated_height": 1.0,
        "crane_tons": 16,
        "lifting_radius": 5,
        "lifting_method": "单机吊装",
        "special_requirements": ["电机绝缘测试需在吊装前完成", "电机与泵对中需在管道连接后复核"],
    },
    "阀门": {
        "estimated_weight": 0.5,
        "estimated_height": 0.5,
        "crane_tons": 8,
        "lifting_radius": 4,
        "lifting_method": "人工或手动葫芦",
        "special_requirements": ["阀门需做强度和严密性试验"],
    },
    "储罐": {
        "estimated_weight": 20.0,
        "estimated_height": 12.0,
        "crane_tons": 250,
        "lifting_radius": 15,
        "lifting_method": "倒装法或正装法",
        "special_requirements": ["储罐体积大，需确认现场组装空间", "罐底基础平整度要求高", "焊接需考虑防风措施", "充水试验需在所有附件安装完成后进行"],
    },
    # 矿山/选矿设备
    "破碎机": {
        "estimated_weight": 15.0,
        "estimated_height": 4.0,
        "crane_tons": 50,
        "lifting_radius": 8,
        "lifting_method": "单机吊装",
        "special_requirements": ["破碎机重心高，吊装需注意平衡", "颚式破碎机需整体吊装或分体吊装后组装", "圆锥破碎机主轴需垂直吊装", "吊装前确认基础螺栓孔位置"],
    },
    "磨矿机": {
        "estimated_weight": 80.0,
        "estimated_height": 5.0,
        "crane_tons": 200,
        "lifting_radius": 12,
        "lifting_method": "双机抬吊或单机吊装",
        "special_requirements": ["磨机筒体重量大，需编制专项吊装方案", "筒体吊装需使用专用吊耳或吊带", "端盖与筒体组装后整体吊装", "吊装前确认主轴承已安装找平", "大型磨机需考虑厂房内桥式起重机配合"],
    },
    "分级机": {
        "estimated_weight": 8.0,
        "estimated_height": 6.0,
        "crane_tons": 25,
        "lifting_radius": 6,
        "lifting_method": "单机吊装",
        "special_requirements": ["螺旋分级机槽体长，吊装需多点吊挂", "旋流器组需整体吊装", "注意安装倾角"],
    },
    "浮选机": {
        "estimated_weight": 5.0,
        "estimated_height": 3.0,
        "crane_tons": 16,
        "lifting_radius": 5,
        "lifting_method": "单机吊装",
        "special_requirements": ["多槽浮选机可单槽吊装后连接", "槽体吊装注意保护衬里", "叶轮定子需在槽体就位后安装"],
    },
    "磁选机": {
        "estimated_weight": 6.0,
        "estimated_height": 3.0,
        "crane_tons": 20,
        "lifting_radius": 5,
        "lifting_method": "单机吊装",
        "special_requirements": ["磁选机周围避免铁磁性物体", "滚筒吊装注意磁系保护", "湿式磁选机注意槽体密封"],
    },
    "浓密机": {
        "estimated_weight": 25.0,
        "estimated_height": 8.0,
        "crane_tons": 50,
        "lifting_radius": 15,
        "lifting_method": "单机吊装或分段吊装",
        "special_requirements": ["浓密机池体直径大，需现场组装", "中心传动装置需精确吊装就位", "耙架需在池体就位后安装", "注意池体水平度"],
    },
    "过滤机": {
        "estimated_weight": 10.0,
        "estimated_height": 4.0,
        "crane_tons": 25,
        "lifting_radius": 6,
        "lifting_method": "单机吊装",
        "special_requirements": ["压滤机机架需整体吊装", "真空过滤机滤盘需水平吊装", "注意滤布保护"],
    },
    # 湿法冶炼设备
    "浸出槽": {
        "estimated_weight": 12.0,
        "estimated_height": 8.0,
        "crane_tons": 25,
        "lifting_radius": 6,
        "lifting_method": "单机吊装",
        "special_requirements": ["浸出槽衬里需保护，禁止焊接和敲击", "大型浸出槽可现场卷制组装", "搅拌器需在槽体就位后安装", "注意防腐层检查"],
    },
    "萃取设备": {
        "estimated_weight": 8.0,
        "estimated_height": 4.0,
        "crane_tons": 20,
        "lifting_radius": 5,
        "lifting_method": "单机吊装",
        "special_requirements": ["萃取槽体需水平安装", "有机相区域需防静电", "多级萃取槽需按序连接"],
    },
    "电解槽": {
        "estimated_weight": 5.0,
        "estimated_height": 2.0,
        "crane_tons": 16,
        "lifting_radius": 4,
        "lifting_method": "单机吊装",
        "special_requirements": ["电解槽需绝缘安装", "衬里需保护", "导电排需在槽体就位后安装", "注意酸雾防护"],
    },
    "高压釜": {
        "estimated_weight": 60.0,
        "estimated_height": 10.0,
        "crane_tons": 150,
        "lifting_radius": 10,
        "lifting_method": "单机吊装或双机抬吊",
        "special_requirements": ["高压釜属于压力容器，吊装需有资质单位", "需编制专项吊装方案并专家论证", "使用制造厂指定吊耳", "吊装前确认安全附件已安装", "注意釜体衬里保护"],
    },
    "蒸发结晶器": {
        "estimated_weight": 20.0,
        "estimated_height": 12.0,
        "crane_tons": 50,
        "lifting_radius": 8,
        "lifting_method": "单机吊装",
        "special_requirements": ["多效蒸发设备需按效序吊装", "加热器列管需保护", "结晶器搅拌器需在就位后安装", "注意设备保温"],
    },
    # 火法冶炼设备
    "熔炼炉": {
        "estimated_weight": 100.0,
        "estimated_height": 15.0,
        "crane_tons": 200,
        "lifting_radius": 15,
        "lifting_method": "分段吊装+现场组装",
        "special_requirements": ["熔炼炉体积大，需现场组装", "炉体钢结构分段吊装", "铜水套需逐块吊装就位", "炉衬砌筑需在炉体就位后进行", "需编制专项吊装方案"],
    },
    "吹炼炉": {
        "estimated_weight": 150.0,
        "estimated_height": 8.0,
        "crane_tons": 300,
        "lifting_radius": 12,
        "lifting_method": "双机抬吊或大型履带吊",
        "special_requirements": ["转炉炉体重量大，需编制专项吊装方案", "炉体与托圈组装后整体吊装", "使用专用吊耳", "吊装前确认托轮装置已安装找平", "需专家论证"],
    },
    "回转窑": {
        "estimated_weight": 120.0,
        "estimated_height": 4.0,
        "crane_tons": 200,
        "lifting_radius": 20,
        "lifting_method": "分段吊装+现场组装焊接",
        "special_requirements": ["回转窑长度大，需分段吊装现场焊接", "焊接需100%无损检测", "吊装前确认托轮装置已安装找平", "注意窑体斜度", "需编制专项吊装方案"],
    },
    "余热锅炉": {
        "estimated_weight": 80.0,
        "estimated_height": 20.0,
        "crane_tons": 150,
        "lifting_radius": 12,
        "lifting_method": "分段吊装+现场组装",
        "special_requirements": ["余热锅炉属于压力容器，安装需有资质单位", "汽包需单独吊装就位", "受热面管束需逐组吊装", "钢架需先安装找正", "需编制专项吊装方案"],
    },
    "收尘设备": {
        "estimated_weight": 15.0,
        "estimated_height": 10.0,
        "crane_tons": 50,
        "lifting_radius": 8,
        "lifting_method": "单机吊装或分段吊装",
        "special_requirements": ["大型除尘器壳体需现场组装", "滤袋/极板需在壳体就位后安装", "注意壳体气密性", "灰斗需精确吊装就位"],
    },
    "排烟机": {
        "estimated_weight": 20.0,
        "estimated_height": 4.0,
        "crane_tons": 50,
        "lifting_radius": 6,
        "lifting_method": "单机吊装",
        "special_requirements": ["排烟机叶轮需做动平衡复检", "机壳需水平安装", "转子需精确吊装就位", "注意轴承保护", "大型排烟机需厂房内桥式起重机配合"],
    },
    "冶金起重机": {
        "estimated_weight": 50.0,
        "estimated_height": 2.0,
        "crane_tons": 100,
        "lifting_radius": 15,
        "lifting_method": "厂房内桥式起重机或大型汽车吊",
        "special_requirements": ["冶金起重机属于特种设备，安装需有资质单位", "桥架需在轨道安装完成后吊装", "大车运行机构需先安装", "需编制专项吊装方案", "注意轨道上方作业空间"],
    },

}

DEFAULT_LIFTING_PARAMS = {
    "estimated_weight": 2.0,
    "estimated_height": 2.0,
    "crane_tons": 25,
    "lifting_radius": 6,
    "lifting_method": "单机吊装",
    "special_requirements": [],
}



# v0.1.84：合并矿山设备吊装参数
from .mining_equipment import MINING_LIFTING_PARAMS as _MINING_LIFTING
DEVICE_LIFTING_PARAMS.update(_MINING_LIFTING)

def get_lifting_params(dev_type: str) -> dict:
    """v0.1.68：获取设备类型吊装参数参考。"""
    return DEVICE_LIFTING_PARAMS.get(dev_type, DEFAULT_LIFTING_PARAMS)


def analyze_lifting_environment(spatial_info: dict) -> list:
    """v0.1.68：分析吊装环境。
    
    Args:
        spatial_info: 设备空间信息
    
    Returns:
        吊装环境分析要点列表
    """
    points = []
    
    workshop = spatial_info.get("workshop", "")
    elevation = spatial_info.get("elevation")
    adjacent = spatial_info.get("adjacent_devices", [])
    dev_type = spatial_info.get("type", "")
    x, y = spatial_info.get("x"), spatial_info.get("y")
    
    # 车间环境
    if workshop:
        points.append(f"吊装地点位于{workshop}，需确认车间内吊装通道畅通、吊车占位空间充足")
        points.append(f"需确认车间内桥式起重机（天车）的额定起重量和作业半径是否满足吊装要求")
    else:
        points.append("吊装地点尚未明确分配车间，需先确认设备安装位置和吊装路线")
    
    # 标高分析
    if elevation is not None:
        if elevation > 5:
            points.append(f"设备安装标高{elevation}m，属于高位吊装，需搭设高空作业平台，吊装高度需增加{elevation}m")
            points.append("高位吊装需使用更长的吊装绳索，确认吊车起升高度满足要求")
        elif elevation > 2:
            points.append(f"设备安装标高{elevation}m，吊装高度需增加{elevation}m，注意高处作业安全")
        else:
            points.append(f"设备安装标高{elevation}m，属于低位吊装，施工条件相对较好")
    else:
        points.append("设备标高信息缺失，需从图纸或设计文件中确认安装标高和吊装高度")
    
    # 相邻设备影响
    if adjacent:
        points.append(f"设备周围{len(adjacent)}台相邻设备（最近距离{adjacent[0]['distance']}m），吊装时需注意保护已安装设备")
        if len(adjacent) >= 3:
            points.append("设备周围设备密集，吊装空间受限，需合理安排吊装顺序和吊车占位")
            points.append("密集区域吊装建议使用小型吊车或手动葫芦，避免大型吊车占位影响其他作业")
    else:
        points.append("设备周围无相邻设备，吊装空间充足")
    
    # 坐标分析
    if x is not None and y is not None:
        points.append(f"设备坐标位置（X:{x}m, Y:{y}m），需确认该位置上方无管道、电缆桥架等障碍物")
    
    # 设备类型特殊环境
    type_env = {
        "塔器": ["塔器高度大，需确认吊装路线全程无障碍物，包括厂房门洞、管廊、电缆桥架", "塔器吊装需办理一级吊装作业许可，吊装前进行安全技术交底", "塔器就位后需立即进行垂直度监测和临时固定"],
        "压缩机": ["压缩机重量大，需确认基础养护期已到（一般7-14天）", "压缩机吊装时需保持水平，避免倾斜导致内部部件损坏"],
        "储罐": ["储罐体积大，需确认现场组装空间和吊装作业半径", "储罐倒装法施工需配置提升装置和同步控制系统"],
        "换热器": ["换热器重量较大，需确认吊装能力满足要求", "换热器抽芯检查需预留抽芯空间，吊装时注意保护管束"],
    }
    if dev_type in type_env:
        points.extend(type_env[dev_type])
    
    return points


def suggest_lifting_sequence(spatial_info: dict, all_devices: list = None) -> list:
    """v0.1.68：建议吊装顺序。
    
    Args:
        spatial_info: 设备空间信息
        all_devices: 所有设备列表（可选）
    
    Returns:
        吊装顺序建议列表
    """
    steps = [
        "吊装准备：吊车进场、占位、支腿垫板铺设、吊装索具检查、安全技术交底",
        "试吊：设备离地100-200mm，检查吊车稳定性、索具受力、设备平衡，确认无异常后正式吊装",
        "正式吊装：缓慢起升，旋转至安装位置上方，平稳下落",
        "就位初平：设备就位、初平初正、临时固定",
        "摘钩：设备固定可靠后，摘除吊装索具",
        "精平固定：设备精平精正、地脚螺栓紧固、二次灌浆",
    ]
    
    elevation = spatial_info.get("elevation")
    dev_type = spatial_info.get("type", "")
    adjacent = spatial_info.get("adjacent_devices", [])
    
    # 根据标高调整
    if elevation is not None and elevation > 3:
        steps.insert(2, f"高位吊装辅助：搭设操作平台、挂设安全网、作业人员系安全带（标高{elevation}m）")
    
    # 根据相邻设备调整
    if adjacent:
        steps.append(f"与相邻设备（{', '.join(d['tag'] for d in adjacent[:3])}）的间距复核，确保吊装过程不碰撞")
    
    # 设备类型特殊步骤
    type_steps = {
        "塔器": ["塔器溜尾：使用溜尾吊车或溜尾绳控制塔器底部，防止拖地", "塔器垂直度监测：使用经纬仪实时监测垂直度，偏差不大于塔高的1/1000"],
        "压缩机": ["压缩机水平度监测：吊装过程中保持水平，使用水平仪监测", "压缩机基础复核：吊装前复核基础尺寸、标高、螺栓孔位置"],
        "储罐": ["储罐提升系统检查：倒装法提升装置试运行、同步控制系统调试", "储罐壁板吊装：按排版图顺序吊装壁板，控制错边量和间隙"],
    }
    if dev_type in type_steps:
        for ts in type_steps[dev_type]:
            steps.insert(3, ts)
    
    return steps


def get_lifting_safety_points(spatial_info: dict) -> list:
    """v0.1.68：获取吊装安全注意事项。"""
    points = [
        "吊装作业必须由持证起重工指挥，指挥信号明确、统一",
        "吊装区域设置警戒线，非作业人员不得进入，设专人监护",
        "吊装前检查吊车支腿垫板、吊装索具、卸扣等，确保完好可靠",
        "试吊检查：设备离地100-200mm后暂停，检查吊车稳定性、索具受力、设备平衡",
        "吊装过程中严禁人员站在吊物下方，严禁随吊物升降",
        "六级及以上大风、雷雨、大雾等恶劣天气禁止吊装作业",
        "夜间吊装需有充足照明，照明灯具需设置在吊装作业影响范围外",
    ]
    
    elevation = spatial_info.get("elevation")
    dev_type = spatial_info.get("type", "")
    adjacent = spatial_info.get("adjacent_devices", [])
    
    if elevation is not None and elevation > 3:
        points.append(f"高位吊装（{elevation}m）作业人员必须佩戴速差自控器，搭设牢固的操作平台")
        points.append("高位吊装时，地面和高空需设置双向通讯，确保指挥信号清晰")
    
    if adjacent:
        points.append("设备密集区域吊装，需对已安装设备搭设防护棚或防护罩")
        points.append("多工种交叉作业时，设置隔离层或错时作业，避免物体打击")
    
    type_safety = {
        "塔器": ["塔器吊装需办理一级吊装作业许可，吊装前进行全员安全技术交底", "塔器溜尾区域设置警戒线，严禁人员进入", "塔器就位后需立即进行临时固定，固定可靠后方可摘钩"],
        "压缩机": ["压缩机吊装时，人员不得站在压缩机旋转部件的切线方向", "压缩机试运行区域设置隔声屏障，作业人员佩戴防噪声耳塞"],
        "储罐": ["储罐罐内作业需办理受限空间作业许可，强制通风，定时气体检测", "储罐焊接作业人员需佩戴防尘口罩和防护眼镜", "储罐充水试验时，需监测基础沉降，设置沉降观测点"],
        "换热器": ["换热器水压试验时，升压应缓慢，人员不得站在封头正对面", "换热器抽芯时，抽芯区域设置警戒线，防止管束滑落伤人"],
    }
    if dev_type in type_safety:
        points.extend(type_safety[dev_type])
    
    return points


def calculate_lifting_params(spatial_info: dict) -> dict:
    """v0.1.68：计算吊装参数。
    
    根据设备类型、重量、高度、标高等计算建议的吊车吨位、吊装半径、吊装高度等。
    """
    dev_type = spatial_info.get("type", "")
    elevation = spatial_info.get("elevation") or 0
    params = get_lifting_params(dev_type)
    
    # 计算实际吊装高度（设备高度 + 标高 + 吊装绳索高度 + 安全余量）
    lifting_height = params["estimated_height"] + elevation + 3.0 + 1.0  # 绳索3m + 余量1m
    
    # 计算建议吊车吨位（考虑动载系数1.1和不均衡系数1.2）
    weight = params["estimated_weight"]
    dynamic_factor = 1.1
    imbalance_factor = 1.2
    required_capacity = weight * dynamic_factor * imbalance_factor
    
    # 根据吊装半径和高度调整吊车吨位
    crane_tons = params["crane_tons"]
    if lifting_height > 10:
        crane_tons = max(crane_tons, int(required_capacity * 1.5))
    elif lifting_height > 5:
        crane_tons = max(crane_tons, int(required_capacity * 1.3))
    else:
        crane_tons = max(crane_tons, int(required_capacity * 1.2))
    
    return {
        "device_type": dev_type,
        "estimated_weight": weight,
        "estimated_height": params["estimated_height"],
        "installation_elevation": elevation,
        "calculated_lifting_height": round(lifting_height, 1),
        "required_crane_capacity": round(required_capacity, 1),
        "recommended_crane_tons": crane_tons,
        "recommended_lifting_radius": params["lifting_radius"],
        "recommended_lifting_method": params["lifting_method"],
        "special_requirements": params["special_requirements"],
    }


def generate_lifting_plan(tag: str) -> dict:
    """v0.1.68：生成设备吊装方案。
    
    Args:
        tag: 设备位号
    
    Returns:
        完整的吊装方案
    """
    from . import installation_plan as _ip
    
    # 获取设备空间信息（复用installation_plan的函数）
    spatial_info = _ip.get_device_spatial_info(tag)
    if "error" in spatial_info:
        return spatial_info
    
    # 多源检测设备类型
    from . import equipment_types as _et
    from . import relations as _rel
    if not spatial_info.get("type"):
        g = _rel.load_relations()
        devices = g.get("devices", [])
        device = next((d for d in devices if d["tag"] == tag), None)
        if device:
            spatial_info["type"] = _et.get_equipment_type_from_devices([device])
    
    # 计算吊装参数
    lifting_params = calculate_lifting_params(spatial_info)
    
    # 分析吊装环境
    environment = analyze_lifting_environment(spatial_info)
    
    # 建议吊装顺序
    sequence = suggest_lifting_sequence(spatial_info)
    
    # 安全注意事项
    safety = get_lifting_safety_points(spatial_info)
    
    plan = {
        "tag": tag,
        "name": spatial_info.get("name", tag),
        "type": spatial_info.get("type", ""),
        "workshop": spatial_info.get("workshop", ""),
        "elevation": spatial_info.get("z"),
        "x": spatial_info.get("x"),
        "y": spatial_info.get("y"),
        "generated_at": datetime.datetime.now().isoformat(),
        "lifting_params": lifting_params,
        "lifting_environment": environment,
        "lifting_sequence": sequence,
        "safety_points": safety,
        "adjacent_devices": spatial_info.get("adjacent_devices", []),
        "related_pipes": spatial_info.get("related_pipes", []),
    }
    
    # 保存方案
    plans = _load_plans()
    plans[tag] = plan
    _save_plans(plans)
    
    return plan


def list_lifting_plans() -> list:
    """v0.1.68：列出已生成的吊装方案。"""
    plans = _load_plans()
    return [{"tag": k, "name": v.get("name", k), "type": v.get("type", ""),
             "workshop": v.get("workshop", ""), "crane_tons": v.get("lifting_params", {}).get("recommended_crane_tons", 0),
             "generated_at": v.get("generated_at", "")}
            for k, v in plans.items()]


def get_lifting_stats() -> dict:
    """v0.1.68：获取吊装方案统计。"""
    plans = _load_plans()
    from . import relations as _rel
    g = _rel.load_relations()
    total_devices = len(g.get("devices", []))
    
    type_count = {}
    workshop_count = {}
    crane_distribution = {"小型(≤25t)": 0, "中型(26-80t)": 0, "大型(81-200t)": 0, "特大型(>200t)": 0}
    
    for plan in plans.values():
        t = plan.get("type", "未知")
        type_count[t] = type_count.get(t, 0) + 1
        ws = plan.get("workshop", "未分配")
        workshop_count[ws] = workshop_count.get(ws, 0) + 1
        
        crane = plan.get("lifting_params", {}).get("recommended_crane_tons", 0)
        if crane <= 25:
            crane_distribution["小型(≤25t)"] += 1
        elif crane <= 80:
            crane_distribution["中型(26-80t)"] += 1
        elif crane <= 200:
            crane_distribution["大型(81-200t)"] += 1
        else:
            crane_distribution["特大型(>200t)"] += 1
    
    return {
        "total_plans": len(plans),
        "total_devices": total_devices,
        "coverage_percent": round(len(plans) / total_devices * 100, 1) if total_devices > 0 else 0,
        "type_count": type_count,
        "workshop_count": workshop_count,
        "crane_distribution": crane_distribution,
    }
