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
    """加载已生成的资料清单。返回 {doc_type: [file_names]}。"""
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
    """从上传文件索引中检测已有的资料类文件（按文件名关键词匹配）。"""
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
        fname = info.get("file_name", "")
        for doc_type in docgen.TYPES:
            if doc_type in fname:
                found.add(doc_type)
    return found


def _get_devices() -> list:
    """从空间模型或关系图谱获取设备列表。"""
    spatial_path = os.path.join(config.DATA_DIR, "spatial_model.json")
    if os.path.exists(spatial_path):
        try:
            with open(spatial_path, encoding="utf-8") as f:
                spatial = json.load(f)
            return list(spatial.get("device_index", {}).keys())
        except Exception:  # noqa: BLE001
            pass
    # 回退：从 relations 图谱
    rel_path = os.path.join(config.DATA_DIR, "relations_graph.json")
    if os.path.exists(rel_path):
        try:
            with open(rel_path, encoding="utf-8") as f:
                rel = json.load(f)
            return [d["tag"] for d in rel.get("devices", [])]
        except Exception:  # noqa: BLE001
            pass
    return []


def _get_workshops() -> list:
    """从空间模型获取车间列表。"""
    spatial_path = os.path.join(config.DATA_DIR, "spatial_model.json")
    if os.path.exists(spatial_path):
        try:
            with open(spatial_path, encoding="utf-8") as f:
                spatial = json.load(f)
            return list(spatial.get("workshops", {}).keys())
        except Exception:  # noqa: BLE001
            pass
    return []


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
