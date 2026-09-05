# 繁工AI 本地解析工作台 - FastAPI 主应用
# 启动：python start.py（或双击 run_workbench.bat）
# 访问：http://127.0.0.1:8756

import os
import json
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from . import scanner
from .vector_store import VectorStore
from . import upload_queue

app = FastAPI(title="繁工AI 本地解析工作台", version="0.1.0-mvp")

# 共享扫描状态（单任务）
SCAN_STATUS = {"running": False}
_store = VectorStore()

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
os.makedirs(config.DATA_DIR, exist_ok=True)


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


# ---------- 状态 ----------
@app.get("/api/status")
def status():
    idx = scanner._load_index() if scanner.INDEX_FILE or True else {}
    return {
        "app": "fangong-workbench",
        "version": "0.1.0-mvp",
        "node_name": config.NODE_NAME,
        "scan_running": SCAN_STATUS.get("running", False),
        "parse_switches": {
            "pdf": config.PARSE_PDF, "word": config.PARSE_WORD,
            "excel": config.PARSE_EXCEL, "text": config.PARSE_TEXT,
            "ocr": config.PARSE_IMAGE, "cad": config.PARSE_CAD,
            "project": config.PARSE_PROJECT,
        },
        "vector_count": _store.stats().get("count", 0),
        "queue_pending": upload_queue.pending_count(),
        "indexed_files": len(scanner._load_index()),
        "cloud_endpoint": config.CLOUD_ENDPOINT or "(未配置)",
        "data_dir": config.DATA_DIR,
    }


# ---------- 扫描 ----------
class ScanReq(BaseModel):
    folder: str
    force: bool = False


@app.post("/api/scan")
def start_scan(req: ScanReq):
    if not os.path.isdir(req.folder):
        raise HTTPException(400, f"路径不存在或不可访问：{req.folder}")
    if SCAN_STATUS.get("running"):
        raise HTTPException(409, "已有扫描任务在运行")
    SCAN_STATUS.update({"running": False, "done": 0, "total": 0, "msg": "", "stats": None})
    t = threading.Thread(target=scanner.background_scan, args=(req.folder, req.force, SCAN_STATUS), daemon=True)
    t.start()
    return {"ok": True, "folder": req.folder}


@app.get("/api/scan/status")
def scan_status():
    return {
        "running": SCAN_STATUS.get("running", False),
        "done": SCAN_STATUS.get("done", 0),
        "total": SCAN_STATUS.get("total", 0),
        "msg": SCAN_STATUS.get("msg", ""),
        "stats": SCAN_STATUS.get("stats"),
    }


@app.post("/api/scan/cancel")
def cancel_scan():
    ce = SCAN_STATUS.get("cancel")
    if ce is not None:
        ce.set()
        return {"ok": True}
    return {"ok": False, "msg": "当前没有运行中的扫描"}


# ---------- 结果 ----------
@app.get("/api/results")
def results(status_filter: str = None, limit: int = 200):
    idx = scanner._load_index()
    items = []
    for sha, info in idx.items():
        if status_filter and info.get("status") != status_filter:
            continue
        items.append({"sha256": sha, **info})
    items.sort(key=lambda x: x.get("ts", ""), reverse=True)
    return items[:limit]


@app.get("/api/results/{sha256}")
def result_detail(sha256: str):
    """单个文件解析详情：从本地解析结果缓存读取。"""
    cache_dir = os.path.join(config.DATA_DIR, "parsed_cache")
    path = os.path.join(cache_dir, f"{sha256}.json")
    if not os.path.exists(path):
        raise HTTPException(404, "未找到缓存（重新扫描该文件生成）")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------- 向量检索 ----------
class SearchReq(BaseModel):
    query: str
    top_k: int = 5


@app.post("/api/search")
def search(req: SearchReq):
    try:
        results = _store.search(req.query, top_k=req.top_k)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"检索失败：{e}")
    return {"query": req.query, "results": results}


# ---------- 上传队列 ----------
@app.get("/api/queue")
def queue_list():
    return {"pending": upload_queue.pending_count(), "items": upload_queue.list_pending()}


@app.post("/api/upload")
def do_upload():
    result = upload_queue.upload_all()
    return result


# 静态资源（前端 js/css）
app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


def run():
    import uvicorn
    print("=" * 56)
    print("  繁工AI 本地解析工作台 (MVP)")
    print(f"  访问地址: http://{config.HOST}:{config.PORT}")
    print(f"  数据目录: {config.DATA_DIR}")
    print(f"  解析节点: {config.NODE_NAME}")
    print("=" * 56)
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    run()
