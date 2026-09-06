"""
v0.1.59：多电脑并库时竣工资料合并

多台电脑解析的竣工资料合并到一个完整库，支持自动去重、版本冲突处理、
车间冲突处理、合并日志记录、合并后完整性检查。
"""

import os
import json
import hashlib
import shutil
import datetime
from typing import Optional


_MERGE_LOG_FILE = os.path.join("data", "merge_log.json")
_MERGE_PENDING_FILE = os.path.join("data", "merge_pending.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)
    os.makedirs(os.path.join("data", "generated_docs"), exist_ok=True)


def _file_hash(filepath: str) -> str:
    """计算文件MD5哈希用于去重。"""
    h = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _load_merge_log() -> list:
    """加载合并日志。"""
    if os.path.exists(_MERGE_LOG_FILE):
        try:
            with open(_MERGE_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_merge_log(log: list):
    """保存合并日志。"""
    _ensure_dirs()
    with open(_MERGE_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def _load_pending() -> list:
    """加载待人工确认的冲突。"""
    if os.path.exists(_MERGE_PENDING_FILE):
        try:
            with open(_MERGE_PENDING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_pending(pending: list):
    """保存待人工确认的冲突。"""
    _ensure_dirs()
    with open(_MERGE_PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)


def scan_source_folder(source_path: str) -> dict:
    """扫描源文件夹中的竣工资料，统计文件信息。
    
    Args:
        source_path: 源文件夹路径
    
    Returns:
        扫描结果统计
    """
    if not os.path.exists(source_path):
        return {"error": "源文件夹不存在", "path": source_path}
    
    files = []
    for root, dirs, filenames in os.walk(source_path):
        for fn in filenames:
            if fn.endswith((".docx", ".doc", ".xlsx", ".xls", ".pdf", ".txt")):
                filepath = os.path.join(root, fn)
                rel_path = os.path.relpath(filepath, source_path)
                file_hash = _file_hash(filepath)
                files.append({
                    "filename": fn,
                    "rel_path": rel_path,
                    "full_path": filepath,
                    "size": os.path.getsize(filepath),
                    "hash": file_hash,
                    "mtime": datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
                })
    
    # 按类型统计
    type_count = {}
    for f in files:
        ext = os.path.splitext(f["filename"])[1].lower()
        type_count[ext] = type_count.get(ext, 0) + 1
    
    return {
        "source_path": source_path,
        "total_files": len(files),
        "total_size": sum(f["size"] for f in files),
        "type_count": type_count,
        "files": files,
    }


def merge_archive(source_path: str, node_name: str = "unknown",
                  conflict_strategy: str = "latest") -> dict:
    """合并源文件夹中的竣工资料到本地库。
    
    Args:
        source_path: 源文件夹路径
        node_name: 来源节点名称（电脑标识）
        conflict_strategy: 冲突处理策略
            - "latest": 以最新版为准（默认）
            - "keep_existing": 保留现有
            - "manual": 冲突留待人工确认
    
    Returns:
        合并结果
    """
    _ensure_dirs()
    
    # 扫描源文件夹
    scan_result = scan_source_folder(source_path)
    if "error" in scan_result:
        return scan_result
    
    source_files = scan_result["files"]
    target_dir = os.path.join("data", "generated_docs")
    
    # 统计
    merged = 0
    skipped_duplicate = 0
    conflicts = 0
    pending_conflicts = []
    error_files = []
    
    # 加载现有文件哈希索引
    existing_hashes = {}
    existing_files = {}
    for root, dirs, filenames in os.walk(target_dir):
        for fn in filenames:
            filepath = os.path.join(root, fn)
            rel_path = os.path.relpath(filepath, target_dir)
            file_hash = _file_hash(filepath)
            if file_hash:
                existing_hashes[file_hash] = rel_path
            existing_files[rel_path] = {
                "path": filepath,
                "hash": file_hash,
                "mtime": os.path.getmtime(filepath),
            }
    
    # 合并每个文件
    for sf in source_files:
        try:
            # 1. 哈希去重：内容完全相同的文件跳过
            if sf["hash"] and sf["hash"] in existing_hashes:
                skipped_duplicate += 1
                continue
            
            # 2. 路径冲突处理
            target_rel = sf["rel_path"]
            target_path = os.path.join(target_dir, target_rel)
            
            if target_rel in existing_files:
                # 路径冲突
                existing = existing_files[target_rel]
                if conflict_strategy == "latest":
                    # 比较修改时间，新的覆盖旧的
                    source_mtime = datetime.datetime.fromisoformat(sf["mtime"]).timestamp()
                    if source_mtime > existing["mtime"]:
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        shutil.copy2(sf["full_path"], target_path)
                        merged += 1
                        # 更新哈希索引
                        if sf["hash"]:
                            existing_hashes[sf["hash"]] = target_rel
                        existing_files[target_rel]["hash"] = sf["hash"]
                        existing_files[target_rel]["mtime"] = source_mtime
                    else:
                        skipped_duplicate += 1
                elif conflict_strategy == "keep_existing":
                    skipped_duplicate += 1
                elif conflict_strategy == "manual":
                    conflicts += 1
                    pending_conflicts.append({
                        "file": target_rel,
                        "source": sf["full_path"],
                        "existing": existing["path"],
                        "source_mtime": sf["mtime"],
                        "existing_mtime": datetime.datetime.fromtimestamp(existing["mtime"]).isoformat(),
                        "source_hash": sf["hash"],
                        "existing_hash": existing["hash"],
                        "node": node_name,
                        "status": "pending",
                    })
            else:
                # 新文件，直接复制
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copy2(sf["full_path"], target_path)
                merged += 1
                if sf["hash"]:
                    existing_hashes[sf["hash"]] = target_rel
                existing_files[target_rel] = {
                    "path": target_path,
                    "hash": sf["hash"],
                    "mtime": datetime.datetime.fromisoformat(sf["mtime"]).timestamp(),
                }
        except Exception as e:
            error_files.append({"file": sf["filename"], "error": str(e)})
    
    # 保存待人工确认的冲突
    if pending_conflicts:
        all_pending = _load_pending()
        all_pending.extend(pending_conflicts)
        _save_pending(all_pending)
    
    # 记录合并日志
    log_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "source_path": source_path,
        "node_name": node_name,
        "conflict_strategy": conflict_strategy,
        "total_scanned": scan_result["total_files"],
        "merged": merged,
        "skipped_duplicate": skipped_duplicate,
        "conflicts": conflicts,
        "errors": len(error_files),
        "error_files": error_files[:10],
    }
    merge_log = _load_merge_log()
    merge_log.append(log_entry)
    _save_merge_log(merge_log[-100:])  # 保留最近100条
    
    return {
        "ok": True,
        "log": log_entry,
        "pending_count": len(_load_pending()),
    }


def resolve_pending(index: int, decision: str) -> dict:
    """处理待人工确认的冲突。
    
    Args:
        index: 冲突索引
        decision: 决策 - "use_source"（用源文件）/ "keep_existing"（保留现有）/ "skip"（跳过）
    
    Returns:
        处理结果
    """
    pending = _load_pending()
    if index < 0 or index >= len(pending):
        return {"error": "索引超出范围", "total": len(pending)}
    
    item = pending[index]
    
    if decision == "use_source":
        target_path = os.path.join("data", "generated_docs", item["file"])
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copy2(item["source"], target_path)
        result = "已用源文件覆盖"
    elif decision == "keep_existing":
        result = "已保留现有文件"
    elif decision == "skip":
        result = "已跳过"
    else:
        return {"error": "无效决策", "valid_decisions": ["use_source", "keep_existing", "skip"]}
    
    item["status"] = "resolved"
    item["decision"] = decision
    item["result"] = result
    pending[index] = item
    _save_pending(pending)
    
    return {"ok": True, "result": result, "item": item}


def list_pending() -> list:
    """列出待人工确认的冲突。"""
    return _load_pending()


def list_merge_log(limit: int = 20) -> list:
    """列出合并日志。"""
    log = _load_merge_log()
    return log[-limit:]


def merge_stats() -> dict:
    """获取合并统计信息。"""
    log = _load_merge_log()
    pending = _load_pending()
    
    total_merged = sum(entry.get("merged", 0) for entry in log)
    total_skipped = sum(entry.get("skipped_duplicate", 0) for entry in log)
    total_conflicts = sum(entry.get("conflicts", 0) for entry in log)
    
    # 统计当前资料库文件数
    target_dir = os.path.join("data", "generated_docs")
    current_files = 0
    if os.path.exists(target_dir):
        for root, dirs, filenames in os.walk(target_dir):
            current_files += len(filenames)
    
    return {
        "total_merge_operations": len(log),
        "total_files_merged": total_merged,
        "total_files_skipped": total_skipped,
        "total_conflicts": total_conflicts,
        "pending_conflicts": len([p for p in pending if p.get("status") == "pending"]),
        "resolved_conflicts": len([p for p in pending if p.get("status") == "resolved"]),
        "current_archive_files": current_files,
        "last_merge": log[-1] if log else None,
    }
