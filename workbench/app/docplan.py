# 繁工AI 本地解析工作台 - 工程资料生成计划引擎（v0.1.12）
# 依据 v3.7 口径：
#   · 资料生成随项目进度走——现场提供了哪些资料，就做哪些；
#   · 信息不全 → 进入待办，列出缺什么，补充完整后生成；
#   · 按模板生成（优先 Word），可参考解析库已有关联内容自动预填；
#   · 流程认可后人工下载打印签字。
#
# 双输入：① 已解析库 data/index.json（自动判断"库里已有什么、缺什么"）
#        ② 人工新增资料任务 data/docplan_tasks.json（现场进度到哪、手动登记要做的资料）

import os
import json
import datetime

from . import config

TASKS_PATH = None  # 延迟初始化


def _ensure():
    global TASKS_PATH
    if TASKS_PATH is None:
        TASKS_PATH = os.path.join(config.DATA_DIR, "docplan_tasks.json")
        os.makedirs(config.DATA_DIR, exist_ok=True)


# ---------- 1. 文件名校验规则：文件名/类型 → 资料类别 ----------
# 命中任一关键词即认为该文件属于此类别（同名多次上传只计 1 类）
FILE_CLASS_RULES = [
    ("开箱验收", ["开箱", "箱单", "装箱", "到货验收", "开验"]),
    ("隐蔽工程", ["隐蔽", "隐蔽工程"]),
    ("施工计划", ["施工计划", "进度计划", "project", "mpp"]),
    ("施工方案", ["施工方案"]),
    ("吊装方案", ["吊装", "起重", "吊装方案"]),
    ("技术交底", ["交底", "技术交底", "安全交底"]),
    ("施工日志", ["施工日志", "日志", "日报"]),
    ("设计变更", ["变更", "设计变更", "变更单"]),
    ("货损报告", ["货损", "损坏", "破损", "索赔"]),
    ("竣工资料", ["竣工", "验收资料", "移交"]),
    ("设备台账", ["台账", "清单", "箱单资料", "设备表"]),
    ("图纸", ["图纸", "布置图", ".dxf", ".dwg"]),
    ("规范标准", ["gb", "jg", "规范", "标准"]),
]

# ---------- 2. 资料生成计划：每类资料需要哪些前置文件 ----------
# doc_type 为 docgen.TYPES 里的模板类型；None 表示"仅登记，暂不自动生成"
DOC_PLAN = [
    {"key": "开箱验收记录", "doc_type": "开箱验收记录",
     "needs_files": ["设备台账", "开箱验收", "图纸"],
     "desc": "需要：设备台账（核对位号/型号/数量）＋开箱/到货照片或记录＋所在车间图纸"},
    {"key": "施工方案", "doc_type": "施工方案",
     "needs_files": ["施工计划", "图纸", "设备台账"],
     "desc": "需要：施工计划/进度＋车间图纸＋设备台账（确定施工内容与作业面）"},
    {"key": "吊装方案", "doc_type": "吊装方案",
     "needs_files": ["设备台账", "图纸", "吊装方案"],
     "desc": "需要：设备台账（重量/尺寸/位号）＋车间布置图（吊装路径）＋既有吊装方案参考"},
    {"key": "技术交底", "doc_type": "技术交底",
     "needs_files": ["施工方案", "施工日志", "图纸"],
     "desc": "需要：施工方案或图纸为依据，最好有施工日志明确交底节点"},
    {"key": "隐蔽工程验收记录", "doc_type": "隐蔽工程验收记录",
     "needs_files": ["隐蔽工程", "图纸"],
     "desc": "需要：隐蔽工程影像/记录＋所在部位图纸"},
    {"key": "施工日志", "doc_type": "施工日志",
     "needs_files": ["施工日志", "施工计划"],
     "desc": "有现场日志或日报即可登记汇总"},
    {"key": "设计变更", "doc_type": "设计变更",
     "needs_files": ["设计变更", "图纸"],
     "desc": "需要：变更单＋相关图纸（关联原图号与变更内容）"},
    {"key": "货损报告", "doc_type": "货损报告",
     "needs_files": ["货损报告", "设备台账", "开箱验收"],
     "desc": "需要：货损/破损照片记录＋台账（损失设备信息）＋开箱记录（到货状态佐证）"},
    {"key": "竣工资料", "doc_type": "竣工资料",
     "needs_files": ["施工方案", "隐蔽工程", "竣工资料", "设备台账"],
     "desc": "资料集齐度要求最高：方案＋隐蔽＋竣工资料＋台账，按进度最后编制"},
]


def classify_file(file_name: str):
    """按文件名判定资料类别；返回命中类别列表。"""
    name = (file_name or "").lower()
    hits = []
    for label, kws in FILE_CLASS_RULES:
        for kw in kws:
            if kw.lower() in name:
                hits.append(label)
                break
    return hits


def _load_index():
    idx_path = os.path.join(config.DATA_DIR, "index.json")
    if os.path.exists(idx_path):
        try:
            with open(idx_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


# ---------- 3. 资料计划状态：库里已有什么、每类缺什么 ----------
def plan_status():
    """返回每类资料的准备度：ready=齐可生成；partial=缺部分（列出缺什么）；missing=完全没有前置。"""
    _ensure()
    idx = _load_index()
    have_classes = {}
    for info in idx.values():
        if info.get("status") not in ("parsed", "skipped"):
            continue
        for label in classify_file(info.get("file_name", "")):
            have_classes.setdefault(label, 0)
            have_classes[label] += 1

    plans = []
    for p in DOC_PLAN:
        have = [c for c in p["needs_files"] if c in have_classes]
        missing = [c for c in p["needs_files"] if c not in have_classes]
        have_files = sum(have_classes.get(c, 0) for c in have)
        if not p["needs_files"]:
            state = "ready"
        elif not missing:
            state = "ready"
        elif have:
            state = "partial"
        else:
            state = "missing"
        plans.append({
            "key": p["key"], "doc_type": p["doc_type"], "desc": p["desc"],
            "state": state, "have": have, "missing": missing,
            "have_files": have_files,
        })
    return {
        "plans": plans,
        "ready": sum(1 for p in plans if p["state"] == "ready"),
        "partial": sum(1 for p in plans if p["state"] == "partial"),
        "missing": sum(1 for p in plans if p["state"] == "missing"),
        "classes": dict(sorted(have_classes.items(), key=lambda x: -x[1])),
        "checked_at": datetime.datetime.now().isoformat(),
    }


# ---------- 4. 人工资料任务：现场进度登记/待办（缺项补完再生成） ----------
def load_tasks():
    _ensure()
    if os.path.exists(TASKS_PATH):
        try:
            with open(TASKS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return []
    return []


def save_tasks(tasks):
    _ensure()
    with open(TASKS_PATH, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=1)


def add_task(doc_type: str, name: str = "", fields: dict = None, status: str = "待补充"):
    """人工登记要生成的资料任务。status: 待补充/可生成/已完成"""
    tasks = load_tasks()
    task = {
        "id": datetime.datetime.now().strftime("%Y%m%d%H%M%S") + f"-{len(tasks)}",
        "doc_type": doc_type, "name": name or doc_type,
        "fields": fields or {}, "status": status,
        "created_at": datetime.datetime.now().isoformat(),
    }
    tasks.append(task)
    save_tasks(tasks)
    return task


def update_task(task_id: str, patch: dict):
    tasks = load_tasks()
    for t in tasks:
        if t["id"] == task_id:
            for k, v in patch.items():
                t[k] = v
            save_tasks(tasks)
            return t
    return None


def delete_task(task_id: str):
    tasks = load_tasks()
    n = len(tasks)
    tasks = [t for t in tasks if t["id"] != task_id]
    save_tasks(tasks)
    return len(tasks) < n
