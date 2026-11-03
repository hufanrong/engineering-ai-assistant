"""
v0.1.67：设备安装位置与竣工资料联动

根据设备位置自动生成竣工资料清单，进行完整性检查，与设备状态联动，
按车间/标高分组，资料缺失提醒。
"""

import os
import json
import datetime
import threading
import uuid
from typing import Optional
from . import project_paths as _pp

# v0.1.197：**竣工清单的读改写必须串行化，且临时文件名必须唯一**。
#
# 实测事故（真实项目 e75e857c，228 台设备，/api/completion-archive/all 69 秒）：
#   返回 total_devices=222、failed_count=6，失败原因是
#     FileNotFoundError: ... completion_archive.json.tmp -> completion_archive.json
#     PermissionError:   Operation not permitted: ... completion_archive.json.tmp
#   generate_device_archive_list 每台设备都做一次「读全量 → 改一项 → 写全量」，
#   而 _save_archive 用**固定名字**的 path + ".tmp"。两个设备线程同时写时：
#     A: dump 到 .tmp → rename 走 .tmp
#     B: dump 到 .tmp（此时 .tmp 已被 A 挪走，open 会新建）→ rename 时报 .tmp 不存在
#   在 Windows 上更严重：A 还没 release 句柄时 B 去 os.replace 直接报
#   PermissionError（文件被占用），这正是现场「一键竣工偶尔少几台设备」的来源。
#
#   而且失败是**静默少台**：失败的 6 台被塞进 failed_devices，但 total_devices
#   跟着变成 222 —— /stats 读磁盘得到的数字又是另一个值（实测 89→148 之间徘徊，
#   因为每次运行都覆盖写，中断后留下的是半份清单）。
#   竣工清单是交给监理的归档交付物，少一台就是少一份资料，不能靠并发运气。
#
#   两处改动：
#     ① 临时文件名带 uuid —— 各写各的，不会互抢同一个 .tmp；
#     ② 模块级可重入锁包住整个「读—改—写」——否则即使 tmp 不冲突，
#        后写的线程会用自己那份**旧快照**整份覆盖，前面的写入凭空消失
#        （实测 6 路并发最终只剩 2 条）。
_ARCHIVE_LOCK = threading.RLock()


def _archive_file_path() -> str:
    """v0.1.176：当前项目内的数据文件路径（跨项目隔离）。"""
    return _pp.data_file_with_legacy("completion_archive.json")

def _archive_file() -> str:
    """竣工归档清单的存储路径（按当前项目隔离）。

    v0.1.173：原来写死成全局 data/completion_archive.json —— 全机器只有一份。
    后果是建 A、B 两个项目，在 A 生成过竣工清单后切到从未生成过的 B，
    B 的「竣工资料统计」直接返回 A 的设备数（实测 total_devices=0 却又能
    从同一文件里列出别的项目的 EQ-101 缺件），导出会把别的项目的资料递出去。
    竣工归档是交给监理的项目级交付物，必须跟着项目走。

    取不到项目目录时（老版本无项目数据）回退旧的全局路径，保证已存在的老机器
    升级后仍能读到原有清单，不会突然变成空。
    """
    try:
        from . import project_manager as _pm
        ddir = _pm.get_project_data_dir()
        if ddir:
            return os.path.join(ddir, "completion_archive.json")
    except Exception:  # noqa: BLE001
        pass
    return _archive_file_path()


def _ensure_dirs():
    p = os.path.dirname(_archive_file())
    if p:
        os.makedirs(p, exist_ok=True)


def _load_archive() -> dict:
    try:
        _p = _archive_file_path()
    except _pp.NoProjectError:
        return {}
    """读当前项目的竣工归档清单。

    项目内没有这份文件时，只有「当前无项目、退回全局路径」的情况下才去读旧全局文件；
    有项目但项目内还没有清单 → 返回 {}，不把别的项目的清单借过来。
    """
    path = _archive_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save_archive(archive: dict):
    """整份写回竣工清单。**临时文件名必须唯一**（并发写时不能用固定 .tmp）。

    v0.1.197：固定 path+".tmp" 会在并发下互相踩踏（见文件头注释的实测证据）。
    """
    _ensure_dirs()
    path = _archive_file()
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        # 替换失败也要把临时文件清掉，否则现场目录会堆一堆 .tmp
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _update_archive(key, value) -> dict:
    """原子地「读全量 → 改一条 → 写回全量」，返回写回后的整份清单。

    v0.1.197：竣工清单是**整份 JSON 文件**，任何一次单条更新都是
    read-modify-write。并发出卷（整卷按车间 3 路并发）时，两个线程各自读到
    同一份旧快照、各写各的，后写的把先写的整份覆盖 —— 设备凭空消失。
    所以必须把三步收进一把锁，并把整个操作封成一个函数，
    调用方拿不到「先 load 再 save」的机会，漏锁就不可能发生。
    """
    with _ARCHIVE_LOCK:
        archive = _load_archive()
        archive[key] = value
        _save_archive(archive)
        return archive


# 每类设备需要的竣工资料清单
DEVICE_ARCHIVE_REQUIREMENTS = {
    "泵": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "联轴器对中记录", "required": True},
        {"type": "管道连接记录", "required": True},
        {"type": "单机试运转记录", "required": True},
        {"type": "隐蔽工程验收记录", "required": False},
        {"type": "设计变更通知单", "required": False},
    ],
    "压缩机": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "联轴器对中记录", "required": True},
        {"type": "润滑油系统冲洗记录", "required": True},
        {"type": "管道连接记录", "required": True},
        {"type": "单机试运转记录", "required": True},
        {"type": "隐蔽工程验收记录", "required": False},
        {"type": "设计变更通知单", "required": False},
    ],
    "塔器": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备吊装记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "垂直度测量记录", "required": True},
        {"type": "内件安装记录", "required": True},
        {"type": "管道连接记录", "required": True},
        {"type": "水压试验记录", "required": False},
        {"type": "隐蔽工程验收记录", "required": False},
        {"type": "设计变更通知单", "required": False},
    ],
    "换热器": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "水压试验记录", "required": True},
        {"type": "管道连接记录", "required": True},
        {"type": "隐蔽工程验收记录", "required": False},
        {"type": "设计变更通知单", "required": False},
    ],
    "容器": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "管道连接记录", "required": True},
        {"type": "隐蔽工程验收记录", "required": False},
        {"type": "设计变更通知单", "required": False},
    ],
    "风机": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "联轴器对中记录", "required": True},
        {"type": "单机试运转记录", "required": True},
        {"type": "设计变更通知单", "required": False},
    ],
    "电机": [
        {"type": "开箱验收记录", "required": True},
        {"type": "设备基础验收记录", "required": True},
        {"type": "设备安装记录", "required": True},
        {"type": "绝缘测试记录", "required": True},
        {"type": "单机试运转记录", "required": True},
        {"type": "设计变更通知单", "required": False},
    ],
    "阀门": [
        {"type": "开箱验收记录", "required": True},
        {"type": "阀门试验记录", "required": True},
        {"type": "安装记录", "required": True},
    ],
    "储罐": [
        {"type": "开箱验收记录", "required": True},
        {"type": "基础验收记录", "required": True},
        {"type": "罐底焊接记录", "required": True},
        {"type": "罐壁焊接记录", "required": True},
        {"type": "真空箱试漏记录", "required": True},
        {"type": "充水试验记录", "required": True},
        {"type": "隐蔽工程验收记录", "required": False},
        {"type": "设计变更通知单", "required": False},
    ],
}

# v0.1.84：矿山设备竣工资料要求
_MINING_ARCHIVE_REQ = {
    "破碎机": ["设备开箱检验记录", "设备基础验收记录", "设备安装记录", "设备找平找正记录", "隐蔽工程验收记录", "设备试运转记录", "设备质量证明文件", "设备说明书", "设备竣工图"],
    "球磨机": ["设备开箱检验记录", "设备基础验收记录", "主轴承安装刮研记录", "筒体安装记录", "大齿圈安装检测记录", "传动装置安装记录", "衬板安装记录", "隐蔽工程验收记录", "设备试运转记录", "设备质量证明文件", "设备说明书", "设备竣工图"],
    "浮选机": ["设备开箱检验记录", "设备基础验收记录", "槽体安装记录", "搅拌机构安装记录", "传动装置安装记录", "隐蔽工程验收记录", "设备试运转记录", "设备质量证明文件", "设备说明书", "设备竣工图"],
    "高压釜": ["设备开箱检验记录", "压力容器质量证明书", "设备基础验收记录", "设备安装记录", "内件安装记录", "搅拌装置安装记录", "隐蔽工程验收记录", "耐压试验记录", "气密性试验记录", "衬里检测记录", "安全附件校验记录", "设备说明书", "设备竣工图"],
    "萃取箱": ["设备开箱检验记录", "基础防腐防渗记录", "箱体安装记录", "搅拌机构安装记录", "渗漏试验记录", "隐蔽工程验收记录", "设备试运转记录", "设备质量证明文件", "设备说明书", "设备竣工图"],
    "闪速炉": ["设备开箱检验记录", "炉体基础验收记录", "炉壳安装记录", "冷却壁安装记录", "耐火材料砌筑记录", "烘炉记录", "试压试漏记录", "隐蔽工程验收记录", "设备质量证明文件", "耐火材料质量证明文件", "设备竣工图"],
    "转炉": ["设备开箱检验记录", "设备基础验收记录", "托圈安装记录", "炉体安装记录", "耳轴轴承安装记录", "倾动机构安装记录", "供氧系统安装记录", "隐蔽工程验收记录", "设备试运转记录", "设备质量证明文件", "设备说明书", "设备竣工图"],
    "余热锅炉": ["锅炉质量证明书", "锅炉基础验收记录", "汽包安装记录", "受热面安装记录", "管道安装记录", "隐蔽工程验收记录", "水压试验记录", "烘炉记录", "煮炉记录", "蒸汽严密性试验记录", "安全附件校验记录", "锅炉竣工图"],
}
DEVICE_ARCHIVE_REQUIREMENTS.update(_MINING_ARCHIVE_REQ)


# 默认资料清单（未知设备类型）
DEFAULT_REQUIREMENTS = [
    {"type": "开箱验收记录", "required": True},
    {"type": "设备基础验收记录", "required": True},
    {"type": "设备安装记录", "required": True},
    {"type": "管道连接记录", "required": True},
    {"type": "单机试运转记录", "required": True},
    {"type": "设计变更通知单", "required": False},
]


def _normalize_requirements(reqs) -> list:
    """把资料清单统一成 [{"type": str, "required": bool}]。

    v0.1.177：实测事故 —— 矿山设备那批清单（_MINING_ARCHIVE_REQ）是
    **纯字符串列表**，而 generate_device_archive_list 里按 `req["type"]` 取字段，
    字符串下标一取就 TypeError: string indices must be integers，
    整个「一键竣工归档」直接 500，连带 fieldtest 在收尾处崩掉、整轮报告都写不出来。
    这里在出口处一次性归一，调用方不必再各自判断形状。
    """
    out = []
    for r in (reqs or []):
        if isinstance(r, str):
            t = r.strip()
            if t:
                out.append({"type": t, "required": True})
        elif isinstance(r, dict):
            t = str(r.get("type") or r.get("名称") or "").strip()
            if t:
                out.append({"type": t, "required": bool(r.get("required", True))})
        elif isinstance(r, (list, tuple)) and r:
            t = str(r[0]).strip()
            if t:
                out.append({"type": t, "required": bool(r[1]) if len(r) > 1 else True})
    return out


def get_device_requirements(dev_type: str) -> list:
    """v0.1.67：获取设备类型需要的竣工资料清单。

    Args:
        dev_type: 设备类型

    Returns:
        资料清单（已归一为 [{"type","required"}]，可直接下标取值）
    """
    return _normalize_requirements(
        DEVICE_ARCHIVE_REQUIREMENTS.get(dev_type, DEFAULT_REQUIREMENTS))


def generate_device_archive_list(tag: str, _persist: bool = True) -> dict:
    """v0.1.67：生成单台设备的竣工资料清单。

    Args:
        tag: 设备位号
        _persist: 是否立即落盘（v0.1.197）。批量出全部设备时必须传 False ——
                  否则 228 台设备要整份读+写 228 次全量 JSON。

    Returns:
        设备竣工资料清单
    """
    from . import relations as _rel
    from . import spatial_model as _sm
    from . import construction_schedule as _cs
    
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
    dev_type = sd.get("type", "")
    
    # 获取设备施工状态
    try:
        status_info = _cs.get_device_status(tag)
        construction_status = status_info.get("status", "pending")
    except Exception:
        construction_status = "pending"
    
    # 获取需要的资料清单
    requirements = get_device_requirements(dev_type)
    
    # 检查已有的资料（从generated_docs目录扫描）
    existing_docs = []
    docs_dir = _pp.data_subdir("generated_docs")
    if os.path.exists(docs_dir):
        for root, dirs, files in os.walk(docs_dir):
            for f in files:
                if tag in f:
                    existing_docs.append(f)
    
    # 检查资料完整性
    archive_items = []
    missing_required = []
    missing_optional = []
    
    for req in requirements:
        # v0.1.177：即便上层将来又塞进一个未归一的清单，这里也不再硬下标崩掉整站
        if not isinstance(req, dict):
            req = {"type": str(req), "required": True}
        doc_type = req.get("type")
        if not doc_type:
            continue
        required = req.get("required", True)
        
        # 检查是否已有该类型资料
        has_doc = any(doc_type in doc for doc in existing_docs)
        
        item = {
            "type": doc_type,
            "required": required,
            "status": "completed" if has_doc else "missing",
            "existing_file": next((doc for doc in existing_docs if doc_type in doc), None),
        }
        archive_items.append(item)
        
        if not has_doc:
            if required:
                missing_required.append(doc_type)
            else:
                missing_optional.append(doc_type)
    
    # 完整性评估
    total_required = sum(1 for r in requirements if r["required"])
    completed_required = total_required - len(missing_required)
    completeness_percent = round(completed_required / total_required * 100, 1) if total_required > 0 else 100
    
    result = {
        "tag": tag,
        "name": sd.get("name", tag),
        "type": dev_type,
        "workshop": sd.get("workshop") or (device.get("workshops", [""])[0] if device.get("workshops") else ""),
        "elevation": sd.get("z"),
        "construction_status": construction_status,
        "requirements": archive_items,
        "total_requirements": len(requirements),
        "required_count": total_required,
        "completed_count": len([i for i in archive_items if i["status"] == "completed"]),
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "completeness_percent": completeness_percent,
        "existing_docs": existing_docs,
        "generated_at": datetime.datetime.now().isoformat(),
    }
    
    # 保存到归档
    # v0.1.197：必须走 _update_archive 这个原子入口。原来这里是
    # `archive = _load_archive(); archive[tag] = result; _save_archive(archive)`
    # 三步裸奔，并发出卷时后写的线程拿自己那份**旧快照**整份覆盖，
    # 前面刚写进去的设备凭空消失（实测 6 路并发最终只剩 2 条）。
    # 封装成函数是为了让调用方**没有机会**漏掉锁 —— 只靠约定"记得加锁"必然漏。
    if _persist:
        _update_archive(tag, result)

    return result


def generate_all_devices_archive() -> dict:
    """v0.1.67：生成所有设备的竣工资料清单。
    
    Returns:
        所有设备竣工资料汇总
    """
    from . import relations as _rel
    
    g = _rel.load_relations()
    devices = g.get("devices", [])
    
    all_archives = []
    failed_tags = []
    _results_to_persist = {}
    for d in devices:
        # v0.1.177：单台设备失败不得掀翻整个接口。
        # 实测事故：矿山设备资料清单是纯字符串列表，req["type"] 抛 TypeError，
        # 「一键竣工」整条 500 —— 一台设备的形状问题让 195 台设备的清单全都没了。
        try:
            _tag = (d or {}).get("tag", "") if isinstance(d, dict) else ""
            if not _tag:
                # 缺位号的记录必须显式记账，不能静默少一台
                failed_tags.append({"tag": "", "error": "设备记录缺少 tag（位号）字段"})
                continue
            # v0.1.197：批量时**不逐台落盘**（_persist=False），末尾一次性写回。
            # 实测：228 台设备各做一次「读全量 → 改一条 → 写全量」，单次往返 9.6 ms，
            # 光是无效的全量 JSON 读写就 2.2 秒；叠加并发争抢还有 6 台失败。
            archive = generate_device_archive_list(_tag, _persist=False)
            if "error" in archive:
                # v0.1.177：**带 error 的也必须记账**。
                # 实测事故：一台设备的位号取不到 → 返回 {"error": "设备不存在"} →
                # 这里 `if "error" not in archive` 直接把它丢掉，4 台设备静默变 3 台。
                # /api/completion-archive/all 报 4、一键竣工报 3，两个接口自相矛盾，
                # 而失败设备清单是空的，用户完全看不出少的是哪一台。
                failed_tags.append({"tag": _tag, "error": str(archive.get("error"))[:200]})
                continue
            all_archives.append(archive)
            _results_to_persist[_tag] = archive
        except Exception as _e:  # noqa: BLE001
            failed_tags.append({"tag": d.get("tag", ""), "error": f"{type(_e).__name__}: {_e}"})
    
    # 按车间分组
    by_workshop = {}
    for a in all_archives:
        ws = a.get("workshop", "未分配")
        if ws not in by_workshop:
            by_workshop[ws] = []
        by_workshop[ws].append(a)
    
    # 按标高分组
    by_elevation = {}
    for a in all_archives:
        elev = a.get("elevation")
        key = f"EL{elev}m" if elev is not None else "无标高"
        if key not in by_elevation:
            by_elevation[key] = []
        by_elevation[key].append(a)
    
    # 总体统计
    total_devices = len(all_archives)
    complete_devices = sum(1 for a in all_archives if a["completeness_percent"] >= 100)
    incomplete_devices = total_devices - complete_devices
    avg_completeness = round(sum(a["completeness_percent"] for a in all_archives) / total_devices, 1) if total_devices > 0 else 0
    
    # 缺失资料汇总
    all_missing = {}
    for a in all_archives:
        for doc_type in a["missing_required"]:
            if doc_type not in all_missing:
                all_missing[doc_type] = []
            all_missing[doc_type].append(a["tag"])
    
    # v0.1.197：一次性写回（一把锁、一次读、一次写），不再逐台往返。
    # 这样即使 228 台里有几台失败，也不会因为并发写而互相踩掉已算好的结果。
    if _results_to_persist:
        try:
            with _ARCHIVE_LOCK:
                archive = _load_archive()
                archive.update(_results_to_persist)
                _save_archive(archive)
        except Exception as _se:  # noqa: BLE001
            # 落盘失败不能掀翻统计结果：清单已经算出来了，用户至少要看得到
            failed_tags.append({"tag": "", "error":
                                f"竣工清单写盘失败（统计结果仍然可用）："
                                f"{type(_se).__name__}: {_se}"})

    return {
        "total_devices": total_devices,
        "complete_devices": complete_devices,
        "incomplete_devices": incomplete_devices,
        "avg_completeness_percent": avg_completeness,
        "by_workshop": {ws: len(devs) for ws, devs in by_workshop.items()},
        "by_elevation": {elev: len(devs) for elev, devs in by_elevation.items()},
        "missing_summary": {doc_type: len(tags) for doc_type, tags in all_missing.items()},
        "missing_details": all_missing,
        "devices": all_archives,
        # v0.1.177：失败的设备单独列出，不静默吞掉 —— 用户要能看到「哪台没算出来、因为什么」
        "failed_devices": failed_tags,
        "failed_count": len(failed_tags),
        "generated_at": datetime.datetime.now().isoformat(),
    }


def update_device_doc_status(tag: str, doc_type: str, status: str,
                              file_name: str = None) -> dict:
    """v0.1.67：更新设备资料状态。
    
    Args:
        tag: 设备位号
        doc_type: 资料类型
        status: 状态 - completed/missing
        file_name: 文件名（可选）
    
    Returns:
        更新结果
    """
    archive = _load_archive()
    if tag not in archive:
        return {"error": "设备归档不存在", "tag": tag}
    
    device_archive = archive[tag]
    for item in device_archive.get("requirements", []):
        if item["type"] == doc_type:
            item["status"] = status
            if file_name:
                item["existing_file"] = file_name
            break
    
    # 重新计算完整性
    requirements = device_archive.get("requirements", [])
    total_required = sum(1 for r in requirements if r["required"])
    completed_required = sum(1 for r in requirements if r["required"] and r["status"] == "completed")
    device_archive["completeness_percent"] = round(completed_required / total_required * 100, 1) if total_required > 0 else 100
    device_archive["completed_count"] = len([i for i in requirements if i["status"] == "completed"])
    device_archive["missing_required"] = [r["type"] for r in requirements if r["required"] and r["status"] != "completed"]
    device_archive["missing_optional"] = [r["type"] for r in requirements if not r["required"] and r["status"] != "completed"]
    
    # v0.1.197：同样是读—改—写，必须收进锁里，否则并发出卷时状态更新会被覆盖
    with _ARCHIVE_LOCK:
        _archive_now = _load_archive()
        if tag not in _archive_now:
            return {"error": "设备归档不存在", "tag": tag}
        _archive_now[tag] = device_archive
        _save_archive(_archive_now)
    
    return {"ok": True, "tag": tag, "doc_type": doc_type, "status": status,
            "completeness_percent": device_archive["completeness_percent"]}


def get_archive_stats() -> dict:
    """v0.1.67：获取竣工资料归档统计。

    v0.1.197：必须显式告诉调用方「这份统计是不是全的」。
    实测事故：清单文件被并发写毁坏时只剩 89 条，而 /api/completion-archive/all
    实时算出台账里的 228 台 —— 同一时刻两个接口报出 89 和 228 两个数字，
    /stats 却一个字都不说，用户不知道少的那 139 台去哪了。
    这里额外返回 ledger_devices（台账里实际有多少台）与 stale / coverage，
    让「统计不全」变成一个看得见的状态，而不是悄悄变小的数字。
    """
    archive = _load_archive()
    devices = list(archive.values())
    
    # 台账里实际有多少设备（用于判断这份统计是否完整）
    _ledger = 0
    try:
        from . import relations as _rel
        _ledger = len((_rel.load_relations() or {}).get("devices") or [])
    except Exception:  # noqa: BLE001
        _ledger = 0

    if not devices:
        _msg = "尚未生成竣工资料清单"
        if _ledger:
            _msg = (f"尚未生成竣工资料清单（台账里有 {_ledger} 台设备，"
                    f"请点「一键竣工」生成）")
        return {"ok": True, "total_devices": 0, "message": _msg,
                "ledger_devices": _ledger, "stale": bool(_ledger),
                "coverage": 0.0}
    
    total = len(devices)
    complete = sum(1 for d in devices if d.get("completeness_percent", 0) >= 100)
    avg_completeness = round(sum(d.get("completeness_percent", 0) for d in devices) / total, 1)
    
    # 按车间统计
    by_workshop = {}
    for d in devices:
        ws = d.get("workshop", "未分配")
        if ws not in by_workshop:
            by_workshop[ws] = {"total": 0, "complete": 0}
        by_workshop[ws]["total"] += 1
        if d.get("completeness_percent", 0) >= 100:
            by_workshop[ws]["complete"] += 1
    
    # 按施工状态统计
    by_status = {}
    for d in devices:
        status = d.get("construction_status", "pending")
        by_status[status] = by_status.get(status, 0) + 1
    
    _coverage = round(total / _ledger, 3) if _ledger else (1.0 if total else 0.0)
    _stale = bool(_ledger) and total < _ledger
    _res = {
        "ok": True,
        "total_devices": total,
        "complete_devices": complete,
        "incomplete_devices": total - complete,
        "avg_completeness_percent": avg_completeness,
        "by_workshop": by_workshop,
        "by_construction_status": by_status,
        "ledger_devices": _ledger,
        "coverage": _coverage,
        "stale": _stale,
    }
    if _stale:
        # 清单比台账少，必须明说，不能让用户以为「设备就只有这么多」
        _res["warning"] = (f"竣工清单只覆盖 {total}/{_ledger} 台设备（{_coverage:.0%}）。"
                           f"请重新点「一键竣工」生成完整清单；"
                           f"此前的残缺来自并发写冲突，v0.1.197 已修复。")
    return _res


def list_missing_docs() -> list:
    """v0.1.67：列出所有缺失的资料。"""
    archive = _load_archive()
    missing = []
    
    for tag, device_archive in archive.items():
        for doc_type in device_archive.get("missing_required", []):
            missing.append({
                "tag": tag,
                "name": device_archive.get("name", tag),
                "workshop": device_archive.get("workshop", ""),
                "doc_type": doc_type,
                "required": True,
            })
        for doc_type in device_archive.get("missing_optional", []):
            missing.append({
                "tag": tag,
                "name": device_archive.get("name", tag),
                "workshop": device_archive.get("workshop", ""),
                "doc_type": doc_type,
                "required": False,
            })
    
    return missing
