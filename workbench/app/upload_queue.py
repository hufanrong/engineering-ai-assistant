# 繁工AI 本地解析工作台 - 云端上传队列
# 解析结果（文件原文 + 解析 JSON）打包到本地 data/upload_queue/ 待命；
# 配置 CLOUD_ENDPOINT 后，可手动/定时上传到云端主库合并（SHA256 去重由云端负责）。
# 上传记录写入 data/upload_log.jsonl，全程留痕。

from . import atomic_io as _atomic_io
import os
import json
import time
import shutil
import datetime
import threading
import uuid
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


_ISOLATED_DIR = None   # v0.1.212：非 None 时所有落点都用这个目录（测试/离线隔离）


def _ensure(data_dir=None):
    global QUEUE_DIR, LOG_PATH
    # v0.1.212：允许显式指定数据目录。原来恒走「当前项目」，于是
    # 任何在临时目录里跑的单测/重解析都会把包写进**用户真实项目**的队列 ——
    # 实测事故：tools/test_source_path_fields.py 造的样本
    # 直接进了 322fef90 的待上传队列（pending 变 4），界面上就是 4 个待上传的真文件。
    #
    # 为什么用模块级 _ISOLATED_DIR 而不是「临时改全局再还原」：
    # 第一版就是这么写的（进 enqueue 时把 QUEUE_DIR 指到临时目录、finally 还原），
    # 结果**索引进了临时目录、包文件却进了真实队列** —— 因为 _enqueue_locked
    # 中间会调 _node_id()，而 _node_id() 内部又调了一次 _ensure()，
    # 不带参数就把 QUEUE_DIR 重置回「当前项目」。同一份入队逻辑，
    # 两个落点算出两个目录，又是「同一件事两个答案」。
    # 所以覆盖必须放在 _ensure 这一层，任何内部调用都会尊重它。
    ddir = data_dir or _ISOLATED_DIR or _get_data_dir()
    QUEUE_DIR = os.path.join(ddir, "upload_queue")
    LOG_PATH = os.path.join(ddir, "upload_log.jsonl")
    # 目录可能被外部删除/移动（如整库迁移、导入合并后继续扫描），每次确保存在
    os.makedirs(QUEUE_DIR, exist_ok=True)


_IDX_FILE = "_sha_index.json"


def _idx_path():
    return os.path.join(QUEUE_DIR, _IDX_FILE)


def _load_idx() -> dict:
    """队列内 sha256 索引 {sha: 包名}（v0.1.177）。

    实测事故：上传队列里已有 357 个包时，每上传 1 个文件都要把 357 个 JSON
    全量打开读一遍比对（O(n²)）。用户一次选几百个文件，HTTP 请求就一直在
    事件循环里做同步磁盘 IO —— 端口 8756 在 LISTEN，但 `/` 和 `/api/status`
    全部 30s 超时，整站假死。
    索引损坏/不存在时自动退回全量扫描并重建，不会因为索引丢了就重复入队。
    """
    try:
        with open(_idx_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


# v0.1.198：队列索引与扫描器索引是同一类缺陷，一起修。
#   ① 固定名字的 ".tmp"：两路同时上传/扫描时，A 把 .tmp rename 走了，
#      B 再 rename 就报「不存在」→ 走 except 静默 pass，**索引更新被悄悄丢掉**；
#      Windows 上 A 还持有句柄时 B 直接 PermissionError。
#   ② 原来 except 一律 pass，等于把写盘失败吞掉 —— 用户看不到任何提示，
#      只是发现"队列里明明传了文件，下次扫描又重复入队"。
_IDX_LOCK = threading.RLock()


def _save_idx(idx: dict) -> None:
    """原子写队列索引。临时文件名必须唯一，否则并发写互相踩踏（见上）。"""
    with _IDX_LOCK:
        path = _idx_path()
        tmp = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(idx, f, ensure_ascii=False)
            # v0.1.227：统一走 atomic_io 的重试版 replace（WinError 5 = 被读方占着）
            _atomic_io._replace_with_retry(tmp, path)
        except Exception as _e:  # noqa: BLE001
            # 不再静默：索引写失败会让去重失效、文件重复入队，必须留痕
            try:
                print(f"[upload_queue] 索引写盘失败（去重可能失效）：{_e}")
            except Exception:  # noqa: BLE001
                pass
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass


def _rebuild_idx() -> dict:
    """兜底：索引缺失时全量扫描一次并落盘（只在首次/索引损坏时发生）。"""
    idx = {}
    try:
        for existing in os.listdir(QUEUE_DIR):
            if not existing.endswith(".json") or existing == _IDX_FILE:
                continue
            try:
                with open(os.path.join(QUEUE_DIR, existing), encoding="utf-8") as ef:
                    ep = json.load(ef)
                sha = (ep.get("payload") or {}).get("sha256")
                if sha:
                    idx[sha] = existing[:-5]
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    _save_idx(idx)
    return idx


def enqueue(parse_result, data_dir=None) -> str:
    """把一个解析结果打包进上传队列，返回包文件名（不含扩展）。
    v0.1.138：payload 附带 project_id/project_name，云端按项目合并（同项目合并，不同项目不合并）。
    v0.1.144：按 sha256 去重——队列中已有相同内容的包时跳过（重复解析不重复入队）。
    v0.1.212：新增 data_dir，供临时目录场景（单测、离线重解析）隔离队列。"""
    if data_dir:
        global _ISOLATED_DIR
        with _IDX_LOCK:
            _prev = _ISOLATED_DIR
            try:
                _ISOLATED_DIR = data_dir
                _ensure()
                return _enqueue_locked(parse_result)
            finally:
                _ISOLATED_DIR = _prev
                _ensure()      # 还原后重建真实目录，别留下指向临时目录的全局
    _ensure()
    # v0.1.198：整个「查去重 → 打包落盘 → 更新索引」必须在一把锁里。
    # 原来这三步裸奔，扫描线程与网页上传线程同时入队时：
    #   A 读到 idx（还没有 B 的 sha）→ 落盘 A 的包 → 写回 idx（只有 A）
    #   B 同一时刻也读到同一份 idx → 落盘 B 的包 → 写回 idx（只有 B，A 被覆盖）
    # 结果队列里有两个包（文件都在），但索引只剩 B 的条目 → A 的 sha 去重失效，
    # 下次再扫同一个文件又入队一次，队列无限膨胀。
    # 锁必须是可重入的：_save_idx 内部也要拿同一把锁。
    with _IDX_LOCK:
        return _enqueue_locked(parse_result)


def _enqueue_locked(parse_result) -> str:
    """enqueue 的主体。**调用方必须已持有 _IDX_LOCK。**"""
    # v0.1.144 去重；v0.1.177 改为 O(1) 索引查表（原实现逐包打开读，队列到 357 个时整站假死）
    idx = _load_idx()
    if not idx and os.path.isdir(QUEUE_DIR):
        idx = _rebuild_idx()
    hit = idx.get(parse_result.sha256)
    if hit:
        _log("enqueue_skip", hit, parse_result.file_name, "duplicate", "队列中已存在相同 sha256")
        return hit
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
    _atomic_io.write_json(os.path.join(QUEUE_DIR, f"{key}.json"), pkg, indent=None)
    idx[parse_result.sha256] = key
    _save_idx(idx)
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


def _queue_files() -> list:
    """列出队列里真正的待上传包文件名（已排序）。

    v0.1.208：三个读取点（pending_count / list_pending / upload_all / clear_all）
    原来各自写 `f.endswith(".json")`，把内部索引文件 `_sha_index.json`
    一起算了进去。实测（2026-11-06，项目 322fef90）：
      队列目录实际 = 1 个真包 + _sha_index.json
      pending_count() = 2        （错，多算 1）
      list_pending()  = 1 条     （对）
    同一队列、同一时刻两个接口给出不同答案；WORKbuddy 报告里
    queue_pending: 3 同样是「2 个真包 + 索引」被算成 3。
    更严重的是上传路径：upload_all 会把 _sha_index.json 当包读，
    payload['payload'] 直接 KeyError，被记成「上传失败」——
    用户看到「1 成功 1 失败」，而失败的那一条根本不存在。
    clear_all 也会把索引一起删掉，索引丢失后下次入队全量重建。
    统一走这里，排除以 `_` 开头的内部文件。
    """
    _ensure()
    return sorted(f for f in os.listdir(QUEUE_DIR)
                  if f.endswith(".json") and not f.startswith("_")
                  and f != _IDX_FILE)


def pending_count() -> int:
    _ensure()
    return len(_queue_files())


def list_pending() -> list:
    _ensure()
    out = []
    for f in _queue_files():
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
    files = _queue_files()
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


def clear_all() -> dict:
    """清空上传队列（v0.1.144）。返回 {deleted, message}。
    仅删除队列中的 .json 包文件，不影响已解析入库的数据和 upload_log。

    v0.1.208：原来用 `f.endswith(".json")` 扫目录，会把内部索引
    `_sha_index.json` 一起删掉。索引丢失虽能自动重建，但重建要全量扫队列，
    队列大时正是 v0.1.177 修过的那个 O(n²) 假死场景。改为只删真包。
    """
    _ensure()
    deleted = 0
    for f in _queue_files():
        try:
            os.remove(os.path.join(QUEUE_DIR, f))
            deleted += 1
        except Exception:  # noqa: BLE001
            pass
    _log("clear_queue", "-", "-", "ok", f"清空 {deleted} 个队列包")
    return {"deleted": deleted, "message": f"已清空 {deleted} 个待上传包"}


def remove_packages(packages: list) -> dict:
    """从队列中移除指定包（v0.1.144）。packages 为包文件名列表（不含 .json 也可）。"""
    _ensure()
    want = {p if p.endswith(".json") else p + ".json" for p in (packages or [])}
    want.discard(_IDX_FILE)
    removed = 0
    for f in os.listdir(QUEUE_DIR):
        if f.endswith(".json") and not f.startswith("_") and f in want:
            try:
                os.remove(os.path.join(QUEUE_DIR, f))
                removed += 1
            except Exception:  # noqa: BLE001
                pass
    return {"removed": removed, "message": f"已移除 {removed} 个队列包"}
