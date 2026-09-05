# 繁工AI 本地解析工作台 - 云端上传队列
# 解析结果（文件原文 + 解析 JSON）打包到本地 data/upload_queue/ 待命；
# 配置 CLOUD_ENDPOINT 后，可手动/定时上传到云端主库合并（SHA256 去重由云端负责）。
# 上传记录写入 data/upload_log.jsonl，全程留痕。

import os
import json
import time
import shutil
import datetime
import requests

from . import config

QUEUE_DIR = None          # 延迟初始化
LOG_PATH = None


def _ensure():
    global QUEUE_DIR, LOG_PATH
    if QUEUE_DIR is None:
        QUEUE_DIR = os.path.join(config.DATA_DIR, "upload_queue")
        LOG_PATH = os.path.join(config.DATA_DIR, "upload_log.jsonl")
    # 目录可能被外部删除/移动（如整库迁移、导入合并后继续扫描），每次确保存在
    os.makedirs(QUEUE_DIR, exist_ok=True)


def enqueue(parse_result) -> str:
    """把一个解析结果打包进上传队列，返回包文件名（不含扩展）。"""
    _ensure()
    key = f"{parse_result.sha256[:16]}_{int(time.time()*1000)}"
    pkg = {
        "schema": "fangong-parse-payload-v1",
        "node_name": config.NODE_NAME,
        "node_id": _node_id(),
        "created_at": datetime.datetime.now().isoformat(),
        "payload": {
            "file_name": parse_result.file_name,
            "file_size": parse_result.file_size,
            "sha256": parse_result.sha256,
            "ext": parse_result.ext,
            "parser": parse_result.parser,
            "status": parse_result.status,
            "error": parse_result.error,
            "text": parse_result.text,
            "structure": parse_result.structure,
            "entities": parse_result.entities,
            "chunks": parse_result.chunks,
        },
    }
    with open(os.path.join(QUEUE_DIR, f"{key}.json"), "w", encoding="utf-8") as f:
        json.dump(pkg, f, ensure_ascii=False)
    _log("enqueue", key, parse_result.file_name, "ok", None)
    return key


def _node_id() -> str:
    """节点稳定 ID：基于 data/.node_id 持久化。"""
    _ensure()
    nf = os.path.join(config.DATA_DIR, ".node_id")
    if os.path.exists(nf):
        with open(nf) as f:
            return f.read().strip()
    import uuid
    nid = f"{config.NODE_NAME}-{uuid.uuid4().hex[:8]}"
    with open(nf, "w") as f:
        f.write(nid)
    return nid


def pending_count() -> int:
    _ensure()
    return len([f for f in os.listdir(QUEUE_DIR) if f.endswith(".json")])


def list_pending() -> list:
    _ensure()
    out = []
    for f in sorted(os.listdir(QUEUE_DIR)):
        if f.endswith(".json"):
            try:
                with open(os.path.join(QUEUE_DIR, f), encoding="utf-8") as fh:
                    p = json.load(fh)
                out.append({
                    "package": f,
                    "file_name": p["payload"]["file_name"],
                    "sha256": p["payload"]["sha256"],
                    "status": p["payload"]["status"],
                    "created_at": p["created_at"],
                })
            except Exception:  # noqa: BLE001
                continue
    return out


def upload_all(progress_cb=None) -> dict:
    """把队列上传到云端主库；返回 {ok, failed, skipped}。"""
    _ensure()
    if not config.CLOUD_ENDPOINT:
        return {"ok": 0, "failed": 0, "skipped": len(list_pending()),
                "message": "未配置 CLOUD_ENDPOINT，仅保留在本地队列"}
    url = config.CLOUD_ENDPOINT.rstrip("/") + "/api/parse-nodes/payloads"
    headers = {"X-Node-Id": _node_id()}
    if config.CLOUD_API_KEY:
        headers["Authorization"] = f"Bearer {config.CLOUD_API_KEY}"
    files = [f for f in os.listdir(QUEUE_DIR) if f.endswith(".json")]
    ok = failed = 0
    batch = config.UPLOAD_BATCH_SIZE
    for i in range(0, len(files), batch):
        batch_files = files[i:i + batch]
        for fname in batch_files:
            with open(os.path.join(QUEUE_DIR, fname), encoding="utf-8") as fh:
                payload = json.load(fh)
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=60)
                if r.status_code == 200 or r.status_code == 201:
                    os.remove(os.path.join(QUEUE_DIR, fname))
                    ok += 1
                    _log("upload", fname, payload["payload"]["file_name"], "ok", None)
                else:
                    failed += 1
                    _log("upload", fname, payload["payload"]["file_name"], "fail", f"HTTP {r.status_code}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                _log("upload", fname, payload["payload"]["file_name"], "fail", str(e))
            if progress_cb:
                progress_cb(ok + failed, len(files))
    return {"ok": ok, "failed": failed, "skipped": 0, "message": "上传完成"}


def _log(action: str, package: str, file_name: str, result: str, detail: str):
    _ensure()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.datetime.now().isoformat(),
            "action": action, "package": package, "file_name": file_name,
            "result": result, "detail": detail,
        }, ensure_ascii=False) + "\n")
