"""
v0.1.107：项目管理模块

支持新建项目、选择项目、重命名项目、删除项目（可选保留资料）、项目列表。
每个项目的数据存储在独立目录 data/projects/{project_id}/ 下，
包含 index.json、relations.json、向量库、解析缓存等。
"""

from . import atomic_io as _atomic_io
import os
import json
import uuid
import datetime
import shutil
from typing import Optional, List, Dict


# v0.1.195：项目目录必须跟随 config.DATA_DIR，不能再写死安装目录。
# 实测事故：PROJECTS_ROOT / CURRENT_PROJECT_FILE 原来是按 __file__ 推导的
# 模块级常量，config.DATA_DIR 改了它们也不动。后果有两个：
#   ① 用户把数据目录设到 D:\（或装在只读目录）时，项目照样往安装目录里写，
#      「数据目录可配置」对项目管理完全失效 —— 对可分发部署是硬伤；
#   ② tools/test_gb_fallback.py 的 J 段本来用临时 DATA_DIR 起服务、
#      意图不碰真实 data/，但实际上新建的自测项目落进了真实 projects/，
#      还把 current_project.json 指到这个空项目且没还原 → 下次开程序
#      看到的是空的「_j_节自测_xxxx」，同时 E 段（project_id=None 走当前
#      项目）跟着漂移，断言数从 189 变 188。
from . import config as _config

# 项目根目录
PROJECTS_ROOT = os.path.join(_config.DATA_DIR, "projects")

# 当前项目配置文件
CURRENT_PROJECT_FILE = os.path.join(_config.DATA_DIR, "current_project.json")


def _ensure_root():
    """确保项目根目录存在。"""
    os.makedirs(PROJECTS_ROOT, exist_ok=True)


def _get_project_dir(project_id: str) -> str:
    """获取项目数据目录。"""
    return os.path.join(PROJECTS_ROOT, project_id)


def _get_project_meta_path(project_id: str) -> str:
    """获取项目元数据文件路径。"""
    return os.path.join(_get_project_dir(project_id), "project_meta.json")


def create_project(name: str, description: str = "", client: str = "",
                   location: str = "") -> Dict:
    """
    新建项目。
    
    Args:
        name: 项目名称
        description: 项目描述
        client: 建设单位
        location: 项目地点
    
    Returns:
        项目信息
    """
    _ensure_root()
    
    # 检查同名项目
    existing = list_projects()
    for p in existing:
        if p["name"] == name:
            return {"ok": False, "error": f"项目名称已存在：{name}"}
    
    project_id = str(uuid.uuid4())[:8]
    project_dir = _get_project_dir(project_id)
    
    # 创建项目目录结构
    os.makedirs(os.path.join(project_dir, "parsed_cache"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "uploads"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "vector_db"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "exports"), exist_ok=True)
    
    # 写入项目元数据
    meta = {
        "id": project_id,
        "name": name,
        "description": description,
        "client": client,
        "location": location,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "file_count": 0,
        "device_count": 0,
        "workshop_count": 0,
        "status": "active",
    }
    _atomic_io.write_json(_get_project_meta_path(project_id), meta, indent=2)
    
    # 初始化空的 index.json 和 relations.json
    _atomic_io.write_json(os.path.join(project_dir, "index.json"), {"files": [], "devices": {}, "workshops": {}}, indent=2)
    _atomic_io.write_json(os.path.join(project_dir, "relations.json"), {"devices": {}, "workshops": {}, "relations": []}, indent=2)
    
    # 自动设为当前项目
    set_current_project(project_id)
    
    return {
        "ok": True,
        "project": meta,
        "message": f"项目「{name}」创建成功，已自动切换为当前项目",
    }


def list_projects() -> List[Dict]:
    """获取所有项目列表。"""
    _ensure_root()
    projects = []
    if not os.path.exists(PROJECTS_ROOT):
        return projects
    
    for pid in os.listdir(PROJECTS_ROOT):
        meta_path = _get_project_meta_path(pid)
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                projects.append(meta)
            except Exception:
                pass
    
    # 按创建时间倒序
    projects.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return projects


def get_project(project_id: str) -> Optional[Dict]:
    """获取项目信息。"""
    meta_path = _get_project_meta_path(project_id)
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def set_current_project(project_id: str) -> Dict:
    """
    切换当前项目。
    
    Args:
        project_id: 项目ID
    
    Returns:
        切换结果
    """
    project = get_project(project_id)
    if not project:
        return {"ok": False, "error": f"项目不存在：{project_id}"}
    
    os.makedirs(os.path.dirname(CURRENT_PROJECT_FILE), exist_ok=True)
    with open(CURRENT_PROJECT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "project_id": project_id,
            "project_name": project["name"],
            "switched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, f, ensure_ascii=False, indent=2)
    
    return {
        "ok": True,
        "project": project,
        "message": f"已切换到项目「{project['name']}」",
    }


def get_current_project() -> Optional[Dict]:
    """获取当前项目。"""
    if not os.path.isfile(CURRENT_PROJECT_FILE):
        return None
    try:
        with open(CURRENT_PROJECT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return get_project(data.get("project_id", ""))
    except Exception:
        return None


def rename_project(project_id: str, new_name: str) -> Dict:
    """
    v0.1.130：修改已有项目名称。

    Args:
        project_id: 项目ID
        new_name: 新项目名称（非空，且不与现有项目重名）

    Returns:
        更新后的项目信息
    """
    new_name = (new_name or "").strip()
    if not new_name:
        return {"ok": False, "error": "项目名称不能为空"}
    project = get_project(project_id)
    if not project:
        return {"ok": False, "error": f"项目不存在：{project_id}"}

    # 重名校验（排除自身）
    for p in list_projects():
        if p["id"] != project_id and p["name"] == new_name:
            return {"ok": False, "error": f"项目名称已存在：{new_name}"}

    meta_path = _get_project_meta_path(project_id)
    old_name = project.get("name", "")
    project["name"] = new_name
    project["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _atomic_io.write_json(meta_path, project, indent=2)

    return {
        "ok": True,
        "project": project,
        "message": f"项目「{old_name}」已重命名为「{new_name}」",
    }


def _project_has_data(p: Dict) -> bool:
    """项目里是否还有真实资料（文件或设备）。空壳项目返回 False。"""
    try:
        if int(p.get("file_count") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    try:
        return int(p.get("device_count") or 0) > 0
    except (TypeError, ValueError):
        return False


def _pick_successor_project(exclude_id: str) -> Optional[Dict]:
    """v0.1.215：为「即将被删掉的当前项目」挑一个接任者。

    挑法按用户在乎程度排：
      ① 还有资料的项目（file_count / device_count > 0）——那是用户真正的工程；
      ② 其余任何项目（哪怕是空壳）——空壳也比界面显示「未选择项目」强，
         因为后者给人的观感是「我的工程不见了」；
      ③ 一个都没有 → None。这时「未选择项目」是**真实**状态，不是丢数据。

    同级内按 updated_at（缺失则 created_at）倒序，取最近动过的那个。
    这个函数本身只读，不改任何文件。
    """
    cands = []
    try:
        for p in list_projects():
            if not p or p.get("id") == exclude_id:
                continue
            if not isinstance(p, dict):
                continue
            cands.append(p)
    except Exception:  # noqa: BLE001
        return None
    if not cands:
        return None

    def _recency(p):
        return str(p.get("updated_at") or p.get("created_at") or "")

    with_data = [p for p in cands if _project_has_data(p)]
    if with_data:
        with_data.sort(key=_recency, reverse=True)
        return with_data[0]
    cands.sort(key=_recency, reverse=True)
    return cands[0]


def _settle_current_after_delete(successor: Optional[Dict]) -> Dict:
    """v0.1.215：当前项目被删之后，把「当前项目指针」收尾。

    有接任者 → 切过去；没有 → 才移除指针文件。

    为什么必须这么做：原来 delete_project() 只做 os.remove(CURRENT_PROJECT_FILE)，
    删掉当前项目后指针直接消失，用户下次打开看到「当前未选择项目，请先新建或
    选择项目」——等于自己的工程不见了（现场已反馈过一次）。而且这个悬空状态
    还会让自测阶段⑥ 的「在用户原项目上校验」只能报 `目标=?`，全量自测出现 58/1。
    """
    if successor and successor.get("id"):
        try:
            r = set_current_project(successor["id"])
            if r.get("ok"):
                return {
                    "switched_to": {"id": successor["id"],
                                    "name": successor.get("name", "")},
                    "switch_message": f"已自动切换为项目「{successor.get('name', '')}」",
                }
        except Exception:  # noqa: BLE001
            pass
    try:
        if os.path.isfile(CURRENT_PROJECT_FILE):
            os.remove(CURRENT_PROJECT_FILE)
    except Exception:  # noqa: BLE001
        pass
    return {"switched_to": None,
            "switch_message": "已无其它项目，当前项目置空"}


def ensure_current_project() -> Dict:
    """v0.1.215：启动自愈 —— 指针丢了但项目还在时，自动指回一个。

    这是对「打开程序发现自己的工程不见了」这个现场问题的直接补救。

    触发条件严格限定为「指针文件缺失」或「指针指向一个不存在的项目」：
      · 后端没有「取消选择项目」的接口（前端置空只改本地变量，不打后端），
        所以指针消失只有一种成因 —— 删掉当前项目时被连带删掉（v0.1.214 及
        之前的行为），或者用户手工删了文件/迁移过数据目录；
      · 一个项目都没有时不动作，那时「未选择项目」是真实状态。

    返回 {"healed": bool, "project": {...}|None, "message": str}，只读判断 +
    最多一次写指针，幂等。
    """
    _probe = get_current_project()
    if _probe and _probe.get("id"):
        return {"healed": False, "project": _probe, "message": "当前项目正常"}

    # 指针文件存在但读不出有效项目（指向已删 id / JSON 损坏）也走自愈。
    succ = _pick_successor_project("")
    if not succ:
        return {"healed": False, "project": None,
                "message": "无可用项目，保持未选择状态"}
    try:
        r = set_current_project(succ["id"])
    except Exception:  # noqa: BLE001
        return {"healed": False, "project": None, "message": "自愈写入失败"}
    if not r.get("ok"):
        return {"healed": False, "project": None,
                "message": f"自愈失败：{r.get('error') or '未知'}"}
    return {"healed": True, "project": succ,
            "message": f"当前项目指针缺失，已自动恢复为「{succ.get('name', '')}」"}


def delete_project(project_id: str, force: bool = False, backup: bool = True,
                   delete_data: bool = True) -> Dict:
    """
    删除项目。删除前自动备份到 data/backups/ 目录。
    
    Args:
        project_id: 项目ID
        force: 是否强制删除（不确认）
        backup: 是否自动备份（默认True）
    
    Returns:
        删除结果
    """
    project = get_project(project_id)
    if not project:
        return {"ok": False, "error": f"项目不存在：{project_id}"}

    project_dir = _get_project_dir(project_id)

    # v0.1.215：如果是当前项目，**先挑好接任者**，等资料处理完再切指针。
    # 原来这里只有 os.remove(CURRENT_PROJECT_FILE)，删完指针就悬空：
    # 用户下次打开看到「当前未选择项目」，观感是「我的工程不见了」。
    # 判断顺序也很重要：先挑接任者再删目录，否则 list_projects() 里
    # 还混着即将被删的那个（虽然按 id 排除了，但先删会少一次元数据读取）。
    current = get_current_project()
    _is_current = bool(current and current.get("id") == project_id)
    _successor = _pick_successor_project(project_id) if _is_current else None

    if not delete_data:
        # v0.1.130：仅删除项目记录，资料移入回收站保留（可找回）
        recycled_root = os.path.join(
            os.path.dirname(PROJECTS_ROOT), "recycled_projects")
        os.makedirs(recycled_root, exist_ok=True)
        dest = os.path.join(recycled_root, project_id)
        if os.path.exists(dest):
            dest = os.path.join(recycled_root,
                                f"{project_id}_{int(datetime.datetime.now().timestamp())}")
        if os.path.exists(project_dir):
            shutil.move(project_dir, dest)
        _settle = _settle_current_after_delete(_successor) if _is_current else {}
        result = {
            "ok": True,
            "message": f"项目「{project['name']}」已删除（资料已保留）",
            "deleted_id": project_id,
            "recycled_to": dest,
            "data_deleted": False,
        }
        if _is_current:
            result["switched_to"] = _settle.get("switched_to")
            if _settle.get("switch_message"):
                result["message"] += f"（{_settle['switch_message']}）"
        return result

    # 删除项目（含资料）：删除前自动备份
    backup_result = None
    if backup:
        try:
            from . import project_backup as _pb
            backup_result = _pb.backup_before_delete(project_id)
        except Exception:
            pass

    # 删除项目目录
    if os.path.exists(project_dir):
        shutil.rmtree(project_dir)

    result = {
        "ok": True,
        "message": f"项目「{project['name']}」已删除（含项目资料）",
        "deleted_id": project_id,
        "data_deleted": True,
    }
    # v0.1.215：目录删完再切指针 —— 反过来会在「指针指着还没删的目录」那一瞬间
    # 被并发的 /api/projects/current 读到，统计刷新会把已删项目的数带出来。
    if _is_current:
        _settle = _settle_current_after_delete(_successor)
        result["switched_to"] = _settle.get("switched_to")
        if _settle.get("switch_message"):
            result["message"] += f"（{_settle['switch_message']}）"
    if backup_result and backup_result.get("ok"):
        result["backup"] = backup_result
        result["message"] += f"（删除前已自动备份：{backup_result['output_file']}）"
    return result


def update_project_stats(project_id: str, file_count: int = None,
                         device_count: int = None, workshop_count: int = None) -> Dict:
    """更新项目统计信息。"""
    project = get_project(project_id)
    if not project:
        return {"ok": False, "error": f"项目不存在：{project_id}"}
    
    if file_count is not None:
        project["file_count"] = file_count
    if device_count is not None:
        project["device_count"] = device_count
    if workshop_count is not None:
        project["workshop_count"] = workshop_count
    
    project["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    _atomic_io.write_json(_get_project_meta_path(project_id), project, indent=2)
    
    return {"ok": True, "project": project}


def get_project_data_dir(project_id: str = None) -> str:
    """
    获取项目数据目录。
    
    Args:
        project_id: 项目ID，为None时使用当前项目
    
    Returns:
        项目数据目录路径
    """
    if project_id is None:
        current = get_current_project()
        if current:
            project_id = current["id"]
        else:
            # 没有当前项目时，使用默认目录（兼容旧数据）
            default_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data"
            )
            return default_dir
    
    return _get_project_dir(project_id)


def get_project_index_path(project_id: str = None) -> str:
    """获取项目 index.json 路径。"""
    return os.path.join(get_project_data_dir(project_id), "index.json")


def get_project_relations_path(project_id: str = None) -> str:
    """获取项目 relations.json 路径。"""
    return os.path.join(get_project_data_dir(project_id), "relations.json")


def get_project_vector_dir(project_id: str = None) -> str:
    """获取项目向量库目录。"""
    return os.path.join(get_project_data_dir(project_id), "vector_db")


def get_project_cache_dir(project_id: str = None) -> str:
    """获取项目解析缓存目录。"""
    return os.path.join(get_project_data_dir(project_id), "parsed_cache")


def get_project_uploads_dir(project_id: str = None) -> str:
    """获取项目上传目录。"""
    return os.path.join(get_project_data_dir(project_id), "uploads")


def get_project_exports_dir(project_id: str = None) -> str:
    """获取项目导出目录。"""
    return os.path.join(get_project_data_dir(project_id), "exports")
