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
from lxml import etree

from . import config
from . import template_engine as _te

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


def _device_type_of(equipment: str) -> str:
    """从设备名称提取设备类型（用于模板表匹配）。"""
    if not equipment:
        return ""
    for t, kws in DEVICE_TYPE_KEYWORDS:
        for k in kws:
            if k in equipment:
                return t
    return "通用"


# ---------------- 模板注册 ----------------

def _ensure_builtin_registered() -> int:
    """扫描 templates_builtin/ 把未注册的 docx/xlsx 注册进模板索引。幂等。"""
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
                if not name:
                    continue
                key = f"{tag}|{name}"
                if key in seen:
                    continue
                seen.add(key)
                devices.append({
                    "tag": tag,
                    "name": name,
                    "model": d.get("model", "") or d.get("spec", ""),
                    "manufacturer": d.get("manufacturer", ""),
                    "workshop": dev_ws or workshop,
                    "quantity": d.get("quantity", ""),
                    "weight": d.get("weight", "") or d.get("single_weight", ""),
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
            if not name:
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
                "tag": tag,
                "name": name,
                "model": m.get("model", "") or flds.get("型号", ""),
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
    if replaced == joined:
        return
    texts[0].text = replaced
    for t in texts[1:]:
        t.text = ''


def _fill_element(root, fill: Dict) -> set:
    """替换 root 内所有 {{占位符}}，返回未填字段。"""
    unfilled = set()
    for p in root.findall('.//' + q('p')):
        _fill_para_text(p, fill, unfilled)
    return unfilled


def _render_docx_by_workshop(template_path: str, fill_base: Dict,
                             dev_groups: Dict[str, List[Dict]],
                             workshop: str = "",
                             logical_name: str = "") -> Dict:
    """
    车间级渲染核心：
    - 打开模板 docx，遍历 body 下所有 tbl
    - 每个 tbl 按表序从 _table_index.json 取设备类型 → 匹配 dev_groups[类型]
      - 组内 N 台 → 复制 N 份表，每份填一台设备
      - 无设备 → 跳过
    - 通用表（清单标"通用"）→ 只填项目常量
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

    for seq, tbl in enumerate(tbls_in_body):
        # 优先用清单（表序），缺失时用内容兜底
        dev_type = table_index[seq] if seq < len(table_index) else _classify_table(tbl)
        group = dev_groups.get(dev_type, [])
        if not group:
            # 无该类型设备 → 跳过（通用表例外：保留填项目常量）
            if dev_type != '通用':
                skipped_tables.append(dev_type)
                body.remove(tbl)
                continue
            group = [None]  # 通用表：只填常量，不填设备

        # 每台设备一份表；复制必须基于「未填充的原始表」
        orig_tbl = copy.deepcopy(tbl)
        prev = tbl
        for i, dev in enumerate(group):
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
            unf = _fill_element(cur_tbl, fill)
            total_unfilled.update(unf)
            filled_count += 1
            prev = cur_tbl

    xml_bytes = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    # 去重跳过列表（同类型多表只记录一次）
    seen_skip = []
    for s in skipped_tables:
        if s not in seen_skip:
            seen_skip.append(s)
    return {
        "ok": True,
        "xml": xml_bytes,
        "others": others,
        "filled_count": filled_count,
        "skipped_tables": seen_skip,
        "unfilled_fields": sorted(total_unfilled),
    }


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

    # 找该表类型的车间级模板（docx 或 xlsx）
    chosen = None
    for t in index.get("templates", []):
        dt = t.get("doc_type", "")
        if dt.startswith(DOC_TYPE + "|") and dt.split("|", 1)[1] == category:
            chosen = t
            break
    if not chosen:
        return {"ok": False, "error": f"未找到表类型「{category}」的模板",
                "available": [c for c, _ in CATEGORY_KEYWORDS]}

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
    return {
        "ok": True,
        "output_path": out_path,
        "output_file": out_name,
        "category": category,
        "workshop": workshop or '',
        "device_count": len(devices),
        "filled_tables": result['filled_count'],
        "skipped_tables": result['skipped_tables'],
        "filled_fields": filled_fields,
        "unfilled_fields": result['unfilled_fields'],
    }


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
