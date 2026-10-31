"""
v0.1.147：监理确认模板库（车间级整合版+设备安装册28模板）

基于监理确认过的辊磨筛分车间表格实例，制作内置模板库（templates_builtin/）：
- 保留车间级多表结构：每个原文件=1个表类型模板，内含多张设备类型检查表
- 去数据化：实例数据替换为 {{占位符}}

生成时（按车间整合，非按单设备）：
1. 选择表类型 + 车间
2. 从设备台账取该车间全部设备，按设备类型分组（胶带输送机/振动筛/渣浆泵...）
3. 模板中每个"设备类型表"匹配对应设备组：
   - 组内有 N 台设备 → 该表复制 N 份，每份填一台设备
   - 组内无设备 → 跳过该表
4. 项目常量（施工单位/项目经理/监理单位等）→ 项目配置，逐表填入
5. 输出：一份 docx 含该车间所有设备的同类表

实现：
- ensure_builtin_registered(): 扫描 templates_builtin/ 注册（doc_type=监理确认表）
- render_supervision_doc(): 车间级渲染
- list_by_category(): 按表类型分组返回可用模板
"""

import os
import re
import json
import datetime
import copy
from typing import Optional, Dict, List
from zipfile import ZipFile
import zipfile
from . import gb_form as _gb
from lxml import etree

from . import config
from . import template_engine as _te

# 未填占位符的可见替身。必须落进文档，不能留下 {{模板变量}}（v0.1.174）
UNFILLED_MARK = "【待补充】"

# 内置模板目录
BUILTIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates_builtin",
)
TABLE_INDEX_FILE = os.path.join(BUILTIN_DIR, "_table_index.json")

# 模板表类型清单缓存：{模板文件名: [表0类型, 表1类型, ...]}
_TABLE_INDEX_CACHE = None


def _load_table_index() -> Dict:
    """读取 build_templates 生成的表类型清单（按表序识别每张表设备类型）。"""
    global _TABLE_INDEX_CACHE
    if _TABLE_INDEX_CACHE is not None:
        return _TABLE_INDEX_CACHE
    _TABLE_INDEX_CACHE = {}
    try:
        if os.path.isfile(TABLE_INDEX_FILE):
            with open(TABLE_INDEX_FILE, "r", encoding="utf-8") as f:
                _TABLE_INDEX_CACHE = json.load(f)
    except Exception:  # noqa: BLE001
        pass
    return _TABLE_INDEX_CACHE

DOC_TYPE = "监理确认表"

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
def q(t): return '{%s}%s' % (W_NS, t)

# 表类型 ↔ 文件名关键词映射（模板按此归类）
CATEGORY_KEYWORDS = [
    ("仪表设备管件阀门进场检验记录", ["仪表设备"]),
    ("取源部件安装开孔焊接隐蔽记录", ["取源部件"]),
    ("仪表桥架保护管敷设隐蔽记录", ["仪表桥架"]),
    ("仪表电缆敷设记录", ["仪表电缆"]),
    ("仪表阀门执行机构流量计液位计安装记录", ["流量计"]),
    ("导压管气动管线压力试验记录", ["气动管线压力"]),
    ("导压管气动管线吹扫清洗记录", ["气动管线吹扫"]),
    ("导压管气动管线安装记录", ["导压管"]),
    ("管路脱脂记录", ["脱脂"]),
    ("DCSPLC仪表盘柜安装记录", ["仪表盘柜"]),
    ("单台仪表校准记录", ["校准"]),
    ("仪表回路试验记录", ["回路试验"]),
    ("气源系统压力试验吹扫记录", ["气源"]),
    ("DCSPLC硬件IO通道测试记录", ["IO"]),
    ("DCS画面参数检查测试记录", ["DCS画面", "DCS 画面"]),
    ("联锁保护系统试验记录", ["联锁"]),
    ("仪表报警功能试验记录", ["报警"]),
    ("仪表系统联调投料前试运行记录", ["联调"]),
    ("仪表标定证书台账", ["标定"]),
    ("工程开工报告", ["开工报告"]),
    ("单位工程质量验收记录", ["单位工程"]),
    ("变压器安装施工记录", ["变压器安装"]),
    ("变压器器身检查记录", ["器身"]),
    ("变压器干燥处理记录", ["变压器干燥"]),
    ("高压开关柜安装调整记录", ["开关柜"]),
    ("母线装置安装记录", ["母线装置安装"]),
    ("盘柜安装记录", ["盘柜"]),
    ("二次配线二次回路检查记录", ["二次"]),
    ("电缆终端头中间头制作记录", ["终端头"]),
    ("直流屏蓄电池组安装记录", ["蓄电池组"]),
    ("变压器交接试验记录", ["变压器交接"]),
    ("变压器油化验报告", ["油化验"]),
    ("高压断路器试验记录", ["断路器"]),
    ("隔离开关负荷开关试验记录", ["隔离开关"]),
    ("SF6气体湿度检漏试验记录", ["SF6"]),
    ("CTPT交接试验记录", ["CT"]),
    ("母线绝缘及耐压试验记录", ["母线绝缘"]),
    ("高压电缆交接试验记录", ["高压电缆"]),
    ("继电保护装置单体调试记录", ["单体调试"]),
    ("继电保护定值单", ["定值单"]),
    ("保护整组传动试验记录", ["整组传动"]),
    ("蓄电池充放电试验记录", ["充放电"]),
    ("直流屏及绝缘监察试验记录", ["绝缘监察"]),
    ("接地网接地电阻测试记录", ["接地网"]),
    ("冲击合闸带电试运行签证", ["冲击合闸"]),
    ("低压配电柜MCC操作箱安装记录", ["配电柜"]),
    ("电缆敷设电缆头制作记录", ["电缆敷设"]),
    ("电气导管敷设隐蔽验收记录", ["导管"]),
    ("桥架支架安装记录", ["桥架"]),
    ("电机安装轴承对中记录", ["电机安装"]),
    ("电机干燥处理记录", ["干燥"]),
    ("防爆电气设备安装记录", ["防爆"]),
    ("照明插座安装记录", ["照明"]),
    ("车间接地等电位防静电隐蔽记录", ["防静电隐蔽"]),
    ("低压电缆绝缘电阻测试记录", ["绝缘电阻"]),
    ("电机绝缘直流电阻测试记录", ["直流电阻"]),
    ("电机转向单机试运转记录", ["转向"]),
    ("低压回路通电相序核对记录", ["相序"]),
    ("接地电阻等电位导通测试记录", ["等电位导通"]),
    ("防静电接地电阻测试记录", ["防静电接地"]),
    ("漏电保护器动作试验记录", ["漏电保护"]),
    ("车间系统受电试运行记录", ["受电"]),
    ("管道元件检查记录", ["管道元件"]),
    ("焊接工艺评定记录", ["工艺评定"]),
    ("焊接作业指导书", ["作业指导书"]),
    ("管道基础管墩复测记录", ["管墩"]),
    ("管道支吊架安装记录", ["支吊架"]),
    ("管道预制记录", ["预制"]),
    ("管道安装记录", ["管道安装"]),
    ("设备地脚螺栓紧固记录", ["地脚螺栓"]),
    ("法兰螺栓紧固记录", ["螺栓紧固"]),
    ("管道焊缝位置检查记录", ["焊缝位置"]),
    ("埋地管道隐蔽验收记录", ["埋地"]),
    ("管道封闭前检查记录", ["封闭前"]),
    ("管道焊接检查记录", ["管道焊接"]),
    ("管道热处理报告", ["管道热处理报告"]),
    ("管道热处理硬度检测报告", ["硬度检测"]),
    ("设备耐压试验记录", ["耐压"]),
    ("管道系统压力试验记录", ["压力试验", "水压"]),
    ("管道系统泄漏性试验记录", ["泄漏性"]),
    ("管道吹扫清洗记录", ["吹扫"]),
    ("阀门单体试验记录", ["阀门单体试验"]),
    ("管道补偿装置安装记录", ["补偿装置"]),
    ("管道静电接地测试记录", ["静电接地"]),
    ("管道弯管加工记录", ["弯管"]),
    ("设备找平找正记录", ["找平找正记录", "设备找平", "对中"]),
    ("设备吊装就位记录", ["吊装"]),
    ("施工方案报审表", ["方案报审"]),
    ("安全技术交底记录", ["安全技术交底", "技术交底"]),
    ("图纸会审设计交底纪要", ["图纸会审"]),
    ("设计变更工程洽商记录", ["设计变更"]),
    ("设备材料进场报验单", ["进场报验"]),
    ("焊工资格证登记表", ["焊工"]),
    ("工程缺陷通知单", ["缺陷通知"]),
    ("竣工报告中间交接证书", ["竣工报告", "中间交接"]),
    ("基础沉降观测记录", ["沉降"]),
    ("设备垫铁检查记录", ["垫铁"]),
    ("隐蔽工程验收记录", ["隐蔽"]),
    ("单机试运转缺陷整改记录", ["缺陷整改"]),
    ("试运行验收签证", ["验收签证"]),
    ("备品备件移交清单", ["备品备件"]),
    ("设备清理清扫封闭记录", ["清理清扫"]),
    ("设备绝热施工记录", ["绝热"]),
    ("试运转参数记录", ["试运转参数"]),
    ("设备气密性试验记录", ["气密"]),
    ("设备内件安装记录", ["内件"]),
    ("设备焊接施工记录", ["焊接"]),
    ("焊后热处理记录", ["热处理"]),
    ("无损检测报告底片台账", ["无损"]),
    ("安全阀校验及安装记录", ["安全阀"]),
    ("设备除锈防腐检查记录", ["除锈防腐", "除锈", "防腐"]),
    ("设备报审表", ["报审"]),
    ("设备开箱检查记录", ["开箱"]),
    ("设备安装基础复测记录", ["基础复测"]),
    ("设备安装检查记录", ["安装检查"]),
    ("分项工程质量验收记录", ["分项"]),
    ("分部子分部质量评定表", ["分部"]),
    ("单机无负荷试运转记录", ["试运转", "单机"]),
    ("系统联动试运行记录", ["联动"]),
    ("设备重量确认单", ["重量确认"]),
]

BUILTIN_FIELD_DOC = {
    "项目名称": "工程项目全称（自动取当前项目名）",
    "单位工程": "单位工程名，如：选矿厂",
    "分部工程": "分部工程名，如：工业设备安装",
    "车间": "所在车间，如：辊磨筛分车间",
    "系统名称": "联动试运行系统名，如：辊磨筛分系统设备",
    "施工单位": "施工总包单位（项目配置）",
    "项目经理": "项目经理姓名（项目配置）",
    "技术负责人": "技术负责人姓名（项目配置）",
    "质量负责人": "质量部门负责人（项目配置）",
    "监理单位": "监理单位全称（项目配置）",
    "建设单位": "建设单位（项目配置）",
    "标准编号": "验收标准，如：GB50231-2009（模板已按国标固化）",
    "设备名称": "设备名称（设备台账自动匹配）",
    "设备位号": "设备位号/图号（设备台账自动匹配）",
    "规格型号": "设备规格型号（设备台账自动匹配）",
    "供货厂家": "设备生产厂家（设备台账自动匹配）",
    "施工图号": "施工图纸编号（设备台账/图纸解析）",
    "数量": "设备数量",
    "单重": "设备单重（t）",
    "总重": "设备总重（t）",
    "重量依据": "重量依据来源（厂家图纸/清单）",
}

# 设备类型关键词（用于把车间设备分组）
DEVICE_TYPE_KEYWORDS = [
    ("胶带输送机", ["胶带输送机", "胶带机"]),
    ("给料机", ["给料机"]),
    ("破碎机", ["破碎机", "颚式", "圆锥破", "反击破"]),
    # v0.1.172：选矿主流程设备原来全部落到「通用」，模板匹配时无法报出具体缺哪类表
    ("磨矿设备", ["球磨机", "棒磨机", "半自磨机", "磨机"]),
    ("浮选设备", ["浮选机", "浮选柱", "浮选"]),
    ("磁选设备", ["磁选机"]),
    ("除铁器", ["除铁器", "磁选"]),
    ("除尘设备", ["除尘", "袋式"]),
    ("离心风机", ["风机", "通风机", "G6-51"]),
    ("空压机", ["空压机", "压缩机", "V11"]),
    ("螺旋输送机", ["螺旋输送机", "LS"]),
    ("平板闸门", ["平板闸门", "闸门"]),
    ("振动筛", ["振动筛"]),
    ("电动单梁起重机", ["起重机", "行车"]),
    ("电动葫芦", ["电动葫芦", "葫芦"]),
    ("液下渣浆泵", ["液下渣浆泵"]),
    ("渣浆泵", ["渣浆泵"]),
    ("搅拌设备", ["搅拌", "浓密"]),
    ("减速机", ["减速机", "减速器"]),
    ("微雾抑尘", ["微雾抑尘", "抑尘"]),
]


def _categorize(name: str) -> str:
    """根据模板名关键词归类表类型。"""
    for cat, kws in CATEGORY_KEYWORDS:
        if any(k in name for k in kws):
            return cat
    return "其他"


# v0.1.167：补充通用工艺设备类型 —— 原表只有矿山专用设备（胶带机/破碎机/渣浆泵…），
# 离心泵/储罐/变压器等常规设备全部落到「通用」，与竣工资料链路按名称推断出的
# 泵/储罐/电机不一致，同一台设备在两条链路上给出两种类型。
COMMON_DEVICE_TYPE_KEYWORDS = [
    ("泵", ["离心泵", "齿轮泵", "柱塞泵", "螺杆泵", "隔膜泵", "污水泵", "潜水泵", "泵"]),
    ("风机", ["离心风机", "通风机", "风机"]),
    ("压缩机", ["空压机", "压缩机"]),
    ("换热器", ["换热器", "冷却器", "冷凝器", "再沸器", "空冷器"]),
    ("储罐", ["储罐", "储槽", "罐"]),
    ("塔器", ["塔器", "精馏塔", "吸收塔", "洗涤塔"]),
    ("容器", ["反应釜", "反应器", "容器", "分离器"]),
    ("电机", ["电动机", "电机", "变压器"]),
    ("阀门", ["阀门", "闸阀", "球阀", "蝶阀", "截止阀"]),
    ("起重机", ["起重机", "行车", "电动葫芦", "葫芦"]),
]


def _device_type_of(equipment: str) -> str:
    """从设备名称提取设备类型（用于模板表匹配）。

    v0.1.179：名称为空时返回「通用」而不是空串。
    真实台账里有 13 台设备只有型号、没有名称（G6-51-10D-55kw、LS250、V11-8…）。
    返回空串会让它们落进一个没有任何模板槽位会去取的隐形分组，
    结果就是"提取到了、也合并了，但一张确认表都没出"。
    """
    if not equipment:
        return "通用"
    # 先匹配矿山专用设备（更具体），再回落到通用工艺设备
    for t, kws in DEVICE_TYPE_KEYWORDS:
        for k in kws:
            if k in equipment:
                return t
    for t, kws in COMMON_DEVICE_TYPE_KEYWORDS:
        for k in kws:
            if k in equipment:
                return t
    return "通用"


# ---------------- 模板注册 ----------------

def _ensure_builtin_registered() -> int:
    """扫描 templates_builtin/ 把未注册的 docx/xlsx 注册进模板索引。幂等。

    v0.1.182：整段在 _te._INDEX_LOCK 内执行。原来它自己直接
    `_load_template_index()` / `_save_template_index(index)` 做「读—改—写」，
    与 upload_template 的写入互不互斥：整卷 3 路并发时每路都调这个函数，
    后写的一路把先写的一路的注册结果整份覆盖掉 —— 索引里少了模板，
    生成端随即报「未找到表类型 X 的模板」；同时同内容被判「不一致」而
    重复复制，堆出上万个孤儿副本。
    """
    with _te._INDEX_LOCK:
        return _ensure_builtin_registered_locked()


def _ensure_builtin_registered_locked() -> int:
    """实际实现，**调用方必须已持有 _te._INDEX_LOCK**。"""
    if not os.path.isdir(BUILTIN_DIR):
        return 0
    registered = 0
    index = _te._load_template_index()
    existing_names = {t.get("name") for t in index.get("templates", [])}
    for fn in sorted(os.listdir(BUILTIN_DIR)):
        if not (fn.endswith(".docx") or fn.endswith(".xlsx")):
            continue
        tpl_name = fn[:-5]
        src_path = os.path.join(BUILTIN_DIR, fn)
        category = _categorize(tpl_name)
        doc_type = f"{DOC_TYPE}|{category}"
        if tpl_name in existing_names:
            # 已有记录：校验内容一致性 + doc_type 是否过时
            _stored = None
            for _t in index.get("templates", []):
                if _t.get("name") == tpl_name:
                    _stored = _t
                    break
            _same = False
            if _stored:
                _sf = os.path.join(_te.TEMPLATES_DIR, _stored.get("file_name", ""))
                try:
                    _same = os.path.isfile(_sf) and open(src_path, 'rb').read() == open(_sf, 'rb').read()
                except Exception:
                    _same = False
            if _stored and not _same:
                # 内容不一致（模板已更新）→ 删除旧条目，重新注册
                index["templates"] = [t for t in index.get("templates", []) if t.get("name") != tpl_name]
                try:
                    _te._save_template_index(index)
                except Exception:
                    pass
            elif _stored and _stored.get("doc_type") != doc_type:
                _stored["doc_type"] = doc_type
                try:
                    _te._save_template_index(index)
                except Exception:
                    pass
            if _stored and _same and _stored.get("doc_type") == doc_type:
                continue
        try:
            result = _te.upload_template(src_path, tpl_name, doc_type, f"监理确认模板：{category}")
            if result.get("ok"):
                registered += 1
                existing_names.add(tpl_name)
        except Exception:  # noqa: BLE001
            continue
    return registered


def list_by_category() -> Dict:
    """按表类型分组返回内置模板。"""
    _ensure_builtin_registered()
    index = _te._load_template_index()
    grouped = {}
    for t in index.get("templates", []):
        dt = t.get("doc_type", "")
        if not dt.startswith(DOC_TYPE):
            continue
        cat = dt.split("|", 1)[1] if "|" in dt else t.get("name", "")
        grouped.setdefault(cat, []).append({
            "id": t["id"],
            "name": t["name"],
            "placeholder_count": t.get("placeholder_count", 0),
            "use_count": t.get("use_count", 0),
        })
    return {
        "ok": True,
        "total": sum(len(v) for v in grouped.values()),
        "categories": grouped,
        "fields": BUILTIN_FIELD_DOC,
    }


# ---------------- 项目常量 & 设备数据 ----------------

def _load_project_config(project_id: str = None) -> Dict:
    """读取项目配置常量。"""
    from . import project_manager as _pm
    cfg = {
        "项目名称": "",
        "单位工程": "",
        "分部工程": "工业设备安装",
        "车间": "",
        "系统名称": "",
        "施工单位": "",
        "项目经理": "",
        "技术负责人": "",
        "质量负责人": "",
        "监理单位": "",
        "建设单位": "",
        "标准编号": "《机械设备安装工程施工及验收通用规范》GB50231-2009",
    }
    current = _pm.get_current_project()
    if current:
        cfg["项目名称"] = current.get("name", "")
        cfg["建设单位"] = current.get("client", "")
        cfg["单位工程"] = current.get("unit_works", cfg["单位工程"])
        cfg["分部工程"] = current.get("sub_works", cfg["分部工程"])
        cfg["车间"] = current.get("default_workshop", cfg["车间"])
        cfg["施工单位"] = current.get("contractor", cfg["施工单位"])
        cfg["项目经理"] = current.get("project_manager", cfg["项目经理"])
        cfg["技术负责人"] = current.get("tech_leader", cfg["技术负责人"])
        cfg["质量负责人"] = current.get("quality_leader", cfg["质量负责人"])
        cfg["监理单位"] = current.get("supervisor", cfg["监理单位"])
    # 扩展配置：合并项目 index.json（设备台账/工程常量可能存于此）
    try:
        _dd = _pm.get_project_data_dir(project_id)
        _ip = os.path.join(_dd, "index.json")
        if os.path.isfile(_ip):
            with open(_ip, "r", encoding="utf-8") as _f:
                _ix = json.load(_f)
            _map = {
                "项目名称": "name", "建设单位": "client", "单位工程": "unit_works",
                "分部工程": "sub_works", "车间": "default_workshop",
                "施工单位": "contractor", "项目经理": "project_manager",
                "技术负责人": "tech_leader", "质量负责人": "quality_leader",
                "监理单位": "supervisor", "系统名称": "system_name",
            }
            for _k, _jk in _map.items():
                if not cfg.get(_k) and _ix.get(_jk):
                    cfg[_k] = _ix.get(_jk)
    except Exception:
        pass
    return cfg


def _em_tag_display(tag: str) -> str:
    """内部身份键 → 对外位号。

    v0.1.179：台账没有「位号」列时，合并层必须造一个内部键来保证"一台一行"；
    但那个键（_no_tag_名称|车间|型号|规格|源文件|行号）属于实现细节，
    **绝不能出现在给监理的确认表「设备位号」栏**。这里统一收敛成空，
    表格里就是空栏，由现场人工填写，也是竣工资料的正常做法。
    """
    try:
        from . import equipment_merge as _em
        return _em.display_tag(tag)
    except Exception:  # noqa: BLE001
        t = str(tag or "").strip()
        return "" if t.startswith("_no_tag_") else t


def _get_workshop_devices(workshop: str = "", project_id: str = None) -> List[Dict]:
    """获取指定车间的设备清单（含类型分组）。
    数据源：项目 index.json devices + equipment_merge merged。"""
    devices = []
    seen = set()
    try:
        from . import project_manager as _pm
        data_dir = _pm.get_project_data_dir(project_id)
        idx_path = os.path.join(data_dir, "index.json")
        if os.path.isfile(idx_path):
            with open(idx_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
            for tag, d in (idx.get("devices") or {}).items():
                dev_ws = d.get("workshop", "")
                if workshop and dev_ws and dev_ws != workshop:
                    continue
                name = d.get("name", "")
                # v0.1.179：**无名称但有型号/规格的真实设备也要出表**。
                # 实测（紫金选矿厂真实台账 248 行）：33 行「设备名称」为空，其中 13 行
                # 只填了型号（G6-51-10D-55kw、LS250、V11-8…）。原来这里一律 continue，
                # 这些设备在确认表里一台都出不来。名称缺失不等于设备不存在。
                if not name and not (d.get("model") or d.get("spec")):
                    continue
                key = f"{tag}|{name}"
                if key in seen:
                    continue
                seen.add(key)
                devices.append({
                    # v0.1.179：对外位号 —— 台账没位号时后端给的是内部占位键，
                    # 直接印出去就等于把 _no_tag_xxx 打给监理。这里统一转成空。
                    "tag": _em_tag_display(tag),
                    "name": name,
                    "model": d.get("model", "") or d.get("spec", ""),
                    "manufacturer": d.get("manufacturer", ""),
                    "workshop": dev_ws or workshop,
                    "quantity": d.get("quantity", ""),
                    "weight": d.get("weight", "") or d.get("single_weight", ""),
                    # v0.1.180：单位（台/套=设备，m2/米/kg=材料）—— 材料车间不该出设备记录
                    "unit": d.get("unit", ""),
                    "drawing_no": d.get("drawing_no", ""),
                    "dev_type": _device_type_of(name),
                })
    except Exception:  # noqa: BLE001
        pass

    # equipment_merge 兜底
    try:
        from . import equipment_merge as _em
        merged = _em.get_merged()
        for m in merged:
            name = m.get("name", "")
            # v0.1.179：同 A —— 无名称但有型号/规格的设备不能在这里再被筛掉一次
            if not name and not (m.get("model") or m.get("spec")
                                or (m.get("fields") or {}).get("规格参数")):
                continue
            dev_ws = m.get("workshop", "")
            if workshop and dev_ws and dev_ws != workshop:
                continue
            tag = m.get("canonical_tag", "")
            key = f"{tag}|{name}"
            if key in seen:
                continue
            seen.add(key)
            flds = m.get("fields") or {}
            devices.append({
                "tag": _em_tag_display(tag),
                "name": name,
                "model": (m.get("model", "") or flds.get("型号", "")
                          or m.get("spec", "") or flds.get("规格参数", "")),
                "manufacturer": m.get("manufacturer", "") or flds.get("厂家", ""),
                "workshop": dev_ws or workshop,
                "quantity": flds.get("数量", ""),
                "weight": flds.get("重量", "") or flds.get("单重", ""),
                "drawing_no": flds.get("图号", ""),
                "dev_type": _device_type_of(name),
            })
    except Exception:  # noqa: BLE001
        pass
    return devices


def save_project_config(project_id: str = None, config: Dict = None) -> Dict:
    """保存项目配置常量。"""
    if not config:
        return {"ok": False, "error": "未提供配置内容"}
    from . import project_manager as _pm
    current = _pm.get_current_project()
    pid = project_id or (current.get("id") if current else "")
    if not pid:
        return {"ok": False, "error": "无当前项目，请先新建或选择项目"}
    project = _pm.get_project(pid)
    if not project:
        return {"ok": False, "error": f"项目不存在：{pid}"}
    field_map = {
        "施工单位": "contractor",
        "项目经理": "project_manager",
        "技术负责人": "tech_leader",
        "质量负责人": "quality_leader",
        "监理单位": "supervisor",
        "建设单位": "client",
        "单位工程": "unit_works",
        "分部工程": "sub_works",
        "车间": "default_workshop",
        "系统名称": "system_name",
    }
    changed = []
    for cn, key in field_map.items():
        if cn in config and config[cn] is not None:
            project[key] = str(config[cn]).strip()
            changed.append(cn)
    project["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta_path = _pm._get_project_meta_path(pid)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "project": project,
        "updated": changed,
        "message": f"已保存项目配置：{'、'.join(changed) if changed else '无变化'}",
    }


# ---------------- 车间级渲染 ----------------

def _fill_para_text(p, fill: Dict, unfilled: set):
    """段落级占位符替换（跨 run）。"""
    texts = p.findall('.//' + q('t'))
    if not texts:
        return
    joined = ''.join(t.text or '' for t in texts)
    if '{{' not in joined:
        return
    pat = re.compile(r'\{\{([^}]+)\}\}')
    ms = list(pat.finditer(joined))
    if not ms:
        return
    replaced = joined
    for m in ms:
        field = m.group(1).strip()
        if field in fill and str(fill[field]):
            replaced = replaced.replace(m.group(0), str(fill[field]))
        else:
            unfilled.add(field)
            # v0.1.174：未填字段必须落成可见标记。旧逻辑只记账不替换，
            # 实测结果是交给监理的 Word 里原样留着 {{施工单位}} 模板变量。
            replaced = replaced.replace(m.group(0), UNFILLED_MARK)
    texts[0].text = replaced
    for t in texts[1:]:
        t.text = ''


def _fill_element(root, fill: Dict) -> set:
    """替换 root 内所有 {{占位符}}，返回未填字段。"""
    unfilled = set()
    for p in root.findall('.//' + q('p')):
        _fill_para_text(p, fill, unfilled)
    return unfilled


def _table_signature(tbl) -> tuple:
    """表格结构指纹：逐行逐格文本（占位符原样保留）。
    同一模板内指纹相同的两张表 = 表单内容完全一致，可用于判定「该表与设备类型无关」。"""
    sig = []
    for tr in tbl.findall(q('tr')):
        cells = []
        for tc in tr.findall(q('tc')):
            cells.append(''.join(x.text or '' for x in tc.findall('.//' + q('t')))
                         .strip())
        sig.append(' | '.join(cells))
    return tuple(sig)


def _render_docx_by_workshop(template_path: str, fill_base: Dict,
                             dev_groups: Dict[str, List[Dict]],
                             workshop: str = "",
                             logical_name: str = "") -> Dict:
    """
    车间级渲染核心（v0.1.172 重写「空壳」链路）：
    - 打开模板 docx，遍历 body 下所有 tbl
    - 每个 tbl 按表序从 _table_index.json 取设备类型 → 匹配 dev_groups[类型]
      - 组内 N 台 → 复制 N 份表，每份填一台设备
      - 同一表格指纹（=表单内容完全一致）在多张表出现时，同一台设备只出一次，
        避免同一份表被重复打印 N 遍
      - 该类型无设备，但该表指纹被模板里多个不同设备类型共用（=与类型无关的表）
        → 允许借给模板未覆盖的其它类型设备使用，并记入 type_fallback 供人工核对
      - 该表指纹只属于本类型（=类型专用检查项表）→ 不生产空白表，记入 empty_tables
    - 通用表（清单标"通用"）→ 只填项目常量
    - 覆盖闸门：本车间有设备但一台都没被任何表覆盖 → ok=False，绝不产出空壳文件
    - 输出：保留原文档结构 + 表格序列
    """
    with ZipFile(template_path) as z:
        names = z.namelist()
        doc_xml = z.read('word/document.xml')
        others = {n: z.read(n) for n in names if n != 'word/document.xml'}
    root = etree.fromstring(doc_xml)
    body = root.find(q('body'))

    # 收集 body 直接子元素序列（段落+表格），保留顺序
    children = list(body)
    # 先对所有段落填项目常量（表格之间的标题等）
    for child in children:
        if etree.QName(child).localname == 'p':
            _fill_para_text(child, fill_base, set())

    # 表类型清单（按表序）。注册后文件名带时间戳前缀，需按逻辑名匹配
    tpl_name = os.path.basename(template_path)
    table_index = _load_table_index().get(tpl_name, [])
    if not table_index and logical_name:
        # 去掉注册时间戳前缀：逻辑名 = 原始模板名
        table_index = _load_table_index().get(logical_name + '.docx', [])
    if not table_index:
        # 兜底：文件名末尾匹配（注册名 = 时间戳_序号_逻辑名.docx）
        for k, v in _load_table_index().items():
            if k.endswith(logical_name + '.docx') if logical_name else False:
                table_index = v
                break
    tbls_in_body = body.findall(q('tbl'))

    filled_count = 0
    skipped_tables = []
    total_unfilled = set()
    empty_tables = []          # 模板声明了该类型表，但本车间没有该类型设备
    dedup_tables = []          # 同一张表单在模板里重复出现，已去重（不是缺表）
    type_fallback = []         # 设备借用了「与类型无关的表」，需人工核对
    covered_devices = []       # 真正进了表的设备（位号/名称）
    uncovered_devices = []     # 本车间有、但本模板一张表都没接住的设备（空壳的可见证据）

    # 预扫：每个表格指纹被哪些设备类型共用（共用 ≥2 种 = 该表与设备类型无关）
    sig_types: Dict[tuple, set] = {}
    slot_sig = []
    slot_type = []
    for seq, tbl in enumerate(tbls_in_body):
        dev_type = table_index[seq] if seq < len(table_index) else _classify_table(tbl)
        sig = _table_signature(tbl)
        slot_sig.append(sig)
        slot_type.append(dev_type)
        sig_types.setdefault(sig, set()).add(dev_type)
    declared_types = set(slot_type)

    # 车间实际拥有的设备（按类型），含「通用」= 未能识别出专表类型的设备
    present_types = {t: v for t, v in dev_groups.items() if v}
    # 模板完全没声明的类型 → 只能借「与类型无关的表」，借不到就如实报缺
    borrow_types = [t for t in present_types if t not in declared_types]

    emitted = set()  # (表格指纹, 设备key) —— 同一份表 + 同一台设备只出一次，避免重复打印
    # v0.1.180：**选定"承接表"** —— 模板未声明类型的设备（真实台账 13 类 55 台：
    # 泵、电动单梁起重机、搅拌设备、除尘设备、浮选设备…）需要一张通用格式的表来出记录。
    # 旧实现在借用分支前置了 `len(sig_types[sig]) >= 2`（"同一份表被至少 2 种类型共用
    # 才算与类型无关"），而实测模板 9 张表里同指纹的几张**全被登记成同一类**（胶带输送机×3），
    # 条件永远不成立 → 一台都借不进去 → filled_count=0 → 整份文件被空壳闸门拦掉。
    # 现在改为：在整个模板里挑一张"最通用"的表（指纹被最多类型共用者；都不共用则取第一张），
    # 未覆盖类型的设备**只在这一张表里各出一份**，并在 type_fallback 记账供人工复核。
    _sig_type_count = {}
    for _s in slot_sig:
        _sig_type_count[_s] = _sig_type_count.get(_s, 0) + 1
    _carry_seq = 0
    _best = -1
    for _i, _s in enumerate(slot_sig):
        _cnt = len(sig_types.get(_s, ())) * 100 + _sig_type_count.get(_s, 0)
        if _cnt > _best:
            _best = _cnt
            _carry_seq = _i

    def _dev_key(dev):
        if not dev:
            return ''
        return dev.get('tag') or dev.get('name') or ''

    for seq, tbl in enumerate(tbls_in_body):
        dev_type = slot_type[seq]
        sig = slot_sig[seq]
        queue = []
        # ① 本类型设备（去重：同一份表同一台设备只出一遍）
        for dev in dev_groups.get(dev_type, []):
            key = (sig, _dev_key(dev))
            if key in emitted:
                continue
            emitted.add(key)
            queue.append(dev)
        # ② 通用表：无设备时只填项目常量（也只出一份）
        if not queue and dev_type == '通用':
            key = (sig, '')
            if key not in emitted:
                emitted.add(key)
                queue.append(None)
        # ③ 承接表：模板没声明类型的设备，统一在选定的那张通用表里各出一份
        # v0.1.180 修：**不能再加 `not queue` 前置**。
        # 承接表同时也是某个已声明类型的表（实测是「胶带输送机」，9 张表里占 3 张），
        # 而真实台账绝大多数车间都有胶带输送机 —— 只要 queue 里有一台本类型设备，
        # 这个条件就不成立，未声明类型的设备一台都承接不进来。
        # 实测：脱水车间 19 台里 15 台落空、重介质选矿车间 39 台里 28 台落空。
        # 承接设备只是往同一张表的队列里追加，每台仍各自复制一份，不会少也不会重复。
        if dev_type != '通用' and seq == _carry_seq:
            for other_type in list(borrow_types):
                for dev in present_types.get(other_type, []):
                    # key 用固定标记而不是指纹 —— 承接只发生在唯一一张表上，
                    # 一台设备任何时候都只出一份（防重复出表的关键）
                    key = ('carry', _dev_key(dev))
                    if key in emitted:
                        continue
                    emitted.add(key)
                    queue.append(dev)
                    type_fallback.append({'设备类型': other_type, '设备': dev.get('name', ''),
                                          '借用表': dev_type, '方式': '通用表承接'})
        if not queue:
            # 两种完全不同的情况，记账必须分开，否则用户看到「模板内空表类型」
            # 里列着一个明明有设备的类型，会误判成模板缺表：
            #   ① 本类型有设备，但这张表与前面某张表是同一张表单（指纹相同），
            #      该设备的这一份记录已经出过 → 属重复表单去重，不是缺表
            #   ② 本类型在本车间确实没有设备 → 删表，并计入 empty_tables
            if dev_groups.get(dev_type):
                dedup_tables.append(dev_type)
            else:
                empty_tables.append(dev_type)
            skipped_tables.append(dev_type)
            body.remove(tbl)
            continue

        # 每台设备一份表；复制必须基于「未填充的原始表」
        orig_tbl = copy.deepcopy(tbl)
        prev = tbl
        for i, dev in enumerate(queue):
            if i == 0:
                cur_tbl = tbl
            else:
                cur_tbl = copy.deepcopy(orig_tbl)
                prev.addnext(cur_tbl)
            fill = dict(fill_base)
            if dev:
                fill['设备名称'] = dev.get('name', '')
                fill['设备位号'] = dev.get('tag', '')
                fill['规格型号'] = dev.get('model', '')
                fill['供货厂家'] = dev.get('manufacturer', '')
                fill['施工图号'] = dev.get('drawing_no', '')
                fill['数量'] = dev.get('quantity', '')
                fill['单重'] = dev.get('weight', '')
                covered_devices.append({'位号': dev.get('tag', ''), '名称': dev.get('name', ''),
                                        '设备类型': dev.get('dev_type', '')})
            unf = _fill_element(cur_tbl, fill)
            total_unfilled.update(unf)
            filled_count += 1
            prev = cur_tbl

    # 记账：哪些设备一张表都没接住（= 这份文件对它是空壳）
    covered_keys = {(_d.get('位号') or _d.get('名称') or '') for _d in covered_devices}
    for _t, _devs in present_types.items():
        for _d in _devs:
            if (_d.get('tag') or _d.get('name') or '') not in covered_keys:
                uncovered_devices.append({'位号': _d.get('tag', ''), '名称': _d.get('name', ''),
                                          '设备类型': _d.get('dev_type', '')})

    xml_bytes = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    # 去重跳过列表（同类型多表只记录一次）
    seen_skip = []
    for s in skipped_tables:
        if s not in seen_skip:
            seen_skip.append(s)
    seen_empty = []
    for s in empty_tables:
        if s not in seen_empty:
            seen_empty.append(s)
    # 一台设备会在多张表里出现，覆盖清单按设备去重
    seen_cov = set()
    cov_out = []
    for _c in covered_devices:
        _k = _c.get('位号') or _c.get('名称') or ''
        if _k in seen_cov:
            continue
        seen_cov.add(_k)
        cov_out.append(_c)
    return {
        "ok": True,
        "xml": xml_bytes,
        "others": others,
        "filled_count": filled_count,
        "skipped_tables": seen_skip,
        "empty_tables": seen_empty,
        "dedup_tables": _uniq(dedup_tables),
        "type_fallback": type_fallback,
        "uncovered_devices": uncovered_devices,
        "covered_devices": cov_out,
        "unfilled_fields": sorted(total_unfilled),
    }


def _uniq(seq):
    """保序去重（同一类型在多张表里出现时只记一次）。"""
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


def _classify_slots(template_path: str, logical_name: str = "") -> List[str]:
    """模板声明的设备类型清单（去重）。用于报错时说明「模板只认哪些类型」。"""
    tpl_name = os.path.basename(template_path)
    idx = _load_table_index()
    types = idx.get(tpl_name) or (idx.get(logical_name + '.docx') if logical_name else None) or []
    out = []
    for t in types:
        if t and t not in out:
            out.append(t)
    return out


def _classify_table(tbl) -> str:
    """识别表格对应的设备类型（模板表按内容关键词）。"""
    text = ''.join((t.text or '') for t in tbl.findall('.//' + q('t')))
    for dev_type, kws in DEVICE_TYPE_KEYWORDS:
        for k in kws:
            if k in text:
                return dev_type
    return '通用'


def render_supervision_doc(category: str = "", workshop: str = "",
                           project_id: str = None,
                           extra_data: Dict = None) -> Dict:
    """
    按表类型 + 车间生成监理确认表（车间级整合，一份文件含该车间全部设备）。
    category: 表类型（设备开箱检查记录/设备安装检查记录/...）
    workshop: 车间名（如 辊磨筛分车间）
    """
    _ensure_builtin_registered()
    index = _te._load_template_index()

    # v0.1.183：入口先解别名。
    # 实测缺陷：直接以「设备安装记录」调用时，下面的子串回退会命中外
    # 「防爆电气设备安装记录」（它包含「设备安装记录」这六个字），
    # 唯一候选 → 静默选中，出的表与用户要的完全不是一张。
    # 别名是人确认过的对应关系，必须排在所有猜测规则之前。
    req_category = category
    _alias = _gb.alias_category(category) if category else None
    if _alias:
        category = _alias

    # 找该表类型的车间级模板（docx 或 xlsx）
    chosen = None
    cats = {}
    for t in index.get("templates", []):
        dt = t.get("doc_type", "")
        if dt.startswith(DOC_TYPE + "|"):
            cats.setdefault(dt.split("|", 1)[1], t)
    # 精确匹配优先
    if category in cats:
        chosen = cats[category]
    # v0.1.167：精确匹配不到时按关键词回退 —— 用户输入「仪表」这类常用简称，
    # 原来一律报「未找到表类型」，而可用列表里的表类型是全名（仪表设备管件阀门进场检验记录）
    if not chosen and category:
        # v0.1.167：模糊输入（如「仪表」）不擅自挑一张表 —— 多个候选时返回候选清单，
        # 由调用方明确选定。原来会静默命中第一张，生成的文件与用户意图不符。
        _hits = [c for c in cats if category in c]
        for c, kws in CATEGORY_KEYWORDS:
            if c in cats and c not in _hits and any(k == category for k in kws):
                _hits.append(c)
        if len(_hits) == 1:
            chosen = cats[_hits[0]]
        elif len(_hits) > 1:
            return {"ok": False,
                    "error": f"表类型「{category}」不唯一，请从候选中明确指定",
                    "ambiguous": True,
                    "candidates": sorted(_hits, key=len),
                    "available_categories": sorted(cats)}
    if not chosen:
        # v0.1.183（用户决策）：没有模板时按国标通用格式生成，不再一律报错。
        # 原实现直接返回「未找到表类型」，用户在前端点了也拿不到文件，
        # 而登记表里写的是国标正式表名，用户填得完全正确 —— 不能怪用户。
        if not category:
            return {"ok": False, "error": "未指定表类型",
                    "available_categories": sorted(cats)}
        _r = render_gb_fallback(category=category, workshop=workshop,
                                project_id=project_id,
                                display_name=category,
                                reason=f"模板库无「{category}」的模板，按国标通用格式生成")
        if _r.get('ok'):
            _r['warning'] = (f"模板库无「{category}」的模板，已按国标通用格式生成；"
                             f"如需专用表请补模板后重新生成")
            _r['available_categories'] = sorted(cats)
        return _r

    # 模板文件路径
    tpl_file = chosen.get("file_name", "")
    tpl_path = os.path.join(_te.TEMPLATES_DIR, tpl_file) if tpl_file else ""

    # 收集填充数据
    fill = _load_project_config(project_id)
    if workshop:
        fill['车间'] = workshop
    if extra_data:
        fill.update(extra_data)

    # 车间设备清单 + 按类型分组
    devices = _get_workshop_devices(workshop, project_id)
    dev_groups = {}
    for d in devices:
        dev_groups.setdefault(d['dev_type'], []).append(d)

    # xlsx 模板（重量确认单）走 openpyxl 渲染
    if tpl_path and tpl_path.endswith('.xlsx'):
        return _render_xlsx(tpl_path, fill, devices, project_id)

    # docx 渲染
    result = _render_docx_by_workshop(tpl_path, fill, dev_groups, workshop or '',
                                      logical_name=chosen.get('name', ''))
    if not result.get("ok"):
        return result

    # v0.1.172：空壳闸门 —— 一张表都没填（= 整份文件只剩标题段落）就不产出文件。
    # 原来这里无论 filled_count 是多少都写盘并返回 ok=True，
    # 用户在现场打印出来才发现整份文件只有表头、没有一行设备记录。
    if not result.get('filled_count'):
        _types = sorted({d['dev_type'] for d in devices})
        _slots = _classify_slots(tpl_path, chosen.get('name', ''))
        if not devices:
            _why = (f"「{workshop or '全厂'}」车间没有设备数据，模板内的设备表全部落空。"
                    f"请先上传设备台账并确认设备已归到该车间")
        else:
            _why = (f"模板与「{workshop or '全车间'}」的设备对不上：车间设备类型 "
                    f"{'、'.join(_types) or '未知'}，模板只声明 {'、'.join(_slots) or '未知'}")
        return {
            "ok": False,
            "error": _why,
            "empty_shell_blocked": True,
            "device_count": len(devices),
            "covered_devices": [],
            "uncovered_devices": result.get('uncovered_devices', []),
            "empty_tables": result.get('empty_tables', []),
            "template_types": _slots,
            "workshop_types": _types,
            "suggestion": "缺对应设备类型的监理表模板：需补模板，或改人工填报；不能自动产出空表",
        }

    # 输出到项目 exports
    from . import project_manager as _pm
    data_dir = _pm.get_project_data_dir(project_id)
    exports_dir = os.path.join(data_dir, "exports")
    os.makedirs(exports_dir, exist_ok=True)
    ws_label = workshop or '全车间'
    out_name = f"{chosen['name']}_{ws_label}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    out_path = os.path.join(exports_dir, out_name)
    with ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, data in result['others'].items():
            if n == 'word/document.xml':
                continue
            z.writestr(n, data)
        z.writestr('word/document.xml', result['xml'])

    # 更新模板使用次数
    try:
        t['use_count'] = t.get('use_count', 0) + 1
        _te._save_template_index(index)
    except Exception:  # noqa: BLE001
        pass

    filled_fields = [k for k, v in fill.items() if v]
    _res = {
        "ok": True,
        "output_path": out_path,
        "output_file": out_name,
        "category": category,
        "workshop": workshop or '',
        "device_count": len(devices),
        "filled_tables": result['filled_count'],
        "skipped_tables": result['skipped_tables'],
        "empty_tables": result.get('empty_tables', []),
        "covered_devices": result.get('covered_devices', []),
        "uncovered_devices": result.get('uncovered_devices', []),
        "type_fallback": result.get('type_fallback', []),
        "filled_fields": filled_fields,
        "unfilled_fields": result['unfilled_fields'],
    }
    if _alias and _alias != (req_category or ''):
        # 别名复用：调用方要能看出「要的是 A，实际用的是 B」，
        # 否则待办清单与卷目录对不上账。
        _res['name_alias'] = {"请求": req_category, "借用表": _alias}
    return _res


def _render_xlsx(template_path: str, fill: Dict, devices: List[Dict],
                 project_id: str = None) -> Dict:
    """xlsx 模板渲染（重量确认单）：占位符替换 + 设备行填充。"""
    import openpyxl
    wb = openpyxl.load_workbook(template_path)
    ws = wb.active
    filled = set()
    unfilled = set()
    pat = re.compile(r'\{\{([^}]+)\}\}')
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str) and '{{' in c.value:
                orig = c.value
                replaced = orig
                for m in pat.finditer(orig):
                    field = m.group(1).strip()
                    if field in fill and str(fill[field]):
                        replaced = replaced.replace(m.group(0), str(fill[field]))
                        filled.add(field)
                    else:
                        unfilled.add(field)
                        replaced = replaced.replace(m.group(0), UNFILLED_MARK)
                if replaced != orig:
                    c.value = replaced

    # 设备行填充：表头下方数据行整体按车间设备台账重写。
    # 模板可能含多个表区（重量确认单1 空壳 / 重量确认单2 结构），只保留第一个表区。
    # 表结构：表头行(序号/设备名称/型号规格及技术性能/单位/数量/设备重量[单重/总重]/重量依据)，下一行=单重/总重子表头。
    eq_map = {}
    for d in devices:
        eq_map.setdefault(d['name'], d)  # 同名称多台取第一台（模板按名称一行）

    # 定位所有表头行（含"设备名称"与"重量依据"）
    header_rows = []
    for ri, row in enumerate(ws.iter_rows(min_row=1, max_row=400), start=1):
        vals = [str(c.value) if c.value is not None else '' for c in row]
        if vals and vals[1] == '设备名称' and '重量依据' in vals:
            header_rows.append(ri)
    if not header_rows:
        header_rows = [2]
    target_header = header_rows[0]

    # 删除多余表区（第二个及以后：含该表头及其后全部内容；从后往前删避免行号漂移）
    for extra_h in reversed(header_rows[1:]):
        ws.delete_rows(extra_h, ws.max_row - extra_h + 1)

    # 检测第一个表区的子表头行（单重/总重）：表头下一行若含"单重"则设备行从 header+2 开始
    sub_header = ''
    for c in range(1, 9):
        v = ws.cell(row=target_header + 1, column=c).value
        if v and '单重' in str(v):
            sub_header = '单重'
            break
    start_row = target_header + (2 if sub_header else 1)

    # 设备行区域内的合并单元格先拆分（避免 MergedCell 只读；含跨入设备区的表头合并）
    merges_to_remove = []
    for mr in list(ws.merged_cells.ranges):
        if mr.max_row >= start_row:
            merges_to_remove.append(str(mr))
    for m in merges_to_remove:
        ws.unmerge_cells(m)

    # 收集旧设备行（start_row 起，到备注/签名行止）与旧单重（模板原值，如 90.0061272）
    old_rows = []
    old_weight_by_name = {}
    for ri in range(start_row, ws.max_row + 1):
        vals = [str(ws.cell(row=ri, column=c).value) if ws.cell(row=ri, column=c).value is not None else '' for c in range(1, 9)]
        if vals and (vals[0].startswith('备注') or vals[1].startswith('备注')):
            break  # 备注行起不再属于设备区
        if not any(vals):
            continue
        old_rows.append(ri)
        name = vals[1].strip()
        w = vals[5].strip()
        if name and w and not w.startswith('='):
            try:
                old_weight_by_name[name] = float(w)
            except (TypeError, ValueError):
                pass
    # 清空旧设备行
    for ri in old_rows:
        for col in range(1, 9):
            ws.cell(row=ri, column=col).value = None

    for i, d in enumerate(devices):
        r = start_row + i
        # 行数不足时补一行（继承上一行样式）
        while r > ws.max_row:
            ws.cell(row=r, column=1).value = None
        name = d.get('name', '')
        ws.cell(row=r, column=1).value = i + 1
        ws.cell(row=r, column=2).value = name
        ws.cell(row=r, column=3).value = d.get('model', '')
        ws.cell(row=r, column=4).value = '台'
        qty = d.get('quantity', '')
        try:
            qty_v = float(qty) if str(qty).strip() else 1.0
        except (TypeError, ValueError):
            qty_v = 1.0
        ws.cell(row=r, column=5).value = qty_v
        weight = d.get('weight', '')
        try:
            w_v = float(weight) if str(weight).strip() else None
        except (TypeError, ValueError):
            w_v = None
        if w_v is None and name in old_weight_by_name:
            w_v = old_weight_by_name[name]
        if w_v is not None:
            ws.cell(row=r, column=6).value = w_v
            ws.cell(row=r, column=7).value = f"=F{r}*E{r}"
        else:
            ws.cell(row=r, column=6).value = None
            ws.cell(row=r, column=7).value = None
        basis = d.get('weight_basis', '') or ('厂家随机清单' if name in old_weight_by_name else '待补充')
        ws.cell(row=r, column=8).value = basis

    from . import project_manager as _pm
    data_dir = _pm.get_project_data_dir(project_id)
    exports_dir = os.path.join(data_dir, 'exports')
    os.makedirs(exports_dir, exist_ok=True)
    out_name = f"{os.path.basename(template_path)[:-5]}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    out_path = os.path.join(exports_dir, out_name)
    wb.save(out_path)
    return {
        "ok": True,
        "output_path": out_path,
        "output_file": out_name,
        "filled_fields": sorted(filled),
        "unfilled_fields": sorted(unfilled),
        "device_count": len(devices),
    }


def render_gb_fallback(category: str = "", workshop: str = "",
                        project_id: str = None,
                        form_no: str = "",
                        display_name: str = "",
                        reason: str = "") -> Dict:
    """无模板时按国标通用格式生成表（v0.1.183，用户决策）。

    与 render_supervision_doc 的区别：不依赖模板库，直接按国标表格式构建 docx。
    返回结构与 render_supervision_doc 兼容，并额外带 `gb_fallback: True`，
    调用方（整卷 / 待办清单）据此把钱花在哪张表上记清楚，人工复核能捞出来。

    **一台设备一份表**；车间台账为空时出一份空白表交人工填写，
    并在 `gb_blank` 里标记，不与「模板对不上设备」的空壳混为一谈。
    """
    from . import project_manager as _pm
    fill = _load_project_config(project_id)
    devices = _get_workshop_devices(workshop, project_id) if workshop else []
    _ws = workshop or '全厂'
    _sub = (fill.get('分部工程') or '').strip()

    data_dir = _pm.get_project_data_dir(project_id)
    exports_dir = os.path.join(data_dir, "exports")
    os.makedirs(exports_dir, exist_ok=True)
    _safe = re.sub(r'[\\/:*?"<>|]', '', (display_name or category or '国标表'))[:40]
    out_name = (f"{_safe}_{_ws}_"
                f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.docx")
    out_path = os.path.join(exports_dir, out_name)

    r = _gb.build_gb_form(
        out_path,
        form_name=display_name or category,
        form_no=form_no,
        unit_works=(fill.get('单位工程') or ''),
        sub_works=_sub,
        workshop=_ws,
        devices=devices,
        category=category,
        standard=(fill.get('标准编号') or ''),
    )
    if not r.get('ok'):
        return {"ok": False, "error": r.get('error') or '国标表生成失败'}

    return {
        "ok": True,
        "output_path": out_path,
        "output_file": out_name,
        "category": category,
        "workshop": _ws,
        "device_count": len(devices),
        "filled_tables": len(devices) or 1,
        "skipped_tables": [],
        "empty_tables": [],
        "covered_devices": [d.get('tag') or d.get('name') for d in devices],
        "uncovered_devices": [],
        "type_fallback": [],
        # v0.1.183 兜底标识：不是走模板库出的表
        "gb_fallback": True,
        "gb_form_no": form_no,
        "gb_reason": reason,
        "gb_blank": not devices,
        "filled_fields": [k for k, v in fill.items() if v],
        "unfilled_fields": ["设备位号", "检查情况", "检查结果"],
        "check_item_count": r.get('check_item_count', 0),
    }


def generate_batch(category: str = "", workshop: str = "",
                   project_id: str = None,
                   extra_data: Dict = None) -> Dict:
    """批量生成：按车间生成（对每个车间生成一份整合文件）。"""
    if not workshop:
        return {"ok": False, "error": "未指定车间"}
    return render_supervision_doc(category=category, workshop=workshop,
                                  project_id=project_id, extra_data=extra_data)


def get_workshop_list(project_id: str = None) -> List[str]:
    """获取项目车间列表。"""
    from . import project_manager as _pm
    workshops = []
    try:
        data_dir = _pm.get_project_data_dir(project_id)
        idx_path = os.path.join(data_dir, "index.json")
        if os.path.isfile(idx_path):
            with open(idx_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
            workshops = list((idx.get("workshops") or {}).keys())
    except Exception:  # noqa: BLE001
        pass
    return workshops


def get_equipment_list(project_id: str = None) -> List[Dict]:
    """获取当前项目全部设备（按车间分组，前端选设备/看清单用）。"""
    devices = _get_workshop_devices("", project_id)
    # 按车间分组
    grouped = {}
    for d in devices:
        ws = d.get("workshop") or "未归车间"
        grouped.setdefault(ws, []).append(d)
    return devices, grouped
