"""
v0.1.46：施工日志自动生成

功能：
1. 从现场记录（手机端上传的照片、语音、文字）按日期汇总
2. 自动提取施工内容、人员、机械、材料、质量安全、问题及处理
3. 生成Word格式施工日志（调用docgen模板）
4. 缺失信息提示补充
5. 支持人工修改和补充

设计原则：
- 按日期汇总当天所有现场记录
- 从记录类型（开箱/安装/验收/安全等）推断施工内容
- 从记录文本中提取人员、设备、材料关键词
- 天气/温度等无法自动获取的字段留空提示补充
- 生成后支持人工修改再导出
"""

import os
import json
import re
import datetime
from . import config

LOG_FILE = None


def _ensure():
    global LOG_FILE
    if LOG_FILE is None:
        LOG_FILE = os.path.join(config.DATA_DIR, "construction_logs.json")


def _load() -> dict:
    _ensure()
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {"logs": {}, "daily_summary": {}}


def _save(m: dict):
    _ensure()
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


# ---------------- 现场记录汇总 ----------------

def _load_field_records() -> list:
    """从云库拉取记录或本地缓存加载现场记录。"""
    records = []
    # 优先从本地云库缓存加载
    cloud_dir = os.path.join(config.DATA_DIR, "cloud_field_cache")
    if os.path.exists(cloud_dir):
        for fname in os.listdir(cloud_dir):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(cloud_dir, fname), encoding="utf-8") as f:
                        rec = json.load(f)
                    records.append(rec)
                except Exception:  # noqa: BLE001
                    pass
    # 从现场记录分析结果加载
    field_result_file = os.path.join(config.DATA_DIR, "field_record_results.json")
    if os.path.exists(field_result_file):
        try:
            with open(field_result_file, encoding="utf-8") as f:
                results = json.load(f)
            for r in results if isinstance(results, list) else results.get("results", []):
                records.append(r)
        except Exception:  # noqa: BLE001
            pass
    return records


def _extract_date(record: dict) -> str:
    """从记录中提取日期（YYYY-MM-DD）。"""
    for key in ["date", "ts", "timestamp", "created_at", "upload_time", "time"]:
        val = record.get(key) or record.get("metadata", {}).get(key, "")
        if val:
            # 尝试解析各种日期格式
            val_str = str(val)
            # ISO格式
            m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", val_str)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            # 时间戳
            try:
                ts = float(val_str)
                if ts > 1e12:  # 毫秒
                    ts /= 1000
                return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                pass
    # 默认今天
    return datetime.datetime.now().strftime("%Y-%m-%d")


def _classify_construction_content(record: dict) -> dict:
    """从现场记录推断施工内容分类。"""
    text = (record.get("text", "") or record.get("content", "") or
            record.get("transcript", "") or record.get("ocr_text", ""))
    rec_type = record.get("type", "") or record.get("record_type", "") or ""

    content = {
        "施工内容": [],
        "涉及设备": [],
        "人员": [],
        "材料": [],
        "机械": [],
        "质量安全": [],
        "问题及处理": [],
    }

    # 从记录类型推断
    type_map = {
        "开箱验收": "设备开箱验收",
        "开箱记录": "设备开箱验收",
        "安装记录": "设备安装",
        "隐蔽验收": "隐蔽工程验收",
        "隐蔽记录": "隐蔽工程验收",
        "验收记录": "工程验收",
        "安全检查": "安全检查",
        "安全交底": "安全技术交底",
        "技术交底": "技术交底",
        "施工日志": "日常施工",
        "现场记录": "现场施工",
        "到货记录": "设备材料到货",
        "吊装记录": "设备吊装",
    }
    if rec_type in type_map:
        content["施工内容"].append(type_map[rec_type])
    elif text:
        # 从文本关键词推断
        for kw, label in [("开箱", "设备开箱验收"), ("安装", "设备安装"),
                           ("隐蔽", "隐蔽工程验收"), ("验收", "工程验收"),
                           ("吊装", "设备吊装"), ("焊接", "管道焊接"),
                           ("试压", "压力试验"), ("试运转", "设备试运转"),
                           ("安全", "安全检查"), ("交底", "技术交底"),
                           ("到货", "设备材料到货"), ("领料", "材料领用")]:
            if kw in text:
                content["施工内容"].append(label)
                break

    # 提取设备位号
    for m in re.finditer(r"[A-Z]{1,4}-?\d{2,4}[A-Z]?", text):
        tag = m.group(0)
        if tag not in content["涉及设备"]:
            content["涉及设备"].append(tag)

    # 提取人员（简单模式：X工/X经理/X总/姓名+职务）
    for m in re.finditer(r"[\u4e00-\u9fa5]{1,2}(?:工|经理|总|师傅|工)", text):
        person = m.group(0)
        if person not in content["人员"]:
            content["人员"].append(person)

    # 提取材料关键词
    for kw in ["钢管", "钢板", "法兰", "阀门", "螺栓", "焊条", "焊丝", "保温材料",
               "电缆", "桥架", "仪表", "垫片", "油封", "轴承"]:
        if kw in text:
            content["材料"].append(kw)

    # 提取机械关键词
    for kw in ["汽车吊", "履带吊", "叉车", "卷扬机", "电焊机", "切割机",
               "试压泵", "真空泵", "空压机", "扳手", "千斤顶"]:
        if kw in text:
            content["机械"].append(kw)

    # 质量安全问题
    for kw in ["不合格", "缺陷", "裂纹", "变形", "锈蚀", "泄漏", "超标", "返工"]:
        if kw in text:
            content["问题及处理"].append(f"发现{kw}问题，已记录待处理")
            content["质量安全"].append(f"发现{kw}")
            break

    # 去重
    for k in content:
        if isinstance(content[k], list):
            content[k] = list(dict.fromkeys(content[k]))

    return content


def aggregate_by_date(records: list = None) -> dict:
    """按日期汇总现场记录，生成每日施工日志摘要。"""
    if records is None:
        records = _load_field_records()

    daily = {}
    for rec in records:
        date = _extract_date(rec)
        if date not in daily:
            daily[date] = {
                "date": date,
                "records": [],
                "施工内容": [],
                "涉及设备": [],
                "人员": [],
                "材料": [],
                "机械": [],
                "质量安全": [],
                "问题及处理": [],
                "记录人": set(),
            }
        daily[date]["records"].append(rec)

        # 提取记录人
        uploader = rec.get("uploader", "") or rec.get("uploaded_by", "") or rec.get("metadata", {}).get("uploader", "")
        if uploader:
            daily[date]["记录人"].add(uploader)

        # 分类提取
        content = _classify_construction_content(rec)
        for k in ["施工内容", "涉及设备", "人员", "材料", "机械", "质量安全", "问题及处理"]:
            daily[date][k].extend(content[k])

    # 去重并转换
    result = {}
    for date, d in sorted(daily.items()):
        for k in ["施工内容", "涉及设备", "人员", "材料", "机械", "质量安全", "问题及处理"]:
            d[k] = list(dict.fromkeys(d[k]))
        d["记录人"] = sorted(d["记录人"])
        d["record_count"] = len(d["records"])
        # 移除原始记录（只保留摘要）
        d.pop("records", None)
        result[date] = d

    # 保存
    m = _load()
    m["daily_summary"] = result
    _save(m)

    return result


# ---------------- 施工日志生成 ----------------

def generate_log_data(date: str, project_name: str = "", workshop: str = "",
                      extra_data: dict = None) -> dict:
    """生成指定日期的施工日志数据（供docgen使用）。"""
    m = _load()
    daily = m.get("daily_summary", {})

    if date not in daily:
        # 尝试重新汇总
        daily = aggregate_by_date()

    d = daily.get(date, {
        "date": date, "施工内容": [], "涉及设备": [], "人员": [],
        "材料": [], "机械": [], "质量安全": [], "问题及处理": [],
        "记录人": [], "record_count": 0,
    })

    # 构建当日工作内容
    work_items = []
    if d.get("施工内容"):
        work_items.extend(d["施工内容"])
    if d.get("涉及设备"):
        work_items.append(f"涉及设备：{'、'.join(d['涉及设备'][:10])}")
    work_content = "；".join(work_items) if work_items else "（待补充）"

    # 人员
    personnel = "、".join(d.get("人员", [])) or "（待补充）"
    if d.get("记录人"):
        personnel = f"记录人：{'、'.join(d['记录人'])}；{personnel}"

    # 材料
    materials = "、".join(d.get("材料", [])) or "（待补充）"

    # 机械
    machinery = "、".join(d.get("机械", [])) or "（待补充）"

    # 质量安全
    quality_safety = "；".join(d.get("质量安全", [])) or "正常，无质量安全问题"

    # 问题及处理
    issues = "；".join(d.get("问题及处理", [])) or "无"

    data = {
        "项目名称": project_name or "（待补充）",
        "车间": workshop or "（待补充）",
        "记录人": d.get("记录人", [""])[0] if d.get("记录人") else "（待补充）",
        "记录日期": date,
        "当日工作内容": work_content,
        "天气": "（待补充）",
        "温度": "（待补充）",
        "到场人员": personnel,
        "进场材料": materials,
        "机械使用": machinery,
        "安全质量情况": quality_safety,
        "问题及处理": issues,
    }

    # 合并额外数据
    if extra_data:
        data.update(extra_data)

    # 检查缺失
    missing = []
    for k, v in data.items():
        if v in ("", "（待补充）"):
            missing.append(k)

    return {"data": data, "missing": missing, "record_count": d.get("record_count", 0)}


def save_log(date: str, data: dict):
    """保存人工修改后的施工日志数据。"""
    m = _load()
    m["logs"][date] = {
        "data": data,
        "updated_at": datetime.datetime.now().isoformat(),
        "status": "edited",
    }
    _save(m)


def get_log(date: str) -> dict:
    """获取指定日期的施工日志（优先人工修改版）。"""
    m = _load()
    if date in m.get("logs", {}):
        return m["logs"][date]
    return {"data": generate_log_data(date)["data"], "status": "auto_generated"}


def list_logs() -> list:
    """列出所有已生成的施工日志日期。"""
    m = _load()
    daily = m.get("daily_summary", {})
    logs = m.get("logs", {})
    result = []
    for date in sorted(set(list(daily.keys()) + list(logs.keys())), reverse=True):
        d = daily.get(date, {})
        result.append({
            "date": date,
            "record_count": d.get("record_count", 0),
            "status": "edited" if date in logs else "auto_generated",
            "施工内容": d.get("施工内容", []),
        })
    return result


def stats() -> dict:
    """施工日志统计。"""
    m = _load()
    daily = m.get("daily_summary", {})
    logs = m.get("logs", {})
    total_records = sum(d.get("record_count", 0) for d in daily.values())
    return {
        "days_with_records": len(daily),
        "total_field_records": total_records,
        "edited_logs": len(logs),
        "auto_generated_logs": len(daily) - len(logs),
        "latest_date": max(daily.keys()) if daily else None,
        "earliest_date": min(daily.keys()) if daily else None,
    }


# ==================== v0.1.54 施工日志与设备数据联动增强 ====================

def _get_device_construction_content(eq_type: str) -> list:
    """v0.1.54：根据设备类型生成施工内容建议。"""
    type_content = {
        "泵": ["泵基础验收", "泵就位找平找正", "泵进出口管道连接", "泵联轴器对中", "泵单机试运转"],
        "压缩机": ["压缩机基础验收", "压缩机就位找平", "气缸与滑道对中", "润滑油系统冲洗", "压缩机单机试运转"],
        "塔器": ["塔器基础验收", "塔器吊装就位", "塔器垂直度找正", "塔器接管连接", "塔器内件安装"],
        "换热器": ["换热器基础验收", "换热器就位找平", "换热器管程壳程连接", "换热器水压试验", "换热器保温施工"],
        "容器": ["容器基础验收", "容器吊装就位", "容器垂直度找正", "容器接管连接", "容器水压试验"],
        "风机": ["风机基础验收", "风机就位找平", "风机进出口管道连接", "风机皮带对中", "风机单机试运转"],
        "电机": ["电机基础验收", "电机就位找平", "电机电缆接线", "电机绝缘测试", "电机空载试运转"],
        "阀门": ["阀门检验试压", "阀门支架安装", "阀门法兰连接", "阀门传动装置安装", "阀门开关试验"],
        "储罐": ["储罐基础验收", "储罐底板铺设焊接", "储罐壁板安装焊接", "储罐顶板安装", "储罐充水试验"],
    }
    return type_content.get(eq_type, ["设备基础验收", "设备就位找平", "设备管道连接", "设备试运转"])


def _get_device_quality_safety(eq_type: str) -> dict:
    """v0.1.54：根据设备类型生成质量安全要点。"""
    type_qs = {
        "泵": {"quality": ["泵水平度偏差≤0.05mm/m", "联轴器对中偏差径向≤0.05mm"], "safety": ["机械防护罩安装到位", "试运转时严禁站在旋转方向正面"]},
        "压缩机": {"quality": ["压缩机水平度偏差≤0.05mm/m", "气缸与滑道对中符合规范"], "safety": ["超压保护装置校验合格", "润滑油位正常方可试运转"]},
        "塔器": {"quality": ["塔器垂直度偏差≤高度1/1000", "塔盘水平度偏差≤2mm"], "safety": ["高处作业系挂安全带", "吊装时风力超过六级停止"]},
        "换热器": {"quality": ["换热器水压试验压力为设计1.25倍", "保温层厚度符合设计"], "safety": ["水压试验时严禁站在法兰正面", "升压缓慢严禁超压"]},
        "容器": {"quality": ["容器垂直度偏差≤高度1/1000", "焊缝无损检测合格"], "safety": ["容器内作业办理受限空间票", "试压时严禁站在法兰正面"]},
        "风机": {"quality": ["风机叶轮与机壳间隙均匀", "皮带轮对中偏差符合要求"], "safety": ["皮带防护罩安装齐全", "试运转时测量轴承温度"]},
        "电机": {"quality": ["电机绝缘电阻≥0.5MΩ", "电机底座水平度≤0.05mm/m"], "safety": ["接线前确认电源断开挂牌", "接地电阻≤4Ω"]},
        "阀门": {"quality": ["阀门法兰螺栓紧固力矩符合规范", "阀门开关灵活无卡涩"], "safety": ["高压阀门试压合格方可安装", "法兰紧固按对角顺序"]},
        "储罐": {"quality": ["储罐底板焊接无损检测合格", "充水试验基础沉降符合设计"], "safety": ["罐内作业办理受限空间票", "焊接作业办理动火票"]},
    }
    return type_qs.get(eq_type, {"quality": ["施工质量符合设计和规范要求"], "safety": ["作业人员佩戴防护用品", "设置警戒区"]})


def enrich_log_with_devices(log_data: dict, devices: list = None) -> dict:
    """v0.1.54：用设备数据丰富施工日志。
    
    Args:
        log_data: 原始日志数据
        devices: 设备列表，为空时从relations加载
    
    Returns:
        丰富后的日志数据
    """
    data = dict(log_data)
    
    # 加载设备
    if devices is None:
        try:
            from . import relations as _rel
            g = _rel.load_relations()
            devices = g.get("devices", [])
        except Exception:  # noqa: BLE001
            devices = []
    
    if not devices:
        return data
    
    # 识别设备类型
    try:
        from . import equipment_types as _et
        eq_type = _et.get_equipment_type_from_devices(devices)
    except Exception:  # noqa: BLE001
        eq_type = "通用设备"
    
    data["设备类型"] = eq_type
    data["涉及设备"] = "、".join(d["tag"] for d in devices[:10]) + (f" 等{len(devices)}台" if len(devices) > 10 else "")
    
    # 施工内容建议
    content_suggestions = _get_device_construction_content(eq_type)
    data["施工内容建议"] = "\\n".join(f"{i+1}. {c}" for i, c in enumerate(content_suggestions))
    
    # 质量安全要点
    qs = _get_device_quality_safety(eq_type)
    data["质量要点"] = "\\n".join(f"{i+1}. {q}" for i, q in enumerate(qs["quality"]))
    data["安全要点"] = "\\n".join(f"{i+1}. {s}" for i, s in enumerate(qs["safety"]))
    
    # 设备空间信息
    try:
        from . import spatial_model as _sm
        from . import relations as _rel
        g = _rel.load_relations()
        spatial = _sm.build_spatial_model(g)
        spatial_devs = {d["tag"]: d for d in spatial.get("devices", [])}
        device_locations = []
        for d in devices[:5]:
            tag = d["tag"]
            sd = spatial_devs.get(tag, {})
            loc = []
            if sd.get("workshop"):
                loc.append(sd["workshop"])
            if sd.get("z") is not None:
                loc.append(f"标高{sd['z']}m")
            if loc:
                device_locations.append(f"{tag}({', '.join(loc)})")
        if device_locations:
            data["设备位置"] = "；".join(device_locations)
    except Exception:  # noqa: BLE001
        pass
    
    return data


def generate_log_data_enhanced(date: str, project_name: str = "", workshop: str = "",
                                extra_data: dict = None, devices: list = None) -> dict:
    """v0.1.54：增强版施工日志生成（含设备数据联动）。"""
    result = generate_log_data(date, project_name, workshop, extra_data)
    result["data"] = enrich_log_with_devices(result["data"], devices)
    return result
