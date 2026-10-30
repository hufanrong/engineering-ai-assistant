# -*- coding: utf-8 -*-
"""使用遥测：请求级耗时/异常留痕 + 可脱敏导出的诊断包（v0.1.171）

为什么要有这个模块
------------------
现有 `operation_log.jsonl` 只记「谁在什么时候做了哪类操作」一句话，没有耗时、
没有错误类型、没有失败原因。真实使用中「上传 200 个 PDF 有 30 个没解析出来」
这种事，事后在日志里查不到任何线索 —— 拿这种日志做优化，等于猜。

本模块补三件事：
1. **请求级遥测**：每个 API 调用的路由、状态码、耗时、异常类型，落
   `data/telemetry/requests.jsonl`。用来回答「哪个接口慢」「哪类请求在报错」。
2. **错误指纹**：把错误消息归一成模板（去掉路径、哈希、数字、引号内容）后
   聚合，同一类错误只算一条。避免几十条同类报错淹没真正的问题。
3. **脱敏导出**：产出可直接分享的诊断包。**默认不含**项目名、客户名、地点、
   文件名、绝对路径、设备位号 —— 只保留结构与统计。

最后一条是硬约束：本仓库是公开仓库，真实使用数据里带的是企业业务信息
（项目名、客户、矿区地点）。原始日志一旦推上去就等于对外公开，所以导出的
默认形态必须是脱敏的，且**不提供**"一键上传原始日志"的入口。

数据结构（requests.jsonl 单行一条）
---------------------------------
{"ts": 1793345000.123, "ts_str": "2026-10-30 15:30:00", "method": "POST",
 "route": "/api/upload", "status": 200, "dur_ms": 1234.5,
 "err": "", "err_kind": "", "req_bytes": 0}

只记路由与状态，**不记请求体、不记响应体、不记文件路径**。
"""
import json
import os
import platform
import re
import sys
import threading
import time
from collections import Counter, defaultdict

# ---------------------------------------------------------------- 路径
def _data_dir():
    """与 app/config.py 同一套解析顺序，但本模块不 import config，
    好让它能被独立脚本（tools/wb_loop.py）直接加载。"""
    env = os.environ.get("FANGONG_DATA_DIR", "").strip()
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    wb = os.path.dirname(here)                      # workbench/
    cfg = os.path.join(wb, "data", "storage_config.json")
    try:
        if os.path.exists(cfg):
            with open(cfg, encoding="utf-8") as f:
                p = (json.load(f) or {}).get("data_root") or ""
            if p:
                return p
    except Exception:  # noqa: BLE001
        pass
    return os.path.join(wb, "data")


DATA_DIR = _data_dir()
TELEMETRY_DIR = os.path.join(DATA_DIR, "telemetry")
REQ_LOG = os.path.join(TELEMETRY_DIR, "requests.jsonl")
WATERMARK = os.path.join(TELEMETRY_DIR, ".export_watermark")

_lock = threading.Lock()

# 不记录的路由前缀（静态资源与文档页，跟业务无关，记了只会把日志撑大）
IGNORE_PREFIX = ("/static/", "/web/", "/favicon", "/docs", "/redoc", "/openapi.json")

# 单文件上限：超过就轮转，避免长期运行把磁盘写满
MAX_BYTES = 8 * 1024 * 1024
MAX_KEEP = 3


def _ensure_dir():
    try:
        os.makedirs(TELEMETRY_DIR, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass


def _rotate_if_big():
    try:
        if os.path.exists(REQ_LOG) and os.path.getsize(REQ_LOG) > MAX_BYTES:
            for i in range(MAX_KEEP - 1, 0, -1):
                src = f"{REQ_LOG}.{i}"
                dst = f"{REQ_LOG}.{i + 1}"
                if os.path.exists(src):
                    os.replace(src, dst)
            os.replace(REQ_LOG, REQ_LOG + ".1")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 脱敏
_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|/)[^\s'\"<>|,;]*[\\/][^\s'\"<>|,;]*")
# HEX 必须含至少一个 a-f 字母，否则纯数字串会被它抢走（"1793344689908" 全是数字，
# 却先命中 [0-9a-fA-F]{8,} 被标成 <HASH>）。语义错标不影响安全性，但会让错误聚合失真。
_HEX_RE = re.compile(r"\b(?=[0-9a-fA-F]{8,}\b)(?=[0-9]*[a-fA-F])[0-9a-fA-F]+\b")
_LONGNUM_RE = re.compile(r"\b\d{6,}\b")
_QUOTED_RE = re.compile(r"(['\"])(?:(?!\1).){1,120}\1")
# 文件名（含中文）：`设备台账.xlsx`、`施工图_EQ-101.dxf`、`技术协议.pdf`。
# 注意不能只匹配 ASCII —— 实际业务里文件名绝大多数是中文，漏了等于没脱敏。
_FNAME_RE = re.compile(
    r"[^\s\/<>,;\"'|\u3000]+\.(?:xlsx|xlsm|xls|csv|docx|doc|pdf|txt|md|json|"
    r"dwg|dxf|jpg|jpeg|png|bmp|tif|tiff|zip|rar|7z|xml|mpp|log|py|bat|jsonl)\b",
    re.IGNORECASE)
# 设备位号（EQ-101 / P-101A / V-201 这类）是识别具体装置的钥匙，属业务信息。
# 与 config.EQUIPMENT_TAG_RE 同源思路，但这里更宽松：前面必须不是字母数字，
# 后面不能紧跟字母数字，避免把 GB/T 标准号、普通型号误伤。
# 企业/机构名（…公司/集团/矿业/厂/矿/项目部/研究院 等）。真实错误消息里经常
# 带业务方名称（如「紫金矿业矿区资料」），属企业敏感信息，必须抹掉。
# 中文无空格分隔，无法靠边界词精确定位，用后缀词 + 向前回溯若干中文字符取整块。
_ORG_RE = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9（）()·._-]{1,20}?"
    r"(?:股份有限公司|有限责任公司|有限公司|集团|矿业|矿山|冶炼厂|选矿厂|"
    r"项目部|指挥部|研究院|设计院|工程公司|建设公司|分公司|子公司)")


_TAG_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,4}-\d{1,6}[A-Z]?(?:[/-][A-Z]{0,3}\d{0,4})?)(?![A-Za-z0-9])")
# 标准号白名单：这些不是设备位号，是公开标准，保留原样才有诊断价值
_STD_PREFIX = {"GB", "GBT", "JB", "JBT", "HG", "HGT", "SH", "SHT", "DL", "DLT",
               "YS", "YST", "SY", "SYT", "TB", "QB", "JG", "JGJ", "TJ", "ZB",
               "YD", "SD", "NB", "MT", "AQ", "GA", "FZ", "QC", "JT", "ISO",
               "IEC", "ASTM", "API", "ANSI", "DIN", "EN", "ASME"}


def _mask_equipment_tags(text: str) -> str:
    """把设备位号替换成 <TAG>，但放过公开标准号（GB/T、ISO、ASME 等）。

    设备位号是识别具体装置的钥匙（EQ-101 = 某台设备）。它出现在错误消息里时
    必须抹掉；而 GB/T 12345 这类标准号是公开信息，留着才能看出是哪条标准报的问题。
    """
    def _rep(mt):
        tok = mt.group(1)
        prefix = re.split(r"[-/]", tok)[0].upper()
        if prefix in _STD_PREFIX:
            return tok
        return "<TAG>"
    return _TAG_RE.sub(_rep, text)


def scrub(text: str, limit: int = 300) -> str:
    """把一段文本里的可识别信息抹掉，只留能用来归类的骨架。

    - 绝对路径 / Windows 路径 → <PATH>（路径里通常就是项目名、客户名）
    - 长十六进制（sha256、token） → <HASH>
    - 长数字串（时间戳、ID） → <NUM>
    - 引号内容（文件名、字段值） → <STR>
    最后截断到 limit 字。
    """
    if not text:
        return ""
    s = str(text)
    s = _PATH_RE.sub("<PATH>", s)
    s = _HEX_RE.sub("<HASH>", s)
    s = _LONGNUM_RE.sub("<NUM>", s)
    s = _QUOTED_RE.sub("<STR>", s)
    s = _FNAME_RE.sub("<FILE>", s)
    s = _ORG_RE.sub("<ORG>", s)
    s = _mask_equipment_tags(s)
    s = re.sub(r"[\r\n\t]+", " ", s).strip()
    return s[:limit]


def fingerprint(err_kind: str, err_msg: str) -> str:
    """错误指纹：类型 + 归一化消息，同一类错误聚成同一个键。"""
    return f"{err_kind or 'Unknown'}|{scrub(err_msg, 120)}"


# ---------------------------------------------------------------- 写入
_ID_SEG_RE = re.compile(r"/(?=[^/]*[0-9a-fA-F]{8,}|[0-9]{4,})[^/]+")


def norm_route(route: str) -> str:
    """把实际请求路径归一成路由骨架，便于按路由聚合。

    这里**不能**用 scrub()：`/api/status` 这种正常路由会被路径正则整段吃掉，
    变成 `<PATH>`，聚合表就全成了同一条，统计失去意义（实测踩过）。
    正确做法是保留斜杠分段结构，只把带长 ID / sha 的段替换成 <id>，
    如 /api/scan/retry-failed/9f3f7a449843... → /api/scan/retry-failed/<id>
    """
    r = str(route or "")
    r = _ID_SEG_RE.sub("/<id>", r)
    # 纯数字段（如 /20261030_084638）也归一
    r = re.sub(r"/[0-9][0-9_\-]{3,}", "/<id>", r)
    return r[:120]


def record(method, route, status, dur_ms, err="", err_kind="", req_bytes=0):
    """记一条请求遥测。绝不抛异常：遥测坏了不能把业务拖下水。"""
    try:
        if any(str(route).startswith(p) for p in IGNORE_PREFIX):
            return
        _ensure_dir()
        rec = {
            "ts": round(time.time(), 3),
            "ts_str": time.strftime("%Y-%m-%d %H:%M:%S"),
            "method": method,
            "route": norm_route(route),
            "status": int(status or 0),
            "dur_ms": round(float(dur_ms), 1),
            "err_kind": (err_kind or "")[:60],
            "err": scrub(err, 240) if err else "",
            "req_bytes": int(req_bytes or 0),
        }
        line = json.dumps(rec, ensure_ascii=False)
        with _lock:
            _rotate_if_big()
            with open(REQ_LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 读取
def _iter_records(since_ts=0.0, until_ts=0.0):
    files = [REQ_LOG]
    for i in range(1, MAX_KEEP + 1):
        p = f"{REQ_LOG}.{i}"
        if os.path.exists(p):
            files.append(p)
    for path in files:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    ts = float(r.get("ts") or 0)
                    if since_ts and ts < since_ts:
                        continue
                    if until_ts and ts > until_ts:
                        continue
                    yield r
        except Exception:  # noqa: BLE001
            continue


def _pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    k = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))  # noqa: E501
    return round(s[k], 1)


def stats(since_ts=0.0, until_ts=0.0):
    """按路由聚合的统计。返回 {total, by_route, errors, slow}。"""
    per = defaultdict(lambda: {"n": 0, "durs": [], "codes": Counter()})
    errors = Counter()
    err_examples = {}
    total = 0
    t_min, t_max = 0.0, 0.0
    for r in _iter_records(since_ts, until_ts):
        total += 1
        ts = float(r.get("ts") or 0)
        if ts:
            t_min = ts if not t_min else min(t_min, ts)
            t_max = max(t_max, ts)
        key = f"{r.get('method','')} {r.get('route','')}".strip()
        b = per[key]
        b["n"] += 1
        b["durs"].append(float(r.get("dur_ms") or 0))
        b["codes"][int(r.get("status") or 0)] += 1
        if r.get("err_kind"):
            fp = fingerprint(r.get("err_kind"), r.get("err"))
            errors[fp] += 1
            err_examples.setdefault(fp, r.get("err", ""))

    by_route = []
    for key, b in per.items():
        codes = b["codes"]
        err_n = sum(v for k, v in codes.items() if 500 <= k < 600)
        c4 = sum(v for k, v in codes.items() if 400 <= k < 500)
        by_route.append({
            "route": key,
            "n": b["n"],
            "p50_ms": _pct(b["durs"], 50),
            "p95_ms": _pct(b["durs"], 95),
            "max_ms": round(max(b["durs"]), 1) if b["durs"] else 0.0,
            "status_2xx": sum(v for k, v in codes.items() if 200 <= k < 300),
            "status_4xx": c4,
            "status_5xx": err_n,
        })
    by_route.sort(key=lambda x: (-x["n"],))

    return {
        "total": total,
        "window": {
            "from": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_min)) if t_min else "",
            "to": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_max)) if t_max else "",
            "span_min": round((t_max - t_min) / 60.0, 1) if t_min else 0.0,
        },
        "by_route": by_route,
        "slow": sorted([r for r in by_route if r["p95_ms"] >= 1000],
                       key=lambda x: -x["p95_ms"])[:10],
        "errors": [{"fingerprint": k, "count": v, "example": err_examples.get(k, "")}
                   for k, v in errors.most_common(20)],
    }


# ---------------------------------------------------------------- 导出
def _env_summary():
    """环境摘要：只收判断问题需要的，不含路径与用户名。"""
    out = {
        "system": platform.system(),
        "release": platform.release(),
        "python": sys.version.split()[0],
        "machine_bits": platform.machine(),
    }
    try:
        from importlib.metadata import version as _v
        pkgs = {}
        for pm in ("fastapi", "python-docx", "openpyxl", "ezdxf", "pypdf",
                   "pywin32", "paddleocr", "python-multipart"):
            try:
                pkgs[pm] = _v(pm)
            except Exception:  # noqa: BLE001
                pkgs[pm] = "未安装"
        out["packages"] = pkgs
    except Exception:  # noqa: BLE001
        out["packages"] = {}
    try:
        from . import config as _cfg  # noqa: WPS433
        out["app_version"] = getattr(_cfg, "APP_VERSION", "")
    except Exception:  # noqa: BLE001
        pass
    return out


def _parse_failure_summary():
    """解析失败的结构化摘要：只看类型与错误模板，**不看文件名**。

    数据来自各项目 index.json 里 status=failed 的条目，只统计扩展名与错误指纹。
    """
    res = {"total_failed": 0, "by_ext": {}, "by_fingerprint": [], "by_project": {}}
    fp = Counter()
    ext = Counter()
    by_proj = Counter()

    # 索引有两处：选了项目时在 projects/<id>/index.json，**没选项目时在 data/index.json**
    # （scanner._get_data_dir 的兜底分支）。只扫 projects/ 会把最常见的用法
    # ——「打开程序直接传一批文件，没先建项目」——的失败全部漏成 0，
    # 于是诊断包里写着「0 条解析失败」，等于告诉 AI 侧没毛病。实测踩过。
    def _read(idx_path, label):
        try:
            with open(idx_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            return
        if not isinstance(data, dict):
            return
        for _key, info in data.items():
            if not isinstance(info, dict):
                continue
            if info.get("status") not in ("failed", "pending_manual"):
                continue
            res["total_failed"] += 1
            by_proj[label] += 1
            name = str(info.get("file_name") or "")
            e = os.path.splitext(name)[1].lower() or "(无扩展名)"
            ext[e] += 1
            fp[fingerprint(str(info.get("status") or ""), str(info.get("error") or ""))] += 1

    proj_root = os.path.join(DATA_DIR, "projects")
    if os.path.isdir(proj_root):
        for d in sorted(os.listdir(proj_root)):
            _read(os.path.join(proj_root, d, "index.json"), d)
    _read(os.path.join(DATA_DIR, "index.json"), "(未分项目)")

    res["by_ext"] = dict(ext.most_common(15))
    res["by_project"] = dict(by_proj.most_common(15))
    res["by_fingerprint"] = [{"fingerprint": k, "count": v}
                             for k, v in fp.most_common(15)]
    return res


def export_bundle(since_ts=0.0, advance_watermark=False):
    """产出可直接分享的诊断包（脱敏）。

    since_ts 为 0 时读全部历史；传上一轮的 watermark 就只导出新增部分。
    advance_watermark=True 时把本次截止时间写回水位文件，下一轮从这里继续。
    """
    until = time.time()
    st = stats(since_ts=since_ts, until_ts=until)
    bundle = {
        "bundle_version": 1,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "window": st["window"],
        "requests": {
            "total": st["total"],
            "by_route": st["by_route"],
            "slow_routes": st["slow"],
        },
        "errors": st["errors"],
        "parse_failures": _parse_failure_summary(),
        "environment": _env_summary(),
        "privacy": {
            "sanitized": True,
            "note": "不含项目名/客户/地点/文件名/绝对路径；错误消息中的路径与长串已替换为占位符",
            "rules": ["绝对路径→<PATH>", "长十六进制→<HASH>", "长数字→<NUM>", "引号内容→<STR>"],
        },
    }
    if advance_watermark:
        try:
            os.makedirs(TELEMETRY_DIR, exist_ok=True)
            with open(WATERMARK, "w", encoding="utf-8") as f:
                f.write(str(until))
        except Exception:  # noqa: BLE001
            pass
    return bundle


def read_watermark():
    try:
        if os.path.exists(WATERMARK):
            with open(WATERMARK, encoding="utf-8") as f:
                return float(f.read().strip() or 0)
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def reset_watermark():
    try:
        if os.path.exists(WATERMARK):
            os.remove(WATERMARK)
        return True
    except Exception:  # noqa: BLE001
        return False


def line_count():
    try:
        if not os.path.exists(REQ_LOG):
            return 0
        with open(REQ_LOG, encoding="utf-8") as f:
            return sum(1 for _ in f)
    except Exception:  # noqa: BLE001
        return 0
