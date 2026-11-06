"""
v0.1.107：智能工程文件生成器

输入自然语言（如"生成球磨机安装的安全技术交底"），自动：
1. 识别要生成的文件类型
2. 识别设备名称
3. 从项目数据库读取已有数据自动填充
4. 列出缺失数据提示人工补充
5. 调用对应模块生成文件
"""

import os
import json
import re
import datetime
from typing import Optional, Dict, List, Tuple


# 支持的文件类型映射
DOC_TYPE_MAP = {
    # 安全交底
    "安全交底": {"module": "mining_safety_disclosure", "method": "generate_safety_disclosure",
                "keywords": ["安全交底", "安全技术交底", "安全措施交底"],
                "required_fields": ["设备名称", "项目名称", "施工单位"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 技术交底
    "技术交底": {"module": "mining_technical_disclosure_enhanced", "method": "generate_technical_disclosure",
                "keywords": ["技术交底", "施工技术交底", "技术措施交底"],
                "required_fields": ["设备名称", "项目名称", "施工单位"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 施工方案
    "施工方案": {"module": "mining_construction_plan_enhanced", "method": "generate_construction_plan",
                "keywords": ["施工方案", "安装方案", "施工组织设计"],
                "required_fields": ["设备名称", "项目名称", "施工单位", "编制人"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 吊装方案
    "吊装方案": {"module": "mining_lifting_plan_enhanced", "method": "generate_lifting_plan",
                "keywords": ["吊装方案", "起重方案", "吊装作业方案"],
                "required_fields": ["设备名称", "项目名称", "设备重量", "吊装高度"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 基础验收记录
    "基础验收": {"module": "field_record", "method": "generate_unboxing_record",
                "keywords": ["基础验收", "基础验收记录", "设备基础验收", "设备安装基础复测"],
                "required_fields": ["设备名称", "项目名称", "车间", "基础编号", "验收日期"],
                "auto_fill_fields": ["设备名称", "项目名称", "车间"]},
    # 设备验收记录（前端下拉里的叫法，指向开箱/安装检查表）
    "设备验收": {"module": "field_record", "method": "generate_unboxing_record",
                "keywords": ["设备验收", "设备验收记录", "设备安装验收", "安装验收记录"],
                "required_fields": ["设备名称", "项目名称", "车间", "验收日期"],
                "auto_fill_fields": ["设备名称", "项目名称", "车间"]},
    # 开箱检验记录
    "开箱检验": {"module": "unboxing_record", "method": "generate_unboxing_record",
                "keywords": ["开箱检验", "开箱记录", "设备开箱", "开箱验收", "开箱检验记录"],
                "required_fields": ["设备名称", "项目名称", "车间", "开箱日期", "供货厂家"],
                "auto_fill_fields": ["设备名称", "项目名称", "车间", "供货厂家"]},
    # 隐蔽工程验收
    "隐蔽工程": {"module": "concealment_record", "method": "generate_concealment_record",
                "keywords": ["隐蔽工程", "隐蔽验收", "隐蔽记录", "隐蔽工程验收记录"],
                "required_fields": ["设备名称", "项目名称", "车间", "隐蔽部位", "验收日期"],
                "auto_fill_fields": ["设备名称", "项目名称", "车间"]},
    # 焊接方案（前端下拉里的叫法，复用焊接作业指导书表式）
    "焊接方案": {"module": "welding_plan", "method": "generate_welding_plan",
                "keywords": ["焊接方案", "焊接作业指导书", "焊接工艺方案", "焊接施工方案"],
                "required_fields": ["设备名称", "项目名称", "车间", "焊接方法", "焊工资质"],
                "auto_fill_fields": ["设备名称", "项目名称", "车间"]},
    # 施工日志
    "施工日志": {"module": "construction_log", "method": "generate_log_data_enhanced",
                "keywords": ["施工日志", "施工日记", "日志"],
                "required_fields": ["日期", "项目名称", "天气", "施工内容"],
                "auto_fill_fields": ["项目名称", "日期"]},
    # 竣工资料组卷
    "竣工资料": {"module": "mining_completion_archive_enhanced", "method": "generate_completion_archive",
                "keywords": ["竣工资料", "竣工组卷", "资料组卷", "竣工归档"],
                "required_fields": ["设备名称", "项目名称", "施工单位"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 设计变更
    "设计变更": {"module": "design_change", "method": "generate_design_change",
                "keywords": ["设计变更", "变更单", "设计修改"],
                "required_fields": ["设备名称", "项目名称", "变更内容", "变更原因"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 货损报告
    "货损报告": {"module": "damage_report", "method": "generate_damage_report",
                "keywords": ["货损", "货损报告", "损坏报告", "设备损坏"],
                "required_fields": ["设备名称", "项目名称", "损坏部位", "损坏程度"],
                "auto_fill_fields": ["设备名称", "项目名称"]},
    # 设备安装记录
    "安装记录": {"module": "field_record", "method": "generate_installation_record",
                "keywords": ["安装记录", "设备安装记录", "安装施工记录"],
                "required_fields": ["设备名称", "项目名称", "车间", "安装日期"],
                "auto_fill_fields": ["设备名称", "项目名称", "车间"]},
    # 试运转记录
    "试运转": {"module": "field_record", "method": "generate_test_run_record",
                "keywords": ["试运转", "试运行", "试车", "空运转"],
                "required_fields": ["设备名称", "项目名称", "车间", "试运转日期"],
                "auto_fill_fields": ["设备名称", "项目名称", "车间"]},
}


# 设备名称识别（从知识库中匹配）
def _extract_equipment(text: str, project_id: str = None
                       ) -> Tuple[Optional[str], float]:
    """从文本中提取设备名称。

    v0.1.202：原来只在 mining_equipment_detail.EQUIPMENT_DETAIL 的 8 类设备名
    （球磨机/半自磨机/高压釜/闪速炉/浮选机/颚式破碎机/浓缩机/压滤机）里做子串
    匹配。实测紫金选矿厂真实台账（228 行 / 215 行有名称）命中率
    **仅 14/215 = 6.5%**，未命中的是「Y0#胶带输送机」「金属探测器」
    「重型板式给料机」「液下渣浆泵」「电动单梁起重机」这类**真实且最常见**的设备。

    更糟的是它会把设备名**改写成别的设备**：命中样例里
        「圆锥破碎机」→「颚式破碎机」（两种破碎机完全不同）
        「高压辊磨机变频器」→「球磨机」（变频器被当成磨机）
        「真空带式过滤机」→「压滤机」（两种固液分离设备）
    因为别名表只做「片段命中」，不看整体。用户输入自己的设备名，拿到的表上
    印着另一个设备的名称，这在工程资料里是不能交付的。

    修法：先**精确**认当前项目台账里的真实设备名（台账是权威名单），认到就
    原样返回那个名字；台账里没有时，才回落到内置的 8 类通用设备名，
    且别名不再做无条件改写（只在整段文本没有更精确命中时才用）。
    """
    from . import mining_equipment_detail as _med

    raw = (text or "").strip()
    if not raw:
        return None, 0.0

    # ── ① 台账精确/前缀命中：用项目真实设备名，原名原样返回 ──
    try:
        from . import project_manager as _pm
        data_dir = _pm.get_project_data_dir(project_id)
        idx_path = os.path.join(data_dir, "index.json")
        if os.path.isfile(idx_path):
            with open(idx_path, "r", encoding="utf-8") as f:
                _idx = json.load(f)
            _devs = list((_idx.get("devices") or {}).values())
            # 长名优先：先比「溢流型球磨机」再比「球磨机」，避免被短名截断
            _names = sorted(
                {(d.get("name") or "").strip() for d in _devs} - {""},
                key=len, reverse=True)
            for nm in _names:
                if nm in raw:
                    score = len(nm) / len(raw) * 10 + 2.0  # 台账命中优先于内置名单
                    return nm, score
    except Exception:  # noqa: BLE001  台账读不到不阻断，回落内置名单
        pass

    # ── ② 内置 8 类通用设备：整词命中才认，不做别名改写 ──
    all_equipment = _med.EQUIPMENT_DETAIL.keys() if hasattr(_med, 'EQUIPMENT_DETAIL') else [
        "球磨机", "半自磨机", "高压釜", "闪速炉", "浮选机", "颚式破碎机", "浓缩机", "压滤机"
    ]
    best_match = None
    best_score = 0
    for eq in all_equipment:
        if eq in raw:
            score = len(eq) / len(raw) * 10
            if score > best_score:
                best_score = score
                best_match = eq

    if best_match:
        return best_match, best_score

    # ── ③ 别名兜底：仅当文本里没有任何精确命中，且**没有明显冲突**时才用 ──
    # v0.1.202：取消「圆锥破碎机→颚式破碎机」这类改写 ——
    # 文本里已经出现另一种设备的完整名称时，宁可认不出（返回 need_equipment
    # 让用户补全），也不能把表印成别的设备。
    aliases = {
        "磨机": "球磨机", "球磨": "球磨机", "自磨机": "半自磨机", "半自磨": "半自磨机",
        "反应釜": "高压釜", "加压釜": "高压釜", "闪速熔炼炉": "闪速炉",
        "浮选槽": "浮选机", "破碎机": "颚式破碎机", "鄂破": "颚式破碎机",
        "浓密机": "浓缩机", "过滤机": "压滤机",
    }
    # 这些词出现即说明不是别名指向的那台设备
    _conflict = {
        "颚式破碎机": ("圆锥", "反击", "锤式", "辊式", "对辊"),
        "球磨机": ("辊磨", "立磨", "变频器", "配套"),
        "压滤机": ("带式", "真空", "真空带式"),
        "浓缩机": ("浓密",),
    }
    for alias, real in aliases.items():
        if alias in raw and best_match is None:
            bad = _conflict.get(real, ())
            if any(b in raw for b in bad):
                continue
            best_match = real
            best_score = 0.5
            break

    return best_match, best_score


def _extract_doc_type(text: str) -> Tuple[Optional[str], Dict]:
    """从文本中识别文件类型。"""
    best_type = None
    best_config = None
    best_match_len = 0
    
    for doc_type, config in DOC_TYPE_MAP.items():
        for keyword in config["keywords"]:
            if keyword in text and len(keyword) > best_match_len:
                best_match_len = len(keyword)
                best_type = doc_type
                best_config = config
    
    return best_type, best_config


def _extract_project_name(text: str) -> Optional[str]:
    """从文本中提取项目名称（如果有的话）。"""
    # 匹配"XX项目"模式
    match = re.search(r'([\u4e00-\u9fa5a-zA-Z0-9]+项目)', text)
    if match:
        return match.group(1)
    return None


def _extract_workshop(text: str) -> Optional[str]:
    """从文本中提取车间名称。"""
    match = re.search(r'([\u4e00-\u9fa50-9]+车间)', text)
    if match:
        return match.group(1)
    return None


def _get_project_data(project_id: str = None) -> Dict:
    """从项目数据库读取已有数据。"""
    from . import project_manager as _pm
    
    data_dir = _pm.get_project_data_dir(project_id)
    index_path = os.path.join(data_dir, "index.json")
    relations_path = os.path.join(data_dir, "relations.json")
    
    result = {
        "project_name": "",
        "devices": {},
        "workshops": {},
        "files": [],
        "relations": [],
    }
    
    # 读取当前项目名称
    current = _pm.get_current_project()
    if current:
        result["project_name"] = current.get("name", "")
    
    # 读取 index.json
    if os.path.isfile(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
            result["devices"] = idx.get("devices", {})
            result["workshops"] = idx.get("workshops", {})
            result["files"] = idx.get("files", [])
        except Exception:
            pass
    
    # 读取 relations.json
    if os.path.isfile(relations_path):
        try:
            with open(relations_path, "r", encoding="utf-8") as f:
                rel = json.load(f)
            result["relations"] = rel.get("relations", [])
        except Exception:
            pass
    
    return result


def _auto_fill_fields(doc_type: str, equipment: str, project_data: Dict,
                      text: str) -> Tuple[Dict, List[str]]:
    """
    自动填充字段，并返回缺失字段列表。
    
    Returns:
        (filled_fields, missing_fields)
    """
    config = DOC_TYPE_MAP.get(doc_type, {})
    required = config.get("required_fields", [])
    
    filled = {}
    missing = []
    
    # 设备名称
    if "设备名称" in required:
        if equipment:
            filled["设备名称"] = equipment
        else:
            missing.append("设备名称")
    
    # 项目名称
    if "项目名称" in required:
        project_name = _extract_project_name(text)
        if not project_name:
            project_name = project_data.get("project_name", "")
        if project_name:
            filled["项目名称"] = project_name
        else:
            missing.append("项目名称")
    
    # 施工单位
    if "施工单位" in required:
        missing.append("施工单位（可选填）")
    
    # 车间
    if "车间" in required:
        workshop = _extract_workshop(text)
        if not workshop and equipment:
            # 从项目数据中查找设备所在车间
            devices = project_data.get("devices", {})
            for tag, dev in devices.items():
                if equipment in str(dev.get("name", "")) or equipment in tag:
                    workshop = dev.get("workshop", "")
                    if workshop:
                        break
        if workshop:
            filled["车间"] = workshop
        else:
            missing.append("车间")
    
    # 日期类字段
    date_fields = ["验收日期", "开箱日期", "安装日期", "试运转日期", "日期"]
    for df in date_fields:
        if df in required:
            filled[df] = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # 供货厂家
    if "供货厂家" in required:
        if equipment:
            devices = project_data.get("devices", {})
            for tag, dev in devices.items():
                if equipment in str(dev.get("name", "")):
                    manufacturer = dev.get("manufacturer", "")
                    if manufacturer:
                        filled["供货厂家"] = manufacturer
                        break
        if "供货厂家" not in filled:
            missing.append("供货厂家")
    
    # 其他需要人工填写的字段
    manual_fields = ["基础编号", "隐蔽部位", "变更内容", "变更原因",
                     "损坏部位", "损坏程度", "设备重量", "吊装高度",
                     "编制人", "天气", "施工内容"]
    for mf in manual_fields:
        if mf in required:
            missing.append(mf)
    
    return filled, missing


def generate_from_natural_language(text: str, project_id: str = None) -> Dict:
    """
    从自然语言生成工程文件。
    
    Args:
        text: 用户输入的自然语言，如"生成球磨机安装的安全技术交底"
        project_id: 项目ID，为None时使用当前项目
    
    Returns:
        生成结果，包含识别信息、自动填充数据、缺失字段、生成的文件内容
    """
    # 1. 识别文件类型
    doc_type, config = _extract_doc_type(text)
    if not doc_type:
        return {
            "ok": False,
            "error": "无法识别要生成的文件类型",
            "supported_types": list(DOC_TYPE_MAP.keys()),
            "suggestion": "请在输入中包含文件类型，如'生成球磨机安全交底'、'制作高压釜施工方案'等",
        }
    
    # 2. 识别设备名称（v0.1.202：带上 project_id，用项目台账做权威设备名单）
    equipment, eq_score = _extract_equipment(text, project_id=project_id)

    # 3. 读取项目数据
    project_data = _get_project_data(project_id)

    # 3.5 v0.1.202：认不出设备时，退一步用「用户自己写的那个名字」。
    # 批量生成端点拼的是 f"生成{类型}：{设备}"，冒号后面就是用户在下拉/台账里
    # 选中的设备原文 —— 那是**用户提供的事实**，原样印到表上完全正确，
    # 不该因为不在内置 8 类名单里就报「未识别到设备名称」。
    # 实测：228 台真实设备里只有 14 台能被内置名单认出来，其余全部卡在这里，
    # 批量生成走了 25 年也出不来一张表。
    if not equipment:
        _tail = ""
        for _sep in ("：", ":"):
            if _sep in text:
                _tail = text.split(_sep, 1)[1].strip()
                break
        if _tail:
            # 去掉常见的尾部修饰词，保留设备名主体
            for _suffix in ("的验收记录", "验收记录", "记录", "的资料", "资料",
                            "的方案", "方案", "交底"):
                if _tail.endswith(_suffix):
                    _tail = _tail[: -len(_suffix)].strip()
            if _tail:
                equipment, eq_score = _tail, 0.3
    
    # 4. 自动填充字段
    filled, missing = _auto_fill_fields(doc_type, equipment, project_data, text)
    
    # 5. 如果缺少关键信息（设备名称），返回待补充状态
    if not equipment and "设备名称" in missing:
        return {
            "ok": False,
            "stage": "need_equipment",
            "doc_type": doc_type,
            "message": f"已识别要生成「{doc_type}」，但未识别到设备名称",
            "filled_fields": filled,
            "missing_fields": missing,
            "available_equipment": list(project_data.get("devices", {}).keys()),
            "suggestion": "请补充设备名称，或从已有设备中选择",
        }
    
    # 6. 调用对应模块生成文件（v0.1.201：必须真正落盘才算成功）
    try:
        result = _call_generator(doc_type, equipment, filled, text, project_id=project_id)
    except Exception as e:
        return {
            "ok": False,
            "error": f"生成文件时出错：{str(e)}",
            "doc_type": doc_type,
            "equipment": equipment,
            "filled_fields": filled,
            "missing_fields": missing,
        }

    # v0.1.201：落盘层没产出文件时，不允许再把「生成成功」报给前端。
    # 原来这里无条件返回 ok=True，正是「报成功零产出」的来源。
    if not (isinstance(result, dict) and result.get("persisted") and result.get("output_path")):
        return {
            "ok": False,
            "stage": "persist_failed",
            "doc_type": doc_type,
            "equipment": equipment,
            "filled_fields": filled,
            "missing_fields": missing,
            "error": (result or {}).get("error") or "生成内容已完成，但未产出可下载的文件",
            "result": result,
        }

    return {
        "ok": True,
        "stage": "generated",
        "doc_type": doc_type,
        "equipment": equipment,
        "input_text": text,
        "filled_fields": filled,
        "missing_fields": missing,
        "missing_count": len(missing),
        "has_missing": len(missing) > 0,
        "result": result,
        "output_path": result.get("output_path"),
        "output_file": result.get("output_file"),
        "file_name": result.get("output_file"),
        "docx_name": result.get("output_file"),
        "gb_fallback": result.get("gb_fallback"),
        "gb_reason": result.get("gb_reason"),
        "message": f"已生成「{equipment}{doc_type}」" + (f"，有{len(missing)}项数据需要人工补充完善" if missing else "，数据完整"),
    }


# ==================== v0.1.201 落盘路由 ====================
#
# 实测缺陷（本轮重建的证据）：
#   POST /api/smart-doc/batch-generate {"file_type":"施工方案","devices":["球磨机"]}
#   → {"ok":true,"success":1,"failed":0}
#   但项目目录 generated_docs 下 docx 数量 14 → 14（一个都没多）。
#   11 个前端可选类型里 8 个这样「报成功、零产出」，另 3 个（吊装方案 /
#   设备验收记录 / 焊接方案）报 failed。
#
# 根因：_call_generator 调的都是 mining_*「内容编排」模块，它们只返回
#   sections/plan 这类 JSON 结构，从不写 docx；`else` 分支更是直接返回
#   status=template_generated 的占位 JSON。调用方 main.py 只看 r["ok"]，
#   于是把「生成了个 JSON」当成「生成了份文件」记成功。
#
# 修法：分两步走
#   ① 内容层：仍由 mining_* 产生结构化内容（它懂矿山工艺，别推翻）；
#   ② 落盘层：统一交给 _persist_docx()，用 docgen.fill_template 出真 docx，
#      写进项目 generated_docs/<类型>/，再登记 doc_relations。
#   表单类（验收/隐蔽/开箱…）优先复用现有监理检查记录表，
#   没有对应表才按国标通用格式生成 —— 依据用户的既定规则：
#   「就用现有的检查记录表，没有提供的模板时，统一根据国标模板制作」。

# 智能生成类型 -> 归档类型名（generated_docs 下的目录名）。
# v0.1.201：归档目录名必须同时满足两件事：
#   ① 前端按目录名展示与下载，得是用户认得的表名；
#   ② 竣工组卷（archive.VOLUMES）按 docgen 标准类型取数，名对不上就归不进卷。
# 原来直接用内部短名（开箱检验 / 隐蔽工程 / 设备验收），两头都吃亏：
# 用户看到的是「开箱检验」而不是他要的「开箱检验记录」，组卷时也认不出。
_ARCHIVE_TYPE = {
    # 这两类 docgen 与竣工组卷（VOLUMES 04 卷）都用标准名，映射过去两边都对得上
    "开箱检验": "开箱验收记录",
    "隐蔽工程": "隐蔽工程验收记录",
    "技术交底": "技术交底",
    # 以下在 docgen 里没有同名类型，用**用户认得的那张表的全名**做归档名。
    # 它们不进 VOLUMES 是既成事实（监理检查记录表本来就单独归档），
    # 但不能因此把名字压成「开箱检验」「设备验收」这种内部短名 ——
    # 用户按下拉选的是「设备验收记录」，历史里看到「设备验收」会以为是两份东西。
    "基础验收": "设备安装基础复测记录",
    "设备验收": "设备安装检查记录",
    "安装记录": "设备安装检查记录",
    "试运转": "单机无负荷试运转记录",
    "安全交底": "安全技术交底记录",
    "焊接方案": "焊接作业指导书",
}


def _archive_type_of(doc_type: str) -> str:
    """内部类型 -> 归档目录名（找不到映射时用原名）。"""
    return _ARCHIVE_TYPE.get(doc_type, doc_type)


# 归档目录名 -> 内部类型（_ARCHIVE_TYPE 的反向表）。
# v0.1.201 修「再生成」时发现的同类缺陷：归档目录里躺的是**归档名**
# （如 焊接作业指导书 / 设备安装检查记录），而生成器只认**内部类型**
# （焊接方案 / 设备验收）。原来 /api/smart-doc/regenerate 直接拿目录名去
# 生成，外部接口实测返回 {"ok": false, "error": "重新生成未产出文件"}，
# 也就是「生成历史里点重新生成一直失败」。
# 反向表保证归档名能回到能生成的那个内部类型上。
_INTERNAL_TYPE_OF_ARCHIVE = {}
for _it, _an in _ARCHIVE_TYPE.items():
    # 多个内部类型映射到同一归档名时，取最短的那个（最贴近用户原始叫法），
    # 例如 设备验收/安装记录 都归档为 设备安装检查记录，回到「设备验收」。
    if _an not in _INTERNAL_TYPE_OF_ARCHIVE or len(_it) < len(_INTERNAL_TYPE_OF_ARCHIVE[_an]):
        _INTERNAL_TYPE_OF_ARCHIVE[_an] = _it


def _internal_type_of(archive_name: str) -> str:
    """归档目录名 -> 内部类型（认不出时原样返回，由调用方决定成败）。"""
    name = (archive_name or "").strip()
    return _INTERNAL_TYPE_OF_ARCHIVE.get(name, name)


_FORM_TYPE_HINTS = {
    # 智能生成的类型 -> 现有检查记录表名（复用既有模板，用户规则第一条）
    "开箱检验": "设备开箱检查记录",
    "隐蔽工程": "隐蔽工程验收记录",
    "基础验收": "设备安装基础复测记录",
    "安装记录": "设备安装检查记录",
    "试运转": "单机无负荷试运转记录",
    "安全交底": "安全技术交底记录",
    "技术交底": "技术交底记录",
    "设备验收": "设备安装检查记录",
    "焊接方案": "焊接作业指导书",
}

# 这些类型的内容由 mining_* 结构化模块产出，但**不走表单复用**、必须落成方案类 docx。
# 焊接方案不在此列：它有现成的「焊接作业指导书」表，按用户规则应当复用现表。
_CONTENT_ONLY_TYPES = ("施工方案", "吊装方案", "技术交底", "安全交底", "竣工资料")


def _device_descriptor_for(equipment: str, filled: Dict,
                           project_id: str = None) -> Optional[list]:
    """把「设备名称」补全成表单渲染器要的 {tag, name, model} 三件套。

    v0.1.202：render_gb_form 的表头要「设备名称 / 设备位号 / 规格型号」三列，
    只传一个名字 —— 位号与型号本来就在台账里，没必要让监理回头再抄一遍。
    台账里认不出同名设备时，位号留空（国标表本来就是现场手填位号），
    名称仍然用用户给的那个字面值，绝不拿别的设备名顶上。
    """
    name = (equipment or "").strip()
    if not name:
        return None
    desc = {"tag": "", "name": name, "model": ""}
    try:
        from . import project_manager as _pm
        idx_path = os.path.join(_pm.get_project_data_dir(project_id), "index.json")
        if os.path.isfile(idx_path):
            with open(idx_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
            for tag, d in (idx.get("devices") or {}).items():
                if (d.get("name") or "").strip() == name:
                    from . import supervision_templates as _st
                    desc["tag"] = _st._em_tag_display(tag)
                    desc["model"] = d.get("model") or d.get("spec") or ""
                    break
    except Exception:  # noqa: BLE001  台账读不到就只带名称，不影响出表
        pass
    return [desc]


def _persist_docx(doc_type: str, equipment: str, filled: Dict,
                  payload: Dict, project_id: str = None) -> Dict:
    """把已生成的内容落成真实 docx 并入库。

    v0.1.201：这是本轮的关键补丁。原来整条链路没有这一步，
    所以接口能返回 ok=True 却一个文件都没有。
    """
    from . import archive as _ar
    from . import docgen as _dg

    # 1) 表单类优先复用现有检查记录表（用户规则：有现表用现表）
    form_name = _FORM_TYPE_HINTS.get(doc_type)
    if form_name and doc_type not in _CONTENT_ONLY_TYPES:
        try:
            from . import supervision_templates as _st
            r = _st.render_gb_fallback(
                category=form_name,
                workshop=filled.get("车间", ""),
                project_id=project_id,
                display_name=form_name,
                reason="智能生成：复用现有检查记录表（未提供专用模板）",
                # v0.1.202：必须把当前这台设备传下去。
                # 原来不传，render_gb_fallback 只按车间查台账；实测批量生成
                # 球磨机1/2/3 得到 3 份**内容完全相同**的表，且「设备名称」
                # 「设备位号」两列全空 —— 用户拿到的三份表分不出是哪台设备的。
                devices=_device_descriptor_for(equipment, filled, project_id)
                if equipment else None,
            )
            if r.get("ok") and r.get("output_path"):
                # v0.1.201：render_gb_fallback 落在 exports/，而生成历史只读
                # generated_docs/ —— 不统一的话，复用现表生成的文件照样在
                # 「生成历史」里看不到、也下载不了（和原缺陷同一个症状）。
                # 这里把它搬进 generated_docs/<类型>/ 这一处唯一归档位置，
                # 并清掉 exports 里刚产生的同一份副本，避免同一张表被数两次。
                src = r["output_path"]
                with open(src, "rb") as fh:
                    blob = fh.read()
                new_path = _ar._save_generated(
                    _archive_type_of(doc_type), blob,
                    # v0.1.202：原来这里不传设备，档案里这份表与设备的关联是空的，
                    # 「按设备查资料」查不到它。批量生成 3 台设备时三份表全挂在空设备上。
                    devices=[equipment] if equipment else None,
                    workshops=[filled["车间"]] if filled.get("车间") else None)
                try:
                    os.remove(src)
                except Exception:  # noqa: BLE001 副本清理失败不影响交付
                    pass
                r["output_path"] = new_path
                r["output_file"] = os.path.basename(new_path)
                r["doc_type"] = doc_type
                r["equipment"] = equipment
                r["persisted"] = True
                r["engine"] = "gb_form"
                return r
        except Exception:  # noqa: BLE001  模板库异常 → 落到 docgen 口径
            pass

    # 2) 方案/交底/日志类走 docgen 模板，产出真正的 docx
    dg_type = _DOCGEN_ALIAS.get(doc_type, doc_type)
    if dg_type in _dg.TYPES:
        data = {
            "项目名称": filled.get("项目名称", "") or "【待补充】",
            "车间": filled.get("车间", "") or "【待补充】",
            "编制单位": filled.get("施工单位", "") or "【待补充】",
            "编制人": filled.get("编制人", "") or "【待补充】",
            "_devices": [{"tag": equipment, "name": equipment, "count": 1}] if equipment else [],
        }
        # 把内容层已经编排好的章节带进模板，避免重复劳动
        if isinstance(payload, dict):
            _secs = []
            for s in (payload.get("plan") or {}).get("sections", []) or []:
                if isinstance(s, dict) and s.get("title"):
                    body = s.get("content") or ""
                    _secs.append(f"{s['title']}\n{body}" if body else s["title"])
            if _secs:
                data["施工内容"] = "\n".join(_secs)
                data["施工工艺"] = "\n".join(_secs)
                data["进度安排"] = "\n".join(_secs)
                data["安全措施"] = "\n".join(_secs)
                data["质量措施"] = "\n".join(_secs)

        try:
            content, missing = _dg.fill_template(dg_type, data)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"生成 docx 失败：{e}"}

        path = _ar._save_generated(_archive_type_of(doc_type), content,
                                   devices=[{"tag": equipment}] if equipment else None,
                                   workshops=[filled["车间"]] if filled.get("车间") else None)
        return {
            "ok": True,
            "persisted": True,
            "engine": "docgen",
            "output_path": path,
            "output_file": os.path.basename(path),
            "doc_type": dg_type,
            "equipment": equipment,
            "missing_fields": missing,
            "gb_fallback": True,
            "gb_reason": "未提供专用模板，按国标通用格式生成",
        }

    # 3) 两类都没覆盖 → 明确失败，绝不返回「假成功」
    return {
        "ok": False,
        "error": (f"类型「{doc_type}」暂无可落盘的模板（docgen 支持："
                  f"{'、'.join(_dg.TYPES)}）。请改用现有检查记录表，或补充该类型模板。"),
        "doc_type": doc_type,
        "equipment": equipment,
        "persisted": False,
    }


def regenerate_by_type(doc_type: str, equipment: str = "",
                       project_id: str = None, doc_id: str = "") -> Dict:
    """按已知类型直接重新生成（跳过自然语言解析）。

    v0.1.201 实测发现的第 3 处「再生成」缺陷：前端「生成历史」里点重新生成，
    原来走的是 generate_from_natural_language，而那条链路必须从自然语言里
    认出设备名，认不出就停在 stage="need_equipment" 直接返回。实测拿归档名
    「焊接作业指导书」去重生成，外部接口返回
        {"ok": false, "error": "重新生成未产出文件"}
    —— 也就是用户视角的「重新生成按钮一直失败」。

    再生成本来就已经知道类型（从归档目录名反查得到），不该再依赖自然语言
    解析，直接用已知类型走落盘层。

    v0.1.202：设备名必须**从原文件读回来**。原实现 equipment 缺省为空，
    实测对「设备安装检查记录」点再生成，产出的新表「设备名称」列是空的 ——
    用户是想把那台设备的表重做一遍，结果拿回一张不知道是谁的表。
    资料来源：archive 落盘时登记过 doc_relations（devices 字段），
    按 doc_id 取回即可；取不到才留空（不编造设备名）。
    """
    # ① 没显式给设备名时，从原文件的关联记录里恢复
    if not equipment and doc_id:
        try:
            from . import doc_relations as _dr
            rec = (_dr.get_all() or {}).get(doc_id) or {}
            devs = [d for d in (rec.get("devices") or []) if str(d).strip()]
            if devs:
                equipment = str(devs[0]).strip()
        except Exception:  # noqa: BLE001  关联读不到就用空，不影响出表
            pass

    try:
        project_data = _get_project_data(project_id)
        filled, missing = _auto_fill_fields(doc_type, equipment, project_data, equipment)
        result = _persist_docx(doc_type, equipment, filled, {}, project_id=project_id)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"重新生成失败：{e}", "doc_type": doc_type}

    if not (isinstance(result, dict) and result.get("persisted") and result.get("output_path")):
        return {"ok": False,
                "error": (result or {}).get("error") or "重新生成未产出文件",
                "doc_type": doc_type, "result": result}
    return {"ok": True, "stage": "regenerated", "doc_type": doc_type,
            "equipment": equipment,
            "output_path": result.get("output_path"),
            "output_file": result.get("output_file"),
            "file_name": result.get("output_file"),
            "missing_fields": (result.get("missing_fields") or missing),
            "gb_fallback": result.get("gb_fallback"),
            "gb_reason": result.get("gb_reason"),
            "persisted": True}


# 智能生成类型 -> docgen 模板类型（名字对不上的做一次显式映射）
_DOCGEN_ALIAS = {
    "安全交底": "技术交底",          # 安全交底与交底同表式，仅有内容差异
    "开箱检验": "开箱验收记录",
    "隐蔽工程": "隐蔽工程验收记录",
    "基础验收": "开箱验收记录",
    "安装记录": "隐蔽工程验收记录",
    "试运转": "隐蔽工程验收记录",
}


def _call_generator(doc_type: str, equipment: str, filled: Dict, text: str,
                    project_id: str = None) -> Dict:
    """调用对应模块生成文件（v0.1.201：内容层 + 落盘层两步走）。"""
    project_name = filled.get("项目名称", "矿山工程项目")
    workshop = filled.get("车间", "")

    payload = {}
    try:
        if doc_type == "安全交底":
            from . import mining_safety_disclosure as _msd
            payload = _msd.generate_safety_disclosure(equipment, project_name, workshop)
        elif doc_type == "技术交底":
            from . import mining_technical_disclosure_enhanced as _mtde
            payload = _mtde.generate_technical_disclosure(equipment, project_name, workshop)
        elif doc_type == "施工方案":
            from . import mining_construction_plan_enhanced as _mcpe
            payload = _mcpe.generate_construction_plan(equipment, project_name, workshop)
        elif doc_type == "吊装方案":
            from . import mining_lifting_plan_enhanced as _mlpe
            payload = _mlpe.generate_lifting_plan(equipment, project_name, workshop)
        elif doc_type == "竣工资料":
            from . import mining_completion_archive_enhanced as _mcae
            payload = _mcae.generate_completion_archive(equipment, project_name, workshop)
        elif doc_type == "施工日志":
            from . import construction_log as _cl
            date = filled.get("日期", datetime.datetime.now().strftime("%Y-%m-%d"))
            payload = _cl.generate_log_data_enhanced(date, project_name, workshop)
    except Exception as e:  # noqa: BLE001  内容层异常不阻断落盘
        payload = {"ok": False, "error_content_layer": str(e)}

    # 无论内容层给了什么，最终必须有真文件落盘
    return _persist_docx(doc_type, equipment, filled, payload, project_id=project_id)


def get_supported_types() -> Dict:
    """获取支持的文件类型列表。"""
    types = []
    for doc_type, config in DOC_TYPE_MAP.items():
        types.append({
            "type": doc_type,
            "keywords": config["keywords"],
            "required_fields": config["required_fields"],
        })
    return {
        "ok": True,
        "total": len(types),
        "types": types,
    }


def analyze_input(text: str) -> Dict:
    """
    仅分析输入，不生成文件。用于前端实时提示。
    """
    doc_type, config = _extract_doc_type(text)
    equipment, eq_score = _extract_equipment(text)
    project_name = _extract_project_name(text)
    workshop = _extract_workshop(text)
    
    return {
        "ok": True,
        "input": text,
        "recognized_doc_type": doc_type,
        "recognized_equipment": equipment,
        "recognized_project": project_name,
        "recognized_workshop": workshop,
        "can_generate": doc_type is not None,
        "confidence": "高" if (doc_type and equipment) else ("中" if doc_type else "低"),
    }
