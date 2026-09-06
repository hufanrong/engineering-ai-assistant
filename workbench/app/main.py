# 繁工AI 本地解析工作台 - FastAPI 主应用
# 启动：python start.py（或双击 run_workbench.bat）
# 访问：http://127.0.0.1:8756

import os
import json
import threading
from typing import Union, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body
from fastapi.responses import FileResponse, StreamingResponse, Response
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
from . import chat_parser
from . import spatial_model
from . import completeness_check
from parsers.engines import parse_file

app = FastAPI(title="繁工AI 本地解析工作台", version="0.1.64")

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
def cloud_pull_field(force: bool = False):
    """把云端现场上传（照片/语音/文字）全部拉取到本地并自动解析入库，手机现场资料进入项目库。
    v0.1.40：本地拉取追踪+去重，已拉取过的现场记录跳过（force=true 强制重拉）。"""
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
    # v0.1.40：本地拉取追踪（去重）
    pulled_file = os.path.join(config.DATA_DIR, "field_pulled.json")
    pulled = {}
    if os.path.exists(pulled_file):
        try:
            with open(pulled_file, encoding="utf-8") as pf:
                pulled = json.load(pf)
        except Exception:  # noqa: BLE001
            pulled = {}
    n = 0
    skipped = 0
    errors = []
    for it in items:
        sha = it.get("sha256")
        # v0.1.40：跳过已拉取的记录（除非 force）
        if not force and sha in pulled:
            skipped += 1
            continue
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
            # v0.1.40：登记拉取记录
            pulled[sha] = {
                "file_name": it.get("file_name", ""),
                "project": it.get("project", ""),
                "uploader": it.get("uploader", ""),
                "ts": it.get("ts", ""),
                "kind": it.get("kind", ""),
                "pulled_at": datetime.datetime.now().isoformat(),
                "node": config.NODE_NAME,
            }
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
    # v0.1.37：现场记录自动分析（识别类型+预填字段+缺失提醒），结果回写云库
    record_analyzed = 0
    record_generated = 0
    try:
        from . import field_record as _fr
        for it in items:
            sha = it.get("sha256", "")
            if not sha:
                continue
            # 收集该条记录的文本内容（note + 语音转写 + OCR）
            note = it.get("note", "") or ""
            transcript = it.get("transcript", "") or ""
            ocr_text = ""
            # 从 parsed_cache 找 OCR 结果
            cache_path = os.path.join(config.DATA_DIR, "parsed_cache", f"{sha}.json")
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, encoding="utf-8") as cf:
                        _cache = json.load(cf)
                    if _cache.get("parser") == "ocr":
                        ocr_text = _cache.get("text", "") or ""
                except Exception:  # noqa: BLE001
                    pass
            # 分析
            analysis = _fr.analyze(note, ocr_text, transcript,
                                    metadata={"project": it.get("project", ""),
                                              "uploader": it.get("uploader", ""),
                                              "ts": it.get("ts", "")})
            if analysis.get("doc_type"):
                # 回写云库
                try:
                    requests.post(f"{base}/api/cloud/field-record-result",
                                  headers=_cloud_headers(),
                                  json={"sha256": sha, "record_type": analysis["doc_type"],
                                        "confidence": analysis["confidence"],
                                        "data": analysis["data"],
                                        "missing": analysis["missing"],
                                        "node_name": config.NODE_NAME}, timeout=10)
                    record_analyzed += 1
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass
    # v0.1.40：保存拉取追踪
    try:
        with open(pulled_file, "w", encoding="utf-8") as pf:
            json.dump(pulled, pf, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass
    return {"pulled": n, "skipped": skipped, "errors": errors[:20],
            "parsed": scan_stat.get("parsed", 0), "duplicate": scan_stat.get("duplicate", 0),
            "failed": scan_stat.get("failed", 0),
            "plate_back": plate_back,
            "voice_transcribed": transcribe_ok,
            "voice_pending": transcribe_pending,
            "record_analyzed": record_analyzed,
            "record_generated": record_generated,
            "total_pulled": len(pulled)}


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


class ChatAnalyzeReq(BaseModel):
    file_path: str = ""


@app.post("/api/chat/analyze")
def chat_analyze(req: ChatAnalyzeReq):
    """群聊文件分析（v0.1.34）：解析消息+提取位号/车间/事项+摘要。"""
    if not req.file_path or not os.path.exists(req.file_path):
        raise HTTPException(400, "文件不存在")
    return chat_parser.analyze_chat(req.file_path)


@app.get("/api/chat/candidates")
def chat_candidates():
    """v0.1.43：群聊提及设备候选列表（待人工确认）。"""
    from . import relations as _rel
    candidates = _rel.list_chat_candidates()
    return {"ok": True, "count": len(candidates), "candidates": candidates}


@app.post("/api/chat/candidate/{tag}/confirm")
def chat_candidate_confirm(tag: str, payload: dict = Body(...)):
    """v0.1.43：确认群聊提及设备（加入正式设备图谱）。"""
    from . import relations as _rel
    workshop = payload.get("workshop", "")
    note = payload.get("note", "")
    if not workshop:
        raise HTTPException(400, "需要指定车间")
    result = _rel.confirm_chat_candidate(tag, workshop, note)
    return {"ok": True, "tag": tag, "confirmed": result}


@app.post("/api/chat/candidate/{tag}/reject")
def chat_candidate_reject(tag: str, payload: dict = Body(default={})):
    """v0.1.43：拒绝群聊提及设备（不再提示）。"""
    from . import relations as _rel
    reason = payload.get("reason", "")
    result = _rel.reject_chat_candidate(tag, reason)
    return result


@app.get("/api/chat/rejected")
def chat_rejected():
    """v0.1.43：已拒绝的候选设备列表。"""
    from . import relations as _rel
    return {"ok": True, "items": _rel.list_rejected_candidates()}


@app.get("/api/chat/list")
def chat_list():
    """列出已解析的群聊文件（从 index 中 parser=chat 的文件）。"""
    idx_path = os.path.join(config.DATA_DIR, "index.json")
    if not os.path.exists(idx_path):
        return {"items": []}
    with open(idx_path, encoding="utf-8") as f:
        idx = json.load(f)
    items = []
    for sha, info in idx.items():
        if info.get("parser") == "chat":
            cache_path = os.path.join(config.DATA_DIR, "parsed_cache", f"{sha}.json")
            chat_info = {}
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, encoding="utf-8") as cf:
                        cache = json.load(cf)
                    ch = (cache.get("structure") or {}).get("chat") or {}
                    chat_info = {
                        "message_count": ch.get("message_count", 0),
                        "sender_count": ch.get("sender_count", 0),
                        "tags": ch.get("tags", []),
                        "workshops": ch.get("workshops", []),
                        "topics": ch.get("topics", []),
                    }
                except Exception:  # noqa: BLE001
                    pass
            items.append({"sha256": sha, **info, **chat_info})
    return {"items": items, "count": len(items)}


@app.get("/api/spatial/structure")
def spatial_structure():
    """设备空间结构模型（v0.1.35）：车间→设备层级+坐标+相邻关系。"""
    spatial = spatial_model.load_spatial()
    if not spatial:
        return {"ok": False, "message": "空间模型未构建，请先重建图谱"}
    # 返回精简版（不含完整 cad_positions 避免过大）
    slim = {
        "stats": spatial["stats"],
        "workshops": {},
    }
    for ws_name, ws in spatial["workshops"].items():
        slim["workshops"][ws_name] = {
            "device_count": ws["device_count"],
            "cad_annotated": ws["cad_annotated"],
            "excel_only": ws["excel_only"],
            "pending": ws["pending"],
            "devices": [],
        }
        for tag in ws["devices"]:
            d = spatial["device_index"][tag]
            slim["workshops"][ws_name]["devices"].append({
                "tag": tag, "x": d["x"], "y": d["y"],
                "coord_status": d["coord_status"],
                "sources": d["sources"],
                "neighbors": d["neighbors"][:10],
            })
    return {"ok": True, **slim}


@app.get("/api/spatial/device/{tag}")
def spatial_device(tag: str):
    """单设备空间信息：坐标、车间、相邻设备、来源图纸。"""
    spatial = spatial_model.load_spatial()
    if not spatial:
        raise HTTPException(404, "空间模型未构建")
    dev = spatial["device_index"].get(tag)
    if not dev:
        raise HTTPException(404, f"设备 {tag} 不在空间模型中")
    return dev


@app.get("/api/spatial/workshop/{workshop}")
def spatial_workshop(workshop: str):
    """指定车间设备布局。"""
    spatial = spatial_model.load_spatial()
    if not spatial:
        raise HTTPException(404, "空间模型未构建")
    return spatial_model.get_workshop_layout(spatial, workshop)


@app.get("/api/doc-relations/list")
def doc_relations_list():
    """v0.1.39：所有资料的设备/车间关联列表。"""
    from . import doc_relations as _dr
    return {"ok": True, "stats": _dr.stats(), "docs": _dr.get_all()}


@app.get("/api/doc-relations/device/{tag}")
def doc_relations_device(tag: str):
    """v0.1.39：某台设备关联的所有资料。"""
    from . import doc_relations as _dr
    return {"ok": True, "tag": tag, "docs": _dr.get_by_device(tag)}


@app.get("/api/doc-relations/workshop/{workshop}")
def doc_relations_workshop(workshop: str):
    """v0.1.39：某个车间关联的所有资料。"""
    from . import doc_relations as _dr
    from urllib.parse import unquote
    ws = unquote(workshop)
    return {"ok": True, "workshop": ws, "docs": _dr.get_by_workshop(ws)}


@app.post("/api/doc-relations/scan")
def doc_relations_scan():
    """v0.1.39：扫描所有已生成资料，自动登记关联。"""
    from . import doc_relations as _dr
    n = _dr.scan_generated_docs()
    return {"ok": True, "scanned": n, "stats": _dr.stats()}


@app.get("/api/cloud/field-pulled")
def cloud_field_pulled():
    """v0.1.40：本地已拉取的现场记录清单（去重追踪）。"""
    pulled_file = os.path.join(config.DATA_DIR, "field_pulled.json")
    if not os.path.exists(pulled_file):
        return {"ok": True, "count": 0, "items": []}
    try:
        with open(pulled_file, encoding="utf-8") as f:
            pulled = json.load(f)
        items = [dict(v, sha256=k) for k, v in pulled.items()]
        items.sort(key=lambda x: x.get("pulled_at", ""), reverse=True)
        return {"ok": True, "count": len(items), "items": items[:200]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)}


@app.post("/api/cloud/field-pulled/clear")
def cloud_field_pulled_clear():
    """v0.1.40：清空本地拉取追踪（下次拉取会重新下载所有现场记录）。"""
    pulled_file = os.path.join(config.DATA_DIR, "field_pulled.json")
    if os.path.exists(pulled_file):
        os.remove(pulled_file)
    return {"ok": True, "message": "已清空拉取追踪"}


@app.get("/api/elevation/map")
def elevation_map():
    """v0.1.38：设备标高映射（从台账/CAD/OCR提取的 z 坐标）。"""
    try:
        from . import spatial_model as _sm
        emap = _sm._load_elevation_from_cache()
        return {"ok": True, "count": len(emap), "devices": emap}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)}


@app.post("/api/spatial/device/{tag}/update")
def spatial_device_update(tag: str, payload: dict = Body(...)):
    """v0.1.41：人工更新设备位置（坐标/车间/标高）。"""
    from . import spatial_model as _sm
    result = _sm.update_device_location(
        tag,
        x=payload.get("x"),
        y=payload.get("y"),
        z=payload.get("z"),
        workshop=payload.get("workshop"),
        coord_status=payload.get("coord_status", "人工确认"),
        note=payload.get("note", ""),
    )
    return result


@app.post("/api/spatial/device/{tag}/confirm")
def spatial_device_confirm(tag: str, payload: dict = Body(default={})):
    """v0.1.41：确认设备位置（位置待确认 → 人工确认）。"""
    from . import spatial_model as _sm
    return _sm.confirm_device(tag, workshop=payload.get("workshop"))


@app.post("/api/equipment-merge/run")
def equipment_merge_run():
    """v0.1.45：执行设备台账多版本合并去重。"""
    from . import relations as _rel
    from . import equipment_merge as _em
    g = _rel.load_relations()
    # 构建 docs 带 _cache
    docs = {}
    import os, json as _json
    idx_file = os.path.join("data", "index.json")
    if os.path.exists(idx_file):
        with open(idx_file, encoding="utf-8") as f:
            idx = _json.load(f)
        for sha, info in idx.items():
            cache_file = os.path.join("data", "parsed_cache", f"{sha}.json")
            if os.path.exists(cache_file):
                with open(cache_file, encoding="utf-8") as f:
                    cache = _json.load(f)
                docs[sha] = {"_cache": cache, "file_name": info.get("file_name", "")}
    result = _em.run_merge(docs)
    return {"ok": True, **result}


@app.get("/api/equipment-merge/list")
def equipment_merge_list():
    """v0.1.45：合并后的设备列表。"""
    from . import equipment_merge as _em
    return {"ok": True, "items": _em.get_merged()}


@app.get("/api/equipment-merge/pending")
def equipment_merge_pending():
    """v0.1.45：待人工确认的匹配对。"""
    from . import equipment_merge as _em
    return {"ok": True, "items": _em.get_pending()}


@app.post("/api/equipment-merge/confirm/{index}")
def equipment_merge_confirm(index: int, payload: dict = Body(...)):
    """v0.1.45：人工确认/拒绝待合并项。action: confirm/reject/merge_as_new"""
    from . import equipment_merge as _em
    action = payload.get("action", "confirm")
    canonical_tag = payload.get("canonical_tag", "")
    result = _em.confirm_merge(index, action, canonical_tag)
    return result


@app.post("/api/equipment-merge/resolve-conflict")
def equipment_merge_resolve_conflict(payload: dict = Body(...)):
    """v0.1.45：解决字段冲突。"""
    from . import equipment_merge as _em
    canonical_tag = payload.get("canonical_tag", "")
    field = payload.get("field", "")
    choose = payload.get("choose", "new")
    result = _em.resolve_conflict(canonical_tag, field, choose)
    return result



@app.post("/api/construction-log/aggregate")
def construction_log_aggregate():
    """v0.1.46：按日期汇总现场记录，生成施工日志摘要。"""
    from . import construction_log as _cl
    result = _cl.aggregate_by_date()
    return {"ok": True, "days": len(result), "dates": sorted(result.keys(), reverse=True)}


@app.get("/api/construction-log/list")
def construction_log_list():
    """v0.1.46：列出所有施工日志日期。"""
    from . import construction_log as _cl
    return {"ok": True, "items": _cl.list_logs()}


@app.get("/api/construction-log/{date}")
def construction_log_get(date: str):
    """v0.1.46：获取指定日期的施工日志数据。"""
    from . import construction_log as _cl
    result = _cl.generate_log_data(date)
    return {"ok": True, "date": date, **result}


@app.post("/api/construction-log/{date}/save")
def construction_log_save(date: str, payload: dict = Body(...)):
    """v0.1.46：保存人工修改后的施工日志数据。"""
    from . import construction_log as _cl
    _cl.save_log(date, payload.get("data", {}))
    return {"ok": True, "date": date}


@app.post("/api/construction-log/{date}/generate")
def construction_log_generate(date: str, payload: dict = Body(default={})):
    """v0.1.46：生成指定日期的施工日志Word文件。"""
    from . import construction_log as _cl
    from . import docgen as _dg
    result = _cl.generate_log_data(date,
                                    project_name=payload.get("project_name", ""),
                                    workshop=payload.get("workshop", ""),
                                    extra_data=payload.get("extra_data"))
    data = result["data"]
    saved = _cl.get_log(date)
    if saved.get("status") == "edited":
        data.update(saved.get("data", {}))
    content, missing = _dg.fill_template("施工日志", data)
    fname = "施工日志_" + date + ".docx"
    from urllib.parse import quote as _q
    disp = "attachment; filename=\"construction_log.docx\"; filename*=UTF-8''" + _q(fname)
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": disp})



@app.post("/api/piping/build")
def piping_build():
    """v0.1.47：构建管线网络（从CAD图纸提取管线和连接关系）。"""
    from . import piping_network as _pn
    import os, json as _json
    docs = {}
    idx_file = os.path.join("data", "index.json")
    if os.path.exists(idx_file):
        with open(idx_file, encoding="utf-8") as f:
            idx = _json.load(f)
        for sha, info in idx.items():
            cache_file = os.path.join("data", "parsed_cache", sha + ".json")
            if os.path.exists(cache_file):
                with open(cache_file, encoding="utf-8") as f:
                    cache = _json.load(f)
                docs[sha] = {"_cache": cache, "file_name": info.get("file_name", "")}
    result = _pn.build_piping_network(docs)
    return {"ok": True, "total_pipes": result["total_pipes"],
            "total_connections": result["total_connections"],
            "devices_with_pipes": result["devices_with_pipes"]}


@app.get("/api/piping/pipes")
def piping_pipes():
    """v0.1.47：列出所有管线。"""
    from . import piping_network as _pn
    return {"ok": True, "items": _pn.list_all_pipes()}


@app.get("/api/piping/connections")
def piping_connections():
    """v0.1.47：列出所有设备连接关系。"""
    from . import piping_network as _pn
    return {"ok": True, "items": _pn.list_connections()}


@app.get("/api/piping/device/{tag}")
def piping_device(tag: str):
    """v0.1.47：获取指定设备的管线和连接关系。"""
    from . import piping_network as _pn
    return {"ok": True, "tag": tag,
            "pipes": _pn.get_device_pipes(tag),
            "connections": _pn.get_device_connections(tag)}


@app.get("/api/piping/pipe/{pipe_no}")
def piping_pipe_info(pipe_no: str):
    """v0.1.47：获取指定管线的详细信息。"""
    from . import piping_network as _pn
    info = _pn.get_pipe_info(pipe_no)
    if not info:
        return {"ok": False, "error": "管线不存在"}
    return {"ok": True, **info}



@app.get("/api/archive/status-enhanced")
def archive_status_enhanced_api():
    """v0.1.48：增强版归档状态（多级分类：卷→专业→车间→设备）。"""
    from . import archive as _arch
    return {"ok": True, **_arch.archive_status_enhanced()}


@app.get("/api/archive/catalog")
def archive_catalog(volume_no: str = None):
    """v0.1.48：生成卷内详细目录。"""
    from . import archive as _arch
    rows = _arch.generate_volume_catalog(volume_no)
    return {"ok": True, "rows": rows, "count": len(rows) - 1}


@app.get("/api/archive/completeness")
def archive_completeness_check():
    """v0.1.48：归档完整性检查（与completeness_check联动）。"""
    from . import archive as _arch
    return {"ok": True, **_arch.check_archive_completeness()}


@app.get("/api/archive/export-enhanced")
def archive_export_enhanced():
    """v0.1.48：增强版归档导出（多级文件夹结构）。"""
    from . import archive as _arch
    from urllib.parse import quote
    content = _arch.export_archive_enhanced()
    fname = "繁工AI_竣工资料归档包_增强版.zip"
    disp = "attachment; filename=\"archive_enhanced.zip\"; filename*=UTF-8''" + quote(fname)
    return Response(content=content, media_type="application/zip",
                    headers={"Content-Disposition": disp})


@app.get("/api/construction-log/generate-enhanced")
def construction_log_generate_enhanced(date: str, project_name: str = "", workshop: str = ""):
    """v0.1.54：增强版施工日志生成（含设备数据联动）。"""
    from . import construction_log as _cl
    result = _cl.generate_log_data_enhanced(date, project_name, workshop)
    return {"ok": True, **result}


@app.get("/api/spatial-visualization/svg")
def spatial_visualization_svg(workshop: str = None, eq_type: str = None):
    """v0.1.58：设备安装位置与管线联动SVG图。"""
    from . import spatial_visualization as _sv
    svg = _sv.generate_spatial_svg(workshop, eq_type)
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/api/spatial-visualization/html")
def spatial_visualization_html(workshop: str = None, eq_type: str = None):
    """v0.1.58：设备安装位置与管线联动HTML页面。"""
    from . import spatial_visualization as _sv
    html = _sv.generate_spatial_html(workshop, eq_type)
    return Response(content=html, media_type="text/html")



@app.get("/api/spatial-visualization/elevation/list")
def spatial_visualization_elevation_list():
    """v0.1.61：列出所有标高层。"""
    from . import spatial_visualization as _sv
    return {"ok": True, "elevations": _sv.list_elevations()}


@app.get("/api/spatial-visualization/elevation/layer")
def spatial_visualization_elevation_layer(elevation: float = None,
                                            workshop: str = None,
                                            device_type: str = None):
    """v0.1.61：生成指定标高层的设备位置SVG。"""
    from . import spatial_visualization as _sv
    svg = _sv.generate_elevation_layer_svg(elevation=elevation, workshop=workshop, device_type=device_type)
    return Response(content=svg, media_type="image/svg+xml")



@app.get("/api/spatial-visualization/3d/views")
def spatial_visualization_3d_views():
    """v0.1.62：列出可用三维视角。"""
    from . import spatial_visualization as _sv
    return {"ok": True, "views": _sv.list_views()}


@app.get("/api/spatial-visualization/3d/isometric")
def spatial_visualization_3d_isometric(view: str = "isometric",
                                        workshop: str = None,
                                        device_type: str = None,
                                        show_piping: bool = True):
    """v0.1.62：生成三维等轴测/正交视图SVG。"""
    from . import spatial_visualization as _sv
    svg = _sv.generate_isometric_svg(view=view, workshop=workshop,
                                       device_type=device_type, show_piping=show_piping)
    return Response(content=svg, media_type="image/svg+xml")

@app.get("/api/spatial-visualization/elevation/stack")
def spatial_visualization_elevation_stack(workshop: str = None,
                                           device_type: str = None):
    """v0.1.61：生成分层堆叠视图。"""
    from . import spatial_visualization as _sv
    svg = _sv.generate_elevation_stack_svg(workshop=workshop, device_type=device_type)
    return Response(content=svg, media_type="image/svg+xml")

@app.get("/api/spatial-visualization/stats")
def spatial_visualization_stats():
    """v0.1.58：可视化统计信息。"""
    from . import spatial_visualization as _sv
    return {"ok": True, **_sv.get_stats()}


@app.post("/api/archive-merge/scan")
def archive_merge_scan(body: dict):
    """v0.1.59：扫描源文件夹中的竣工资料。"""
    from . import archive_merge as _am
    source_path = body.get("source_path", "")
    if not source_path:
        raise HTTPException(status_code=400, detail="缺少source_path")
    return {"ok": True, **_am.scan_source_folder(source_path)}


@app.post("/api/archive-merge/merge")
def archive_merge_merge(body: dict):
    """v0.1.59：合并源文件夹中的竣工资料到本地库。"""
    from . import archive_merge as _am
    source_path = body.get("source_path", "")
    node_name = body.get("node_name", "unknown")
    conflict_strategy = body.get("conflict_strategy", "latest")
    if not source_path:
        raise HTTPException(status_code=400, detail="缺少source_path")
    return {"ok": True, **_am.merge_archive(source_path, node_name, conflict_strategy)}


@app.get("/api/archive-merge/pending")
def archive_merge_pending():
    """v0.1.59：列出待人工确认的冲突。"""
    from . import archive_merge as _am
    return {"ok": True, "pending": _am.list_pending()}


@app.post("/api/archive-merge/resolve")
def archive_merge_resolve(body: dict):
    """v0.1.59：处理待人工确认的冲突。"""
    from . import archive_merge as _am
    index = body.get("index", -1)
    decision = body.get("decision", "")
    return {"ok": True, **_am.resolve_pending(index, decision)}


@app.get("/api/archive-merge/log")
def archive_merge_log(limit: int = 20):
    """v0.1.59：列出合并日志。"""
    from . import archive_merge as _am
    return {"ok": True, "log": _am.list_merge_log(limit)}



@app.post("/api/relations-merge/merge")
def relations_merge_merge(body: dict):
    """v0.1.63：合并源关系图谱到本地。"""
    from . import relations_merge as _rm
    source_relations = body.get("source_relations", {})
    node_name = body.get("node_name", "unknown")
    conflict_strategy = body.get("conflict_strategy", "latest")
    if not source_relations:
        raise HTTPException(status_code=400, detail="缺少source_relations")
    return {"ok": True, **_rm.merge_relations(source_relations, node_name, conflict_strategy)}


@app.post("/api/relations-merge/merge-file")
def relations_merge_merge_file(body: dict):
    """v0.1.63：从JSON文件合并关系图谱。"""
    from . import relations_merge as _rm
    filepath = body.get("filepath", "")
    node_name = body.get("node_name", "unknown")
    conflict_strategy = body.get("conflict_strategy", "latest")
    if not filepath:
        raise HTTPException(status_code=400, detail="缺少filepath")
    source = _rm.load_relations_from_file(filepath)
    if "error" in source:
        return {"ok": False, **source}
    return {"ok": True, **_rm.merge_relations(source, node_name, conflict_strategy)}


@app.get("/api/relations-merge/pending")
def relations_merge_pending():
    """v0.1.63：列出待人工确认的冲突。"""
    from . import relations_merge as _rm
    return {"ok": True, "pending": _rm.list_pending()}


@app.post("/api/relations-merge/resolve")
def relations_merge_resolve(body: dict):
    """v0.1.63：处理待人工确认的冲突。"""
    from . import relations_merge as _rm
    index = body.get("index", -1)
    decision = body.get("decision", "")
    return {"ok": True, **_rm.resolve_pending(index, decision)}


@app.get("/api/relations-merge/log")
def relations_merge_log(limit: int = 20):
    """v0.1.63：列出合并日志。"""
    from . import relations_merge as _rm
    return {"ok": True, "log": _rm.list_merge_log(limit)}


@app.get("/api/relations-merge/stats")
def relations_merge_stats():
    """v0.1.63：合并统计信息。"""
    from . import relations_merge as _rm
    return {"ok": True, **_rm.merge_stats()}



@app.post("/api/construction-schedule/auto")
def construction_schedule_auto(body: dict):
    """v0.1.64：根据设备位置自动安排施工顺序。"""
    from . import construction_schedule as _cs
    start_date = body.get("start_date")
    days_per_device = body.get("days_per_device", 2)
    workshop_parallel = body.get("workshop_parallel", 1)
    return {"ok": True, **_cs.auto_schedule_devices(start_date, days_per_device, workshop_parallel)}


@app.get("/api/construction-schedule/gantt")
def construction_schedule_gantt(workshop: str = None):
    """v0.1.64：生成施工进度甘特图SVG。"""
    from . import construction_schedule as _cs
    svg = _cs.generate_gantt_svg(workshop=workshop)
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/api/construction-schedule/stats")
def construction_schedule_stats():
    """v0.1.64：获取施工进度统计。"""
    from . import construction_schedule as _cs
    return {"ok": True, **_cs.get_schedule_stats()}


@app.post("/api/construction-schedule/status")
def construction_schedule_status(body: dict):
    """v0.1.64：更新设备施工状态。"""
    from . import construction_schedule as _cs
    tag = body.get("tag", "")
    status = body.get("status", "")
    notes = body.get("notes", "")
    if not tag or not status:
        raise HTTPException(status_code=400, detail="缺少tag或status")
    return {"ok": True, **_cs.update_device_status(tag, status, notes)}


@app.get("/api/construction-schedule/status")
def construction_schedule_get_status(tag: str = None):
    """v0.1.64：获取设备施工状态。"""
    from . import construction_schedule as _cs
    return {"ok": True, **_cs.get_device_status(tag)}


@app.get("/api/construction-schedule/workshops")
def construction_schedule_workshops():
    """v0.1.64：列出施工进度中的车间。"""
    from . import construction_schedule as _cs
    return {"ok": True, "workshops": _cs.list_workshops_in_schedule()}

@app.get("/api/relations-merge/integrity")
def relations_merge_integrity():
    """v0.1.63：检查关系图谱完整性。"""
    from . import relations_merge as _rm
    return {"ok": True, **_rm.check_relations_integrity()}

@app.get("/api/archive-merge/stats")
def archive_merge_stats():
    """v0.1.59：合并统计信息。"""
    from . import archive_merge as _am
    return {"ok": True, **_am.merge_stats()}

@app.get("/api/piping/stats")
def piping_stats():
    """v0.1.47：管线网络统计。"""
    from . import piping_network as _pn
    return {"ok": True, **_pn.stats()}

@app.get("/api/construction-log/stats")
def construction_log_stats():
    """v0.1.46：施工日志统计。"""
    from . import construction_log as _cl
    return {"ok": True, **_cl.stats()}

@app.get("/api/equipment-merge/stats")
def equipment_merge_stats():
    """v0.1.45：合并统计。"""
    from . import equipment_merge as _em
    return {"ok": True, **_em.stats()}


@app.get("/api/spatial/pending")
def spatial_pending():
    """v0.1.41：位置待确认的设备列表。"""
    from . import spatial_model as _sm
    spatial = _sm.load_spatial()
    pending = []
    for tag, dev in spatial.get("device_index", {}).items():
        if dev.get("coord_status") == "位置待确认":
            pending.append({"tag": tag, "workshop": dev.get("workshop", ""),
                            "x": dev.get("x"), "y": dev.get("y"), "z": dev.get("z"),
                            "sources": dev.get("source_types", [])})
    return {"ok": True, "count": len(pending), "devices": pending}


@app.get("/api/spatial/ai-summary")
def spatial_ai_summary():
    """AI 可读的空间结构文本摘要。"""
    spatial = spatial_model.load_spatial()
    if not spatial:
        return {"ok": False, "message": "空间模型未构建"}
    summary = spatial_model.generate_ai_summary(spatial)
    return {"ok": True, "summary": summary, "chars": len(summary)}


@app.get("/api/completeness/check")
def api_completeness_check(phase: str = None):
    """资料完整性检查（v0.1.36）：按工程阶段检查哪些资料缺失，列出待补充清单。"""
    return completeness_check.check_completeness(phase)


@app.get("/api/completeness/todo")
def api_completeness_todo(limit: int = 50):
    """待补充资料清单（按优先级排序）。"""
    items = completeness_check.get_todo_list(limit)
    return {"items": items, "count": len(items)}


@app.get("/api/completeness/phase-status")
def api_completeness_phase_status():
    """各阶段资料完成状态。"""
    return {"phases": completeness_check.get_phase_status()}


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
