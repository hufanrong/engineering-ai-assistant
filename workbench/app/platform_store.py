# 繁工AI 本地解析工作台 - 平台级规范库（v0.1.15）
# 国标/规范/通用文件独立建库，与子项目解析库分开（多项目共享）；
# 上传时立即检查有效期，每 PLATFORM_CHECK_DAYS（默认180天=6个月）再次核验；
# 配置 PLATFORM_SEARCH_ENDPOINT 后可联网自动核验/搜索最新版替换；
# AI 检索子项目库时可同时检索平台库（引用规范正文内容，而非只有名称）。
# 新电脑安装时：导出 .fpglib 平台库包 → 导入即可复用全部规范库。

import os
import io
import re
import json
import shutil
import hashlib
import zipfile
import datetime

from . import config
from .vector_store import VectorStore
from parsers.engines import parse_file

PLATFORM_DIR = config.PLATFORM_DIR
INDEX_PATH = os.path.join(PLATFORM_DIR, "platform_index.json")
CACHE_DIR = os.path.join(PLATFORM_DIR, "parsed_cache")
FILES_DIR = os.path.join(PLATFORM_DIR, "files")
VECTOR_DB = os.path.join(PLATFORM_DIR, "vectordb")

# 常见标准号：GB/GB-T/JGJ/HG-T/DL-T/JB-T/SH-T/SY-T/NB-T/CJ-T/TSG/AQ/ISO/EN/API/ASME 等
STD_NO_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"((?:GB|GB/T|GB/Z|JGJ|JG/T|HG|HG/T|DL|DL/T|JB|JB/T|SH|SH/T|SY|SY/T|NB|NB/T|"
    r"CJ|CJ/T|YS|YS/T|JC|JC/T|QB|QB/T|AQ|TSG|JJG|JJF|ISO|EN|DIN|ASTM|API|ASME|IEC)"
    r"[ /]?\d{2,5}(?:\.\d{1,4})?(?:[-—]\d{4})?)"
    r"(?![A-Za-z0-9])"
)

STATUS_CURRENT = "现行"
STATUS_PENDING = "待核验"
STATUS_OBSOLETE = "废止"


def _ensure():
    for d in (PLATFORM_DIR, CACHE_DIR, FILES_DIR):
        os.makedirs(d, exist_ok=True)


def _load_index() -> dict:
    _ensure()
    if os.path.exists(INDEX_PATH):
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_index(idx: dict):
    _ensure()
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)


def _save_cache(res):
    _ensure()
    with open(os.path.join(CACHE_DIR, f"{res.sha256}.json"), "w", encoding="utf-8") as f:
        json.dump({
            "file_name": res.file_name, "file_size": res.file_size,
            "sha256": res.sha256, "ext": res.ext, "parser": res.parser,
            "status": res.status, "error": res.error,
            "text": res.text[:30000], "structure": res.structure,
            "entities": res.entities, "created_at": res.created_at,
        }, f, ensure_ascii=False, indent=1)


def _extract_std(text: str, filename: str) -> tuple:
    """从正文前 2000 字符 / 文件名提取（标准号, 标准名）。"""
    text = text or ""
    candidates = []
    for src in (text[:2000], filename or ""):
        m = STD_NO_RE.search(src)
        if m:
            std_no = m.group(1).strip().replace(" ", "").replace("—", "-")
            # 标准名：标准号之后同一行紧邻的中文内容（最多 40 字）
            rest = src[m.end():m.end() + 80]
            name_m = re.match(r"[\s：:·（）()\-—]*([\u4e00-\u9fa5A-Za-z0-9（）()·\-—]{2,40})", rest)
            std_name = name_m.group(1).strip() if name_m else ""
            candidates.append((std_no, std_name))
    if candidates:
        # 正文优先于文件名
        return candidates[0]
    return ("", "")


def add_file(raw: bytes, filename: str) -> dict:
    """上传一个规范文件：落盘 → 解析 → 提取标准号 → 台账 → 独立向量化。"""
    _ensure()
    sha = hashlib.sha256(raw).hexdigest()
    idx = _load_index()
    if sha in idx:
        return {"status": "duplicate", "sha256": sha, "file_name": filename}
    if not raw:
        return {"status": "failed", "error": "空文件"}
    safe_name = os.path.basename(filename or "unnamed")
    saved = os.path.join(FILES_DIR, f"{sha[:12]}_{safe_name}")
    with open(saved, "wb") as f:
        f.write(raw)
    res = parse_file(saved)
    if res.status not in ("parsed", "partial"):
        return {"status": res.status, "error": res.error, "sha256": sha, "file_name": safe_name}
    std_no, std_name = _extract_std(res.text, safe_name)
    now = datetime.datetime.now()
    next_check = now + datetime.timedelta(days=config.PLATFORM_CHECK_DAYS)
    idx[sha] = {
        "sha256": sha,
        "file_name": safe_name,
        "std_no": std_no,
        "std_name": std_name,
        "status": STATUS_CURRENT if std_no else STATUS_PENDING,
        "uploaded_at": now.isoformat(),
        "last_check": now.isoformat(),
        "next_check": next_check.strftime("%Y-%m-%d"),
        "parser": res.parser,
        "error": res.error,
        "vectorized": False,
    }
    # v0.1.15：首次上传即核验是否过期（有标准号才核验；无法联网→保持待核验人工处理）
    if std_no and config.STD_VERIFY_ON_UPLOAD:
        try:
            from . import std_verify
            v = std_verify.verify_std(std_no)
            idx[sha]["verify_source"] = v.get("source", "")
            idx[sha]["verify_confidence"] = v.get("confidence", 0)
            idx[sha]["verify_sources"] = v.get("sources", [])
            if v.get("status") == STATUS_CURRENT:
                idx[sha]["status"] = STATUS_CURRENT
                idx[sha]["verified_at"] = now.isoformat()
            elif v.get("status") == STATUS_OBSOLETE:
                idx[sha]["status"] = STATUS_OBSOLETE
                idx[sha]["obsolete_note"] = f"已废止，最新版：{v.get('latest_no') or '待查'}（请上传最新版替换）"
            else:
                # 无法核验（unknown）→ 待核验，人工确认后再定（不默认当现行）
                idx[sha]["status"] = STATUS_PENDING
        except Exception:  # noqa: BLE001（核验失败不阻断入库）
            pass
    try:
        store = VectorStore(db_path=VECTOR_DB)
        n = store.index_file(res)
        idx[sha]["vectorized"] = n > 0
    except Exception as e:  # noqa: BLE001（真实环境向量化失败不阻断入库）
        idx[sha]["vectorized"] = False
        idx[sha]["vectorize_error"] = str(e)
    _save_cache(res)
    _save_index(idx)
    return {"status": "added", "sha256": sha, "file_name": safe_name,
            "std_no": std_no, "std_name": std_name}


def list_items() -> dict:
    idx = _load_index()
    items = [dict(v, sha256=k) for k, v in idx.items()]
    items.sort(key=lambda x: (x.get("std_no") or x.get("file_name") or ""))
    return {"count": len(items), "items": items}


def delete(sha: str) -> dict:
    idx = _load_index()
    if sha not in idx:
        return {"ok": False, "error": "未找到该条目"}
    info = idx.pop(sha)
    _save_index(idx)
    # 清理缓存与原文（best-effort，不阻断）
    for base in (os.path.join(CACHE_DIR, f"{sha}.json"),
                 os.path.join(FILES_DIR, f"{info.get('file_name','')}")):
        try:
            if os.path.exists(base):
                os.remove(base)
        except Exception:  # noqa: BLE001
            pass
    try:
        os.remove(os.path.join(FILES_DIR, f"{sha[:12]}_{info.get('file_name','')}"))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "sha256": sha}


def mark_status(sha: str, status: str) -> dict:
    if status not in (STATUS_CURRENT, STATUS_PENDING, STATUS_OBSOLETE):
        return {"ok": False, "error": f"状态必须是 {STATUS_CURRENT}/{STATUS_PENDING}/{STATUS_OBSOLETE}"}
    idx = _load_index()
    if sha not in idx:
        return {"ok": False, "error": "未找到该条目"}
    idx[sha]["status"] = status
    idx[sha]["status_marked_at"] = datetime.datetime.now().isoformat()
    _save_index(idx)
    return {"ok": True, "sha256": sha, "status": status}


def verify_one(sha256: str) -> dict:
    """v0.1.28：立即核验单条规范（不等到期），多源聚合核验并更新状态。"""
    idx = _load_index()
    info = idx.get(sha256)
    if not info:
        return {"ok": False, "error": "未找到该条目"}
    std_no = info.get("std_no")
    if not std_no:
        return {"ok": False, "error": "该条目无标准号"}
    from . import std_verify
    now = datetime.datetime.now()
    v = std_verify.verify_std(std_no)
    info["verify_source"] = v.get("source", "")
    info["verify_confidence"] = v.get("confidence", 0)
    info["verify_sources"] = v.get("sources", [])
    info["last_check"] = now.isoformat()
    info["next_check"] = (now + datetime.timedelta(days=config.PLATFORM_CHECK_DAYS)).strftime("%Y-%m-%d")
    if v.get("status") == STATUS_OBSOLETE:
        info["status"] = STATUS_OBSOLETE
        info["obsolete_note"] = f"已废止，最新版：{v.get('latest_no') or '待查'}（请上传最新版替换）"
    elif v.get("status") == STATUS_CURRENT:
        info["status"] = STATUS_CURRENT
        info["verified_at"] = now.isoformat()
    else:
        info["status"] = STATUS_PENDING
    _save_index(idx)
    return {"ok": True, "status": info["status"], "source": info.get("verify_source"),
            "confidence": info.get("verify_confidence"), "latest_no": v.get("latest_no")}


def check_expiry() -> dict:
    """到期核验：next_check 已到 → 标记待核验（或配置联网端点则自动核验替换）。"""
    idx = _load_index()
    now = datetime.datetime.now()
    today = now.strftime("%Y-%m-%d")
    due = []          # 到期待核验
    checked = 0
    replaced = []     # 联网替换记录
    for sha, info in idx.items():
        nc = info.get("next_check", "")
        if nc and nc <= today:
            checked += 1
            info["last_check"] = now.isoformat()
            info["next_check"] = (now + datetime.timedelta(days=config.PLATFORM_CHECK_DAYS)).strftime("%Y-%m-%d")
            if info.get("status") == STATUS_CURRENT:
                info["status"] = STATUS_PENDING
            due.append({"sha256": sha, "std_no": info.get("std_no"),
                        "file_name": info.get("file_name")})
    if due:
        from . import std_verify
        for d in due:
            std_no = d.get("std_no")
            if not std_no:
                continue
            v = std_verify.verify_std(std_no)
            info = idx.get(d["sha256"])
            if not info:
                continue
            info["verify_source"] = v.get("source", "")
            info["verify_confidence"] = v.get("confidence", 0)
            info["verify_sources"] = v.get("sources", [])
            if v.get("status") == STATUS_OBSOLETE:
                info["status"] = STATUS_OBSOLETE
                info["obsolete_note"] = f"已废止，最新版：{v.get('latest_no') or '待查'}（请上传最新版替换）"
                replaced.append({"std_no": std_no, "latest_no": v.get("latest_no") or "",
                                 "sha256": d["sha256"]})
            elif v.get("status") == STATUS_CURRENT:
                info["status"] = STATUS_CURRENT
                info["verified_at"] = now.isoformat()
            # unknown → 保持待核验，人工处理
    _save_index(idx)
    return {"checked": checked, "due": due, "replaced": replaced,
            "search_endpoint": config.PLATFORM_SEARCH_ENDPOINT or "(未配置，需人工核验)"}


def search(query: str, top_k: int = 5) -> list:
    """检索平台库（废止条目不参与）。"""
    try:
        store = VectorStore(db_path=VECTOR_DB)
        return store.search(query, top_k=top_k)
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)}]


def export_platform() -> bytes:
    """导出平台库包 .fpglib（index + parsed_cache + files 原文 + manifest）。"""
    _ensure()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(INDEX_PATH):
            zf.write(INDEX_PATH, "platform_index.json")
        for base, prefix in ((CACHE_DIR, "parsed_cache"), (FILES_DIR, "files")):
            if os.path.isdir(base):
                for fn in sorted(os.listdir(base)):
                    fp = os.path.join(base, fn)
                    if os.path.isfile(fp):
                        zf.write(fp, f"{prefix}/{fn}")
        zf.writestr("manifest.json", json.dumps({
            "app": "fangong-workbench", "format": "platform-fglib-v1",
            "exported_at": datetime.datetime.now().isoformat(),
            "node": config.NODE_NAME,
        }, ensure_ascii=False, indent=1))
    return buf.getvalue()


def import_platform(raw: bytes) -> dict:
    """导入平台库包：SHA256 去重合并（重复跳过），新增项落盘+解析+向量化。"""
    stats = {"added": 0, "dup": 0, "failed": 0, "error": None}
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        names = zf.namelist()
        if "platform_index.json" not in names:
            stats["error"] = "不是有效的 .fpglib 平台库包（缺少 platform_index.json）"
            return stats
        man = json.loads(zf.read("manifest.json").decode("utf-8")) if "manifest.json" in names else {}
        if man.get("format") != "platform-fglib-v1":
            stats["error"] = "平台库包格式不兼容"
            return stats
        incoming = json.loads(zf.read("platform_index.json").decode("utf-8"))
        for sha, info in incoming.items():
            if sha in _load_index():
                stats["dup"] += 1
                continue
            fname = os.path.basename(info.get("file_name", ""))
            # 原文在包内则用原文，否则仅登记
            entry = f"files/{sha[:12]}_{fname}" if f"files/{sha[:12]}_{fname}" in names else None
            if entry:
                raw_file = zf.read(entry)
                r = add_file(raw_file, fname)
                stats["added" if r["status"] == "added" else "dup"] += 1
            else:
                stats["failed"] += 1
        return stats
    except zipfile.BadZipFile:
        stats["error"] = "文件损坏或不是 .fpglib 平台库包"
        return stats
    except Exception as e:  # noqa: BLE001
        stats["error"] = f"导入失败：{e}"
        return stats
