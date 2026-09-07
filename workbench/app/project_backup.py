"""
v0.1.110：项目数据备份与恢复

支持将项目的所有数据打包为 .fgbak 备份文件，以及从备份文件恢复项目。
备份内容：index.json、relations.json、parsed_cache/、vector_db/、uploads/、exports/、project_meta.json
"""

import os
import json
import zipfile
import datetime
import shutil
from typing import Optional, Dict, List


# 备份目录
BACKUP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "backups"
)

# 需要备份的文件和目录
BACKUP_ITEMS = [
    "index.json",
    "relations.json",
    "confirmed_relations.json",
    "rejected_candidates.json",
    "project_meta.json",
    "parsed_cache",
    "vector_db",
    "uploads",
    "exports",
]


def _ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)


def export_project(project_id: str, output_path: str = None) -> Dict:
    """
    导出项目数据为 .fgbak 备份文件。
    
    Args:
        project_id: 项目ID
        output_path: 输出文件路径，为None时自动生成到备份目录
    
    Returns:
        导出结果
    """
    from . import project_manager as _pm
    
    project = _pm.get_project(project_id)
    if not project:
        return {"ok": False, "error": f"项目不存在：{project_id}"}
    
    project_dir = _pm.get_project_data_dir(project_id)
    if not os.path.isdir(project_dir):
        return {"ok": False, "error": f"项目数据目录不存在：{project_dir}"}
    
    # 生成输出路径
    if not output_path:
        _ensure_backup_dir()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c for c in project["name"] if c.isalnum() or c in "_-")
        output_path = os.path.join(BACKUP_DIR, f"{safe_name}_{timestamp}.fgbak")
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # 打包
    file_count = 0
    total_size = 0
    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 写入备份元数据
            meta = {
                "backup_version": "1.0",
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "project_id": project_id,
                "project_name": project["name"],
                "project_description": project.get("description", ""),
                "project_client": project.get("client", ""),
                "project_location": project.get("location", ""),
                "original_created_at": project.get("created_at", ""),
            }
            zf.writestr("backup_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
            
            # 写入项目数据
            for item in BACKUP_ITEMS:
                item_path = os.path.join(project_dir, item)
                if os.path.isfile(item_path):
                    zf.write(item_path, item)
                    file_count += 1
                    total_size += os.path.getsize(item_path)
                elif os.path.isdir(item_path):
                    for root, dirs, files in os.walk(item_path):
                        for f in files:
                            fp = os.path.join(root, f)
                            arcname = os.path.relpath(fp, project_dir)
                            zf.write(fp, arcname)
                            file_count += 1
                            total_size += os.path.getsize(fp)
    except Exception as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        return {"ok": False, "error": f"打包失败：{str(e)}"}
    
    backup_size = os.path.getsize(output_path)
    
    return {
        "ok": True,
        "project_id": project_id,
        "project_name": project["name"],
        "output_path": output_path,
        "output_file": os.path.basename(output_path),
        "file_count": file_count,
        "data_size": total_size,
        "backup_size": backup_size,
        "message": f"项目「{project['name']}」已导出为 {os.path.basename(output_path)}（{file_count}个文件，{backup_size/1024:.1f}KB）",
    }


def import_project(backup_path: str, new_project_name: str = None,
                   overwrite_project_id: str = None) -> Dict:
    """
    从备份文件导入项目。
    
    Args:
        backup_path: 备份文件路径（.fgbak）
        new_project_name: 新项目名称，为None时使用备份中的名称
        overwrite_project_id: 覆盖现有项目ID，为None时创建新项目
    
    Returns:
        导入结果
    """
    from . import project_manager as _pm
    
    if not os.path.isfile(backup_path):
        return {"ok": False, "error": f"备份文件不存在：{backup_path}"}
    
    # 读取备份元数据
    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            meta_json = zf.read("backup_meta.json").decode("utf-8")
            meta = json.loads(meta_json)
    except Exception as e:
        return {"ok": False, "error": f"读取备份文件失败：{str(e)}"}
    
    project_name = new_project_name or meta.get("project_name", "导入的项目")
    
    # 确定目标项目
    if overwrite_project_id:
        project = _pm.get_project(overwrite_project_id)
        if not project:
            return {"ok": False, "error": f"要覆盖的项目不存在：{overwrite_project_id}"}
        project_id = overwrite_project_id
        project_dir = _pm.get_project_data_dir(project_id)
        # 清空现有数据
        for item in BACKUP_ITEMS:
            item_path = os.path.join(project_dir, item)
            if os.path.isfile(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
    else:
        # 创建新项目
        result = _pm.create_project(
            name=project_name,
            description=meta.get("project_description", ""),
            client=meta.get("project_client", ""),
            location=meta.get("project_location", ""),
        )
        if not result["ok"]:
            return result
        project_id = result["project"]["id"]
        project_dir = _pm.get_project_data_dir(project_id)
    
    # 解压备份数据到项目目录
    file_count = 0
    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            for name in zf.namelist():
                if name == "backup_meta.json":
                    continue
                # 安全检查：防止路径穿越
                if name.startswith("..") or name.startswith("/"):
                    continue
                target_path = os.path.join(project_dir, name)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with zf.open(name) as src, open(target_path, "wb") as dst:
                    dst.write(src.read())
                file_count += 1
    except Exception as e:
        return {"ok": False, "error": f"解压失败：{str(e)}"}
    
    # 更新项目元数据中的统计
    try:
        idx_path = os.path.join(project_dir, "index.json")
        if os.path.isfile(idx_path):
            with open(idx_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
            file_count_idx = len(idx.get("files", [])) if isinstance(idx.get("files"), list) else len(idx)
            device_count = len(idx.get("devices", {}))
            workshop_count = len(idx.get("workshops", {}))
            _pm.update_project_stats(project_id, file_count_idx, device_count, workshop_count)
    except Exception:
        pass
    
    return {
        "ok": True,
        "project_id": project_id,
        "project_name": project_name,
        "file_count": file_count,
        "mode": "覆盖" if overwrite_project_id else "新建",
        "message": f"项目「{project_name}」已导入（{file_count}个文件），模式：{'覆盖现有项目' if overwrite_project_id else '创建新项目'}",
    }


def list_backups() -> Dict:
    """列出所有备份文件。"""
    _ensure_backup_dir()
    backups = []
    if os.path.isdir(BACKUP_DIR):
        for f in os.listdir(BACKUP_DIR):
            if f.endswith(".fgbak"):
                fp = os.path.join(BACKUP_DIR, f)
                backups.append({
                    "file_name": f,
                    "file_path": fp,
                    "file_size": os.path.getsize(fp),
                    "created_at": datetime.datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M:%S"),
                })
    backups.sort(key=lambda x: x["created_at"], reverse=True)
    return {
        "ok": True,
        "total": len(backups),
        "backups": backups,
        "backup_dir": BACKUP_DIR,
    }


def delete_backup(backup_file: str) -> Dict:
    """删除备份文件。"""
    backup_path = os.path.join(BACKUP_DIR, backup_file)
    if not os.path.isfile(backup_path):
        # 尝试直接用传入的路径
        if os.path.isfile(backup_file):
            backup_path = backup_file
        else:
            return {"ok": False, "error": f"备份文件不存在：{backup_file}"}
    
    os.remove(backup_path)
    return {
        "ok": True,
        "message": f"备份文件 {os.path.basename(backup_path)} 已删除",
    }


def backup_before_delete(project_id: str) -> Dict:
    """
    删除项目前自动备份。
    
    Args:
        project_id: 项目ID
    
    Returns:
        备份结果
    """
    from . import project_manager as _pm
    
    project = _pm.get_project(project_id)
    if not project:
        return {"ok": False, "error": f"项目不存在：{project_id}"}
    
    _ensure_backup_dir()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in project["name"] if c.isalnum() or c in "_-")
    backup_path = os.path.join(BACKUP_DIR, f"deleted_{safe_name}_{timestamp}.fgbak")
    
    result = export_project(project_id, backup_path)
    if result["ok"]:
        result["message"] = f"删除前已自动备份：{result['output_file']}"
    return result
