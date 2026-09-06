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

import datetime

from . import config
from . import scanner
from .vector_store import VectorStore
from . import upload_queue
from . import relations
from . import ai_chat, docgen
from . import packager
from . import platform_store
from . import docplan
from . import archive
from . import voice_transcribe
from . import workshop_assign
from . import device_workshop
from . import tag_alias
from . import version_manager
from . import field_record
from parsers.engines import parse_file

app = FastAPI(title="繁工AI 本地解析工作台", version="0.1.33")

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


@app.get("/api/scan/failed-list")
def scan_failed_list():
    """失败 + 待处理文件清单（v0.1.21）。"""
    return {"items": scanner.list_failed()}


class RetryOneReq(BaseModel):
    sha256: str


class DeleteFailedReq(BaseModel):
    shas: list[str]


@app.post("/api/scan/retry-failed/{sha}")
def retry_failed_one(sha: str):
    """重试单个失败文件（同步执行，返回该文件结果）。"""
    st = scanner.retry_failed_files(shas=[sha])
    return {"stats": st, "target": sha}


@app.post("/api/scan/failed/delete")
def delete_failed(req: DeleteFailedReq):
    return scanner.delete_failed(req.shas)


@app.post("/api/scan/failed/clear")
def clear_failed():
    """清空全部失败/待处理登记。"""
    items = scanner.list_failed()
    return scanner.delete_failed([it["sha256"] for it in items])


@app.post("/api/scan/retry-failed")
def retry_failed():
    """重试全部 failed/pending_manual 文件（人工触发，后台执行）。"""
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
    platform: bool = False   # 同时检索平台级规范库（v0.1.10）


@app.post("/api/search")
def search(req: SearchReq):
    try:
        results = _store.search(req.query, top_k=req.top_k)
        for r in results:
            r["source"] = "project"
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"检索失败：{e}")
    if req.platform:
        try:
            plat = platform_store.search(req.query, top_k=req.top_k)
            idx = platform_store._load_index()
            for r in plat:
                r["source"] = "platform"
                sha = (r.get("meta") or {}).get("sha256", "")
                info = idx.get(sha, {})
                r["std_no"] = info.get("std_no", "")
                r["std_name"] = info.get("std_name", "")
                r["status"] = info.get("status", "")
            results = results + plat
        except Exception as e:  # noqa: BLE001
            results.append({"source": "platform", "error": str(e)})
    return {"query": req.query, "results": results}


# ---------- AI 助手（v0.1.16） ----------
class AiChatReq(BaseModel):
    query: str
    history: list | None = None


@app.get("/api/ai/status")
def ai_status():
    return {"mode": config.AI_MODE,
            "gateway": config.AI_GATEWAY_ENDPOINT or "(未配置)",
            "doc_types": docgen.TYPES}


@app.post("/api/ai/chat")
def ai_chat_api(req: AiChatReq):
    r = ai_chat.chat(req.query, req.history)
    return r


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
            # 去重（v0.1.22）：与解析库 index 比对，已入库则跳过（断点重传/重复选文件夹安全）
            if sha in scanner._load_index():
                results.append({"file": name, "status": "duplicate", "parser": "",
                                "error": "已入库，自动跳过", "sha256": sha, "uploader": uploader})
                continue
            saved = os.path.join(save_dir, f"{sha[:12]}_{name}")
            with open(saved, "wb") as fh:
                fh.write(raw)
            res = parse_file(saved)
            if res.status == "parsed" or res.status == "partial":
                _store.index_file(res)
                upload_queue.enqueue(res)
                scanner._save_parsed_cache(res)
            # 登记索引（供去重/失败管理/统计共用，v0.1.22）
            idx = scanner._load_index()
            idx[res.sha256] = {
                "file_name": res.file_name, "file_path": saved,
                "status": res.status, "parser": res.parser,
                "error": res.error, "entities": len(res.entities),
                "retry_count": 0, "uploader": uploader,
                "ts": datetime.datetime.now().isoformat(),
            }
            scanner._save_index(idx)
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


class ConfirmCandidateReq(BaseModel):
    tag: str
    workshop: str
    note: str = ""


@app.post("/api/relations/confirm-candidate")
def relations_confirm(req: ConfirmCandidateReq):
    """人工确认候选设备（铭牌未在台账）归属车间（v0.1.23）。"""
    if not req.tag.strip() or not req.workshop.strip():
        raise HTTPException(400, "需要位号与车间")
    info = relations.confirm_candidate(req.tag, req.workshop, req.note)
    return {"ok": True, "confirmed": info}


@app.get("/api/relations/drawings")
def relations_drawings():
    """图纸网络：图号/图名/车间/覆盖设备/图纸间互引（v0.1.13）。"""
    g = relations.load_relations()
    return {"items": g.get("drawings", []), "count": len(g.get("drawings", []))}


@app.get("/api/relations/layout")
def relations_layout():
    """设备-车间映射：以设计院图纸（cad）车间为准，台账次之；平票进人工确认（v0.1.13）。"""
    g = relations.load_relations()
    return {"items": g.get("layout", []), "count": len(g.get("layout", [])),
            "confirmed": sum(1 for r in g.get("layout", []) if r.get("confirmed")),
            "need_confirm": sum(1 for r in g.get("layout", []) if r.get("workshop") is None)}


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


class DocPlanTaskReq(BaseModel):
    doc_type: str = ""
    name: str = ""
    fields: dict = None
    status: str = ""


@app.get("/api/docgen/types")
def docgen_types():
    """方案类型 + 必填/可选字段清单。"""
    return {"types": docgen.list_types()}


def _prefill_data(workshop: str = "", doc_type: str = ""):
    """从解析库深度预填：车间设备 + 设备参数 + 规范正文引用 + 缺失字段列出（v0.1.30）。"""
    from . import docgen
    result = docgen.prefill_from_db(doc_type or "施工方案", workshop)
    # 兼容旧字段
    result["workshop"] = workshop
    result["references"] = [{"std_no": c.get("std_no", ""), "std_name": c.get("std_name", ""),
                              "status": c.get("status", "")} for c in result.get("citations", [])]
    return result


class PrefillReq(BaseModel):
    workshop: str = ""
    doc_type: str = ""


@app.post("/api/docgen/prefill")
def docgen_prefill(req: PrefillReq = None, workshop: str = "", doc_type: str = ""):
    """从解析库（关联图谱）自动预填：车间设备清单 + 平台库规范引用（v0.1.12/0.1.18）。支持 JSON body 或 query。"""
    if req is not None:
        workshop, doc_type = req.workshop, req.doc_type
    return _prefill_data(workshop, doc_type)


# ---------- ⑨ 云库（手机端对接，v0.1.14） ----------
def _cloud_base():
    return config.CLOUD_ENDPOINT.rstrip("/") if config.CLOUD_ENDPOINT else ""


def _cloud_headers():
    h = {}
    if config.CLOUD_API_KEY:
        h["Authorization"] = f"Bearer {config.CLOUD_API_KEY}"
    return h


@app.get("/api/cloud/info")
def cloud_info():
    """云库连接状态 + 云端统计 + 现场上传统计。"""
    import requests
    base = _cloud_base()
    if not base:
        return {"connected": False, "endpoint": "", "message": "未配置 CLOUD_ENDPOINT（app/config.py）"}
    try:
        st = requests.get(f"{base}/api/cloud/status", timeout=10).json()
        fl = requests.get(f"{base}/api/cloud/field-list", timeout=10).json()
        return {"connected": True, "endpoint": config.CLOUD_ENDPOINT,
                "cloud_files": st.get("files", 0), "cloud_dir": st.get("dir", ""),
                "field_uploads": fl.get("count", 0)}
    except Exception as e:  # noqa: BLE001
        return {"connected": False, "endpoint": config.CLOUD_ENDPOINT, "message": f"连接失败：{e}"}


@app.get("/api/cloud/field-list")
def cloud_field_list(project: str = "", uploader: str = ""):
    import requests
    base = _cloud_base()
    if not base:
        raise HTTPException(400, "未配置 CLOUD_ENDPOINT")
    r = requests.get(f"{base}/api/cloud/field-list", params={"project": project, "uploader": uploader},
                     headers=_cloud_headers(), timeout=15)
    return r.json()


@app.get("/api/cloud/list-proxy")
def cloud_list_proxy(limit: int = 50):
    """云库文件清单（工作台侧代理）。"""
    import requests
    base = _cloud_base()
    if not base:
        raise HTTPException(400, "未配置 CLOUD_ENDPOINT")
    r = requests.get(f"{base}/api/cloud/list", params={"limit": limit}, headers=_cloud_headers(), timeout=15)
    return r.json()


@app.post("/api/cloud/pull-field")
def cloud_pull_field():
    """把云端现场上传（照片/语音/文字）全部拉取到本地并自动解析入库，手机现场资料进入项目库。"""
    import requests
    base = _cloud_base()
    if not base:
        raise HTTPException(400, "未配置 CLOUD_ENDPOINT")
    fl = requests.get(f"{base}/api/cloud/field-list", headers=_cloud_headers(), timeout=15).json()
    items = fl.get("items", [])
    if not items:
        return {"pulled": 0, "message": "云端暂无现场上传"}
    pull_dir = os.path.join(config.DATA_DIR, "field_pull")
    os.makedirs(pull_dir, exist_ok=True)
    n = 0
    errors = []
    for it in items:
        sha = it.get("sha256")
        try:
            r = requests.get(f"{base}/api/cloud/field-file/{sha}", headers=_cloud_headers(), timeout=60)
            if r.status_code != 200:
                errors.append(f"{it.get('file_name')}: HTTP {r.status_code}")
                continue
            fname = it.get("file_name") or f"field_{sha[:8]}"
            ext = os.path.splitext(fname)[1] or ".bin"
            target = os.path.join(pull_dir, f"{sha[:12]}{ext}")
            with open(target, "wb") as fh:
                fh.write(r.content)
            n += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"{it.get('file_name')}: {e}")
    # v0.1.26：语音文件自动转写 → 现场文字记录入资料库（回写云库供手机端查看）
    transcribe_ok, transcribe_pending = 0, 0
    for it in items:
        fname = it.get("file_name") or ""
        sha = it.get("sha256") or ""
        if not (voice_transcribe.is_voice_file(fname) or it.get("kind") == "voice"):
            continue
        tgt = os.path.join(pull_dir, f"{sha[:12]}{os.path.splitext(fname)[1] or '.bin'}")
        if not os.path.exists(tgt):
            continue
        text, mode = voice_transcribe.transcribe_audio(tgt)
        if text:
            tf = os.path.join(pull_dir, f"语音转写_{sha[:8]}.txt")
            with open(tf, "w", encoding="utf-8") as fh:
                fh.write(f"项目：{it.get('project', '')}\n上传人：{it.get('uploader', '')}\n时间：{it.get('ts', '')}\n语音转写（{mode}）：\n{text}\n")
            transcribe_ok += 1
            try:
                requests.post(f"{base}/api/cloud/field-transcribe",
                              headers=_cloud_headers(),
                              json={"sha256": sha, "text": text, "mode": mode}, timeout=10)
            except Exception:  # noqa: BLE001
                pass
        else:
            transcribe_pending += 1
    # 自动解析入库（幂等去重）
    scan_stat = {}
    if n:
        scan_stat = scanner.scan_folder(pull_dir)
    # v0.1.23：OCR 铭牌摘要回写云端现场记录（手机端清单可见识别结果）
    plate_back = 0
    for cache in os.listdir(os.path.join(config.DATA_DIR, "parsed_cache")):
        if not cache.endswith(".json"):
            continue
        try:
            with open(os.path.join(config.DATA_DIR, "parsed_cache", cache), encoding="utf-8") as f:
                pc = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        if pc.get("parser") == "ocr":
            pl = (pc.get("structure") or {}).get("plate") or {}
            if pl.get("tags") or pl.get("params"):
                try:
                    requests.post(f"{base}/api/cloud/field-plate",
                                  headers=_cloud_headers(),
                                  json={"sha256": pc.get("sha256", ""), "plate": pl}, timeout=10)
                    plate_back += 1
                except Exception:  # noqa: BLE001
                    pass
    return {"pulled": n, "errors": errors[:20],
            "parsed": scan_stat.get("parsed", 0), "duplicate": scan_stat.get("duplicate", 0),
            "failed": scan_stat.get("failed", 0),
            "plate_back": plate_back,
            "voice_transcribed": transcribe_ok,
            "voice_pending": transcribe_pending}


@app.get("/api/docplan/status")
def docplan_status():
    """工程资料生成计划：库里已有什么、每类资料缺什么（缺项进待办补完再生成）。"""
    return docplan.plan_status()


@app.get("/api/docplan/tasks")
def docplan_tasks():
    return {"items": docplan.load_tasks()}


@app.post("/api/docplan/task")
def docplan_task_add(req: DocPlanTaskReq):
    t = docplan.add_task(req.doc_type, req.name or "", req.fields or {}, req.status or "待补充")
    return {"ok": True, "task": t}


@app.post("/api/docplan/task/{task_id}")
def docplan_task_update(task_id: str, req: DocPlanTaskReq):
    patch = {}
    if req.doc_type: patch["doc_type"] = req.doc_type
    if req.name: patch["name"] = req.name
    if req.fields is not None: patch["fields"] = req.fields
    if req.status: patch["status"] = req.status
    t = docplan.update_task(task_id, patch)
    if not t:
        raise HTTPException(404, "任务不存在")
    return {"ok": True, "task": t}


@app.delete("/api/docplan/task/{task_id}")
def docplan_task_delete(task_id: str):
    if not docplan.delete_task(task_id):
        raise HTTPException(404, "任务不存在")
    return {"ok": True}


class DocPlanGenReq(BaseModel):
    doc_type: str
    workshop: str = ""
    fields: dict | None = None


@app.post("/api/docplan/generate")
def docplan_generate(req: DocPlanGenReq):
    """计划页一键生成：解析库预填（车间设备+规范引用）+ 用户补充字段 → 生成 Word 下载（v0.1.18）。"""
    if req.doc_type not in docgen.TYPES:
        raise HTTPException(400, f"未知方案类型：{req.doc_type}")
    pf = _prefill_data(req.workshop, req.doc_type)
    data = {
        "项目名称": "", "施工单位": "", "编制人": "",
        "_devices": [{"tag": d["tag"], "name": d.get("name", "见台账"), "count": 1} for d in pf["devices"][:60]],
    }
    if req.workshop:
        data["车间"] = req.workshop
    if req.fields:
        data.update({k: v for k, v in req.fields.items() if str(v or "").strip()})
    try:
        content, missing = docgen.fill_template(req.doc_type, data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"生成失败：{e}")
    archive._save_generated(req.doc_type, content)  # v0.1.24 生成即存档（组卷来源）
    import io
    from urllib.parse import quote
    fname = f"繁工AI_{req.doc_type}_{datetime_now()}.docx"
    ascii_name = f"fanGongAI_doc_{datetime_now()}.docx"
    return StreamingResponse(io.BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"})


@app.post("/api/docgen/generate")
def docgen_generate(req: DocGenReq):
    """按模板生成 Word。返回 docx 文件下载；缺失必填字段以『待补充』占位并红色标注。"""
    if req.doc_type not in docgen.TYPES:
        raise HTTPException(400, f"未知方案类型：{req.doc_type}")
    try:
        content, missing = docgen.fill_template(req.doc_type, req.data or {})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"生成失败：{e}")
    archive._save_generated(req.doc_type, content)  # v0.1.24 生成即存档（组卷来源）
    import io
    from urllib.parse import quote
    fname = f"繁工AI_{req.doc_type}_{datetime_now()}.docx"
    ascii_name = f"fanGongAI_doc_{datetime_now()}.docx"
    return StreamingResponse(io.BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"})


def datetime_now() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y%m%d_%H%M")


# ---------- 库导出/合并（v0.1.9，多电脑解析合并打底） ----------
@app.get("/api/library/export")
def library_export():
    """导出 .fglib 库包（index + parsed_cache + relations + manifest）。"""
    import io
    from urllib.parse import quote
    content = packager.export_library()
    fname = f"繁工AI_解析库_{datetime_now()}.fglib"
    ascii_name = f"fangong_library_{datetime_now()}.fglib"
    return StreamingResponse(io.BytesIO(content), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(fname)}'})


@app.post("/api/library/import")
async def library_import(file: UploadFile = File(...)):
    """导入 .fglib 库包：SHA256 去重合并，随后重建关联图谱。"""
    raw = await file.read()
    stats = packager.import_library(raw)
    if stats.get("error"):
        raise HTTPException(400, stats["error"])
    return {"ok": True, "stats": stats}


# ---------- 平台级规范库（v0.1.10） ----------

class WorkshopAssignReq(BaseModel):
    sha: str
    workshop: str


class WorkshopBatchReq(BaseModel):
    shas: list
    workshop: str


@app.get("/api/workshop/list")
def workshop_list():
    """车间资料划分：按车间分组 + 未归车间清单（v0.1.27）。"""
    return {"groups": workshop_assign.list_by_workshop()}


@app.post("/api/workshop/assign")
def workshop_assign_one(req: WorkshopAssignReq):
    """单文件人工指定车间（重建图谱后生效）。"""
    if not req.sha.strip() or not req.workshop.strip():
        raise HTTPException(400, "需要 sha 与车间")
    return {"ok": True, "assigned": workshop_assign.manual_assign(req.sha, req.workshop)}


@app.post("/api/workshop/batch-assign")
def workshop_batch_assign(req: WorkshopBatchReq):
    """批量指定车间。"""
    if not req.shas or not req.workshop.strip():
        raise HTTPException(400, "需要 shas 与车间")
    n = workshop_assign.batch_assign(req.shas, req.workshop)
    return {"ok": True, "assigned": n}


@app.post("/api/workshop/re-auto")
def workshop_re_auto():
    """对未归车间的文件重新自动识别。"""
    n = workshop_assign.re_auto_unassigned()
    return {"ok": True, "newly_assigned": n}


class DeviceWorkshopReq(BaseModel):
    tag: str
    workshop: str


@app.get("/api/device-workshop/list")
def device_workshop_list():
    """设备级车间归属列表（v0.1.29）：跨车间箱单设备按台账/位号分到各车间。"""
    return {"devices": device_workshop.list_devices(), "groups": device_workshop.list_by_workshop(),
            "stats": device_workshop.stats()}


@app.post("/api/device-workshop/assign")
def device_workshop_assign(req: DeviceWorkshopReq):
    """人工指定单台设备车间（最高优先，重建图谱后生效）。"""
    if not req.tag.strip() or not req.workshop.strip():
        raise HTTPException(400, "需要 tag 与车间")
    ok = device_workshop.manual_assign(req.tag, req.workshop)
    return {"ok": ok, "tag": req.tag, "workshop": device_workshop.get_workshop(req.tag)}


@app.post("/api/device-workshop/rebuild")
def device_workshop_rebuild():
    """从已解析台账重新提取设备车间归属（不覆盖人工登记）。"""
    from . import relations
    docs = relations._load_docs() if hasattr(relations, "_load_docs") else {}
    if not docs:
        # 从 parsed_cache 重建 docs
        import os as _os, json as _json
        cache_dir = _os.path.join(config.DATA_DIR, "parsed_cache")
        if _os.path.exists(cache_dir):
            for fn in _os.listdir(cache_dir)[:2000]:
                try:
                    with open(_os.path.join(cache_dir, fn), encoding="utf-8") as f:
                        c = _json.load(f)
                    docs[c.get("sha256", fn)] = c
                except Exception:
                    pass
    n = device_workshop.rebuild_from_excel(docs)
    return {"ok": True, "newly_assigned": n, "total": device_workshop.stats()["total"]}


class TagAliasReq(BaseModel):
    primary: str
    alias: str


@app.get("/api/tag-alias/list")
def tag_alias_list():
    """设计院编号↔厂家编号映射列表（v0.1.31）：已确认+待人工确认。"""
    return {"confirmed": tag_alias.list_confirmed(), "pending": tag_alias.list_pending(),
            "stats": tag_alias.stats()}


@app.post("/api/tag-alias/confirm")
def tag_alias_confirm(req: TagAliasReq):
    """人工确认映射（待确认→已确认，重建图谱后生效）。"""
    if not req.primary.strip() or not req.alias.strip():
        raise HTTPException(400, "需要 primary 与 alias")
    ok = tag_alias.confirm(req.primary, req.alias)
    return {"ok": ok, "primary": req.primary, "alias": req.alias}


@app.post("/api/tag-alias/reject")
def tag_alias_reject(req: TagAliasReq):
    """人工拒绝映射（从待确认移除）。"""
    if not req.primary.strip() or not req.alias.strip():
        raise HTTPException(400, "需要 primary 与 alias")
    ok = tag_alias.reject(req.primary, req.alias)
    return {"ok": ok}


class VersionSetLatestReq(BaseModel):
    file_name: str
    sha256: str


@app.get("/api/versions/list")
def versions_list():
    """文件版本对照表（v0.1.32）：多版本文件列表+最新版+冲突标记。"""
    return {"multi_version": version_manager.list_multi_version(),
            "conflicts": version_manager.list_conflicts(),
            "stats": version_manager.stats()}


@app.get("/api/versions/conflicts")
def versions_conflicts():
    """待人工确认的版本冲突列表。"""
    return {"conflicts": version_manager.list_conflicts(),
            "stats": version_manager.stats()}


@app.post("/api/versions/set-latest")
def versions_set_latest(req: VersionSetLatestReq):
    """人工指定某版本为最新版（清除冲突标记）。"""
    if not req.file_name.strip() or not req.sha256.strip():
        raise HTTPException(400, "需要 file_name 与 sha256")
    ok = version_manager.set_latest(req.file_name, req.sha256)
    return {"ok": ok, "file_name": req.file_name, "latest_sha256": req.sha256}


class FieldRecordAnalyzeReq(BaseModel):
    text: str = ""
    ocr_text: str = ""
    transcript: str = ""
    metadata: dict = {}


class FieldRecordGenerateReq(BaseModel):
    doc_type: str
    data: dict = {}


@app.post("/api/field-record/analyze")
def field_record_analyze(req: FieldRecordAnalyzeReq):
    """现场记录快速分析（v0.1.33）：自动识别类型+提取字段+列出缺失。"""
    return field_record.analyze(req.text, req.ocr_text, req.transcript, req.metadata)


@app.post("/api/field-record/generate")
def field_record_generate(req: FieldRecordGenerateReq):
    """生成现场记录 Word。"""
    if not req.doc_type:
        raise HTTPException(400, "需要 doc_type")
    try:
        content, missing = field_record.generate(req.doc_type, req.data or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    import io
    from urllib.parse import quote
    fname = f"繁工AI_{req.doc_type}_{datetime_now()}.docx"
    return StreamingResponse(io.BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             headers={"Content-Disposition": f'attachment; filename="field_record.docx"; filename*=UTF-8''' + quote(fname)})


@app.get("/api/archive/status")
def archive_status():
    """竣工资料组卷状态：每卷已有/缺失、齐全度（v0.1.24）。"""
    return archive.archive_status()


@app.post("/api/archive/export")
def archive_export():
    """按竣工归档卷宗导出 zip（卷目录 + 卷内目录.xlsx + 资料文件）。"""
    import io
    from urllib.parse import quote
    content = archive.export_archive()
    fname = f"繁工AI_竣工资料归档包_{datetime_now()}.zip"
    ascii_name = f"fangong_archive_{datetime_now()}.zip"
    return StreamingResponse(io.BytesIO(content), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(fname)}'})


@app.post("/api/platform/upload")
async def platform_upload(files: list[UploadFile] = File(...)):
    """上传规范/国标文件 → 独立平台库（解析→标准号提取→向量化→台账）。"""
    results = []
    for f in files:
        try:
            raw = await f.read()
            r = platform_store.add_file(raw, f.filename or "unnamed")
            results.append(r)
        except Exception as e:  # noqa: BLE001
            results.append({"file": f.filename, "status": "failed", "error": str(e)})
    return {"ok": True, "results": results}


@app.get("/api/platform/list")
def platform_list():
    return platform_store.list_items()


class PlatformStatusReq(BaseModel):
    sha256: str
    status: str


@app.post("/api/platform/status")
def platform_status(req: PlatformStatusReq):
    r = platform_store.mark_status(req.sha256, req.status)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "操作失败"))
    return r


class PlatformDeleteReq(BaseModel):
    sha256: str


@app.post("/api/platform/delete")
def platform_delete(req: PlatformDeleteReq):
    r = platform_store.delete(req.sha256)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "未找到"))
    return r


class PlatformVerifyReq(BaseModel):
    sha256: str


@app.post("/api/platform/verify")
def platform_verify_one(req: PlatformVerifyReq):
    """立即核验单条规范（v0.1.28）：不等到期，直接多源核验并更新状态。"""
    return platform_store.verify_one(req.sha256)


@app.post("/api/platform/check-expiry")
def platform_check_expiry():
    """到期核验：到 6 个月检查周期的规范标记待核验；配置了联网端点则自动核验替换。"""
    return platform_store.check_expiry()


@app.get("/api/platform/export")
def platform_export():
    """导出平台库包 .fpglib（新电脑安装时导入即可复用）。"""
    import io
    from urllib.parse import quote
    content = platform_store.export_platform()
    fname = f"繁工AI_平台规范库_{datetime_now()}.fpglib"
    ascii_name = f"fangong_platform_{datetime_now()}.fpglib"
    return StreamingResponse(io.BytesIO(content), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(fname)}'})


@app.post("/api/platform/import")
async def platform_import(file: UploadFile = File(...)):
    raw = await file.read()
    stats = platform_store.import_platform(raw)
    if stats.get("error"):
        raise HTTPException(400, stats["error"])
    return {"ok": True, "stats": stats}


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
