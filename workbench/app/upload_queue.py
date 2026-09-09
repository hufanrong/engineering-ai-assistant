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


def _get_data_dir():
    """获取当前项目数据目录。"""
    try:
        from . import project_manager as _pm
        current = _pm.get_current_project()
        if current:
            return _pm.get_project_data_dir(current["id"])
    except Exception:
        pass
    return config.DATA_DIR


def _ensure():
    global QUEUE_DIR, LOG_PATH
    ddir = _get_data_dir()
    QUEUE_DIR = os.path.join(ddir, "upload_queue")
    LOG_PATH = os.path.join(ddir, "upload_log.jsonl")
    # 目录可能被外部删除/移动（如整库迁移、导入合并后继续扫描），每次确保存在
    os.makedirs(QUEUE_DIR, exist_ok=True)


def enqueue(parse_result) -> str:
    """把一个解析结果打包进上传队列，返回包文件名（不含扩展）。
    v0.1.138：payload 附带 project_id/project_name，云端按项目合并（同项目合并，不同项目不合并）。"""
    _ensure()
    proj_id, proj_name = "", ""
    try:
        from . import project_manager as _pm
        cur = _pm.get_current_project()
        if cur:
            proj_id = cur.get("id", "")
            proj_name = cur.get("name", "")
    except Exception:  # noqa: BLE001
        pass
    key = f"{parse_result.sha256[:16]}_{int(time.time()*1000)}"
    pkg = {
        "schema": "fangong-parse-payload-v1",
        "node_name": config.NODE_NAME,
        "node_id": _node_id(),
        "project_id": proj_id,
        "project_name": proj_name,
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
    nf = os.path.join(_get_data_dir(), ".node_id")
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


def tail_logs(n=3) -> list:
    """读取最近 n 条操作日志（含云端上传结果）。"""
    _ensure()
    if not os.path.isfile(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
        return [json.loads(x) for x in lines[-n:]]
    except Exception:  # noqa: BLE001
        return []


def upload_all(packages: list = None, progress_cb=None) -> dict:
    """把队列上传到云端主库；返回 {ok, failed, skipped}。
    packages：可选，指定要上传的包文件名列表（不含 .json），空/None 表示全部。"""
    _ensure()
    if not config.CLOUD_ENDPOINT:
        return {"ok": 0, "failed": 0, "skipped": len(list_pending()),
                "message": "未配置 CLOUD_ENDPOINT，仅保留在本地队列"}
    url = config.CLOUD_ENDPOINT.rstrip("/") + "/api/parse-nodes/payloads"
    # 节点标识已随 payload 的 node_name/node_id 上传，header 只放纯 ASCII 鉴权头
    # （HTTP header 不支持中文，避免 latin-1 编码崩溃）
    headers = {}
    if config.CLOUD_API_KEY:
        headers["Authorization"] = f"Bearer {config.CLOUD_API_KEY}"
    files = [f for f in os.listdir(QUEUE_DIR) if f.endswith(".json")]
    if packages:
        want = {p if p.endswith(".json") else p + ".json" for p in packages}
        files = [f for f in files if f in want]
        if not files:
            return {"ok": 0, "failed": 0, "skipped": 0, "message": "所选文件不在上传队列"}
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
