# 繁工AI 本地解析工作台 - FastAPI 主应用
# 启动：python start.py（或双击 run_workbench.bat）
# 访问：http://127.0.0.1:8756

import os
import json
import threading
from typing import Union, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from . import scanner
from .vector_store import VectorStore
from . import upload_queue
from . import relations
from . import docgen
from parsers.engines import parse_file

app = FastAPI(title="繁工AI 本地解析工作台", version="0.1.7")

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
        "version": app.version,
        "node_name": config.NODE_NAME,
        "scan_running": SCAN_STATUS.get("running", False),
        "parse_switches": {
            "pdf": config.PARSE_PDF, "word": config.PARSE_WORD,
            "excel": config.PARSE_EXCEL, "text": config.PARSE_TEXT,
            "ocr": config.OPTIONAL_READY.get("ocr", False) and (config.AUTO_DETECT_OPTIONAL or config.PARSE_IMAGE),
            "cad": config.OPTIONAL_READY.get("cad", False) and (config.AUTO_DETECT_OPTIONAL or config.PARSE_CAD),
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
    folder: Union[str, List[str]]
    force: bool = False


@app.post("/api/scan")
def start_scan(req: ScanReq):
    folders = [req.folder] if isinstance(req.folder, str) else list(req.folder)
    for f in folders:
        if not os.path.isdir(f):
            raise HTTPException(400, f"路径不存在或不可访问：{f}")
    if SCAN_STATUS.get("running"):
        raise HTTPException(409, "已有扫描任务在运行")
    SCAN_STATUS.update({"running": False, "done": 0, "total": 0, "msg": "", "stats": None})
    t = threading.Thread(target=scanner.background_scan, args=(folders, req.force, SCAN_STATUS), daemon=True)
    t.start()
    return {"ok": True, "folders": folders}


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


@app.post("/api/scan/retry-failed")
def retry_failed():
    """重试全部 failed 文件（人工触发，后台执行）。"""
    if SCAN_STATUS.get("running"):
        raise HTTPException(409, "已有任务在运行")
    SCAN_STATUS.update({"running": False, "done": 0, "total": 0, "msg": "", "stats": None})

    def _run():
        try:
            scanner.retry_failed_files(SCAN_STATUS)
        except Exception as e:  # noqa: BLE001
            SCAN_STATUS.update({"running": False, "msg": f"重试异常: {e}"})

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"ok": True}


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


@app.get("/api/upload/log")
def upload_log(limit: int = 100):
    """上传/打包留痕记录（upload_log.jsonl 尾部）。"""
    log_path = os.path.join(config.DATA_DIR, "upload_log.jsonl")
    if not os.path.exists(log_path):
        return {"items": []}
    lines = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
    return {"items": lines[-limit:]}


@app.post("/api/upload-files")
async def upload_files(files: list[UploadFile] = File(...), uploader: str = Form("")):
    """浏览器/手机端直接上传文件 → 落盘 → 解析 → 向量化 → 上传队列。
    uploader：上传人姓名（手机端场景，非必填）。"""
    import hashlib
    save_dir = os.path.join(config.DATA_DIR, "uploads")
    os.makedirs(save_dir, exist_ok=True)
    results = []
    for f in files:
        try:
            name = os.path.basename(f.filename or "unnamed")
            raw = await f.read()
            if len(raw) > config.MAX_FILE_MB * 1024 * 1024:
                results.append({"file": name, "status": "failed", "error": "超过大小上限"})
                continue
            if not raw:
                results.append({"file": name, "status": "failed", "error": "空文件"})
                continue
            sha = hashlib.sha256(raw).hexdigest()
            saved = os.path.join(save_dir, f"{sha[:12]}_{name}")
            with open(saved, "wb") as fh:
                fh.write(raw)
            res = parse_file(saved)
            if res.status == "parsed" or res.status == "partial":
                _store.index_file(res)
                upload_queue.enqueue(res)
                scanner._save_parsed_cache(res)
            results.append({
                "file": name,
                "status": res.status,
                "parser": res.parser,
                "error": res.error,
                "sha256": res.sha256,
                "entities": len(res.entities),
                "uploader": uploader,
            })
        except Exception as e:  # noqa: BLE001
            results.append({"file": f.filename or "unnamed", "status": "failed", "error": str(e)})
    return {"ok": True, "results": results}


# ---------- 关联图谱（多图纸联动） ----------
@app.get("/api/relations")
def relations_overview():
    """关联图谱总览：车间/图纸/设备统计 + 待人工确认列表。"""
    return relations.load_relations()


@app.post("/api/relations/rebuild")
def relations_rebuild():
    """扫描/上传完成后，重建跨文件关联图谱（后台执行）。"""
    if SCAN_STATUS.get("running"):
        raise HTTPException(409, "扫描进行中，请稍后再重建")
    def _run():
        try:
            relations.build_relations(force=True)
        except Exception as e:  # noqa: BLE001
            print(f"[relations] rebuild error: {e}")
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"ok": True, "msg": "关联图谱重建已开始（后台）"}


@app.get("/api/relations/workshop/{workshop}")
def relations_workshop(workshop: str):
    """单个车间详情：图纸列表 + 设备列表 + 全场图位置 + 车间内设备间距。"""
    g = relations.load_relations()
    ws = next((w for w in g.get("workshops", []) if w["workshop"] == workshop), None)
    if not ws:
        raise HTTPException(404, f"未找到车间：{workshop}")
    devs = [d for d in g.get("devices", []) if workshop in d.get("workshops", [])]
    dists = [r for r in g.get("distances", []) if r.get("workshop") == workshop]
    return {"workshop": ws, "devices": devs, "distances": dists}


@app.get("/api/relations/distances")
def relations_distances(workshop: str = ""):
    """设备间距清单（可选按车间过滤）。口径：同图坐标差 × 标题栏比例 / 1000 = 米。"""
    g = relations.load_relations()
    dists = g.get("distances", [])
    if workshop:
        dists = [r for r in dists if r.get("workshop") == workshop]
    return {"count": len(dists), "distances": dists}


# ---------- 工程资料生成（v0.1.7） ----------
class DocGenReq(BaseModel):
    doc_type: str
    data: dict = {}


@app.get("/api/docgen/types")
def docgen_types():
    """方案类型 + 必填/可选字段清单。"""
    return {"types": docgen.list_types()}


@app.post("/api/docgen/prefill")
def docgen_prefill(workshop: str = "", doc_type: str = ""):
    """从解析库（关联图谱）自动预填：车间设备清单等。"""
    g = relations.load_relations()
    devices = [d for d in g.get("devices", []) if not workshop or workshop in d.get("workshops", [])]
    dev_list = [{"tag": d["tag"], "name": "见台账", "count": 1,
                 "files": d.get("files", [])[:3]} for d in devices[:100]]
    return {"workshop": workshop, "devices": dev_list}


@app.post("/api/docgen/generate")
def docgen_generate(req: DocGenReq):
    """按模板生成 Word。返回 docx 文件下载；缺失必填字段以『待补充』占位并红色标注。"""
    if req.doc_type not in docgen.TYPES:
        raise HTTPException(400, f"未知方案类型：{req.doc_type}")
    try:
        content, missing = docgen.fill_template(req.doc_type, req.data or {})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"生成失败：{e}")
    import io
    from urllib.parse import quote
    fname = f"繁工AI_{req.doc_type}_{datetime_now()}.docx"
    ascii_name = f"fanGongAI_doc_{datetime_now()}.docx"
    return StreamingResponse(io.BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"})


def datetime_now() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y%m%d_%H%M")


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
