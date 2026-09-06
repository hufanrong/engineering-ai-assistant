"""
v0.1.70：设备安装位置与技术交底联动

根据设备位置（车间、标高、坐标、相邻设备、管线）自动生成技术交底要点，
包括工程概况、施工准备、施工工艺、质量标准、安全注意事项、环保要求。
"""

import os
import json
import datetime
from typing import Optional


_DISCLOSURE_FILE = os.path.join("data", "technical_disclosures.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_disclosures() -> dict:
    if os.path.exists(_DISCLOSURE_FILE):
        try:
            with open(_DISCLOSURE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_disclosures(disclosures: dict):
    _ensure_dirs()
    with open(_DISCLOSURE_FILE, "w", encoding="utf-8") as f:
        json.dump(disclosures, f, ensure_ascii=False, indent=2)


# 设备类型技术交底模板
DEVICE_DISCLOSURE_TEMPLATES = {
    "泵": {
        "construction_process": [
            "设备开箱检验：核对设备型号、规格、数量，检查外观有无损伤，随机技术文件是否齐全",
            "基础验收：检查基础尺寸、标高、中心线、地脚螺栓孔位置，基础混凝土强度达到设计要求",
            "设备就位：使用吊车或手动葫芦将设备吊装就位，注意保护设备表面",
            "初平初正：调整设备水平度和中心线偏差，初拧地脚螺栓",
            "管道连接：进出口管道与设备法兰连接，管道不得强行对口，连接后复核设备对中",
            "联轴器对中：使用百分表测量联轴器径向和端面偏差，调整至规范允许范围内",
            "二次灌浆：地脚螺栓孔灌浆，养护期达到要求后紧固地脚螺栓",
            "精平精正：最终调整设备水平度和对中，紧固所有连接螺栓",
            "单机试运转：检查润滑油、冷却水、电气接线，点动检查转向，空载试运转2小时，负荷试运转4小时",
        ],
        "quality_standards": [
            "设备水平度偏差不大于0.1mm/m",
            "联轴器径向偏差不大于0.05mm，端面偏差不大于0.03mm",
            "地脚螺栓紧固力矩符合设计要求",
            "管道法兰平行度偏差不大于法兰外径的1.5‰，且不大于2mm",
            "试运转轴承温度不超过75℃，振动值不超过4.5mm/s",
            "密封处无泄漏",
        ],
    },
    "压缩机": {
        "construction_process": [
            "设备开箱检验：核对主机、辅机、电气、仪表等各部件，检查转子转动是否灵活",
            "基础验收：基础承重能力满足要求，基础尺寸偏差在规范允许范围内",
            "主机就位：使用大吨位吊车吊装主机就位，吊装时保持水平，避免倾斜",
            "初平初正：调整主机水平度，初拧地脚螺栓",
            "辅机安装：安装油站、冷却器、过滤器、气液分离器等辅机",
            "管道连接：工艺管道、润滑油管道、冷却水管道连接，管道清洗合格后连接",
            "润滑油系统冲洗：润滑油系统循环冲洗，油质化验合格",
            "联轴器对中：精确对中，偏差控制在规范允许范围内",
            "二次灌浆与精平：灌浆养护后精平精正，紧固地脚螺栓",
            "单机试运转：空载试运转4小时，负荷试运转8小时，检查各参数正常",
        ],
        "quality_standards": [
            "主机水平度偏差不大于0.05mm/m",
            "联轴器径向偏差不大于0.03mm，端面偏差不大于0.02mm",
            "润滑油系统冲洗后油质颗粒度不低于NAS 8级",
            "轴承温度不超过70℃",
            "振动值不超过2.8mm/s",
            "各级压力、温度符合设计要求",
        ],
    },
    "塔器": {
        "construction_process": [
            "设备开箱检验：核对塔体、内件、附件，检查塔体椭圆度、直线度",
            "基础验收：基础标高、中心线、地脚螺栓位置检查，基础沉降观测点设置",
            "塔体吊装：使用双机抬吊或单机溜尾法吊装，吊装前办理一级吊装作业许可",
            "就位初平：塔体就位后初平，使用经纬仪监测垂直度",
            "临时固定：塔体临时固定，缆风绳或支撑牢固可靠",
            "内件安装：塔盘、填料、分布器等内件安装，安装前塔内部清理干净",
            "管道连接：工艺管道、仪表管道连接，管道支架安装牢固",
            "附件安装：人孔、手孔、液位计、安全阀、压力表等附件安装",
            "水压试验：按设计压力进行水压试验，保压30分钟无渗漏",
            "垂直度最终检测：使用经纬仪检测塔体垂直度，偏差不大于塔高的1/1000",
        ],
        "quality_standards": [
            "塔体垂直度偏差不大于塔高的1/1000，且不大于30mm",
            "塔盘水平度偏差不大于2mm/m",
            "填料装填均匀，高度偏差不大于设计值的±5%",
            "水压试验保压30分钟压力降不大于0.05MPa",
            "地脚螺栓紧固力矩符合设计要求",
            "所有密封面无渗漏",
        ],
    },
    "换热器": {
        "construction_process": [
            "设备开箱检验：核对壳体、管束、管箱、浮头盖等部件，检查管束有无变形",
            "基础验收：基础尺寸、标高检查",
            "设备就位：吊装就位，注意管束方向",
            "初平初正：调整水平度",
            "水压试验：壳程和管程分别进行水压试验，试验压力为设计压力的1.25倍",
            "管道连接：进出口管道连接，管道不得强行对口",
            "抽芯检查：如需抽芯检查，预留抽芯空间，抽芯时保护管束",
            "附件安装：排气阀、排液阀、温度计、压力表安装",
            "保温：水压试验合格后进行保温施工",
        ],
        "quality_standards": [
            "设备水平度偏差不大于0.1mm/m",
            "水压试验保压30分钟无渗漏",
            "管板与管子连接无渗漏",
            "法兰密封面无损伤",
            "保温层厚度偏差不大于设计值的+10%/-5%",
        ],
    },
    "容器": {
        "construction_process": [
            "设备开箱检验：核对设备型号、规格，检查外观",
            "基础验收：基础尺寸、标高检查",
            "设备就位：吊装就位",
            "初平初正：调整水平度和垂直度",
            "管道连接：进出口管道连接",
            "附件安装：人孔、液位计、安全阀、压力表安装",
            "水压试验：按设计压力进行水压试验",
            "保温：试验合格后保温",
        ],
        "quality_standards": [
            "立式容器垂直度偏差不大于高度的1/1000",
            "卧式容器水平度偏差不大于0.1mm/m",
            "水压试验保压30分钟无渗漏",
            "所有附件安装方向正确",
        ],
    },
    "风机": {
        "construction_process": [
            "设备开箱检验：核对风机、电机、联轴器，检查叶轮转动是否灵活",
            "基础验收：基础尺寸、标高检查",
            "风机就位：吊装就位",
            "电机就位：电机吊装就位",
            "初平初正：调整风机和电机水平度",
            "联轴器对中：精确对中",
            "管道连接：进出口管道连接，设置柔性接头",
            "二次灌浆与精平：灌浆后精平",
            "单机试运转：点动检查转向，空载试运转2小时",
        ],
        "quality_standards": [
            "风机水平度偏差不大于0.1mm/m",
            "联轴器径向偏差不大于0.05mm",
            "轴承温度不超过75℃",
            "振动值不超过4.5mm/s",
            "叶轮与壳体无摩擦",
        ],
    },
    "电机": {
        "construction_process": [
            "设备开箱检验：核对电机型号、功率、电压，检查绝缘电阻",
            "基础验收：基础尺寸、标高检查",
            "电机就位：吊装就位",
            "初平初正：调整水平度",
            "电气接线：电源线、接地线连接，接线端子紧固",
            "绝缘测试：测量定子绕组绝缘电阻，不低于0.5MΩ",
            "联轴器对中：与被驱动设备对中",
            "单机试运转：点动检查转向，空载试运转2小时，检查电流、温度、振动",
        ],
        "quality_standards": [
            "电机水平度偏差不大于0.1mm/m",
            "绝缘电阻不低于0.5MΩ",
            "轴承温度不超过80℃",
            "振动值不超过4.5mm/s",
            "空载电流不超过额定电流的30%",
            "接线端子温度不超过环境温度+50℃",
        ],
    },
    "阀门": {
        "construction_process": [
            "阀门检验：核对型号、规格、压力等级，外观检查",
            "阀门试验：强度试验和严密性试验，试验压力为公称压力的1.5倍（强度）和1.1倍（严密性）",
            "阀门就位：按设计方向安装，注意介质流向",
            "法兰连接：法兰垫片安装正确，螺栓对称均匀紧固",
            "焊接连接：焊接前坡口处理，焊接后无损检测",
            "传动装置安装：执行机构、手轮安装，操作灵活",
            "调试：阀门开关试验，限位调整",
        ],
        "quality_standards": [
            "强度试验保压5分钟无渗漏",
            "严密性试验保压5分钟无渗漏",
            "阀门开关灵活，无卡涩",
            "法兰螺栓紧固力矩均匀",
            "焊缝无损检测合格",
        ],
    },
    "储罐": {
        "construction_process": [
            "基础验收：基础平整度、坡度、承载力检查，设置沉降观测点",
            "罐底铺设：按排版图铺设罐底板，控制错边量和间隙",
            "罐底焊接：采用收缩变形小的焊接顺序，焊接后真空箱试漏",
            "罐壁安装：倒装法或正装法安装罐壁，控制垂直度和椭圆度",
            "罐壁焊接：立缝和环缝焊接，焊接后煤油试漏",
            "固定顶安装：顶板铺设和焊接",
            "附件安装：人孔、接管、液位计、盘梯、平台安装",
            "充水试验：充水至设计液位，保压48小时，检查基础沉降和罐壁变形",
            "防腐保温：试验合格后进行防腐和保温施工",
        ],
        "quality_standards": [
            "罐底真空箱试漏无渗漏",
            "罐壁煤油试漏无渗漏",
            "罐壁垂直度偏差不大于罐高的1/1000，且不大于50mm",
            "充水试验基础沉降均匀，不均匀沉降不大于50mm",
            "焊缝无损检测合格",
            "防腐层厚度符合设计要求",
        ],
    },
}

DEFAULT_TEMPLATE = {
    "construction_process": [
        "设备开箱检验：核对设备型号、规格、数量，检查外观",
        "基础验收：检查基础尺寸、标高、中心线",
        "设备就位：吊装就位",
        "初平初正：调整水平度和位置",
        "管道连接：进出口管道连接",
        "附件安装：各类附件安装",
        "试运转：单机试运转，检查各项参数",
    ],
    "quality_standards": [
        "设备水平度偏差不大于0.1mm/m",
        "地脚螺栓紧固力矩符合设计要求",
        "管道连接无泄漏",
        "试运转各项参数符合设计要求",
    ],
}


def get_disclosure_template(dev_type: str) -> dict:
    """v0.1.70：获取设备类型技术交底模板。"""
    return DEVICE_DISCLOSURE_TEMPLATES.get(dev_type, DEFAULT_TEMPLATE)


def generate_technical_disclosure(tag: str) -> dict:
    """v0.1.70：生成设备技术交底。
    
    Args:
        tag: 设备位号
    
    Returns:
        完整的技术交底
    """
    from . import installation_plan as _ip
    from . import equipment_types as _et
    from . import relations as _rel
    
    # 获取设备空间信息
    spatial_info = _ip.get_device_spatial_info(tag)
    if "error" in spatial_info:
        return spatial_info
    
    # 多源检测设备类型
    dev_type = spatial_info.get("type", "")
    if not dev_type:
        g = _rel.load_relations()
        devices = g.get("devices", [])
        device = next((d for d in devices if d["tag"] == tag), None)
        if device:
            dev_type = _et.get_equipment_type_from_devices([device])
    
    # 获取交底模板
    template = get_disclosure_template(dev_type)
    
    # 1. 工程概况
    project_overview = [
        f"工程名称：{tag} {spatial_info.get('name', tag)} 安装工程",
        f"设备类型：{dev_type or '未知'}",
        f"安装位置：{spatial_info.get('workshop', '未分配车间')}",
    ]
    if spatial_info.get("z") is not None:
        project_overview.append(f"安装标高：EL{spatial_info['z']}m")
    if spatial_info.get("x") is not None and spatial_info.get("y") is not None:
        project_overview.append(f"坐标位置：X={spatial_info['x']}m, Y={spatial_info['y']}m")
    if spatial_info.get("adjacent_devices"):
        project_overview.append(f"相邻设备：{', '.join(d['tag'] for d in spatial_info['adjacent_devices'][:3])}")
    if spatial_info.get("related_pipes"):
        project_overview.append(f"相关管线：{len(spatial_info['related_pipes'])}条")
    
    # 2. 施工准备
    construction_preparation = [
        "技术准备：施工图纸会审完成，施工方案编制并审批，技术交底完成",
        "人员准备：施工人员持证上岗，特殊工种（起重工、焊工、电工）持证有效",
        "机具准备：吊车、手动葫芦、千斤顶、水平仪、经纬仪、百分表等机具检验合格",
        "材料准备：地脚螺栓、垫片、灌浆料、润滑油等材料进场验收合格",
        "现场准备：施工场地平整，道路畅通，吊装作业区域清理，安全警戒线设置",
    ]
    
    # 根据位置环境增加准备要求
    elevation = spatial_info.get("z")
    if elevation is not None and elevation > 3:
        construction_preparation.append(f"高位作业准备：搭设操作平台，挂设安全网，作业人员配备速差自控器（标高{elevation}m）")
    if spatial_info.get("adjacent_devices") and len(spatial_info["adjacent_devices"]) >= 3:
        construction_preparation.append("密集区域作业准备：对已安装设备搭设防护棚，合理安排作业时间避免交叉作业")
    if dev_type == "塔器":
        construction_preparation.append("塔器吊装专项准备：编制专项吊装方案，办理一级吊装作业许可，吊车占位和支腿垫板检查")
    
    # 3. 施工工艺
    construction_process = template["construction_process"]
    
    # 4. 质量标准
    quality_standards = template["quality_standards"]
    
    # 5. 安全注意事项
    safety_points = [
        "进入施工现场必须佩戴安全帽，高处作业必须系安全带",
        "吊装作业由持证起重工指挥，指挥信号明确统一，吊装区域设置警戒线",
        "吊装前检查吊车支腿、索具、卸扣，试吊检查设备平衡",
        "高处作业工具必须系保险绳，严禁抛掷工具和材料",
        "临时用电必须由持证电工接线，使用合格的配电箱和漏电保护器",
        "动火作业必须办理动火证，配备灭火器材，设专人监护",
        "夜间施工必须有充足照明，照明灯具设置在作业影响范围外",
        "六级及以上大风、雷雨、大雾等恶劣天气禁止高处作业和吊装作业",
    ]
    
    # 根据位置增加安全要求
    if elevation is not None and elevation > 5:
        safety_points.append(f"高位作业（{elevation}m）必须搭设牢固的操作平台，设置防护栏杆和挡脚板")
        safety_points.append("高位作业人员必须佩戴速差自控器，工具必须系保险绳")
    if spatial_info.get("adjacent_devices") and len(spatial_info["adjacent_devices"]) >= 3:
        safety_points.append("设备密集区域作业，必须对已安装设备采取防护措施，避免碰撞和损伤")
        safety_points.append("多工种交叉作业时，设置隔离层或错时作业，避免物体打击")
    
    # 设备类型特殊安全要求
    type_safety = {
        "塔器": ["塔器吊装必须办理一级吊装作业许可，吊装前进行全员安全技术交底", "塔器溜尾区域设置警戒线，严禁人员进入", "塔器就位后必须立即进行临时固定，固定可靠后方可摘钩"],
        "压缩机": ["压缩机吊装时人员不得站在旋转部件切线方向", "压缩机试运行区域设置隔声屏障，作业人员佩戴防噪声耳塞"],
        "储罐": ["罐内作业必须办理受限空间作业许可，强制通风，定时气体检测", "储罐焊接作业人员佩戴防尘口罩和防护眼镜", "储罐充水试验时监测基础沉降，设置沉降观测点"],
        "换热器": ["换热器水压试验时升压缓慢，人员不得站在封头正对面", "换热器抽芯时抽芯区域设置警戒线，防止管束滑落伤人"],
    }
    if dev_type in type_safety:
        safety_points.extend(type_safety[dev_type])
    
    # 6. 环保要求
    environmental_points = [
        "施工现场设置垃圾桶，垃圾分类存放，及时清运",
        "机械设备维修保养时设置接油盘，防止油污污染土壤",
        "清洗液、废油等危险废物分类收集，交由有资质单位处理",
        "施工噪声控制在规范允许范围内，夜间施工办理夜间施工许可",
        "施工现场道路定期洒水降尘，易飞扬材料覆盖存放",
        "焊接作业设置焊烟收集装置，减少烟尘排放",
        "施工完毕后及时清理现场，做到工完料尽场地清",
    ]
    
    disclosure = {
        "tag": tag,
        "name": spatial_info.get("name", tag),
        "type": dev_type,
        "workshop": spatial_info.get("workshop", ""),
        "elevation": spatial_info.get("z"),
        "generated_at": datetime.datetime.now().isoformat(),
        "project_overview": project_overview,
        "construction_preparation": construction_preparation,
        "construction_process": construction_process,
        "quality_standards": quality_standards,
        "safety_points": safety_points,
        "environmental_points": environmental_points,
        "adjacent_devices": spatial_info.get("adjacent_devices", []),
        "related_pipes": spatial_info.get("related_pipes", []),
    }
    
    # 保存
    disclosures = _load_disclosures()
    disclosures[tag] = disclosure
    _save_disclosures(disclosures)
    
    return disclosure


def list_disclosures() -> list:
    """v0.1.70：列出已生成的技术交底。"""
    disclosures = _load_disclosures()
    return [{"tag": k, "name": v.get("name", k), "type": v.get("type", ""),
             "workshop": v.get("workshop", ""), "generated_at": v.get("generated_at", "")}
            for k, v in disclosures.items()]


def get_disclosure_stats() -> dict:
    """v0.1.70：获取技术交底统计。"""
    disclosures = _load_disclosures()
    from . import relations as _rel
    g = _rel.load_relations()
    total_devices = len(g.get("devices", []))
    
    type_count = {}
    workshop_count = {}
    for d in disclosures.values():
        t = d.get("type", "未知")
        type_count[t] = type_count.get(t, 0) + 1
        ws = d.get("workshop", "未分配")
        workshop_count[ws] = workshop_count.get(ws, 0) + 1
    
    return {
        "total_disclosures": len(disclosures),
        "total_devices": total_devices,
        "coverage_percent": round(len(disclosures) / total_devices * 100, 1) if total_devices > 0 else 0,
        "type_count": type_count,
        "workshop_count": workshop_count,
    }
