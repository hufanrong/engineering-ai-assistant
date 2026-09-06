# 繁工AI 云端合并主库（v0.1.14）
# 部署在服务器/公司主机上，接收各电脑解析节点上传的 payload（data/upload_queue 打包内容），
# 按 SHA256 去重合并为一个完整云库；手机端/外部 Agent 可在线检索；
# 支持把云库导出为 .fglib 供任意电脑导入；也支持直接导入工作台导出的 .fglib。
#
# 部署：pip install -r requirements.txt → 双击 run_server.bat → http://127.0.0.1:8760
# 工作台配置：app/config.py 的 CLOUD_ENDPOINT = "http://<服务器IP>:8760"，CLOUD_API_KEY 与下方一致

import os
import io
import json
import zipfile
import hashlib
import datetime
import requests

from fastapi import FastAPI, HTTPException, UploadFile, File, Header, Form, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloud_data")
os.makedirs(BASE_DIR, exist_ok=True)

INDEX_PATH = os.path.join(BASE_DIR, "cloud_index.json")
PAYLOAD_DIR = os.path.join(BASE_DIR, "payloads")
os.makedirs(PAYLOAD_DIR, exist_ok=True)

# 手机端现场上传（照片/语音/文字）：field_data/{项目}/{上传人}/…，电脑端拉取后本地解析
FIELD_DIR = os.path.join(BASE_DIR, "field_data")
FIELD_INDEX = os.path.join(BASE_DIR, "field_index.json")
os.makedirs(FIELD_DIR, exist_ok=True)

# 与工作台 app/config.py 的 CLOUD_API_KEY 保持一致；留空则不鉴权（仅内网推荐）
API_KEY = "fanGong_cloud_2026"

# 手机端 AI 对话桥接：填写电脑工作台地址（如 http://192.168.1.10:8756），
# 手机 → 云库 → 工作台 AI 助手（本地多库检索+资料生成）；留空则云库本地轻量检索回答。
AI_WORKBENCH_ENDPOINT = ""

app = FastAPI(title="繁工AI 云端合并主库", version="0.1.19")


def _load_index() -> dict:
    if os.path.exists(INDEX_PATH):
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_index(idx: dict):
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)


def _check_auth(authorization: str):
    if not API_KEY:
        return
    if not authorization or authorization != f"Bearer {API_KEY}":
        raise HTTPException(401, "API Key 无效")


@app.get("/api/cloud/status")
def cloud_status():
    idx = _load_index()
    return {"app": "fangong-cloud", "version": app.version,
            "files": len(idx), "dir": BASE_DIR}


# ---------- 工作台上传队列对接（upload_queue.upload_all 打这个接口） ----------
@app.post("/api/parse-nodes/payloads")
def receive_payload(payload: dict, authorization: str = Header("")):
    _check_auth(authorization)
    sha = (payload.get("payload") or {}).get("sha256", "")
    if not sha:
        raise HTTPException(400, "缺少 sha256")
    idx = _load_index()
    if sha in idx:
        return {"ok": True, "status": "duplicate", "sha256": sha}
    pkg = {"received_at": datetime.datetime.now().isoformat(), **payload}
    with open(os.path.join(PAYLOAD_DIR, f"{sha}.json"), "w", encoding="utf-8") as f:
        json.dump(pkg, f, ensure_ascii=False)
    idx[sha] = {
        "sha256": sha,
        "file_name": (payload.get("payload") or {}).get("file_name", ""),
        "parser": (payload.get("payload") or {}).get("parser", ""),
        "status": (payload.get("payload") or {}).get("status", ""),
        "node_name": payload.get("node_name", ""),
        "received_at": pkg["received_at"],
    }
    _save_index(idx)
    return {"ok": True, "status": "added", "sha256": sha}


@app.get("/api/cloud/list")
def cloud_list(limit: int = 500):
    idx = _load_index()
    items = [dict(v, sha256=k) for k, v in idx.items()]
    items.sort(key=lambda x: x.get("received_at", ""), reverse=True)
    return {"count": len(items), "items": items[:limit]}


@app.post("/api/cloud/search")
def cloud_search(req: dict):
    """云库检索（手机端/外部 Agent 读取入口）。query/top_k。"""
    query = (req or {}).get("query", "")
    top_k = int((req or {}).get("top_k", 5))
    if not query:
        raise HTTPException(400, "缺少 query")
    idx = _load_index()
    # 轻量检索（v0.1.19 增强：大小写不敏感 + 中文二连字子串计分，手机端 AI 检索质量）
    ql = query.lower()
    qs = set(ql.split())
    grams = [ql[i:i+2] for i in range(max(len(ql) - 1, 0))] if len(ql) >= 2 else []
    scored = []
    for sha in list(idx)[:2000]:
        p = os.path.join(PAYLOAD_DIR, f"{sha}.json")
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                pkg = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        text = ((pkg.get("payload") or {}).get("text", "") or "")[:20000]
        tl = text.lower()
        score = sum(1 for w in qs if w in tl)
        if len(ql) > 1 and ql in tl:
            score += 3
        score += sum(0.5 for g in grams if g in tl)  # 中文二连字命中
        if score > 0:
            scored.append({"score": round(score, 2), "sha256": sha,
                           "file_name": (pkg.get("payload") or {}).get("file_name", ""),
                           "text": text[:500], "node_name": pkg.get("node_name", "")})
    scored.sort(key=lambda x: -x["score"])
    return {"query": query, "results": scored[:top_k]}


@app.post("/api/cloud/ai-chat")
def cloud_ai_chat(req: dict, authorization: str = Header("")):
    """手机端 AI 助手桥接（v0.1.19）：手机 → 云库 → 电脑工作台 AI。
    配置 AI_WORKBENCH_ENDPOINT 后转发至工作台 /api/ai/chat（本地多库检索+Word 资料生成）；
    未配置则用云库自身轻量检索回答。"""
    _check_auth(authorization)
    query = (req or {}).get("query", "")
    if not query:
        raise HTTPException(400, "缺少 query")
    history = (req or {}).get("history") or []
    ep = AI_WORKBENCH_ENDPOINT.strip().rstrip("/")
    if ep:
        try:
            r = requests.post(f"{ep}/api/ai/chat",
                              json={"query": query, "history": history}, timeout=120)
            if r.status_code == 200:
                return {"bridge": "workbench", "endpoint": ep, **r.json()}
            return {"bridge": "workbench", "error": f"工作台返回 {r.status_code}", "mode": "error"}
        except Exception as e:  # noqa: BLE001
            return {"bridge": "workbench", "error": f"工作台不可达：{e}，已降级云库本地检索", "mode": "error",
                    "fallback": _cloud_local_answer(query)}
    return {"bridge": "cloud_local", "endpoint": "", **_cloud_local_answer(query)}


def _cloud_local_answer(query: str, top_k: int = 5) -> dict:
    """云库本地轻量回答：检索相关文件 + 状态汇总。"""
    res = cloud_search({"query": query, "top_k": top_k})
    lines = []
    if res["results"]:
        lines.append("云端资料命中：")
        for i, it in enumerate(res["results"][:5], 1):
            lines.append(f"  {i}. 《{it.get('file_name','')}》（{it.get('node_name','')}）：{(it.get('text') or '')[:80]}…")
    else:
        lines.append("云端资料未命中。可先在手机端上传现场照片/语音/文字，或让电脑端同步解析库。")
    lines.append("（提示：在云库服务器配置 AI_WORKBENCH_ENDPOINT 指向电脑工作台，可获得完整 AI 问答与资料生成）")
    return {"mode": "cloud_local", "answer": "\n".join(lines), "sources": {"project": len(res["results"])}}


# ---------- 云库 <-> .fglib 互导（多电脑并库闭环） ----------
@app.get("/api/cloud/export-fglib")
def cloud_export():
    """导出云端完整库 .fglib（工作台"导入库包合并"可直接并入）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(INDEX_PATH):
            zf.write(INDEX_PATH, "index.json")
        for fn in sorted(os.listdir(PAYLOAD_DIR)):
            fp = os.path.join(PAYLOAD_DIR, fn)
            if fn.endswith(".json"):
                zf.write(fp, f"parsed_cache/{fn}")
        zf.writestr("manifest.json", json.dumps({
            "app": "fangong-cloud", "format": "fglib-v1",
            "exported_at": datetime.datetime.now().isoformat(),
            "node": "cloud-master",
        }, ensure_ascii=False, indent=1))
    content = buf.getvalue()
    return StreamingResponse(io.BytesIO(content), media_type="application/zip",
                             headers={"Content-Disposition": "attachment; filename=\"fangong_cloud_library.fglib\""})


def _load_field_index() -> dict:
    if os.path.exists(FIELD_INDEX):
        try:
            with open(FIELD_INDEX, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_field_index(idx: dict):
    with open(FIELD_INDEX, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)


# ---------- 手机端现场上传（免登录，只需写上传人姓名；同一手机再次上传不重复确认） ----------
@app.post("/api/cloud/field-upload")
async def field_upload(project: str = Form("默认项目"), uploader: str = Form("未署名"),
                       note: str = Form(""), kind: str = Form("photo"),
                       file: UploadFile = File(None)):
    """手机端上传现场照片/语音/文字到云库待解析区。
    project=项目名、uploader=上传人姓名（手机端记住后不再询问）、note=文字说明、kind=photo/voice/text。"""
    project = (project or "默认项目").strip()
    uploader = (uploader or "未署名").strip()
    fidx = _load_field_index()
    if file is not None:
        raw = await file.read()
        if not raw:
            raise HTTPException(400, "空文件")
        fname = file.filename or "现场.jpg"
        import hashlib
        sha = hashlib.sha256(raw).hexdigest()
        if sha in fidx:
            return {"ok": True, "status": "duplicate", "sha256": sha, "uploader": uploader}
        safe_proj = "".join(c if c.isalnum() else "_" for c in project)[:40] or "默认项目"
        safe_up = "".join(c if c.isalnum() else "_" for c in uploader)[:40] or "未署名"
        d = os.path.join(FIELD_DIR, safe_proj, safe_up)
        os.makedirs(d, exist_ok=True)
        # 保留原始文件名，避免重名覆盖
        base, ext = os.path.splitext(fname)
        target = os.path.join(d, f"{base}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}{ext[:10]}")
        with open(target, "wb") as fh:
            fh.write(raw)
        fidx[sha] = {"project": project, "uploader": uploader, "kind": kind,
                     "note": note, "file": target, "file_name": fname,
                     "ts": datetime.datetime.now().isoformat()}
        _save_field_index(fidx)
        return {"ok": True, "status": "added", "sha256": sha, "uploader": uploader, "file": fname}
    # 纯文字现场记录（如：语音转文字/手输施工记录）
    if not note.strip():
        raise HTTPException(400, "需要文件或文字内容")
    d = os.path.join(FIELD_DIR, "文字记录")
    os.makedirs(d, exist_ok=True)
    fname = f"文字_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
    target = os.path.join(d, fname)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(f"项目：{project}\n上传人：{uploader}\n时间：{datetime.datetime.now().isoformat()}\n{note}")
    sha = "txt-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    fidx[sha] = {"project": project, "uploader": uploader, "kind": "text",
                 "note": note, "file": target, "file_name": fname,
                 "ts": datetime.datetime.now().isoformat()}
    _save_field_index(fidx)
    return {"ok": True, "status": "added", "sha256": sha, "uploader": uploader, "file": fname}


@app.post("/api/cloud/field-plate")
def field_plate(payload: dict = Body(...)):
    """工作台解析现场照片后回写铭牌识别摘要（v0.1.23），手机端清单可见。"""
    sha = payload.get("sha256", "")
    pl = payload.get("plate") or {}
    fidx = _load_field_index()
    if sha and sha in fidx:
        fidx[sha]["plate"] = pl
        _save_field_index(fidx)
        return {"ok": True, "updated": sha}
    return {"ok": True, "updated": None}


@app.post("/api/cloud/field-transcribe")
def field_transcribe(payload: dict = Body(...)):
    """工作台语音转写回写（v0.1.26）：手机端清单可见转写文本。"""
    sha = payload.get("sha256", "")
    text = payload.get("text") or ""
    mode = payload.get("mode") or ""
    fidx = _load_field_index()
    if sha and sha in fidx:
        fidx[sha]["transcript"] = text
        fidx[sha]["transcribe_mode"] = mode
        _save_field_index(fidx)
        return {"ok": True, "updated": sha}
    return {"ok": True, "updated": None}


@app.get("/api/cloud/field-list")
def field_list(project: str = "", uploader: str = ""):
    """电脑端拉取现场上传清单；可按项目/上传人过滤。"""
    fidx = _load_field_index()
    items = [dict(v, sha256=k) for k, v in fidx.items()]
    if project:
        items = [x for x in items if x.get("project") == project]
    if uploader:
        items = [x for x in items if x.get("uploader") == uploader]
    items.sort(key=lambda x: x.get("ts", ""), reverse=True)
    return {"count": len(items), "items": items[:1000]}


@app.get("/api/cloud/field-file/{sha}")
def field_file(sha: str):
    """下载现场上传的原始文件（电脑端拉取解析用）。"""
    fidx = _load_field_index()
    info = fidx.get(sha)
    if not info or not os.path.exists(info.get("file", "")):
        raise HTTPException(404, "文件不存在或已清理")
    with open(info["file"], "rb") as f:
        raw = f.read()
    fname = info.get("file_name", "现场文件")
    from urllib.parse import quote
    # 中文文件名：ASCII fallback + RFC 5987 filename*（避免 latin-1 编码崩溃）
    ascii_name = "".join(ch if ord(ch) < 128 else "_" for ch in fname) or "field.bin"
    cd = f'attachment; filename="{ascii_name}"; filename*=UTF-8''{quote(fname)}'
    return StreamingResponse(io.BytesIO(raw), media_type="application/octet-stream",
                             headers={"Content-Disposition": cd})


@app.post("/api/cloud/import-fglib")
async def cloud_import(file: UploadFile = File(...)):
    """导入工作台导出的 .fglib：SHA256 去重并入云库。"""
    raw = await file.read()
    stats = {"added": 0, "dup": 0, "error": None}
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        names = zf.namelist()
        if "index.json" not in names:
            stats["error"] = "不是有效的 .fglib 库包"
            return stats
        idx = _load_index()
        incoming = json.loads(zf.read("index.json").decode("utf-8"))
        for sha, info in incoming.items():
            if sha in idx:
                stats["dup"] += 1
                continue
            entry = f"parsed_cache/{sha}.json"
            if entry in names:
                with open(os.path.join(PAYLOAD_DIR, f"{sha}.json"), "wb") as f:
                    f.write(zf.read(entry))
            idx[sha] = {
                "sha256": sha,
                "file_name": info.get("file_name", ""),
                "parser": info.get("parser", ""),
                "status": info.get("status", ""),
                "node_name": "fglib-import",
                "received_at": datetime.datetime.now().isoformat(),
            }
            stats["added"] += 1
        _save_index(idx)
        return stats
    except zipfile.BadZipFile:
        stats["error"] = "文件损坏或不是 .fglib 库包"
        return stats
    except Exception as e:  # noqa: BLE001
        stats["error"] = f"导入失败：{e}"
        return stats


if __name__ == "__main__":
    import uvicorn
    print("=" * 56)
    print("  繁工AI 云端合并主库")
    print("  访问地址: http://127.0.0.1:8760")
    print(f"  数据目录: {BASE_DIR}")
    print("=" * 56)
    uvicorn.run(app, host="0.0.0.0", port=8760, log_level="warning")
