# 繁工AI 本地解析工作台 - 资料完整性检查（v0.1.36）
# 目的：根据项目进度阶段，自动检查哪些工程资料缺失，列出待补充清单。
#       支持项目级、车间级、设备级三个维度的资料完整性检查。
#
# 口径（用户锁定）：
#   - 如果发现提供资料不全时，提醒缺少哪些关键内容，让人操作人按项补充完整
#   - 资料生成是根据项目进度来的，到这一步了就做，信息不全放代办
#   - 最终这些资料用来制作对应的工程资料

import os
import json
import glob

from . import config
from . import docgen
from . import project_scope as _scope


# 工程阶段定义（按时间顺序）
PHASES = [
    {
        "key": "准备阶段",
        "label": "施工准备",
        "order": 1,
        "project_docs": ["施工方案", "施工计划", "技术交底"],
        "description": "开工前应完成施工方案、施工计划、技术交底",
    },
    {
        "key": "到货阶段",
        "label": "设备到货",
        "order": 2,
        "device_docs": ["开箱验收记录"],
        "description": "每台设备到货后应有开箱验收记录",
    },
    {
        "key": "施工阶段",
        "label": "施工过程",
        "order": 3,
        "workshop_docs": ["施工日志", "隐蔽工程验收记录"],
        "device_docs": [],
        "description": "施工过程中应有施工日志、隐蔽工程验收记录",
    },
    {
        "key": "吊装阶段",
        "label": "吊装作业",
        "order": 4,
        "project_docs": ["吊装方案"],
        "description": "大型设备吊装前应有吊装方案",
    },
    {
        "key": "变更阶段",
        "label": "设计变更",
        "order": 5,
        "project_docs": ["设计变更"],
        "description": "有设计变更时应有变更记录",
    },
    {
        "key": "竣工阶段",
        "label": "竣工验收",
        "order": 6,
        "project_docs": ["竣工资料"],
        "description": "工程完工后应有竣工资料",
    },
]

# 设备级必查资料（每台设备都应有）
DEVICE_REQUIRED_DOCS = ["开箱验收记录"]

# 车间级必查资料（每个车间都应有）
WORKSHOP_REQUIRED_DOCS = ["施工日志", "隐蔽工程验收记录"]


def _load_generated_docs() -> dict:
    """加载已生成的资料清单。返回 {doc_type: [file_names]}。

    v0.1.168：改用 archive._gen_dir() 取目录 —— 原来写死全局 DATA_DIR/generated_docs，
    项目切换后仍读到别的项目的资料，完整性检查会给出错误的「已具备」结论。
    """
    try:
        from . import archive as _ar
        gen_dir = _ar._gen_dir()
    except Exception:  # noqa: BLE001
        gen_dir = os.path.join(config.DATA_DIR, "generated_docs")
    result = {}
    if not os.path.exists(gen_dir):
        return result
    for doc_type in os.listdir(gen_dir):
        type_dir = os.path.join(gen_dir, doc_type)
        if not os.path.isdir(type_dir):
            continue
        files = [f for f in os.listdir(type_dir) if f.endswith(".docx")]
        if files:
            result[doc_type] = sorted(files)
    return result


def _load_index_docs() -> set:
    """从上传文件索引中检测已有的资料类文件（按文件名关键词匹配）。

    v0.1.199：原来读全局 data/index.json——真实部署里文件索引都在
    项目目录（projects/<id>/index.json），全局那个根本不存在，
    这个函数于是恒返回空集，导致「已有资料」永远检测不到。
    """
    idx = {}
    try:
        from . import project_manager as _pm
        p = _pm.get_project_index_path(None)
        if p and os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                idx = json.load(f)
    except Exception:  # noqa: BLE001
        idx = {}
    if not idx:
        # 兜底：旧全局索引（迁移期）
        idx_path = os.path.join(config.DATA_DIR, "index.json")
        if not os.path.exists(idx_path):
            return set()
        try:
            with open(idx_path, encoding="utf-8") as f:
                idx = json.load(f)
        except Exception:  # noqa: BLE001
            return set()
    found = set()
    for info in idx.values():
        if not isinstance(info, dict):
            continue
        fname = info.get("file_name", "")
        for doc_type in docgen.TYPES:
            if doc_type in fname:
                found.add(doc_type)
    return found


def _current_project_ledger() -> tuple:
    """当前项目的设备清单（位号列表, 车间列表），取自项目自己的 index.json。

    v0.1.192：完整性检查的**设备级**与**车间级**两个阶段原来恒报「100% 完成」——
    根因是 _get_devices() / _get_workshops() 只读全局的 spatial_model.json /
    relations_graph.json，而真实部署里这两个文件根本不存在：设备台账是**项目自己的**
    index.json（supervision_integration._project_workshops 读的就是它）。
    结果 devices=[]、workshops=[]，「设备到货」「施工过程」两个阶段的
    total_required 恒为 0，界面直接显示 100% 完成 ——
    一台设备、一个车间都没查过，这是假绿灯。
    实测：真实项目 e75e857c（228 台设备 / 19 个车间）查出来
    「设备到货」required=0、completion=100%，而同一项目的竣工归档统计
    说 228 台设备全部缺件（complete_devices=0）—— 两个接口自相矛盾。
    这里补上项目台账这条取数路径。
    """
    try:
        from . import project_manager as _pm
        try:
            ddir = _pm.get_project_data_dir()
        except TypeError:  # noqa: BLE001
            ddir = _pm.get_project_data_dir(None)
        if not ddir:
            return [], []
        idx_path = os.path.join(ddir, "index.json")
        if not os.path.isfile(idx_path):
            return [], []
        with open(idx_path, "r", encoding="utf-8") as f:
            idx = json.load(f)
        devs = idx.get("devices") or {}
        tags, wss = [], []
        for _k, _d in devs.items():
            _tag, _ws = _k, ""
            if isinstance(_d, dict):
                _tag = _d.get("tag") or _d.get("位号") or _d.get("code") or _k
                _ws = (_d.get("workshop") or "").strip()
            if _tag:
                tags.append(str(_tag))
            if _ws and _ws not in wss:
                wss.append(_ws)
        return tags, sorted(wss)
    except Exception:  # noqa: BLE001
        return [], []


def _get_devices() -> list:
    """从空间模型或关系图谱获取设备列表。

    v0.1.199：路径改走项目隔离（原来读全局 data/spatial_model.json、
    data/relations_graph.json，真实部署里这两个文件不存在，恒走空分支）。
    """
    spatial_path = _scope.path("spatial_model.json")
    if os.path.exists(spatial_path):
        try:
            with open(spatial_path, encoding="utf-8") as f:
                spatial = json.load(f)
            return list(spatial.get("device_index", {}).keys())
        except Exception:  # noqa: BLE001
            pass
    # 回退：从 relations 图谱
    rel_path = _scope.path("relations_graph.json")
    if os.path.exists(rel_path):
        try:
            with open(rel_path, encoding="utf-8") as f:
                rel = json.load(f)
            return [d["tag"] for d in rel.get("devices", [])]
        except Exception:  # noqa: BLE001
            pass
    # v0.1.192：再回退到当前项目的设备台账（真实部署里前面两条路都是空的）。
    _tags, _wss = _current_project_ledger()
    return _tags


def _get_workshops() -> list:
    """从空间模型获取车间列表。

    v0.1.199：路径改走项目隔离。
    """
    spatial_path = _scope.path("spatial_model.json")
    if os.path.exists(spatial_path):
        try:
            with open(spatial_path, encoding="utf-8") as f:
                spatial = json.load(f)
            return list(spatial.get("workshops", {}).keys())
        except Exception:  # noqa: BLE001
            pass
    # v0.1.192：空间模型没有时用当前项目的设备台账推车间
    # （台账里每台设备都带车间，车间列表就是台账里出现过的车间）。
    _tags, _wss = _current_project_ledger()
    return _wss


def check_completeness(phase_filter: str = None) -> dict:
    """检查资料完整性。
    phase_filter: 只检查指定阶段（如"施工准备"），None 检查全部。
    返回 {phases: [...], missing: [...], stats: {...}}。"""
    generated = _load_generated_docs()
    uploaded = _load_index_docs()
    devices = _get_devices()
    workshops = _get_workshops()

    # 已有的资料类型（生成 + 上传）
    existing_types = set(generated.keys()) | uploaded

    phases_result = []
    missing_items = []

    for phase in PHASES:
        if phase_filter and phase["label"] != phase_filter and phase["key"] != phase_filter:
            continue

        phase_missing = []
        phase_existing = []

        # 项目级资料
        for doc_type in phase.get("project_docs", []):
            if doc_type in existing_types:
                phase_existing.append({"type": doc_type, "level": "项目级", "count": len(generated.get(doc_type, [])) or 1})
            else:
                phase_missing.append({"type": doc_type, "level": "项目级", "priority": "高"})

        # 车间级资料（v0.1.39：用 doc_relations 精准判断每个车间）
        for doc_type in phase.get("workshop_docs", []):
            try:
                from . import doc_relations as _dr
                for ws in workshops:
                    if _dr.workshop_has_doc_type(ws, doc_type):
                        phase_existing.append({"type": doc_type, "level": "车间级", "workshop": ws})
                    else:
                        phase_missing.append({"type": doc_type, "level": "车间级", "workshop": ws, "priority": "中"})
            except Exception:  # noqa: BLE001
                if doc_type in existing_types:
                    phase_existing.append({"type": doc_type, "level": "车间级", "count": 1})
                else:
                    for ws in workshops:
                        phase_missing.append({"type": doc_type, "level": "车间级", "workshop": ws, "priority": "中"})

        # 设备级资料（v0.1.39：用 doc_relations 精准判断每台设备）
        for doc_type in phase.get("device_docs", []):
            try:
                from . import doc_relations as _dr
                for dev in devices:
                    if _dr.device_has_doc_type(dev, doc_type):
                        phase_existing.append({"type": doc_type, "level": "设备级", "device": dev})
                    else:
                        phase_missing.append({"type": doc_type, "level": "设备级", "device": dev, "priority": "高"})
            except Exception:  # noqa: BLE001
                if doc_type in existing_types:
                    phase_existing.append({"type": doc_type, "level": "设备级", "count": 1})
                else:
                    for dev in devices:
                        phase_missing.append({"type": doc_type, "level": "设备级", "device": dev, "priority": "高"})

        # 计算完成度
        total = len(phase_existing) + len(phase_missing)
        completion = round(len(phase_existing) / total * 100, 1) if total > 0 else 100.0

        phases_result.append({
            "phase": phase["label"],
            "order": phase["order"],
            "description": phase["description"],
            "existing": phase_existing,
            "missing": phase_missing,
            "completion": completion,
            "total_required": total,
            "completed": len(phase_existing),
        })

        missing_items.extend(phase_missing)

    # 按优先级排序待办
    priority_order = {"高": 0, "中": 1, "低": 2}
    missing_items.sort(key=lambda x: (priority_order.get(x.get("priority", "低"), 3), x.get("type", "")))

    stats = {
        "total_phases": len(phases_result),
        "total_missing": len(missing_items),
        "high_priority": sum(1 for m in missing_items if m.get("priority") == "高"),
        "medium_priority": sum(1 for m in missing_items if m.get("priority") == "中"),
        "devices": len(devices),
        "workshops": len(workshops),
        "generated_doc_types": len(generated),
        "uploaded_doc_types": len(uploaded),
        "overall_completion": round(
            sum(p["completion"] for p in phases_result) / len(phases_result), 1
        ) if phases_result else 100.0,
    }

    return {
        "phases": phases_result,
        "missing": missing_items,
        "stats": stats,
        "generated_docs": {k: len(v) for k, v in generated.items()},
    }


def get_todo_list(limit: int = 50) -> list:
    """获取待补充资料清单（按优先级排序）。"""
    result = check_completeness()
    return result["missing"][:limit]


def get_phase_status() -> list:
    """获取各阶段资料完成状态。"""
    result = check_completeness()
    return [
        {
            "phase": p["phase"],
            "completion": p["completion"],
            "completed": p["completed"],
            "total": p["total_required"],
            "missing_count": len(p["missing"]),
        }
        for p in result["phases"]
    ]
