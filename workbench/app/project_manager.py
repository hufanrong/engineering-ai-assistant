"""
v0.1.107：项目管理模块

支持新建项目、选择项目、删除项目、项目列表。
每个项目的数据存储在独立目录 data/projects/{project_id}/ 下，
包含 index.json、relations.json、向量库、解析缓存等。
"""

import os
import json
import uuid
import datetime
import shutil
from typing import Optional, List, Dict


# 项目根目录
PROJECTS_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "projects"
)

# 当前项目配置文件
CURRENT_PROJECT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "current_project.json"
)


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
    with open(_get_project_meta_path(project_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    
    # 初始化空的 index.json 和 relations.json
    with open(os.path.join(project_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"files": [], "devices": {}, "workshops": {}}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(project_dir, "relations.json"), "w", encoding="utf-8") as f:
        json.dump({"devices": {}, "workshops": {}, "relations": []}, f, ensure_ascii=False, indent=2)
    
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


def delete_project(project_id: str, force: bool = False, backup: bool = True) -> Dict:
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
    
    # 删除前自动备份
    backup_result = None
    if backup:
        try:
            from . import project_backup as _pb
            backup_result = _pb.backup_before_delete(project_id)
        except Exception:
            pass
    
    project_dir = _get_project_dir(project_id)
    
    # 如果是当前项目，清除当前项目设置
    current = get_current_project()
    if current and current["id"] == project_id:
        if os.path.isfile(CURRENT_PROJECT_FILE):
            os.remove(CURRENT_PROJECT_FILE)
    
    # 删除项目目录
    if os.path.exists(project_dir):
        shutil.rmtree(project_dir)
    
    result = {
        "ok": True,
        "message": f"项目「{project['name']}」已删除",
        "deleted_id": project_id,
    }
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
    
    with open(_get_project_meta_path(project_id), "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)
    
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
