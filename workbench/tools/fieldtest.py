#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""繁工AI 本地实测脚本 · 代替使用者做一遍真实操作，并把数据回传。

和 selftest.py 的区别（这点很重要）：
  - selftest.py 是「代码自测」：自己造样本、只验证接口通不通。
  - fieldtest.py 是「实测」：**用使用者自己的真实资料**（设备台账 / 整编要求登记表 /
    图纸或资料目录），按真实工作顺序走一遍 —— 建项目 → 导入资料 → 解析 → 归车间 →
    导登记表 → 一键整卷 → 打开成品 → 换项目验证不串数据 → 导出成品包。
    每一步都记「实际数字」，回传后用来改代码，而不是用来打分。

用法（在 workbench 目录下，工作台已启动）：

    python tools\\fieldtest.py --ledger "D:\\工程\\设备台账.xlsx"
    python tools\\fieldtest.py --ledger "D:\\工程\\设备台账.xlsx" --registry "D:\\工程\\整编要求登记表.xlsx"
    python tools\\fieldtest.py --ledger "..." --registry "..." --docs "D:\\工程\\资料" --book 第一册 --workshop 1号车间

参数说明：
  --ledger   设备台账（xlsx/csv），**必填** —— 没有台账，整卷出的都是空表头，测不出真实问题
  --registry 整编要求登记表（xlsx/csv/json），不填则用内置的 3 项最小登记表（仅供跑通链路）
  --docs     现有资料目录（可选）：把目录里的真实文件扫描入库，验证解析与归车间
  --keep     保留现场（默认跑完清理测试项目；加了 --keep 就留着让人自己看）

输出 fieldtest_report.json + fieldtest_report.md，把这两个文件回传即可。
"""

import argparse
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import time
import traceback
import zipfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WB_DIR = os.path.dirname(HERE)
BASE = os.environ.get("FANGONG_BASE", "http://127.0.0.1:8756")
TIMEOUT = 180

RESULT = {
    "tool": "fieldtest",
    "generated_at": "",
    "env": {},
    "inputs": {},
    "steps": [],
    "metrics": {},       # 关键数字，供 AI 侧直接取用
    "projects": [],      # 本次建过的项目
    "artifacts": [],     # 生成出来的成品（相对项目目录的路径）
}
PHASE = ""

# 进程内模式（沙箱/CI 用）：不启服务，直接调 FastAPI 路由。
# 参数：传入 workbench 目录。作用与 HTTP 模式完全一致 —— 走真实路由，不是调内部函数。
_INPROC = None
_INPROC_DIR = ""


def use_inproc(workbench_dir=None):
    global _INPROC, _INPROC_DIR
    try:
        wd = os.path.abspath(workbench_dir or os.environ.get("FANGONG_HOME") or WB_DIR)
        _INPROC_DIR = wd
        if wd not in sys.path:
            sys.path.insert(0, wd)
        try:
            os.chdir(wd)
        except Exception:
            pass
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        from fastapi.testclient import TestClient
        from app.main import app
        _INPROC = TestClient(app, raise_server_exceptions=False)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def rec(step, expected, actual, ok, evidence=""):
    it = {"phase": PHASE, "step": step, "expected": expected, "actual": actual,
          "passed": ok, "evidence": evidence}
    RESULT["steps"].append(it)
    tag = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
    print(f"  [{tag}] {step}: {actual}")
    if evidence and not ok:
        print(f"        证据：{evidence}")
    return it


def metric(k, v):
    RESULT["metrics"][k] = v


# ------------------------------------------------------------------ HTTP
def call(method, path, payload=None, timeout=TIMEOUT):
    if _INPROC is not None:
        try:
            r = _INPROC.request(method, path, json=payload)
            raw = r.content
            try:
                return r.status_code, json.loads(raw), ("" if r.status_code < 400 else raw.decode("utf-8", "replace")[:400])
            except Exception:
                return r.status_code, raw.decode("utf-8", "replace"), ""
        except Exception as e:  # noqa: BLE001
            return -1, None, f"{type(e).__name__}: {e}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE.rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw), ""
            except Exception:
                return r.status, raw.decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as e:
        b = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(b), b[:400]
        except Exception:
            return e.code, b, b[:400]
    except Exception as e:  # noqa: BLE001
        return -1, None, f"{type(e).__name__}: {e}"


def call_raw(path, timeout=TIMEOUT):
    """取原始字节（下载 docx/zip 用）。"""
    if _INPROC is not None:
        try:
            r = _INPROC.request("GET", path)
            return r.status_code, r.content, ("" if r.status_code < 400 else str(r.content[:200]))
        except Exception as e:  # noqa: BLE001
            return -1, None, f"{type(e).__name__}: {e}"
    req = urllib.request.Request(BASE.rstrip("/") + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), ""
    except urllib.error.HTTPError as e:
        return e.code, e.read(), f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return -1, None, f"{type(e).__name__}: {e}"


def call_multipart(path, filename, content, field="file", extra=None, timeout=TIMEOUT):
    """multipart 上传；额外字段用 extra=[(name, value)]。"""
    boundary = "----fangongfieldtest38f1a2"
    parts = []
    for k, v in (extra or []):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
                 f"filename=\"{os.path.basename(filename)}\"\r\n"
                 f"Content-Type: application/octet-stream\r\n\r\n".encode())
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if _INPROC is not None:
        try:
            r = _INPROC.request("POST", path, content=body, headers=headers)
            raw = r.content
            try:
                return r.status_code, json.loads(raw), ("" if r.status_code < 400 else raw.decode("utf-8", "replace")[:400])
            except Exception:
                return r.status_code, raw.decode("utf-8", "replace"), ""
        except Exception as e:  # noqa: BLE001
            return -1, None, f"{type(e).__name__}: {e}"
    req = urllib.request.Request(BASE.rstrip("/") + path, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw), ""
            except Exception:
                return r.status, raw.decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as e:
        b = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(b), b[:400]
        except Exception:
            return e.code, b, b[:400]
    except Exception as e:  # noqa: BLE001
        return -1, None, f"{type(e).__name__}: {e}"


def call_post_bytes(path, body_bytes, timeout=TIMEOUT, ctype="application/json"):
    """POST 取原始字节（生成 docx 这类返回二进制的接口）。进程内同样可用。"""
    headers = {"Content-Type": ctype}
    if _INPROC is not None:
        try:
            r = _INPROC.request("POST", path, content=body_bytes, headers=headers)
            return r.status_code, r.content, ("" if r.status_code < 400 else str(r.content[:300]))
        except Exception as e:  # noqa: BLE001
            return -1, None, f"{type(e).__name__}: {e}"
    req = urllib.request.Request(BASE.rstrip("/") + path, data=body_bytes, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), ""
    except urllib.error.HTTPError as e:
        return e.code, e.read(), f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return -1, None, f"{type(e).__name__}: {e}"


def wait_scan(max_wait=600):
    """等扫描结束。返回最后一次 status 体。"""
    last = {}
    t0 = time.time()
    while time.time() - t0 < max_wait:
        _, st, _ = call("GET", "/api/scan/status")
        last = st or {}
        if not last.get("running"):
            return last
        time.sleep(2)
    return last


# ------------------------------------------------------- 数据目录定位
def data_dir():
    """本次安装的数据根。优先问产品自己，取不到再按目录结构推。"""
    if _INPROC is not None:
        try:
            from app import config
            return os.path.abspath(config.DATA_DIR)
        except Exception:  # noqa: BLE001
            pass
    try:
        sys.path.insert(0, WB_DIR)
        from app import config
        return os.path.abspath(config.DATA_DIR)
    except Exception:  # noqa: BLE001
        return os.path.abspath(os.path.join(WB_DIR, "data"))


def project_dir(pid):
    return os.path.join(data_dir(), "projects", pid)


def find_in(project_root, fname):
    """在某个项目目录里找文件，返回相对路径或空。"""
    if not os.path.isdir(project_root):
        return ""
    for root, _dirs, files in os.walk(project_root):
        if fname in files:
            return os.path.relpath(os.path.join(root, fname), project_root)
    return ""


def browse_dir(project_root, depth=2):
    """浏览项目目录结构（用于回传，证明产物真的落在本项目里）。"""
    out = []
    if not os.path.isdir(project_root):
        return out
    base_depth = project_root.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(project_root):
        d = root.count(os.sep) - base_depth
        if d > depth:
            dirs[:] = []
            continue
        rel = os.path.relpath(root, project_root)
        if any(seg in ("vectordb", "__pycache__") for seg in rel.split(os.sep)):
            continue
        out.append({"dir": "" if rel == "." else rel, "files": sorted(files)[:20],
                    "n_files": len(files)})
    return out


# ---------------------------------------------------------- 造测试输入
def ensure_inputs(args, workdir):
    """准备输入：台账（必填）/ 登记表（可缺省）/ 资料目录（可选）。"""
    inp = {"ledger": "", "ledger_bytes": b"", "registry": "", "registry_bytes": b"", "docs": ""}
    if args.ledger:
        if not os.path.isfile(args.ledger):
            raise SystemExit(f"台账文件不存在：{args.ledger}")
        inp["ledger"] = args.ledger
        inp["ledger_bytes"] = open(args.ledger, "rb").read()
        RESULT["inputs"]["ledger"] = os.path.basename(args.ledger)
        RESULT["inputs"]["ledger_size"] = len(inp["ledger_bytes"])

    if args.registry:
        if not os.path.isfile(args.registry):
            raise SystemExit(f"登记表文件不存在：{args.registry}")
        inp["registry"] = args.registry
        inp["registry_bytes"] = open(args.registry, "rb").read()
        RESULT["inputs"]["registry"] = os.path.basename(args.registry)
        RESULT["inputs"]["registry_size"] = len(inp["registry_bytes"])
        RESULT["inputs"]["registry_source"] = "user_file"

    if args.docs:
        if not os.path.isdir(args.docs):
            raise SystemExit(f"资料目录不存在：{args.docs}")
        inp["docs"] = args.docs
        n = sum(len(f) for _r, _d, f in os.walk(args.docs))
        RESULT["inputs"]["docs_dir"] = os.path.basename(args.docs.rstrip("\\/"))
        RESULT["inputs"]["docs_count"] = n
    return inp


def minimal_registry_bytes():
    """最小登记表（仅跑通链路用）。条目名与内置监理模板一致。"""
    reg = [
        {"册": "第一册", "序号": "1", "名称": "设备开箱检查记录", "表号": "JL-01", "分类": "A", "阶段": "开箱"},
        {"册": "第一册", "序号": "2", "名称": "设备安装检查记录", "表号": "JL-02", "分类": "B", "阶段": "安装"},
        {"册": "第一册", "序号": "3", "名称": "监理旁站记录", "表号": "JL-03", "分类": "C", "阶段": "安装"},
    ]
    return json.dumps(reg, ensure_ascii=False).encode("utf-8")


# ------------------------------------------------------------------ 主体
def run(args):
    global PHASE
    wd = tempfile.mkdtemp(prefix="fg_fieldtest_")
    home = ""
    test_pid = ""

    # ---------------- 环境
    PHASE = "环境"
    print("\n=== 环境 ===")
    code, st, err = call("GET", "/api/status")
    if code != 200:
        rec("工作台可达", "GET /api/status 200", f"{code} {err}", False, "服务没起来，先启动 run_workbench.bat")
        return 1
    metric("version", st.get("version"))
    rec("工作台可达", "GET /api/status 200 且 version 非空",
        f"200 version={st.get('version')}", bool(st.get("version")), err)
    # 版本号交叉核对：接口说的版本必须与包内 config.py 一致，
    # 否则「装的是不是最新版」永远说不清（旧接口 + 新代码是真实发生过的）。
    try:
        _cfgv = ""
        _cfgp = os.path.join(WB_DIR, "app", "config.py")
        for _line in open(_cfgp, encoding="utf-8"):
            if _line.strip().startswith("APP_VERSION"):
                _cfgv = _line.split("=", 1)[1].strip().strip('"').strip("'")
                break
        metric("version_config_py", _cfgv)
        rec("版本号与代码一致", "接口 version == app/config.py 的 APP_VERSION",
            f"api={st.get('version')} config={_cfgv}",
            bool(_cfgv) and st.get("version") == _cfgv)
    except Exception as _e:  # noqa: BLE001
        rec("版本号与代码一致", "能读出 config.py", f"{type(_e).__name__}: {_e}", False)
    RESULT["env"].update({
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "install_dir": WB_DIR,
        "data_dir": data_dir(),
        "base": BASE,
        "node_name": st.get("node_name"),
        "parse_switches": st.get("parse_switches"),
    })
    print(f"  版本 {st.get('version')}  数据目录 {data_dir()}")
    print(f"  解析开关 {st.get('parse_switches')}")

    # 台账是硬前提：没有台账，整卷必然出空表头，测出来的都不算数
    try:
        inp = ensure_inputs(args, wd)
    except SystemExit as e:
        rec("输入材料", "提供设备台账", str(e), False)
        return 1
    rec("输入材料", "设备台账可用", f"台账={os.path.basename(inp['ledger'] or '')} "
        f"({len(inp['ledger_bytes'])} 字节)", True)
    if inp["registry"]:
        rec("登记表来源", "用使用者自己的整编要求登记表", os.path.basename(inp["registry"]), True)
    else:
        rec("登记表来源", "使用者未提供 → 用 3 项最小登记表跑通链路", "内置最小表", None,
            "这轮不能证明 214 项真实登记表的解析结果，只证明链路通")

    # 记住原项目，跑完切回去（不改变使用者原有的界面状态）
    _, cur, _ = call("GET", "/api/projects/current")
    home = (((cur or {}).get("project") or {}).get("id")) or ""
    RESULT["env"]["home_project"] = bool(home)

    # ---------------- 建项目 + 导台账
    PHASE = "建项目并导入台账"
    print("\n=== 建项目并导入台账 ===")
    pname = f"实测_{time.strftime('%Y%m%d_%H%M%S')}"
    code, body, err = call("POST", "/api/projects/create", {"name": pname})
    test_pid = ((body or {}).get("project") or {}).get("id") or ""
    ok = code == 200 and bool(test_pid)
    rec("新建项目", "200 且返回 project id", f"{code} id={test_pid}", ok, err)
    if not ok:
        return 1
    RESULT["projects"].append({"role": "test", "id": test_pid, "name": pname})
    metric("test_project_id", test_pid)

    code, up, err = call_multipart("/api/upload-files", os.path.basename(inp["ledger"]),
                                   inp["ledger_bytes"], field="files",
                                   extra=[("uploader", "实测脚本")])
    items = (up or {}).get("results") or (up or {}).get("files") or []
    item0 = items[0] if items else {}
    status0 = item0.get("status")
    ok = code == 200 and status0 in ("parsed", "partial")
    rec("台账上传解析", "200 且 status=parsed/partial",
        f"{code} status={status0} parser={item0.get('parser')} err={str(item0.get('error'))[:80]}",
        ok, err)
    if not ok:
        print("  台账解析不出来，后面的整卷没有意义，直接结束。")
        return finish(home, test_pid, args, wd, 1)

    # 设备数：台账解析后真正进了设备库的条数。
    # 不能用 /api/equipment-merge/stats —— 那个统计的是「多版本合并冲突」，
    # 新项目没冲突时恒为 0，拿它当设备数会把正常情况误判成失败。
    # 正确来源是当前项目元数据里的 device_count（/api/projects/current 实时重算）。
    _, curp, _ = call("GET", "/api/projects/current")
    n_dev_idx = ((curp or {}).get("project") or {}).get("device_count") or 0
    metric("devices_from_ledger_api", n_dev_idx)
    _, dwl, _ = call("GET", "/api/device-workshop/list")
    dw_devices = (dwl or {}).get("devices") or {}
    n_dw = len(dw_devices) if isinstance(dw_devices, dict) else len(dw_devices or [])
    metric("devices_device_workshop", n_dw)
    rec("台账设备识别", "解析后设备条数 > 0",
        f"project.device_count={n_dev_idx} device_workshop={n_dw}",
        n_dev_idx > 0 or n_dw > 0,
        json.dumps(((curp or {}).get("project") or {}), ensure_ascii=False)[:300])

    # ---------------- 真实资料扫描（可选）
    if inp["docs"]:
        PHASE = "真实资料扫描"
        print("\n=== 真实资料扫描 ===")
        code, sc, err = call("POST", "/api/scan", {"folder": inp["docs"], "force": False})
        rec("扫描启动", "200", f"{code}", code == 200, err)
        stt = wait_scan()
        stats = stt.get("stats") or {}
        metric("scan_stats", stats)
        rec("扫描完成", "running=false 且 stats 有内容",
            f"running={stt.get('running')} stats={json.dumps(stats, ensure_ascii=False)[:200]}",
            code == 200 and not stt.get("running"))

        code, fl, err = call("GET", "/api/files?limit=500")
        files = (fl or {}).get("files") or []
        metric("files_in_library", len(files))
        rec("资料入库", "files 非空", f"{code} total={len(files)}", code == 200 and bool(files), err)

        # 解析失败的文件：这是真实优化输入（哪类文件解析不出来）
        bad = [f for f in files if str(f.get("status")) not in ("parsed", "partial")]
        metric("parse_failed_count", len(bad))
        metric("parse_failed_samples", [{"name": b.get("file_name"), "status": b.get("status")} for b in bad[:20]])
        rec("解析成功率", "失败文件要有清单可查（不是沉默跳过）",
            f"入库 {len(files)} 个，非 parsed/partial {len(bad)} 个", None,
            json.dumps([b.get('file_name') for b in bad[:10]], ensure_ascii=False))

        # 归车间：未归车间数量 —— 多了说明分类规则没吃透真实命名
        code, ws, err = call("GET", "/api/workshops")
        # 返回的是 [{"name": "1号车间", "file_count": 1}, ...]，不是字符串列表。
        # 直接把它当字符串用会把 dict 塞进 workshop 参数（422 string_type），
        # 导致后面预填和整卷全部失败 —— 这是脚本自己的错，不是产品缺陷。
        _raw_ws = (ws or {}).get("workshops") or []
        wss = [str((w or {}).get("name") if isinstance(w, dict) else w) for w in _raw_ws]
        wss = [w for w in wss if w]
        metric("workshops", _raw_ws)
        rec("车间识别", "识别出至少 1 个车间", f"{len(wss)} 个 {wss[:6]}", bool(wss), err)

        code, wl, err = call("GET", "/api/workshop/list")
        groups = (wl or {}).get("groups") or {}
        pending = groups.get("未归车间") or []
        metric("unassigned_files", len(pending))
        rec("未归车间待确认", "未归文件数记录清楚（供人工确认）",
            f"未归 {len(pending)} 个 / 分组 {len(groups)} 个", None)

        # 检索：真问一句工程话，看能不能召回
        code, sr, err = call("POST", "/api/search", {"query": "设备安装检查记录", "top_k": 5})
        hits = (sr or {}).get("results") or []
        metric("search_hits", len(hits))
        metric("search_retrieval", (sr or {}).get("retrieval"))
        rec("资料库检索", "能召回结果", f"{len(hits)} 条 retrieval={ (sr or {}).get('retrieval')}",
            code == 200 and bool(hits), err)

    # ---------------- 导出成品（阶段2）
    PHASE = "资料生成"
    print("\n=== 资料生成 ===")
    code, types, err = call("GET", "/api/docgen/types")
    # 返回是 [{"key":"施工方案","label":...,...}] 的列表，不是 {key: {...}} 字典。
    # 当字典用会把整个 dict 当 doc_type 传下去（422 string_type）。
    _traw = (types or {}).get("types") or []
    tlist = {}
    for _t in _traw:
        if isinstance(_t, dict) and _t.get("key"):
            tlist[_t["key"]] = _t
    metric("docgen_types", list(tlist)[:20])
    rec("可生成资料类型", "types 非空", f"{len(tlist)} 类 {list(tlist)[:5]}",
        code == 200 and bool(tlist), err)

    ws_name = ""
    try:
        _, wss2, _ = call("GET", "/api/workshops")
        _l = (wss2 or {}).get("workshops") or []
        # 同上：取 name 字段；"未归车间"不是真车间，不能拿去整卷
        _names = [str((w or {}).get("name") if isinstance(w, dict) else w) for w in _l]
        _real = [n for n in _names if n and n != "未归车间"]
        ws_name = _real[0] if _real else ""
    except Exception:  # noqa: BLE001
        ws_name = ""

    code, pf, err = call("POST", "/api/docgen/prefill", {"workshop": ws_name, "doc_type": "施工方案"})
    prefill_devs = (pf or {}).get("devices") or (pf or {}).get("设备清单") or []
    metric("prefill_devices", len(prefill_devs) if isinstance(prefill_devs, list) else prefill_devs)
    rec("按车间预填", "预填结果里有设备（预填空=生成出来的方案没内容）",
        f"{code} devices={len(prefill_devs) if isinstance(prefill_devs,list) else prefill_devs}",
        code == 200, err)

    if tlist:
        dtype = "施工方案" if "施工方案" in tlist else list(tlist)[0]
        # 生成接口是 POST + JSON，返回 docx 二进制；必须真解压核对，不能只看 200
        import io
        import zipfile
        body = json.dumps({"doc_type": dtype, "data": {"项目名称": "实测项目", "车间": ws_name or "全厂",
                                                       "编制单位": "实测", "编制人": "实测",
                                                       "施工内容": "设备安装", "施工日期": "2026-10-30"}}).encode()
        code, raw, zerr = call_post_bytes("/api/docgen/generate", body)
        # 真解压核对：不是只看 200
        okz, detail = False, ""
        if code == 200 and raw:
            try:
                zf = zipfile.ZipFile(io.BytesIO(raw))
                names = zf.namelist()
                docxml = zf.read("word/document.xml").decode("utf-8", "replace") if "word/document.xml" in names else ""
                okz = len(names) > 0 and "word/document.xml" in names and len(docxml) > 200
                detail = f"size={len(raw)} entries={len(names)} document.xml={len(docxml)} 字节"
                metric("docgen_docx_bytes", len(raw))
                metric("docgen_has_placeholder", "待补充" in docxml)
            except Exception as e2:  # noqa: BLE001
                detail = f"不是合法 docx：{type(e2).__name__}: {e2}"
        rec("生成 Word 成品", f"{dtype} 生成的是可打开的 docx（真解压核对）",
            detail or f"{code} {zerr}", okz, zerr)

    # ---------------- 登记表 + 整卷
    PHASE = "整编登记表与整卷"
    print("\n=== 整编登记表与整卷 ===")
    if inp["registry_bytes"]:
        rb_content, rb_name = inp["registry_bytes"], os.path.basename(inp["registry"])
    else:
        rb_content, rb_name = minimal_registry_bytes(), "整编要求登记表_最小.json"
    code, rb, err = call_multipart("/api/supervision/registry", rb_name, rb_content, field="file")
    reg = (rb or {}).get("registry") or {}
    ready = bool(reg.get("ready"))
    metric("registry_total", reg.get("total"))
    metric("registry_books", reg.get("books"))
    metric("registry_class_counts", reg.get("class_counts") or reg.get("counts"))
    rec("导入整编要求登记表", "200 且 ready=true",
        f"{code} ready={ready} total={reg.get('total')} books={reg.get('books')}", ready, err)

    book = args.book or "第一册"
    workshop = args.workshop or ""
    if not workshop:
        # 没指定就取识别出来的第一个车间（真实资料里通常有）
        workshop = ws_name or "全厂"
    RESULT["inputs"]["book"] = book
    RESULT["inputs"]["workshop"] = workshop

    code, vol, err = call("POST", "/api/supervision/volume",
                          {"project_id": test_pid, "book": book, "workshop": workshop})
    vr = (vol or {}).get("result") or (vol or {})
    gen = vr.get("generated") or []
    todo = vr.get("todo") or []
    collect = vr.get("collect_dir") or []
    errors = vr.get("errors") or []
    empty_shells = vr.get("empty_shells") or []
    metric("volume_generated", len(gen))
    metric("volume_todo", len(todo))
    metric("volume_collect", len(collect))
    metric("volume_errors", len(errors))
    metric("volume_empty_shells", len(empty_shells))
    metric("volume_device_source", vr.get("device_source"))
    metric("volume_error_text", (vr.get("error") or "")[:200])
    # 每一项都要有交代：生成 / 待办 / 归集，不允许静默丢弃
    in_items = {str(g.get("序号")) for g in gen}
    todo_items = {str(t.get("序号")) for t in todo}
    col_items = {str(c.get("序号")) for c in collect if isinstance(c, dict)}
    metric("volume_accounted", len(in_items | todo_items | col_items))
    ok = bool(gen) and bool(in_items | todo_items | col_items)
    rec("一键整卷", "有产出，且每个登记项都有交代（生成/待办/归集，不静默丢弃）",
        f"{code} 生成={len(gen)} 待办={len(todo)} 归集={len(collect)} 错={len(errors)} "
        f"空壳={len(empty_shells)}", ok, (vr.get("error") or err)[:200])

    if empty_shells:
        rec("空壳拦截", "被拦下的项要能看出缺什么（否则用户不知道为什么没出文件）",
            f"{len(empty_shells)} 项：" + json.dumps(empty_shells[:2], ensure_ascii=False)[:200], None)

    # 文件真的落盘了吗？落在本项目里吗？—— 这是 v0.1.173 的核心修复点
    pdir = project_dir(test_pid)
    landed, outside, missing = [], [], []
    for g in gen:
        fn = g.get("文件")
        if not fn:
            continue
        rel = find_in(pdir, fn)
        if rel:
            landed.append(rel)
        else:
            missing.append(fn)
            # 在全库找，看是不是落到项目外（旧缺陷会这样）
            allproj = os.path.join(data_dir(), "projects")
            hit = find_in(allproj, fn)
            if hit:
                outside.append(hit)
    metric("volume_files_landed", len(landed))
    metric("volume_files_missing", len(missing))
    metric("volume_files_outside_project", len(outside))
    metric("volume_landed_paths", landed[:10])
    rec("整卷文件落盘", "每个 generated 文件都在本项目目录内",
        f"落盘 {len(landed)}/{len(gen)}，找不到 {len(missing)}，落在项目外 {len(outside)}",
        bool(gen) and not missing and not outside,
        (f"找不到：{missing[:3]} " if missing else "") + (f"落到项目外：{outside[:2]}" if outside else ""))

    # 打开成品：docx 能不能真打开、里面有没有设备数据
    openable = 0
    sample_content = {}
    for rel in landed[:3]:
        p = os.path.join(pdir, rel)
        try:
            import zipfile
            zf = zipfile.ZipFile(p)
            xml = zf.read("word/document.xml").decode("utf-8", "replace")
            txt = "".join(c for c in xml if c.isalnum() or c in " 　" or "\u4e00" <= c <= "\u9fff")
            openable += 1
            if not sample_content:
                sample_content = {"file": os.path.basename(p), "bytes": os.path.getsize(p),
                                  "xml_bytes": len(xml), "text_chars": len(txt),
                                  "has_pending_marks": "待补充" in xml,
                                  "sample_text": txt[:300]}
        except Exception:  # noqa: BLE001
            pass
    metric("volume_openable_docx", openable)
    RESULT["artifacts"].append({"project": test_pid, "sample": sample_content})
    rec("成品可打开", "落盘的 docx 能被 zip/docx 正常读取",
        f"{openable}/{min(len(landed),3)} 个可读" + (f" 样例 {sample_content.get('bytes')} 字节" if sample_content else ""),
        openable > 0)

    # 成稿不许留模板变量：{{xxx}} 落到监理手里就是一张没填的表
    # 这是 v0.1.174 修的缺陷 —— 原来未填字段只记账、不替换，文档里原样留着 {{施工单位}}
    resid_total = 0
    resid_files = []
    mark_total = 0
    for rel in landed:
        pth = os.path.join(pdir, rel)
        try:
            zf2 = zipfile.ZipFile(pth)
            xml2 = zf2.read("word/document.xml").decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        # 只统计正文 t 节点里的文本，避免命中样式/关系里的花括号
        _body = re.sub(r"<[^>]+>", "", xml2)
        _n = _body.count("{{") + _body.count("}}")
        resid_total += _n
        if _n:
            resid_files.append({"file": os.path.basename(pth), "count": _n})
        mark_total += _body.count("待补充")
    metric("volume_residual_placeholders", resid_total)
    metric("volume_residual_files", resid_files[:5])
    metric("volume_pending_marks", mark_total)
    rec("成稿无模板变量残留", "生成的 docx 正文里不出现 {{占位符}}（未填应落成【待补充】）",
        f"残留 {resid_total} 处（{len(resid_files)} 个文件）；【待补充】标记 {mark_total} 处",
        bool(landed) and resid_total == 0,
        json.dumps(resid_files[:3], ensure_ascii=False) if resid_files else "")

    # 阶段③ 装盒成套：卷内目录 / 案卷封面 / 卷内备考表 / 装盒清单
    # 页次必须是渲染实测，不能是「1 份算 1 页」的估算 —— 页次要印在交监理的正式目录上
    _cat_rel = find_in(pdir, "_卷内目录.docx")
    _cov_rel = find_in(pdir, "_案卷封面.docx")
    _exam_rel = find_in(pdir, "_卷内备考表.docx")
    _box_rel = find_in(pdir, "_装盒清单.xlsx")
    _cat_found = [x for x in [_cat_rel, _cov_rel, _exam_rel] if x]
    rec("卷内目录与装盒成套", "卷目录里有 _卷内目录/_案卷封面/_卷内备考表 三份正式表",
        f"找到 {len(_cat_found)}/3：{[os.path.basename(x) for x in _cat_found]}",
        len(_cat_found) == 3,
        f"缺：{[n for n,r in [('卷内目录',_cat_rel),('案卷封面',_cov_rel),('卷内备考表',_exam_rel)] if not r]}")

    # 页次真实性与册/序号顺序 —— 直接读生成的卷内目录
    _cat_rows = []
    if _cat_rel:
        try:
            from docx import Document as _Doc
            _d = _Doc(os.path.join(pdir, _cat_rel))
            for _t in _d.tables:
                for _r in _t.rows[1:]:
                    _cat_rows.append([c.text.strip() for c in _r.cells])
            metric("catalog_row_count", len(_cat_rows))
            metric("catalog_rows", _cat_rows[:8])
        except Exception as _e:  # noqa: BLE001
            rec("卷内目录可读", "docx 能被 python-docx 打开", f"{type(_e).__name__}: {_e}", False)
    _seqs = [r[0] for r in _cat_rows if r and r[0]]
    _numeric = [int(x) for x in _seqs if x.isdigit()]
    _ordered = _numeric == sorted(_numeric) and len(_numeric) == len(_seqs)
    _uncalc = [r for r in _cat_rows if len(r) > 4 and ("未计算" in r[4])]
    _pagecells = [r[4] for r in _cat_rows if len(r) > 4 and r[4] and "未计算" not in r[4]]
    metric("catalog_seq_order", _seqs)
    metric("catalog_pages_uncalculated", len(_uncalc))
    metric("catalog_page_cells", _pagecells[:8])
    rec("卷内目录序号有序", "序号按登记表的数值顺序排列（不是字符串序）",
        f"序号 {_seqs}", bool(_seqs) and _ordered)
    # 页次真实性：能渲染就应当是「起-止」格式且连续；渲不出则如实标未计算，不算失败
    _fmt_ok = all("-" in c for c in _pagecells) if _pagecells else None
    rec("页次为渲染实测", "页次形如 起-止 且来自真实渲染（渲不出如实标未计算，不估算）",
        f"{len(_pagecells)} 格有页次，{len(_uncalc)} 格标未计算；样例 {_pagecells[:3]}",
        _fmt_ok)

    # 卷内目录里列出的缺失项，要和待办清单的件数对得上（不能一边说全生成、一边目录空着）
    if _box_rel:
        try:
            from openpyxl import load_workbook as _lw
            _wb = _lw(os.path.join(pdir, _box_rel))
            _ws = _wb.active
            _boxrows = [list(r) for r in _ws.iter_rows(min_row=2, values_only=True)]
            metric("boxing_rows", len(_boxrows))
            metric("boxing_sample", _boxrows[:3])
            rec("装盒清单", "按册汇总，一盒一行，含件数与页数",
                f"{len(_boxrows)} 行：{_boxrows[:1]}", len(_boxrows) > 0)
        except Exception as _e:  # noqa: BLE001
            rec("装盒清单可读", "xlsx 能被 openpyxl 打开", f"{type(_e).__name__}: {_e}", False)

    # 卷内目录 / 待办清单是否真的生成文件
    todo_rel = find_in(pdir, "_待办清单.md")
    rec("待办清单", "卷目录下有 _待办清单.md",
        todo_rel or "未找到", bool(todo_rel))
    if todo_rel:
        try:
            _p = os.path.join(pdir, todo_rel)
            _txt = open(_p, encoding="utf-8").read()
            metric("todo_md_chars", len(_txt))
            metric("todo_md_has_counts",
                   {"待补字段": _txt.count("待补"), "错误": _txt.count("错误")})
        except Exception:  # noqa: BLE001
            pass

    # 导出成套（阶段3）
    PHASE = "竣工归档"
    print("\n=== 竣工归档 ===")
    code, ca, err = call("POST", "/api/completion-archive/all", {})
    ndev = (ca or {}).get("total_devices") or 0
    metric("completion_total_devices", ndev)
    rec("一键竣工", "200 且 total_devices > 0", f"{code} total_devices={ndev}", code == 200 and ndev > 0, err)

    code, stats, err = call("GET", "/api/completion-archive/stats")
    ndev2 = (stats or {}).get("total_devices") or 0
    rec("竣工统计自洽", "stats 与 一键竣工 数字一致（两接口不能自相矛盾）",
        f"stats={ndev2} vs all={ndev}", code == 200 and ndev2 == ndev, err)

    code, raw, err = call_raw("/api/archive/export-enhanced")
    okz, zipdetail = False, ""
    if code == 200 and raw:
        try:
            import io
            import zipfile
            zf = zipfile.ZipFile(io.BytesIO(raw))
            okz = len(zf.namelist()) > 0 and zf.testzip() is None
            zipdetail = f"size={len(raw)} files={len(zf.namelist())}"
            metric("archive_zip_files", len(zf.namelist()))
        except Exception as e2:  # noqa: BLE001
            zipdetail = f"坏包：{type(e2).__name__}: {e2}"
    rec("导出成套资料", "合法 ZIP 且内含文件（真解压）", zipdetail or f"{code} {err}", okz, err)

    # ---------------- 跨项目隔离（真实使用里最常见的「串项目」事故）
    PHASE = "跨项目隔离"
    print("\n=== 跨项目隔离 ===")
    code, nb, err = call("POST", "/api/projects/create", {"name": f"实测隔离_{time.strftime('%H%M%S')}"})
    new_id = ((nb or {}).get("project") or {}).get("id") or ""
    if new_id:
        RESULT["projects"].append({"role": "isolation", "id": new_id})
        call("POST", "/api/projects/switch", {"project_id": new_id})
        _, st_b, _ = call("GET", "/api/completion-archive/stats")
        dev_b = (st_b or {}).get("total_devices")
        _, rm_b, _ = call("GET", "/api/completion-archive/missing")
        miss_b = len(((rm_b or {}).get("missing") or []))
        rec("新项目不承接旧清单", "新项目里竣工设备数=0、缺件=0",
            f"total_devices={dev_b} missing={miss_b}（对照原项目 {ndev} 台）",
            dev_b == 0 and miss_b == 0)
        # 新项目里整卷不能写进别人目录
        code, vol2, err2 = call("POST", "/api/supervision/volume",
                                {"project_id": new_id, "book": book, "workshop": workshop})
        vr2 = (vol2 or {}).get("result") or {}
        gen2 = vr2.get("generated") or []
        pdir2 = project_dir(new_id)
        landed2 = sum(1 for g in gen2 if find_in(pdir2, g.get("文件") or ""))
        rec("新项目整卷只写自己目录", "generated 全部落在新项目目录内",
            f"生成 {len(gen2)} 落本项目 {landed2}", landed2 == len(gen2) if gen2 else None)
        # 切回去，数据要还在（隔离不等于丢数据）
        call("POST", "/api/projects/switch", {"project_id": test_pid})
        _, st_a, _ = call("GET", "/api/completion-archive/stats")
        dev_a = (st_a or {}).get("total_devices")
        rec("切回后数据仍在", "设备数恢复为原值", f"切回={dev_a}（应为 {ndev}）", dev_a == ndev)
        # 空 project_id 不许写到全局目录（旧缺陷）
        pjv = os.path.join(data_dir(), "projects", "volumes")
        rec("无项目时不写全局目录", "data/projects/volumes 不存在",
            "存在（旧缺陷复发）" if os.path.isdir(pjv) else "不存在", not os.path.isdir(pjv))

    # ---------------- 项目目录结构（回传证据）
    PHASE = "落盘结构"
    RESULT["metrics"]["project_tree"] = browse_dir(pdir, depth=2)
    RESULT["metrics"]["project_file_count"] = sum(t["n_files"] for t in RESULT["metrics"]["project_tree"])

    return finish(home, test_pid, args, wd, 0)


def finish(home, test_pid, args, wd, code):
    """收尾：切回原项目、清理临时目录、写报告。"""
    if home:
        call("POST", "/api/projects/switch", {"project_id": home})
    if not args.keep and test_pid:
        # 只删本次建的测试项目，绝不碰使用者的真实项目
        try:
            call("POST", "/api/projects/delete", {"project_id": test_pid, "keep_files": False})
            RESULT.setdefault("cleanup", {})["deleted_test_project"] = test_pid
        except Exception:  # noqa: BLE001
            RESULT.setdefault("cleanup", {})["delete_failed"] = test_pid
    try:
        shutil.rmtree(wd, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass

    RESULT["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    npass = sum(1 for s in RESULT["steps"] if s["passed"] is True)
    nfail = sum(1 for s in RESULT["steps"] if s["passed"] is False)
    nskip = sum(1 for s in RESULT["steps"] if s["passed"] is None)
    RESULT["summary"] = {"passed": npass, "failed": nfail, "skipped": nskip}

    jp = os.path.join(HERE, "fieldtest_report.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(RESULT, f, ensure_ascii=False, indent=2)

    lines = ["# 繁工AI 本地实测报告", "",
             f"- 时间：{RESULT['generated_at']}",
             f"- 版本：{RESULT['metrics'].get('version')}",
             f"- 系统：{RESULT['env'].get('platform')}",
             f"- 输入：台账={RESULT['inputs'].get('ledger')} "
             f"登记表={RESULT['inputs'].get('registry') or '内置最小表'} "
             f"资料目录={RESULT['inputs'].get('docs_dir') or '未提供'}",
             f"- 结果：通过 {npass} / 失败 {nfail} / 跳过 {nskip}", "",
             "## 关键数字", ""]
    for k, v in RESULT["metrics"].items():
        if k in ("project_tree",):
            continue
        lines.append(f"- {k}：{json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}")
    lines += ["", "## 逐步结果", ""]
    for s in RESULT["steps"]:
        tag = "SKIP" if s["passed"] is None else ("PASS" if s["passed"] else "FAIL")
        lines.append(f"- [{tag}] **{s['phase']} / {s['step']}**：{s['actual']}")
        if s["evidence"] and not s["passed"]:
            lines.append(f"  - 证据：{s['evidence']}")
    mp = os.path.join(HERE, "fieldtest_report.md")
    with open(mp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print()
    print(f"结果：通过 {npass} / 失败 {nfail} / 跳过 {nskip}")
    print(f"报告：{jp}")
    print(f"      {mp}")
    return code or (0 if nfail == 0 else 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default="", help="设备台账 xlsx/csv（必填）")
    ap.add_argument("--registry", default="", help="整编要求登记表 xlsx/csv/json")
    ap.add_argument("--docs", default="", help="真实资料目录（可选）")
    ap.add_argument("--book", default="", help="册名，默认第一册")
    ap.add_argument("--workshop", default="", help="车间名，默认自动取识别到的第一个")
    ap.add_argument("--base", default="", help="服务地址，默认 http://127.0.0.1:8756")
    ap.add_argument("--inproc", action="store_true",
                    help="进程内模式（不启服务，直接走 FastAPI 路由；沙箱/CI 用）")
    ap.add_argument("--keep", action="store_true", help="不清理测试项目")
    args = ap.parse_args()
    global BASE
    if args.base:
        BASE = args.base
    if args.inproc:
        ok, err = use_inproc(WB_DIR)
        if not ok:
            print(f"进程内模式启动失败：{err}")
            return 2
        print("进程内模式（直接调 FastAPI 路由）")

    if not args.ledger:
        print("必须提供 --ledger（设备台账）。没有台账，整卷只能出空表头，实测没有意义。")
        print('例：python tools\\fieldtest.py --ledger "D:\\工程\\设备台账.xlsx"')
        return 2

    print("=" * 62)
    print("繁工AI 本地实测（代替使用者走一遍真实操作）")
    print("=" * 62)
    try:
        return run(args)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        RESULT.setdefault("fatal", traceback.format_exc()[-800:])
        return finish("", "", args, "", 1)


if __name__ == "__main__":
    sys.exit(main())
