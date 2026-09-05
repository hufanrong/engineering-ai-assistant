# 繁工AI 本地解析工作台 - 文件夹扫描 + 解析 + 入库 + 上传队列 一体化
# 幂等：按 sha256 记录已处理文件（data/index.json），重复扫描自动跳过，不重复入库。

import os
import json
import threading
import datetime

from . import config
from parsers.engines import parse_file, ParseResult
from .vector_store import VectorStore
from . import upload_queue

INDEX_FILE = None


def _ensure():
    global INDEX_FILE
    if INDEX_FILE is None:
        INDEX_FILE = os.path.join(config.DATA_DIR, "index.json")
        os.makedirs(config.DATA_DIR, exist_ok=True)


def _load_index() -> dict:
    _ensure()
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_index(idx: dict):
    _ensure()
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)


# 支持处理的扩展名集合（含未启用解析的类型，便于状态展示）
SUPPORTED_EXTS = (
    config.EXT_PDF + config.EXT_WORD + config.EXT_EXCEL + config.EXT_TEXT
    + config.EXT_IMAGE + config.EXT_CAD + config.EXT_PROJECT
)


def scan_folder(folder, force: bool = False, progress_cb=None, cancel_event=None) -> dict:
    """扫描一个或多个文件夹，对每个新文件执行：解析 → 结构化入库 → 分块向量化 → 上传队列。
    folder 可为字符串或字符串列表。返回统计。"""
    folders = [folder] if isinstance(folder, str) else list(folder)
    for f in folders:
        if not os.path.isdir(f):
            return {"error": f"路径不存在：{f}"}

    idx = _load_index()
    store = VectorStore()
    stats = {"found": 0, "parsed": 0, "vectorized": 0, "skipped": 0, "failed": 0, "duplicate": 0}

    file_list = []
    for folder in folders:
        for root, _dirs, files in os.walk(folder):
            for fn in sorted(files):
                ext = os.path.splitext(fn)[1].lower()
                if ext in SUPPORTED_EXTS:
                    file_list.append(os.path.join(root, fn))
    stats["found"] = len(file_list)

    for i, path in enumerate(file_list):
        if cancel_event is not None and cancel_event.is_set():
            break
        try:
            if not force:
                import hashlib
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    for block in iter(lambda: f.read(65536), b""):
                        h.update(block)
                key = h.hexdigest()
                if key in idx and idx[key].get("status") == "parsed":
                    stats["duplicate"] += 1
                    if progress_cb:
                        progress_cb(i + 1, len(file_list), f"重复跳过 {os.path.basename(path)}")
                    continue
            else:
                key = None

            size_mb = os.path.getsize(path) / 1024 / 1024
            if size_mb > config.MAX_FILE_MB:
                stats["skipped"] += 1
                if progress_cb:
                    progress_cb(i + 1, len(file_list), f"超限跳过 {os.path.basename(path)}")
                continue

            res: ParseResult = parse_file(path)
            if res.status == "parsed" or res.status == "partial":
                stats["parsed"] += 1
                n = store.index_file(res)
                if n:
                    stats["vectorized"] += 1
                # 无论是否成功向量化都进上传队列（云端合并保留原文+解析）
                upload_queue.enqueue(res)
                _save_parsed_cache(res)
            else:
                stats["skipped" if res.status == "skipped" else "failed"] += 1

            key = key or res.sha256
            idx[key] = {
                "file_name": res.file_name,
                "file_path": path,
                "status": res.status,
                "parser": res.parser,
                "error": res.error,
                "entities": len(res.entities),
                "ts": datetime.datetime.now().isoformat(),
            }
            _save_index(idx)
            if progress_cb:
                progress_cb(i + 1, len(file_list), f"{res.status}: {res.file_name}")
        except Exception as e:  # noqa: BLE001
            stats["failed"] += 1
            if progress_cb:
                progress_cb(i + 1, len(file_list), f"异常 {os.path.basename(path)}: {e}")

    return stats


def _save_parsed_cache(res: ParseResult):
    """把解析结果缓存到 data/parsed_cache/{sha256}.json，供详情页读取。"""
    cache_dir = os.path.join(config.DATA_DIR, "parsed_cache")
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, f"{res.sha256}.json"), "w", encoding="utf-8") as f:
        json.dump({
            "file_name": res.file_name, "file_size": res.file_size,
            "sha256": res.sha256, "ext": res.ext, "parser": res.parser,
            "status": res.status, "error": res.error,
            "text": res.text[:20000], "structure": res.structure,
            "entities": res.entities, "created_at": res.created_at,
        }, f, ensure_ascii=False, indent=1)


def retry_failed_files(status: dict = None) -> dict:
    """从登记里找出 failed 文件，重新解析并入库（供人工点"重试失败"）。"""
    idx = _load_index()
    store = VectorStore()
    targets = [(sha, info) for sha, info in idx.items() if info.get("status") == "failed"]
    stats = {"retried": 0, "recovered": 0, "still_failed": 0, "missing": 0}

    for i, (sha, info) in enumerate(targets):
        path = info.get("file_path")
        if not path or not os.path.exists(path):
            stats["missing"] += 1
            if status is not None:
                status.update({"msg": f"文件已不在原位置: {info.get('file_name')}"})
            continue
        res = parse_file(path)
        if res.status == "parsed" or res.status == "partial":
            store.index_file(res)
            upload_queue.enqueue(res)
            _save_parsed_cache(res)
            stats["recovered"] += 1
            idx[sha] = {
                "file_name": res.file_name, "file_path": path,
                "status": res.status, "parser": res.parser,
                "error": res.error, "entities": len(res.entities),
                "ts": datetime.datetime.now().isoformat(),
            }
        else:
            stats["still_failed"] += 1
            idx[sha] = {**info, "ts": datetime.datetime.now().isoformat()}
        stats["retried"] += 1
        _save_index(idx)
        if status is not None:
            status.update({"done": i + 1, "total": len(targets), "msg": f"重试: {info.get('file_name')}"})
    if status is not None:
        status.update({"running": False, "stats": stats, "msg": "重试完成"})
    return stats


def background_scan(folder, force: bool = False, status: dict = None):
    """后台线程执行扫描（任务线程，不阻塞 API）。status: 共享 dict 用于轮询进度。"""
    cancel = threading.Event()
    if status is not None:
        status["running"] = True
        status["cancel"] = cancel

    def cb(done, total, msg):
        if status is not None:
            status.update({"done": done, "total": total, "msg": msg})

    try:
        stats = scan_folder(folder, force=force, progress_cb=cb, cancel_event=cancel)
        if status is not None:
            status.update({"running": False, "done": stats.get("found", 0), "stats": stats, "msg": "完成"})
    except Exception as e:  # noqa: BLE001
        if status is not None:
            status.update({"running": False, "msg": f"扫描异常: {e}"})
