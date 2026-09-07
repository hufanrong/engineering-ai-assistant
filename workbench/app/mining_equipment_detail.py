"""
v0.1.100：矿山设备知识库持续完善

增加设备详细参数、施工要点、质量标准、验收规范、常见故障等信息。
"""

import os
import json
from typing import Optional


# ============================================================
# 设备详细参数库
# ============================================================

EQUIPMENT_DETAILS = {
    "球磨机": {
        "category": "选矿设备",
        "subcategory": "磨矿设备",
        "typical_models": ["MQY2740", "MQY3245", "MQY3660", "MQY4060", "Φ2.7×4.0m", "Φ3.2×4.5m", "Φ3.6×6.0m", "Φ4.0×6.0m"],
        "key_parameters": {
            "筒体直径": "2.7~4.0m",
            "筒体长度": "4.0~6.0m",
            "装球量": "30~120t",
            "电机功率": "400~2000kW",
            "转速": "16~24r/min",
            "处理量": "30~200t/h",
            "给料粒度": "≤25mm",
            "排料粒度": "0.074~0.3mm",
        },
        "main_components": ["筒体", "端盖", "主轴承", "大齿圈", "小齿轮", "减速机", "电机", "衬板", "进料装置", "出料装置", "润滑系统"],
        "construction_key_points": [
            "基础混凝土强度达到设计强度75%以上方可安装",
            "主轴承轴瓦刮研接触点不少于2点/cm²",
            "筒体安装水平度偏差不大于0.1mm/m",
            "大齿圈端面跳动不大于1.5mm，径向跳动不大于1.0mm",
            "齿轮啮合侧隙0.8~1.6mm，接触率沿齿高不少于40%，沿齿长不少于50%",
            "衬板螺栓紧固力矩按厂家要求，一般800~1200N·m",
            "高低压润滑系统调试正常，高压泵压力8~12MPa",
            "试运转时主轴承温度不超过65℃，温升不超过35℃",
        ],
        "quality_standards": [
            "GB 50231-2009 机械设备安装工程施工及验收通用规范",
            "GB 50275-2010 风机、压缩机、泵安装工程施工及验收规范",
            "JB/T 6346 选矿设备 球磨机和棒磨机",
            "厂家安装使用说明书",
        ],
        "common_faults": [
            {"fault": "主轴承温度过高", "cause": "润滑不良/轴瓦接触不良/冷却水中断", "solution": "检查润滑系统/重新刮研轴瓦/恢复冷却水"},
            {"fault": "齿轮异响", "cause": "啮合间隙不当/齿面磨损/润滑不足", "solution": "调整间隙/更换齿轮/补充润滑油"},
            {"fault": "筒体振动大", "cause": "衬板松动/装球不均/基础松动", "solution": "紧固衬板/调整装球/紧固地脚螺栓"},
            {"fault": "漏浆", "cause": "端盖密封磨损/衬板螺栓松动", "solution": "更换密封/紧固螺栓"},
        ],
        "acceptance_items": ["基础验收", "主轴承安装", "筒体吊装", "齿轮传动安装", "衬板安装", "润滑系统调试", "空载试运转", "负载试运转"],
    },
    "半自磨机": {
        "category": "选矿设备",
        "subcategory": "磨矿设备",
        "typical_models": ["Φ5.5×8.5m", "Φ6.0×9.5m", "Φ7.0×10.5m", "Φ8.0×12.0m", "SAG5585", "SAG6095"],
        "key_parameters": {
            "筒体直径": "5.5~8.0m",
            "筒体长度": "8.5~12.0m",
            "装球量": "100~300t（占容积8~12%）",
            "电机功率": "3000~8000kW",
            "转速": "10~15r/min",
            "处理量": "500~3000t/h",
            "给料粒度": "≤300mm",
            "排料粒度": "0.5~5mm",
        },
        "main_components": ["筒体", "端盖", "静压轴承", "环形电机（或齿轮传动）", "衬板（波形/提升条）", "进料装置", "出料篦板", "润滑系统", "气动离合器"],
        "construction_key_points": [
            "筒体翻身必须使用专用吊具，严禁直接用钢丝绳捆绑筒体",
            "静压轴承高压油膜建立后方可盘车，油膜压力6~10MPa",
            "环形电机气隙均匀度偏差不大于±5%",
            "波形衬板提升条方向一致，螺栓紧固力矩1500~2500N·m",
            "气动离合器间隙调整0.5~1.0mm，摩擦面清洁无油污",
            "筒体安装水平度偏差不大于0.05mm/m",
            "试运转时轴承温度不超过70℃，振动速度不大于4.5mm/s",
        ],
        "quality_standards": [
            "GB 50231-2009 机械设备安装工程施工及验收通用规范",
            "JB/T 1386 半自磨机技术条件",
            "厂家安装使用说明书",
        ],
        "common_faults": [
            {"fault": "静压轴承油膜建立失败", "cause": "高压泵故障/油路堵塞/密封泄漏", "solution": "检修高压泵/清洗油路/更换密封"},
            {"fault": "衬板脱落", "cause": "螺栓松动/衬板磨损超限", "solution": "停机紧固/更换衬板"},
            {"fault": "气动离合器打滑", "cause": "摩擦片磨损/气压不足/摩擦面有油污", "solution": "更换摩擦片/调整气压/清洁摩擦面"},
        ],
        "acceptance_items": ["基础验收", "静压轴承安装", "筒体翻身吊装", "传动系统安装", "衬板安装", "润滑系统调试", "气动离合器调试", "空载试运转", "负载试运转"],
    },
    "高压釜": {
        "category": "湿法冶炼设备",
        "subcategory": "浸出设备",
        "typical_models": ["Φ3.0×15m", "Φ3.5×18m", "Φ4.0×20m", "Φ4.5×25m", "GSH-3015", "GSH-4020"],
        "key_parameters": {
            "筒体直径": "3.0~4.5m",
            "筒体长度": "15~25m",
            "设计压力": "1.5~3.0MPa",
            "设计温度": "150~250℃",
            "容积": "80~350m³",
            "搅拌功率": "75~315kW",
            "搅拌转速": "50~100r/min",
            "材质": "碳钢衬钛/哈氏合金/双相钢",
        },
        "main_components": ["筒体", "封头", "钛衬里（或复合板）", "搅拌装置", "机械密封", "加热盘管", "进料/出料口", "安全阀", "压力表", "温度计", "人孔"],
        "construction_key_points": [
            "钛衬里焊接采用氩弧焊，焊后进行酸洗钝化处理",
            "钛衬里电火花检测电压10~15kV，不得有击穿点",
            "机械密封静压试验压力为设计压力的1.25倍，保压30min无泄漏",
            "耐压试验（水压）压力为设计压力的1.25倍，保压时间不少于30min",
            "气密性试验压力为设计压力的1.0倍，保压30min，泄漏率不大于0.5%",
            "安全阀整定压力为设计压力的1.05~1.10倍，铅封完好",
            "搅拌轴垂直度偏差不大于0.1mm/m，径向跳动不大于0.5mm",
            "安装完成后进行整体酸洗钝化，去除铁离子污染",
        ],
        "quality_standards": [
            "GB 150 压力容器",
            "GB/T 151 热交换器",
            "TSG 21 固定式压力容器安全技术监察规程",
            "JB/T 4730 承压设备无损检测",
            "HG/T 20581 钢制化工容器材料选用规定",
        ],
        "common_faults": [
            {"fault": "钛衬里腐蚀泄漏", "cause": "电火花检测遗漏/焊接缺陷/介质冲刷", "solution": "补焊修复/更换衬里/加强检测"},
            {"fault": "机械密封泄漏", "cause": "密封面磨损/弹簧失效/冷却水中断", "solution": "更换密封/检修弹簧/恢复冷却水"},
            {"fault": "搅拌轴振动大", "cause": "轴承磨损/轴弯曲/叶轮不平衡", "solution": "更换轴承/校直轴/做动平衡"},
            {"fault": "安全阀起跳", "cause": "超压/整定压力漂移/安全阀故障", "solution": "泄压/重新校验/更换安全阀"},
        ],
        "acceptance_items": ["材料验收", "焊接检验", "钛衬里电火花检测", "耐压试验", "气密性试验", "机械密封试验", "安全阀校验", "搅拌装置调试", "整体酸洗钝化"],
    },
    "闪速炉": {
        "category": "火法冶炼设备",
        "subcategory": "熔炼设备",
        "typical_models": ["反应塔Φ5.0×6.5m", "反应塔Φ6.0×7.5m", "反应塔Φ7.0×8.5m", "FSF-50", "FSF-60"],
        "key_parameters": {
            "反应塔直径": "5.0~7.0m",
            "反应塔高度": "6.5~8.5m",
            "沉淀池长度": "15~25m",
            "处理量": "1000~4000t/d（干精矿）",
            "熔炼温度": "1250~1400℃",
            "富氧浓度": "60~95%",
            "铜锍品位": "60~70%",
        },
        "main_components": ["反应塔", "沉淀池", "上升烟道", "精矿喷嘴", "铜水套", "耐火材料", "燃烧器", "排烟口", "放铜口", "放渣口", "加料系统"],
        "construction_key_points": [
            "反应塔安装垂直度偏差不大于高度的1/1000，且不大于10mm",
            "铜水套逐块进行水压试验，试验压力为工作压力的1.5倍，保压30min无渗漏",
            "铜水套安装间隙均匀，密封填料饱满",
            "炉壳焊接采用连续焊，焊后进行RT或UT检测，合格率100%",
            "耐火砌筑严格按烘炉曲线进行，烘炉时间7~14天",
            "精矿喷嘴安装位置偏差不大于±5mm，喷嘴角度偏差不大于±1°",
            "上升烟道与余热锅炉接口密封良好，不得漏风",
            "放铜口、放渣口安装位置准确，水套冷却正常",
        ],
        "quality_standards": [
            "GB 50231-2009 机械设备安装工程施工及验收通用规范",
            "GB 50236 现场设备、工业管道焊接工程施工规范",
            "YB/T 4409 闪速炉技术规范",
            "厂家安装使用说明书",
        ],
        "common_faults": [
            {"fault": "反应塔耐火材料侵蚀过快", "cause": "炉温过高/精矿喷嘴偏析/耐火材料质量差", "solution": "控制炉温/调整喷嘴/更换优质耐火材料"},
            {"fault": "铜水套漏水", "cause": "水套腐蚀/焊接缺陷/超温烧损", "solution": "补焊/更换水套/控制炉温"},
            {"fault": "精矿喷嘴堵塞", "cause": "精矿含水高/喷嘴结垢/风压不足", "solution": "控制精矿水分/清理喷嘴/提高风压"},
            {"fault": "炉结严重", "cause": "炉温偏低/配料不当/喷枪角度不对", "solution": "提高炉温/调整配料/调整喷枪"},
        ],
        "acceptance_items": ["炉壳制作验收", "铜水套水压试验", "炉壳焊接检测", "反应塔安装", "铜水套安装", "耐火砌筑", "精矿喷嘴安装", "烘炉", "投料试车"],
    },
    "浮选机": {
        "category": "选矿设备",
        "subcategory": "选别设备",
        "typical_models": ["SF-4", "SF-8", "SF-16", "SF-20", "JJF-8", "JJF-16", "XCF-8", "KYF-16", "Φ2m", "Φ3m", "Φ4m"],
        "key_parameters": {
            "单槽容积": "4~50m³",
            "叶轮直径": "0.5~1.2m",
            "叶轮转速": "150~300r/min",
            "电机功率": "15~132kW",
            "充气量": "0.5~1.5m³/(m²·min)",
            "处理量": "5~50t/h（单槽）",
            "槽体深度": "1.0~2.5m",
        },
        "main_components": ["槽体", "叶轮", "定子", "主轴", "电机", "皮带轮", "充气装置", "刮板装置", "液位调节装置", "给矿/排矿口"],
        "construction_key_points": [
            "槽体焊接完成后进行盛水试验，24h无渗漏",
            "主轴垂直度偏差不大于0.5mm/m",
            "叶轮与槽底间隙按厂家要求，一般5~15mm",
            "叶轮与定子间隙均匀，偏差不大于±2mm",
            "皮带轮对齐偏差不大于1mm，皮带张紧度适中",
            "刮板装置运行平稳，刮板与槽沿间隙5~10mm",
            "充气系统调节灵活，充气量稳定",
            "试运转时轴承温度不超过70℃，振动不大于0.1mm",
        ],
        "quality_standards": [
            "GB 50231-2009 机械设备安装工程施工及验收通用规范",
            "JB/T 1552 浮选机技术条件",
            "厂家安装使用说明书",
        ],
        "common_faults": [
            {"fault": "叶轮磨损过快", "cause": "矿浆磨蚀性强/材质不达标/间隙不当", "solution": "更换耐磨材质/调整间隙/定期检查"},
            {"fault": "充气量不足", "cause": "鼓风机故障/管路堵塞/叶轮磨损", "solution": "检修鼓风机/清理管路/更换叶轮"},
            {"fault": "槽体漏浆", "cause": "焊缝缺陷/法兰密封失效", "solution": "补焊/更换密封"},
            {"fault": "主轴振动大", "cause": "轴承磨损/叶轮不平衡/基础松动", "solution": "更换轴承/做动平衡/紧固基础"},
        ],
        "acceptance_items": ["槽体制作验收", "盛水试验", "主轴安装", "叶轮定子安装", "传动系统安装", "充气系统调试", "刮板装置调试", "空载试运转", "负载试运转"],
    },
    "颚式破碎机": {
        "category": "矿山设备",
        "subcategory": "破碎设备",
        "typical_models": ["PE-400×600", "PE-600×900", "PE-750×1060", "PE-900×1200", "PE-1200×1500", "C80", "C100", "C125", "C160"],
        "key_parameters": {
            "给料口尺寸": "400×600~1500×1800mm",
            "最大给料粒度": "350~1300mm",
            "排料口调整范围": "40~200mm",
            "处理量": "15~1000t/h",
            "电机功率": "30~400kW",
            "偏心轴转速": "150~300r/min",
            "破碎比": "3~6",
        },
        "main_components": ["机架", "定颚", "动颚", "偏心轴", "肘板", "肘板座", "拉杆", "弹簧", "飞轮", "皮带轮", "电机", "调整装置", "润滑系统"],
        "construction_key_points": [
            "机架安装水平度偏差不大于0.1mm/m",
            "偏心轴与轴瓦接触角60°~90°，接触点不少于1~2点/cm²",
            "动颚与定颚齿板间隙均匀，排料口尺寸符合要求",
            "肘板与肘板座接触面积不少于70%",
            "飞轮和皮带轮端面跳动不大于1mm",
            "皮带张紧度适中，两轮对齐偏差不大于1mm",
            "润滑系统畅通，各润滑点供油正常",
            "试运转时轴承温度不超过70℃，温升不超过40℃",
        ],
        "quality_standards": [
            "GB 50231-2009 机械设备安装工程施工及验收通用规范",
            "JB/T 2255 颚式破碎机技术条件",
            "厂家安装使用说明书",
        ],
        "common_faults": [
            {"fault": "轴承温度过高", "cause": "润滑不良/轴瓦接触不良/负荷过大", "solution": "补充润滑/重新刮研/调整负荷"},
            {"fault": "肘板断裂", "cause": "过载/材质缺陷/安装不当", "solution": "更换肘板/安装过载保护/正确安装"},
            {"fault": "齿板磨损过快", "cause": "物料磨蚀性强/材质不达标", "solution": "更换高锰钢齿板/定期翻面使用"},
            {"fault": "飞轮回转不平稳", "cause": "偏心轴弯曲/轴承磨损/飞轮松动", "solution": "校直轴/更换轴承/紧固飞轮"},
        ],
        "acceptance_items": ["基础验收", "机架安装", "偏心轴安装", "动颚安装", "肘板安装", "传动系统安装", "润滑系统调试", "空载试运转", "负载试运转"],
    },
    "浓缩机": {
        "category": "选矿设备",
        "subcategory": "脱水设备",
        "typical_models": ["Φ6m", "Φ9m", "Φ12m", "Φ18m", "Φ24m", "Φ30m", "Φ36m", "Φ45m", "NZ-12", "NZ-24", "NG-30"],
        "key_parameters": {
            "池子直径": "6~45m",
            "池子深度": "3~6m",
            "沉降面积": "28~1590m²",
            "耙架转速": "0.05~0.5r/min",
            "电机功率": "3~45kW",
            "处理量": "20~2000t/d",
            "底流浓度": "40~70%",
        },
        "main_components": ["池子", "耙架", "中心传动装置", "提耙装置", "进料筒", "溢流堰", "底流泵", "桥架", "润滑系统", "控制系统"],
        "construction_key_points": [
            "池子混凝土浇筑密实，内壁光滑，不得有渗漏",
            "中心传动装置安装水平度偏差不大于0.1mm/m",
            "耙架安装水平度偏差不大于5mm",
            "耙架与池底间隙均匀，一般50~100mm",
            "提耙装置动作灵活，限位准确",
            "溢流堰水平度偏差不大于±3mm",
            "进料筒安装垂直，中心偏差不大于10mm",
            "试运转时耙架运行平稳，无卡阻，电流稳定",
        ],
        "quality_standards": [
            "GB 50231-2009 机械设备安装工程施工及验收通用规范",
            "JB/T 1816 浓缩机技术条件",
            "厂家安装使用说明书",
        ],
        "common_faults": [
            {"fault": "耙架扭矩过大", "cause": "底流浓度过高/排料不畅/耙架变形", "solution": "降低底流浓度/清理排料口/校正耙架"},
            {"fault": "池子渗漏", "cause": "混凝土裂缝/密封失效", "solution": "注浆修补/更换密封"},
            {"fault": "提耙装置失灵", "cause": "液压故障/限位开关损坏/机械卡阻", "solution": "检修液压系统/更换限位/排除卡阻"},
            {"fault": "溢流浑浊", "cause": "絮凝剂添加不足/进料不均/耙速过快", "solution": "调整絮凝剂/均匀进料/降低耙速"},
        ],
        "acceptance_items": ["池子验收", "中心传动安装", "耙架安装", "提耙装置调试", "进料筒安装", "溢流堰安装", "空载试运转", "负载试运转"],
    },
    "压滤机": {
        "category": "选矿设备",
        "subcategory": "脱水设备",
        "typical_models": ["XMZ100/1000", "XMZ200/1250", "XMZ500/1500", "XMZ1000/2000", "KM500", "KM1000", "APN100", "APN200"],
        "key_parameters": {
            "过滤面积": "50~1000m²",
            "滤板尺寸": "800×800~2000×2000mm",
            "滤板数量": "20~100块",
            "过滤压力": "0.6~1.6MPa",
            "油缸压力": "10~30MPa",
            "电机功率": "7.5~55kW",
            "处理量": "5~100t/h",
            "滤饼水分": "8~15%",
        },
        "main_components": ["机架", "滤板", "滤布", "压紧装置（液压/机械）", "油缸", "液压站", "进料泵", "翻板装置", "拉板装置", "控制系统", "接液盘"],
        "construction_key_points": [
            "机架安装水平度偏差不大于0.1mm/m",
            "主梁平行度偏差不大于2mm",
            "滤板排列整齐，密封面清洁无损伤",
            "滤布铺设平整，无褶皱，密封良好",
            "液压系统试压无泄漏，压力稳定",
            "压紧力达到设计要求，保压30min压力降不大于5%",
            "拉板装置运行平稳，定位准确",
            "翻板装置动作灵活，密封良好",
            "试运转时各动作顺序正确，无卡阻",
        ],
        "quality_standards": [
            "GB 50231-2009 机械设备安装工程施工及验收通用规范",
            "JB/T 4333 厢式压滤机和板框压滤机技术条件",
            "厂家安装使用说明书",
        ],
        "common_faults": [
            {"fault": "滤板间喷浆", "cause": "滤布破损/密封面有异物/压紧力不足", "solution": "更换滤布/清理密封面/提高压紧力"},
            {"fault": "液压系统不保压", "cause": "油缸内泄/电磁阀泄漏/液压油不足", "solution": "更换密封/检修阀件/补充液压油"},
            {"fault": "拉板失灵", "cause": "链条松动/限位开关损坏/电机故障", "solution": "张紧链条/更换限位/检修电机"},
            {"fault": "滤饼水分高", "cause": "过滤压力不足/过滤时间短/滤布堵塞", "solution": "提高压力/延长时间/清洗滤布"},
        ],
        "acceptance_items": ["机架安装", "滤板安装", "滤布安装", "液压系统调试", "压紧试验", "拉板装置调试", "翻板装置调试", "空载试运转", "负载试运转"],
    },
}


# ============================================================
# 设备施工阶段要点库
# ============================================================

EQUIPMENT_PHASE_POINTS = {
    "球磨机": {
        "开箱检验": ["核对设备型号、规格、数量与合同一致", "检查筒体、端盖有无变形、裂纹", "检查主轴承轴瓦有无划痕、裂纹", "核对衬板、螺栓数量", "检查随机文件（合格证、说明书、图纸）", "记录设备外观状况，拍照存档"],
        "基础验收": ["基础混凝土强度报告（≥75%设计强度）", "基础尺寸复核（中心线、标高、地脚螺栓孔）", "基础表面清理，凿毛处理", "基础沉降观测记录"],
        "设备安装": ["主轴承座安装，水平度≤0.1mm/m", "轴瓦刮研，接触点≥2点/cm²", "筒体吊装，使用专用吊具", "筒体水平度≤0.1mm/m", "大齿圈安装，端面跳动≤1.5mm", "齿轮啮合调整，侧隙0.8~1.6mm", "衬板安装，螺栓力矩800~1200N·m", "润滑系统安装调试"],
        "试运转": ["空载试运转2~4小时", "主轴承温度≤65℃，温升≤35℃", "齿轮啮合无异常声响", "润滑系统压力正常", "振动速度≤4.5mm/s", "负载试运转8~24小时", "记录运行参数，填写试运转记录"],
    },
    "高压釜": {
        "开箱检验": ["核对设备型号、规格、材质", "检查钛衬里表面有无划伤、污染", "检查法兰密封面有无损伤", "核对随机文件（压力容器合格证、监检证书）", "记录设备编号、出厂日期"],
        "基础验收": ["基础混凝土强度报告", "基础尺寸复核", "基础预埋件检查"],
        "设备安装": ["设备就位，中心线偏差≤5mm", "标高偏差≤±5mm", "水平度≤0.1mm/m", "钛衬里电火花检测（10~15kV）", "耐压试验（1.25倍设计压力）", "气密性试验（1.0倍设计压力）", "机械密封静压试验", "搅拌装置安装调试", "安全阀校验铅封"],
        "试运转": ["水压试验合格", "气密性试验合格", "搅拌装置空载试运转", "机械密封无泄漏", "轴承温度≤70℃", "带料试运行，记录温度、压力、搅拌电流"],
    },
}


def get_equipment_detail(equipment_name: str) -> dict:
    """获取设备详细信息。"""
    if equipment_name in EQUIPMENT_DETAILS:
        return {
            "ok": True,
            "equipment": equipment_name,
            "detail": EQUIPMENT_DETAILS[equipment_name],
        }
    
    # 模糊匹配
    for key in EQUIPMENT_DETAILS:
        if equipment_name in key or key in equipment_name:
            return {
                "ok": True,
                "equipment": key,
                "detail": EQUIPMENT_DETAILS[key],
                "matched_by": "fuzzy",
            }
    
    return {
        "ok": False,
        "error": f"未找到设备详细信息: {equipment_name}",
        "available_equipment": list(EQUIPMENT_DETAILS.keys()),
    }


def get_all_equipment_details() -> dict:
    """获取所有设备详细信息列表。"""
    equipment_list = []
    for name, detail in EQUIPMENT_DETAILS.items():
        equipment_list.append({
            "name": name,
            "category": detail.get("category", ""),
            "subcategory": detail.get("subcategory", ""),
            "typical_models": detail.get("typical_models", []),
            "key_parameters_count": len(detail.get("key_parameters", {})),
            "construction_points_count": len(detail.get("construction_key_points", [])),
            "quality_standards_count": len(detail.get("quality_standards", [])),
            "common_faults_count": len(detail.get("common_faults", [])),
            "acceptance_items_count": len(detail.get("acceptance_items", [])),
        })
    
    return {
        "ok": True,
        "total": len(equipment_list),
        "equipment_list": equipment_list,
    }


def get_equipment_construction_points(equipment_name: str, phase: str = "") -> dict:
    """获取设备施工要点。"""
    detail_result = get_equipment_detail(equipment_name)
    if not detail_result.get("ok"):
        return detail_result
    
    detail = detail_result["detail"]
    points = detail.get("construction_key_points", [])
    
    if phase:
        # 按阶段筛选
        phase_points = []
        for p in points:
            if phase in p or any(kw in p for kw in _phase_keywords(phase)):
                phase_points.append(p)
        if phase_points:
            points = phase_points
    
    return {
        "ok": True,
        "equipment": detail_result["equipment"],
        "phase": phase,
        "construction_points": points,
        "total": len(points),
    }


def get_equipment_quality_standards(equipment_name: str) -> dict:
    """获取设备质量标准。"""
    detail_result = get_equipment_detail(equipment_name)
    if not detail_result.get("ok"):
        return detail_result
    
    return {
        "ok": True,
        "equipment": detail_result["equipment"],
        "quality_standards": detail_result["detail"].get("quality_standards", []),
        "total": len(detail_result["detail"].get("quality_standards", [])),
    }


def get_equipment_common_faults(equipment_name: str) -> dict:
    """获取设备常见故障。"""
    detail_result = get_equipment_detail(equipment_name)
    if not detail_result.get("ok"):
        return detail_result
    
    return {
        "ok": True,
        "equipment": detail_result["equipment"],
        "common_faults": detail_result["detail"].get("common_faults", []),
        "total": len(detail_result["detail"].get("common_faults", [])),
    }


def get_equipment_acceptance_items(equipment_name: str) -> dict:
    """获取设备验收项目。"""
    detail_result = get_equipment_detail(equipment_name)
    if not detail_result.get("ok"):
        return detail_result
    
    return {
        "ok": True,
        "equipment": detail_result["equipment"],
        "acceptance_items": detail_result["detail"].get("acceptance_items", []),
        "total": len(detail_result["detail"].get("acceptance_items", [])),
    }


def get_equipment_phase_points(equipment_name: str, phase: str = "") -> dict:
    """获取设备分阶段施工要点（从EQUIPMENT_PHASE_POINTS）。"""
    if equipment_name not in EQUIPMENT_PHASE_POINTS:
        # 尝试模糊匹配
        for key in EQUIPMENT_PHASE_POINTS:
            if equipment_name in key or key in equipment_name:
                equipment_name = key
                break
        else:
            return {"ok": False, "error": f"未找到设备分阶段要点: {equipment_name}"}
    
    phase_data = EQUIPMENT_PHASE_POINTS[equipment_name]
    
    if phase:
        if phase in phase_data:
            return {
                "ok": True,
                "equipment": equipment_name,
                "phase": phase,
                "points": phase_data[phase],
                "total": len(phase_data[phase]),
            }
        else:
            return {"ok": False, "error": f"未找到阶段: {phase}", "available_phases": list(phase_data.keys())}
    
    return {
        "ok": True,
        "equipment": equipment_name,
        "phases": list(phase_data.keys()),
        "phase_data": phase_data,
        "total_phases": len(phase_data),
    }


def _phase_keywords(phase: str) -> list:
    """阶段关键词映射。"""
    mapping = {
        "开箱": ["开箱", "检验", "验收", "到货", "装箱"],
        "基础": ["基础", "混凝土", "地脚", "预埋"],
        "安装": ["安装", "找平", "找正", "水平", "紧固", "吊装", "刮研", "啮合"],
        "试运转": ["试运转", "试运行", "空载", "负载", "温度", "振动", "试车"],
        "验收": ["验收", "检查", "检测", "试验"],
    }
    for key, kws in mapping.items():
        if key in phase:
            return kws
    return [phase]


def get_knowledge_base_stats() -> dict:
    """获取知识库统计。"""
    return {
        "ok": True,
        "detailed_equipment_count": len(EQUIPMENT_DETAILS),
        "phase_points_equipment_count": len(EQUIPMENT_PHASE_POINTS),
        "categories": list(set(d.get("category", "") for d in EQUIPMENT_DETAILS.values())),
        "subcategories": list(set(d.get("subcategory", "") for d in EQUIPMENT_DETAILS.values())),
        "total_construction_points": sum(len(d.get("construction_key_points", [])) for d in EQUIPMENT_DETAILS.values()),
        "total_quality_standards": sum(len(d.get("quality_standards", [])) for d in EQUIPMENT_DETAILS.values()),
        "total_common_faults": sum(len(d.get("common_faults", [])) for d in EQUIPMENT_DETAILS.values()),
        "total_acceptance_items": sum(len(d.get("acceptance_items", [])) for d in EQUIPMENT_DETAILS.values()),
    }
