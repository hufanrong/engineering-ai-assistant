"""
v0.1.65：设备安装位置与施工方案联动

根据设备位置（车间、标高、坐标、相邻设备）自动生成施工方案要点，
包括施工环境分析、施工顺序建议、安全注意事项、质量控制要点。
"""

import os
import json
import datetime
from typing import Optional


_PLAN_FILE = os.path.join("data", "installation_plans.json")

# v0.1.84：矿山设备施工方案要点
MINING_INSTALLATION_NOTES = {
    "破碎机": {"key_points": ["基础二次灌浆强度需达到设计要求", "机架水平度≤0.1mm/m", "动颚/动锥与机架间隙需符合技术文件", "排矿口调整机构需灵活可靠", "润滑系统需清洗干净，润滑油牌号符合设计"], "safety_points": ["试运转时严禁人员靠近进料口", "液压系统需先排空气再升压", "大件吊装需设警戒区"]},
    "球磨机": {"key_points": ["主轴承轴瓦刮研接触点≥2点/cm²", "筒体吊装需用专用吊梁，严禁钢丝绳直接捆绑筒体", "大齿圈端面跳动≤0.5mm/m，径向跳动≤0.5mm/m", "大小齿轮啮合接触率沿齿高≥40%沿齿长≥50%", "衬板螺栓需按规定力矩紧固，需涂防松剂"], "safety_points": ["筒体吊装是重大危险源，需编制专项方案并审批", "筒体内作业需办理受限空间作业证", "大齿圈吊装需防止旋转伤人", "试运转时严禁人员靠近旋转部件"]},
    "浮选机": {"key_points": ["槽体安装水平度≤0.5mm/m，槽体接缝需严密无渗漏", "搅拌轴垂直度≤0.1mm/m，叶轮与槽底间隙需符合技术文件", "三角带张紧力需适当，皮带轮对齐度≤1mm", "充气系统需清洗干净，气量调节需灵活可靠"], "safety_points": ["搅拌机构试运转时严禁将手伸入槽内", "多槽联动需逐台启动，避免同时启动过载", "电气设备需接地可靠"]},
    "高压釜": {"key_points": ["压力容器安装需由持证单位施工，人员需持证上岗", "釜体吊装需编制专项方案，钛钢复合层需用软垫保护", "支座滑动端与固定端需区分，滑动端需预留热膨胀量", "搅拌装置轴封需按技术文件要求安装，机械密封需进行静压试验", "耐压试验介质需符合设计要求，升压需分级缓慢", "安全阀/爆破片需校验合格后安装，压力表需检定合格"], "safety_points": ["耐压试验区域需设警戒区，严禁承压状态下紧固螺栓", "高温高压设备需防止烫伤", "有毒介质设备需防止泄漏中毒", "受限空间作业需办证并通风检测"]},
    "萃取箱": {"key_points": ["PVC/PP/玻璃钢箱体安装需防止变形，支撑点需均匀受力", "箱体水平度≤0.5mm/m，需进行盛水渗漏试验24h无渗漏", "搅拌轴垂直度≤0.1mm/m，叶轮与箱底间隙需符合技术文件", "相界面调节机构需灵活可靠，溢流堰水平度需符合要求", "管道阀门需耐腐材质，法兰密封需用耐酸垫片"], "safety_points": ["有机溶剂萃取系统需防火防爆，电气需防爆等级符合要求", "萃取剂有毒有害，需防止接触皮肤和吸入", "受限空间作业需办证并通风检测", "消防设施需配备到位"]},
    "闪速炉": {"key_points": ["超大型冶金炉需分段安装，炉壳拼装需控制圆度和垂直度", "冷却壁/水套安装需保证间隙均匀，水路需逐组进行水压试验", "耐火材料砌筑需严格按砌筑方案，砖缝需符合设计要求，膨胀缝需预留", "反应塔安装需保证垂直度，铜水套需逐块进行水压试验", "烘炉需按烘炉曲线严格控制升温速度，严禁超温"], "safety_points": ["高温熔融金属设备是重大危险源，需防止喷溅和爆炸", "烘炉期间需24小时值班监控温度", "炉内作业需办证并通风检测，需防止煤气中毒", "大件吊装需编制专项方案", "高处作业需系安全带"]},
    "转炉": {"key_points": ["托圈与炉体间隙需均匀，需符合热膨胀要求", "耳轴轴承座安装水平度≤0.1mm/m，轴承间隙需符合技术文件", "倾动机构减速器需清洗干净，制动器需调整可靠，需进行0°/90°/180°倾动试验", "氧枪升降机构需灵活可靠，氧枪定位精度需符合要求", "烟罩与炉口间隙需符合设计，需防止冒烟"], "safety_points": ["高温熔融金属设备需防止喷溅和爆炸", "倾动机构试运转时炉下严禁站人", "氧气系统需严格脱脂，需防止氧气泄漏引发火灾", "煤气区域需防止中毒", "高处作业需系安全带"]},
    "余热锅炉": {"key_points": ["汽包吊装是重大危险源，需编制专项方案，汽包支座需预留热膨胀量", "受热面管排需进行通球试验，焊口需进行无损检测", "炉墙砌筑需按烘炉曲线要求，膨胀缝需预留", "水压试验压力需按规范计算，升压需分级缓慢", "烘炉需按烘炉曲线严格控制升温速度", "安全阀需校验合格后安装，需进行热态校验"], "safety_points": ["水压试验区域需设警戒区，严禁承压状态下紧固螺栓", "烘炉期间需24小时值班", "高温高压设备需防止烫伤", "汽包内作业需办证并通风检测", "高处作业需系安全带"]},
}



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


def get_device_spatial_info(tag: str) -> dict:
    """v0.1.65：获取设备空间信息。
    
    Args:
        tag: 设备位号
    
    Returns:
        设备空间信息（位置、车间、标高、相邻设备、相关管线）
    """
    from . import relations as _rel
    from . import spatial_model as _sm
    from . import piping_network as _pn
    
    g = _rel.load_relations()
    spatial = _sm.build_spatial_model(g)
    spatial_devs = {d["tag"]: d for d in spatial.get("devices", [])}
    
    device = None
    for d in g.get("devices", []):
        if d["tag"] == tag:
            device = d
            break
    
    if not device:
        return {"error": "设备不存在", "tag": tag}
    
    sd = spatial_devs.get(tag, {})
    
    # 获取相邻设备
    adjacent_devices = []
    if sd.get("x") is not None and sd.get("y") is not None:
        for other_tag, other_sd in spatial_devs.items():
            if other_tag == tag:
                continue
            if other_sd.get("x") is not None and other_sd.get("y") is not None:
                dist = ((sd["x"] - other_sd["x"]) ** 2 + (sd["y"] - other_sd["y"]) ** 2) ** 0.5
                if dist < 10:  # 10米范围内视为相邻
                    adjacent_devices.append({
                        "tag": other_tag,
                        "distance": round(dist, 2),
                        "workshop": other_sd.get("workshop", ""),
                        "type": other_sd.get("type", ""),
                    })
    adjacent_devices.sort(key=lambda d: d["distance"])
    
    # 获取相关管线
    try:
        network = _pn.build_piping_network()
        related_pipes = []
        for conn in network.get("connections", []):
            if conn.get("from_device") == tag or conn.get("to_device") == tag:
                related_pipes.append({
                    "pipe_no": conn.get("pipe_no", ""),
                    "from": conn.get("from_device", ""),
                    "to": conn.get("to_device", ""),
                })
    except Exception:
        related_pipes = []
    
    return {
        "tag": tag,
        "name": sd.get("name", tag),
        "type": sd.get("type", ""),
        "workshop": sd.get("workshop") or (device.get("workshops", [""])[0] if device.get("workshops") else ""),
        "x": sd.get("x"),
        "y": sd.get("y"),
        "z": sd.get("z"),
        "elevation": sd.get("z"),
        "adjacent_devices": adjacent_devices[:5],  # 最近的5个
        "related_pipes": related_pipes,
        "sources": device.get("sources", {}),
        "files": device.get("files", []),
    }


def analyze_construction_environment(spatial_info: dict) -> list:
    """v0.1.65：分析施工环境。
    
    Args:
        spatial_info: 设备空间信息
    
    Returns:
        施工环境分析要点列表
    """
    points = []
    
    workshop = spatial_info.get("workshop", "")
    elevation = spatial_info.get("elevation")
    adjacent = spatial_info.get("adjacent_devices", [])
    related_pipes = spatial_info.get("related_pipes", [])
    dev_type = spatial_info.get("type", "")
    
    # 车间环境
    if workshop:
        points.append(f"施工地点位于{workshop}，需提前确认车间内施工通道畅通、吊装空间充足")
    else:
        points.append("施工地点尚未明确分配车间，需先确认设备安装位置")
    
    # 标高分析
    if elevation is not None:
        if elevation > 5:
            points.append(f"设备安装标高{elevation}m，属于高位安装，需搭设高空作业平台，作业人员需系安全带")
        elif elevation > 2:
            points.append(f"设备安装标高{elevation}m，需注意高处作业安全，搭设临时操作平台")
        else:
            points.append(f"设备安装标高{elevation}m，属于低位安装，施工条件相对较好")
    else:
        points.append("设备标高信息缺失，需从图纸或设计文件中确认安装标高")
    
    # 相邻设备影响
    if adjacent:
        points.append(f"设备周围{len(adjacent)}台相邻设备（最近距离{adjacent[0]['distance']}m），施工时需注意保护已安装设备，避免碰撞")
        if len(adjacent) >= 3:
            points.append("设备周围设备密集，施工空间受限，需合理安排施工顺序和材料堆放位置")
    else:
        points.append("设备周围无相邻设备，施工空间充足")
    
    # 管线连接
    if related_pipes:
        points.append(f"设备连接{len(related_pipes)}条管线，管道安装需与设备安装交叉作业，注意法兰对中")
    else:
        points.append("暂未识别到设备连接管线，需在管道图中确认设备接口位置")
    
    # 设备类型特殊环境
    type_env = {
        "塔器": ["塔器设备高度大，需确认吊装路线和吊车占位，吊装前需办理吊装作业许可", "塔器垂直度要求高，需使用经纬仪监测垂直度"],
        "压缩机": ["压缩机对基础要求高，需确认基础养护期已到（一般7-14天）", "压缩机运行振动大，需确认周围无精密仪器或对振动敏感的设备"],
        "泵": ["泵类设备数量多，可按区域流水作业，提高施工效率", "泵进出口管道需设置柔性连接或弹簧支架，减少管道应力传递"],
        "换热器": ["换热器重量大，需确认吊装能力，抽芯检查需预留抽芯空间", "换热器水压试验需在管道连接前完成"],
        "储罐": ["储罐体积大，需确认现场组装空间，罐底基础平整度要求高", "储罐焊接需考虑防风措施，雨季施工需做好防雨"],
    }
    if dev_type in type_env:
        points.extend(type_env[dev_type])
    
    return points


def suggest_construction_sequence(spatial_info: dict) -> list:
    """v0.1.65：建议施工顺序。
    
    Args:
        spatial_info: 设备空间信息
    
    Returns:
        施工顺序建议列表
    """
    steps = [
        "施工准备：场地清理、材料进场、机具准备、人员进场、技术交底",
        "基础验收：基础尺寸复核、标高复核、地脚螺栓孔检查、基础养护期确认",
    ]
    
    elevation = spatial_info.get("elevation")
    adjacent = spatial_info.get("adjacent_devices", [])
    dev_type = spatial_info.get("type", "")
    
    # 根据标高调整
    if elevation is not None and elevation > 3:
        steps.append("高空作业准备：搭设操作平台、挂设安全网、检查脚手架")
    
    steps.extend([
        "设备吊装就位：设备吊装、初平初正、临时固定",
        "设备精平：精平精正、地脚螺栓紧固、二次灌浆",
    ])
    
    # 根据相邻设备调整
    if adjacent:
        steps.append(f"与相邻设备（{', '.join(d['tag'] for d in adjacent[:3])}）的间距复核，确保满足操作和维护空间")
    
    steps.extend([
        "管道连接：管道预制、管道安装、法兰连接、焊接检验",
        "附件安装：仪表、阀门、电气接线、接地",
        "单机试运转：设备检查、空载试运转、负载试运转、参数记录",
        "竣工验收：资料整理、自检整改、报验验收",
    ])
    
    # 设备类型特殊步骤
    type_steps = {
        "塔器": ["内件安装：塔盘、填料、分布器等内件安装（在塔器就位固定后进行）"],
        "压缩机": ["润滑油系统冲洗：润滑油管道冲洗、油质化验、油泵试运转"],
        "泵": ["联轴器对中：泵与电机联轴器对中检查，径向和轴向偏差符合规范"],
        "换热器": ["水压试验：壳程和管程水压试验，试验压力符合设计要求"],
    }
    if dev_type in type_steps:
        # 插入到管道连接之前
        insert_idx = next(i for i, s in enumerate(steps) if "管道连接" in s)
        for ts in type_steps[dev_type]:
            steps.insert(insert_idx, ts)
    
    return steps


def get_safety_points(spatial_info: dict) -> list:
    """v0.1.65：获取安全注意事项。
    
    Args:
        spatial_info: 设备空间信息
    
    Returns:
        安全注意事项列表
    """
    points = [
        "进入施工现场必须佩戴安全帽，高空作业必须系安全带",
        "吊装作业必须由持证起重工指挥，吊装区域设置警戒线，非作业人员不得进入",
        "电气设备必须接地，临时用电符合三级配电两级保护要求",
        "动火作业必须办理动火许可证，配备灭火器材，设专人监护",
    ]
    
    elevation = spatial_info.get("elevation")
    adjacent = spatial_info.get("adjacent_devices", [])
    dev_type = spatial_info.get("type", "")
    
    if elevation is not None and elevation > 3:
        points.append(f"高空作业（标高{elevation}m）必须搭设牢固的操作平台，作业人员佩戴速差自控器")
        points.append("高空作业工具必须系防坠绳，材料不得抛掷，使用工具袋传递")
    
    if adjacent:
        points.append("设备密集区域施工，注意保护已安装设备，搭设防护棚或防护罩")
        points.append("多工种交叉作业时，设置隔离层或错时作业，避免物体打击")
    
    type_safety = {
        "塔器": ["塔器吊装需办理一级吊装作业许可，吊装前进行安全技术交底", "塔器内作业需办理受限空间作业许可，配备通风设备和气体检测仪"],
        "压缩机": ["压缩机试车区域设置隔声屏障，作业人员佩戴防噪声耳塞", "润滑油系统试压时，人员不得站在法兰接口正对面"],
        "泵": ["泵试运转时，联轴器防护罩必须安装到位，不得触摸转动部件"],
        "换热器": ["换热器水压试验时，升压应缓慢，人员不得站在封头正对面"],
        "储罐": ["储罐罐内作业需办理受限空间作业许可，强制通风，定时气体检测", "储罐焊接作业人员需佩戴防尘口罩和防护眼镜"],
    }
    if dev_type in type_safety:
        points.extend(type_safety[dev_type])
    
    return points


def get_quality_points(spatial_info: dict) -> list:
    """v0.1.65：获取质量控制要点。
    
    Args:
        spatial_info: 设备空间信息
    
    Returns:
        质量控制要点列表
    """
    points = [
        "设备基础验收必须有监理签字确认，基础尺寸偏差符合规范要求",
        "设备开箱检验必须有建设单位、监理、施工单位三方共同参加，做好记录",
        "设备安装水平度、垂直度使用精度合格的测量仪器，偏差符合规范和设计要求",
        "地脚螺栓紧固使用力矩扳手，紧固力矩符合设计或规范要求",
        "管道焊接必须由持证焊工施焊，焊缝外观检查合格，无损检测比例符合设计要求",
    ]
    
    elevation = spatial_info.get("elevation")
    dev_type = spatial_info.get("type", "")
    
    if elevation is not None:
        points.append(f"设备标高{elevation}m，安装后需复核标高，偏差控制在±5mm以内")
    
    type_quality = {
        "塔器": ["塔器垂直度偏差不大于塔高的1/1000，且不大于30mm", "塔盘水平度偏差不大于3mm，塔盘间距偏差符合设计要求"],
        "压缩机": ["压缩机联轴器对中径向偏差不大于0.05mm，轴向偏差不大于0.02mm", "压缩机试运行时，轴承温度不超过70℃，振动值符合规范要求"],
        "泵": ["泵联轴器对中径向偏差不大于0.05mm，轴向偏差不大于0.02mm", "泵试运行时，轴承温度不超过75℃，机械密封无泄漏"],
        "换热器": ["换热器水压试验压力为设计压力的1.5倍，保压30分钟无渗漏", "换热器抽芯检查时，管束表面无损伤，垫片完好"],
        "储罐": ["储罐罐底焊缝进行真空箱试漏，无渗漏", "储罐壁板垂直度偏差不大于罐高的1/1000，且不大于50mm"],
    }
    if dev_type in type_quality:
        points.extend(type_quality[dev_type])
    
    return points


def generate_installation_plan(tag: str) -> dict:
    """v0.1.65：生成设备安装施工方案。
    
    Args:
        tag: 设备位号
    
    Returns:
        完整的安装施工方案
    """
    spatial_info = get_device_spatial_info(tag)
    if "error" in spatial_info:
        return spatial_info
    
    plan = {
        "tag": tag,
        "name": spatial_info.get("name", tag),
        "type": spatial_info.get("type", ""),
        "workshop": spatial_info.get("workshop", ""),
        "elevation": spatial_info.get("elevation"),
        "generated_at": datetime.datetime.now().isoformat(),
        "device_info": spatial_info,
        "construction_environment": analyze_construction_environment(spatial_info),
        "construction_sequence": suggest_construction_sequence(spatial_info),
        "safety_points": get_safety_points(spatial_info),
        "quality_points": get_quality_points(spatial_info),
        "adjacent_devices": spatial_info.get("adjacent_devices", []),
        "related_pipes": spatial_info.get("related_pipes", []),
    }
    
    # 保存方案
    plans = _load_plans()
    plans[tag] = plan
    _save_plans(plans)
    
    return plan


def list_installation_plans() -> list:
    """v0.1.65：列出已生成的安装方案。"""
    plans = _load_plans()
    return [{"tag": k, "name": v.get("name", k), "type": v.get("type", ""),
             "workshop": v.get("workshop", ""), "generated_at": v.get("generated_at", "")}
            for k, v in plans.items()]


def get_plan_stats() -> dict:
    """v0.1.65：获取安装方案统计。"""
    plans = _load_plans()
    from . import relations as _rel
    g = _rel.load_relations()
    total_devices = len(g.get("devices", []))
    
    type_count = {}
    workshop_count = {}
    for plan in plans.values():
        t = plan.get("type", "未知")
        type_count[t] = type_count.get(t, 0) + 1
        ws = plan.get("workshop", "未分配")
        workshop_count[ws] = workshop_count.get(ws, 0) + 1
    
    return {
        "total_plans": len(plans),
        "total_devices": total_devices,
        "coverage_percent": round(len(plans) / total_devices * 100, 1) if total_devices > 0 else 0,
        "type_count": type_count,
        "workshop_count": workshop_count,
    }
