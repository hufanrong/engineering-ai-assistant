"""
v0.1.110：项目数据备份与恢复

支持将项目的所有数据打包为 .fgbak 备份文件，以及从备份文件恢复项目。

v0.1.218：备份范围从「9 项白名单」改为「跟随目录实际内容」
------------------------------------------------------------
原实现维护一份 `BACKUP_ITEMS` 白名单，只含
index.json / relations.json / confirmed_relations.json / rejected_candidates.json /
project_meta.json / parsed_cache / vector_db / uploads / exports。
而一个真实项目的数据目录里有 19 类业务数据（本轮实测，11 个项目）：

  generated_docs     10 个项目共 178 份 docx   ← 最严重，等于"成果不进备份"
  doc_relations.json  10 个项目
  construction_logs.json 9 个项目
  workshop_assign.json / equipment_merge.json / supervision_registry.json /
  file_level.json / upload_log.jsonl / .node_id / volumes/ / upload_queue/ …

后果不是"少打包一个文件"，而是**删除或恢复项目会静默丢数据**：
  · delete_project(backup=True) → backup_before_delete() → export_project()，
    同一条白名单，所以"删除前已自动备份"这句提示给的安全感是假的；
  · import_project() 按 zip 内实际条目解压，备份里没有的永远恢复不出来。
实测（临时 DATA_DIR 造项目 → 导出 → 导入）：
  包内 generated_docs 条目 = 0，导入后 generated_docs 文件数 = 0，
  而 uploads / exports 完好 —— 两条路径都返回 ok:true。

改法：**以目录实际内容为准，不靠白名单**。
  · 打包：遍历项目目录下的每一个条目（文件或目录），全部进包；
  · 只跳过明确的运行期垃圾（__pycache__、*.pyc、*.tmp），
    这样以后新增一类数据目录不需要再回来改清单。
  · BACKUP_ITEMS 仅保留为"兼容旧调用方/旧备份"的参考常量，不再参与打包判定。
"""

import os
import json
import zipfile
import datetime
import shutil
from typing import Optional, Dict, List


# 备份目录
#
# v0.1.240：**改回跟随 config.DATA_DIR**（不再是 `__file__` 推导的安装目录）。
#
# 这是 v0.1.195 修过的同一类缺陷的漏网之鱼：当时把 project_manager 的
# PROJECTS_ROOT / CURRENT_PROJECT_FILE 改成跟随 config.DATA_DIR，理由是
# 「用户把数据目录设到 D:\ 时，业务数据照样往安装目录里写」+「测试切走
# DATA_DIR 做隔离对这条路径静默失效」。BACKUP_DIR 漏改了，后果一模一样：
#
#   ① 用户把数据目录指到 D:\ → 备份仍然落在安装目录 data\backups（可分发部署
#      时安装目录可能不可写，删除前备份会直接失败）；
#   ② 任何「切 DATA_DIR 做隔离」的测试，只要走到 delete_project(backup=True)
#      或 export_project()，就会往**真实** data\backups 里写 .fgbak。实测
#      2026-11-12 07:25：tools/test_delete_sweep.py 在临时 DATA_DIR 里删了
#      3 个自造项目，真实 data/backups 凭空多出 3 个 .fgbak —— 而测试自己的
#      「真实数据未污染」断言正是抓它的那条（S14）。
#
# tools/test_project_backup_complete.py 第 57 行原来是手工写
# `pb.BACKUP_DIR = os.path.join(_TMP_DATA, "backups")` 来绕，等于每个测试都得
# 自己记得补一句；漏补的那次就是上面这 3 个包。现在改成：
#   · backup_dir() 每次现算（config.DATA_DIR 可能在运行时被切）；
#   · 模块级 BACKUP_DIR 由 __getattr__ 现算给出，读到的永远是最新值；
#   · 若调用方**显式赋值** pb.BACKUP_DIR（旧测试的做法），仍然尊重它。
def backup_dir() -> str:
    """备份目录 —— 每次现算，不缓存（config.DATA_DIR 可能在运行时被切）。"""
    override = globals().get("BACKUP_DIR")
    if override:
        return override
    from . import config as _config
    return os.path.join(_config.DATA_DIR, "backups")


def __getattr__(name):
    # 只有模块里**没有**这个属性时才会走到这里；一旦有人显式赋值
    # pb.BACKUP_DIR，就变成普通模块属性、不再进这里。
    if name == "BACKUP_DIR":
        return backup_dir()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# 需要备份的文件和目录
# v0.1.218：**不再作为打包白名单使用**，仅为兼容历史调用方保留。
# 真正打进包里的内容由 iter_project_items() 按目录实际内容决定。
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

# 打包时唯一跳过的东西：运行期垃圾。**不跳过任何业务数据。**
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIX = (".pyc", ".pyo", ".tmp", ".swp", ".lock")


def iter_project_items(project_dir: str):
    """遍历项目目录下需要备份的所有条目，yield (绝对路径或None, zip 内相对路径)。

    v0.1.218：改为"跟随目录实际内容"。只要在项目目录里，就是项目的数据 ——
    generated_docs（生成成果）、doc_relations / construction_logs /
    workshop_assign / equipment_merge / supervision_registry / file_level /
    upload_log / volumes 这些原来全被白名单挡在包外。

    空目录也会以 (None, "dir/") 的形式产出：vector_db 在还没有建索引时就是空的，
    若只打包文件，恢复后这个目录会消失，等于改变了项目结构。
    """
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_root = os.path.relpath(root, project_dir)
        if rel_root != "." and not files and not dirs:
            # 叶子空目录，用 "dir/" 形式记入 zip
            yield None, rel_root.replace(os.sep, "/") + "/"
            continue
        for f in files:
            if f.endswith(SKIP_SUFFIX):
                continue
            fp = os.path.join(root, f)
            if not os.path.isfile(fp):
                continue
            arcname = os.path.relpath(fp, project_dir)
            yield fp, arcname


def _ensure_backup_dir():
    os.makedirs(backup_dir(), exist_ok=True)


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
        output_path = os.path.join(backup_dir(), f"{safe_name}_{timestamp}.fgbak")
    
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
            # v0.1.218：原来是 `for item in BACKUP_ITEMS`（9 项白名单），
            # 于是 generated_docs（生成成果）、doc_relations / construction_logs /
            # workshop_assign / equipment_merge / supervision_registry / file_level /
            # upload_log / volumes 等 10 类业务数据全被挡在包外 ——
            # "删除前已自动备份"实际上保不住成果，恢复后 generated_docs 为 0。
            # 改为按目录实际内容遍历：项目目录里有什么就备份什么，
            # 以后新增一类数据目录也不必再回来改清单。
            for fp, arcname in iter_project_items(project_dir):
                if fp is None:
                    # 空目录：只记目录名，不计数（没有文件）
                    zf.writestr(arcname, b"")
                    continue
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
        # v0.1.218：原来是 `for item in BACKUP_ITEMS`（同一份 9 项白名单）。
        # 两个问题：
        #   ① 白名单清不掉 generated_docs 等 10 类数据 —— 旧的 docx 会残留，
        #      与"覆盖"语义不符（备份里没有的版本还挂在目录里）；
        #   ② 一旦哪天把 generated_docs 加进白名单，旧备份（不含该目录）做覆盖导入
        #      就会先删掉再解不出来 —— 借"恢复"之名删数据。
        # 改为**只清空备份包里确实带了的顶层条目**：包里有就整体替换，
        # 包里没有就原样留着。这样新备份是干净替换，旧备份也不会误删。
        try:
            with zipfile.ZipFile(backup_path, "r") as _zf:
                # v0.1.219：project_meta.json 既不能清掉、也不能写回 ——
                # 它是**目标项目自己**的身份文件（id/name/created_at），
                # 包里的那份属于源项目。若留在这里，覆盖导入会先把它删掉、
                # 然后又因下面"跳过 project_meta.json"而不解出来，
                # 目标项目直接失去 meta → 列表里消失、后续导出报"项目不存在"
                # （本轮实测：B5 用例导出直接 failed，KeyError output_path）。
                _names = [n for n in _zf.namelist()
                          if n != "backup_meta.json" and n != "project_meta.json"]
        except Exception as e:
            return {"ok": False, "error": f"读取备份文件失败：{str(e)}"}
        _tops = {n.split("/")[0] for n in _names if n.strip()}
        for item in _tops:
            item_path = os.path.join(project_dir, item)
            if os.path.isfile(item_path):
                try:
                    os.remove(item_path)
                except Exception:
                    pass
            elif os.path.isdir(item_path):
                try:
                    shutil.rmtree(item_path)
                except Exception:
                    pass
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
                # v0.1.219：project_meta.json 不能照搬。
                # 包里的那份记的是**源项目**的 id/name/created_at：
                #   · 新建模式：目标目录名是新 id，meta 里却是源 id →
                #     /api/projects 列出两条同 id 的项目（实测 11 项里 322fef90 出现两次），
                #     前端下拉两个 option 同 value，用户根本选不中新项目；
                #   · 覆盖模式：会把目标项目自己的 id/name/created_at 一起改掉。
                # 项目身份以目标项目为准，包里的这份只用于取描述类字段（已在
                # backup_meta.json 里带出、创建时已用上），不写盘。
                if name == "project_meta.json":
                    continue
                # 安全检查：防止路径穿越
                if name.startswith("..") or name.startswith("/"):
                    continue
                target_path = os.path.join(project_dir, name)
                if name.endswith("/"):
                    # v0.1.218：空目录条目，只建目录、不写文件
                    os.makedirs(target_path, exist_ok=True)
                    continue
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
            # v0.1.209：原来写
            #   len(idx["files"]) if isinstance(idx["files"], list) else len(idx)
            # 两个分支都不对：
            #  · files 为空列表时（项目初始化后就是这样）取 len(idx) = 顶层键数，
            #    实测 6（files/devices/workshops/一个sha/ledger_skipped_rows/updated_at），
            #    而真实文件只有 1 个 —— 导入项目后统计栏立刻显示错误文件数；
            #  · files 非空时又漏掉扁平 {sha: info} 写入的条目（上传/扫描走的是这条路）。
            # 改为与 /api/status、前端文件列表同一口径。
            try:
                from . import scanner as _sc
                file_count_idx = _sc.count_index_files(idx)
            except Exception:  # noqa: BLE001
                file_count_idx = 0
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
    if os.path.isdir(backup_dir()):
        for f in os.listdir(backup_dir()):
            if f.endswith(".fgbak"):
                fp = os.path.join(backup_dir(), f)
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
        "backup_dir": backup_dir(),
    }


def delete_backup(backup_file: str) -> Dict:
    """删除备份文件。"""
    backup_path = os.path.join(backup_dir(), backup_file)
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
    backup_path = os.path.join(backup_dir(), f"deleted_{safe_name}_{timestamp}.fgbak")
    
    result = export_project(project_id, backup_path)
    if result["ok"]:
        result["message"] = f"删除前已自动备份：{result['output_file']}"
    return result
