# 繁工AI 云端合并主库（v0.1.11）
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

from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloud_data")
os.makedirs(BASE_DIR, exist_ok=True)

INDEX_PATH = os.path.join(BASE_DIR, "cloud_index.json")
PAYLOAD_DIR = os.path.join(BASE_DIR, "payloads")
os.makedirs(PAYLOAD_DIR, exist_ok=True)

# 与工作台 app/config.py 的 CLOUD_API_KEY 保持一致；留空则不鉴权（仅内网推荐）
API_KEY = "fanGong_cloud_2026"

app = FastAPI(title="繁工AI 云端合并主库", version="0.1.11")


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
    # 简单词频检索（云端轻量方案；后续可接向量模型）
    qs = set(query.lower().split())
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
        score = sum(1 for w in qs if w in text)
        # 中文关键词按子串计分（整句直接命中大幅加分）
        if len(query) > 1 and query in text:
            score += 3
        if score > 0:
            scored.append({"score": score, "sha256": sha,
                           "file_name": (pkg.get("payload") or {}).get("file_name", ""),
                           "text": text[:500], "node_name": pkg.get("node_name", "")})
    scored.sort(key=lambda x: -x["score"])
    return {"query": query, "results": scored[:top_k]}


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
