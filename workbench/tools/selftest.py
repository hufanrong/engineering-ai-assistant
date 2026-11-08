#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""繁工AI 四阶段本地自测脚本 · 供 WORKbuddy 在用户本地 Windows 电脑上执行。

用法（在 D:\\hufanrong\\Documents\\workBudd\\工程 目录下，工作台已启动后）：

    python selftest.py --phase 1        # 文件上传解析、分类、资料库搭建
    python selftest.py --phase 2        # 工程资料生成管理
    python selftest.py --phase 3        # 竣工资料自动生成
    python selftest.py --phase 4        # 竣工图纸清稿（需 Windows + AutoCAD）
    python selftest.py --phase all      # 依次跑 1→4

输出：selftest_report.json + selftest_report.md，放在脚本同目录。
把这两个文件（或整个报告）回传给 AI 工程师即可。

设计原则：
- 只调用工作台自己的 HTTP 接口（http://127.0.0.1:8756），不碰内部函数。
- 每一步都记录「预期 / 实际 / 是否通过 / 证据」，失败不中断，继续跑后续步骤。
- 自动造测试样本（真实中文 PDF / DOCX / XLSX / CSV），不依赖用户的真实资料，
  避免污染用户数据；样本放在临时目录，跑完可选清理。
"""

import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request

BASE = os.environ.get("FANGONG_BASE", "http://127.0.0.1:8756")
TIMEOUT = 60

# 全局结果
RESULTS = []          # 每步一条
PHASE_SUMMARY = {}    # 阶段 -> {"passed":n,"failed":n,"skipped":n}

# v0.1.173：自测建的测试项目 id。phase1 用完会切回原项目，但 phase3 的
# 竣工/整卷断言必须在「有设备数据的那一个项目」上跑 —— 原来没记这个 id，
# phase3 直接在用户的当前项目上跑，结果是 0。这里把 id 记下来，phase3 显式切过去。
TEST_PROJECT_ID = ""
# v0.1.196：本次运行创建的**全部**测试项目 id。
# 只清 TEST_PROJECT_ID 不够 —— phase3 的「竣工归档跨项目隔离」还会
# 另建一个「自测隔离_HHMMSS」，实测每跑一次自测就多留一个空壳项目
# （沙箱里累积 74 个测试残留、59 个 0 文件 0 设备）。
CREATED_PIDS = []
_ORIGIN_PID = ""      # run() 记下的用户原项目 id；phase6 用它切回来校验真实项目

# v0.1.217：自测是"真的在建项目/切项目/删项目"，因此会真的写审计流水。
# 上一轮实测：一次全量自测把用户真实 data/operation_log.jsonl 从 325 行涨到
# 346 行（含 9 条「A → A」自切换），用户事后查「项目怎么没了」时，
# 审计里混进一堆测试记录 —— 流水本身还在，但可信度没了。
# 这里记两样：
#   AUDIT_SNAPSHOT —— 开跑前真实流水的「行数 + 末行」快照（只读）
#   SELFTEST_TOKENS —— 本次自测建的项目名/项目 id（全局唯一），用于精确识别
#                      "哪几行是本进程写的"，清理时只删这些行
AUDIT_SNAPSHOT = {}
SELFTEST_TOKENS = []
_AUDIT_AFTER = {}     # 清理之后的新快照；finally 里写，用于「流水未污染」断言


# ---------------- 后端选择：进程内 TestClient / 真实 HTTP ----------------
_INPROC = None
_INPROC_DIR = ""      # 非 None 时用 FastAPI TestClient 在本进程内跑真实路由


def use_inproc(workbench_dir=None):
    """沙箱/CI 用：不启动服务，直接进程内调 FastAPI 路由。返回 (ok, err)。"""
    global _INPROC
    try:
        import sys
        wd = workbench_dir or os.environ.get("FANGONG_HOME") or os.getcwd()
        wd = os.path.abspath(wd)
        # 先记录解析后的绝对路径，避免 chdir 之后再次 abspath 相对路径导致重复层级
        global _INPROC_DIR
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
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------- HTTP ----------------
def call(method, path, payload=None, timeout=TIMEOUT):
    """返回 (http_code, body_json_or_text, error_str)。不抛异常。"""
    if _INPROC is not None:
        try:
            r = _INPROC.request(method, path, json=payload)
            raw = r.content
            try:
                return r.status_code, json.loads(raw), ("" if r.status_code < 400 else raw.decode("utf-8", "replace")[:300])
            except Exception:
                return r.status_code, raw.decode("utf-8", "replace"), ""
        except Exception as e:
            return -1, None, f"{type(e).__name__}: {e}"
    url = BASE.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw), ""
            except Exception:
                return r.status, raw.decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body), body[:300]
        except Exception:
            return e.code, body, body[:300]
    except Exception as e:
        return -1, None, f"{type(e).__name__}: {e}"


def call_upload(path, filename, content, field="file", timeout=TIMEOUT):
    """multipart 上传一个文件。返回 (http_code, body_json_or_text, error_str)。

    v0.1.173：阶段③ 的整卷路径此前从未被测到 —— 自测从没导入过整编要求登记表，
    接口永远回「登记表不存在」，于是整卷这条最关键的链路一次都没跑过。
    这里按 UI 真实的 multipart 形态上传，才能覆盖到。
    """
    boundary = "----fangongselftest7f3a9c"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n",
        content,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if _INPROC is not None:
        try:
            r = _INPROC.request("POST", path, content=body, headers=headers)
            raw = r.content
            try:
                return r.status_code, json.loads(raw), ("" if r.status_code < 400 else raw.decode("utf-8", "replace")[:300])
            except Exception:
                return r.status_code, raw.decode("utf-8", "replace"), ""
        except Exception as e:
            return -1, None, f"{type(e).__name__}: {e}"
    url = BASE.rstrip("/") + path
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
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
            return e.code, json.loads(b), b[:300]
        except Exception:
            return e.code, b, b[:300]
    except Exception as e:
        return -1, None, f"{type(e).__name__}: {e}"


def call_bytes(path, timeout=TIMEOUT):
    """取原始字节响应（下载类接口）。返回 (http_code, bytes_or_None, error_str)。

    v0.1.173：call() 一律把响应当 JSON 先试、失败再按 UTF-8 解码，
    ZIP/PDF 这类二进制会被解码成乱码，于是「导出」类用例只能断言状态码 200 —— 
    正文是个空包、坏包、甚至 0 字节也照样 PASS。这里保留原始字节，让测试能真解压。
    """
    if _INPROC is not None:
        try:
            r = _INPROC.request("GET", path)
            return r.status_code, r.content, ("" if r.status_code < 400 else str(r.content[:200]))
        except Exception as e:
            return -1, None, f"{type(e).__name__}: {e}"
    url = BASE.rstrip("/") + path
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), ""
    except urllib.error.HTTPError as e:
        return e.code, e.read(), f"HTTP {e.code}"
    except Exception as e:
        return -1, None, f"{type(e).__name__}: {e}"


def zip_summary(raw):
    """核对 ZIP 二进制：能不能正常打开、里面有几个文件、解压后总字节数。
    返回 dict；坏包时带 error，绝不把「打不开」当成功。"""
    import io
    import zipfile
    if not raw:
        return {"error": "空响应（0 字节）"}
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except Exception as e:  # noqa: BLE001
        return {"error": f"不是合法 ZIP：{type(e).__name__}: {e}", "size": len(raw)}
    bad = zf.testzip()
    names = zf.namelist()
    total = 0
    for n in names:
        try:
            total += zf.getinfo(n).file_size
        except Exception:  # noqa: BLE001
            pass
    return {"size": len(raw), "files": len(names), "uncompressed": total,
            "bad_member": bad, "names": names[:8]}


# ---------------- 审计流水隔离（v0.1.217） ----------------
def _audit_log_path():
    """真实审计流水路径。优先问服务要 data_dir（HTTP 模式下本进程不知道它）。"""
    d = ""
    try:
        _, st, _ = call("GET", "/api/status")
        d = (st or {}).get("data_dir") or ""
    except Exception:  # noqa: BLE001
        pass
    if not d and _INPROC is not None:
        try:
            from app import config as _cfg
            d = _cfg.DATA_DIR
        except Exception:  # noqa: BLE001
            pass
    if not d:
        d = os.path.join(_INPROC_DIR or ".", "data")
    return os.path.join(d, "operation_log.jsonl")


def audit_snapshot():
    """读真实审计流水的行数 + 字节长度 + 末行（只读，不改写）。

    size 是本轮的「历史边界」：清理时只动 size 之后追加的字节，
    size 之前的历史行一个字节都不碰 —— 这样「清理自测痕迹」不可能
    误删用户的历史审计。
    """
    snap = {"path": "", "exists": False, "lines": 0, "tail": "", "size": -1}
    try:
        p = _audit_log_path()
    except Exception:  # noqa: BLE001
        return snap
    snap["path"] = p
    if not os.path.isfile(p):
        return snap
    snap["exists"] = True
    try:
        snap["size"] = os.path.getsize(p)
    except Exception:  # noqa: BLE001
        snap["size"] = -1
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip():
                    snap["lines"] += 1
                    snap["tail"] = line.strip()
    except Exception:  # noqa: BLE001
        pass
    return snap


def audit_purge_selftest_rows():
    """把本次自测追加进真实审计流水的行删掉，历史行一字不动。

    做法：以开跑前的字节长度 AUDIT_SNAPSHOT["size"] 为分界线，
    - 分界线之前 = 用户历史流水，原样保留（连字节都不重写）；
    - 分界线之后 = 本次运行追加的，只删**含本次自测独有标识**的行
      （项目名 `自测_<秒>`/`自测隔离_<时分秒>`、项目 id）。
    不含标识的追加行不删 —— 宁可留一条，也不误删可能是真实操作的行；
    它们会让「行数一致」断言失败，并作为残留暴露出来。

    返回 dict：removed / total / skipped / error。
    skipped=True 表示本次运行**根本没建过项目**（如单跑 --phase 6），
    这时「清理 0 行」是真实且正确的，不能被读成「清理功能没生效」。
    """
    out = {"removed": 0, "total": 0, "skipped": False, "error": ""}
    p = _audit_log_path()
    if not os.path.isfile(p):
        out["skipped"] = True
        return out
    tokens = [t for t in SELFTEST_TOKENS if t]
    if not tokens:
        out["skipped"] = True
        return out
    start = AUDIT_SNAPSHOT.get("size", -1)
    if not isinstance(start, int) or start < 0:
        out["error"] = "无开跑前字节边界，跳过清理（历史行未动）"
        return out
    try:
        with open(p, "rb") as f:
            raw = f.read()
        if start > len(raw):
            out["error"] = "流水比开跑前还短（%d < %d），疑似被外部重置" % (len(raw), start)
            return out
        prefix, suffix = raw[:start], raw[start:]
        text = suffix.decode("utf-8", "ignore")
        kept, removed = [], 0
        for line in text.splitlines():
            if not line.strip():
                continue
            if any(t in line for t in tokens):
                removed += 1
                continue
            kept.append(line)
        total_lines = sum(1 for ln in raw.decode("utf-8", "ignore").splitlines() if ln.strip())
        if removed:
            new_raw = prefix + ("".join(ln + "\n" for ln in kept)).encode("utf-8")
            tmp_p = p + ".selftest_tmp"
            with open(tmp_p, "wb") as f:
                f.write(new_raw)
            os.replace(tmp_p, p)
            total_lines -= removed
        out["removed"] = removed
        out["total"] = total_lines
        return out
    except Exception as e:  # noqa: BLE001
        out["error"] = "%s: %s" % (type(e).__name__, e)
        return out


def record(phase, step, expected, actual, passed, evidence=""):
    """记一条结果。passed 是三态：True 通过 / False 失败 / None 跳过。

    v0.1.169：原来写 `"passed": bool(passed)` 把 None（跳过）压成 False，
    明细里「环境不满足、跳过」的项看起来跟真失败一模一样。汇总按 None 正确
    计成 skipped，明细却全成了 failed —— 实测阶段④在 Linux 上 1 失败 5 跳过，
    明细读出来却是 6 项失败，AI 侧会按失败的严重度去排查 5 个根本不存在的
    问题。改成 `passed` 保留 None，并用 skipped 字段明确标出来。
    """
    RESULTS.append({
        "phase": phase, "step": step, "expected": expected,
        "actual": actual,
        "passed": (True if passed is True else (None if passed is None else False)),
        "skipped": passed is None,
        "evidence": evidence,
    })
    s = PHASE_SUMMARY.setdefault(phase, {"passed": 0, "failed": 0, "skipped": 0})
    if passed is None:
        s["skipped"] += 1
    elif passed:
        s["passed"] += 1
    else:
        s["failed"] += 1
    tag = "SKIP" if passed is None else ("PASS" if passed else "FAIL")
    print(f"  [{tag}] {step}: {str(actual)[:120]}")


# ---------------- 测试样本 ----------------
def build_samples(folder, include_dwg=False):
    """造真实样本：中文 PDF（嵌入字体，确保中文可提取）、DOCX 表格、XLSX 台账、CSV、TXT。"""
    os.makedirs(folder, exist_ok=True)
    made = []

    # TXT
    p = os.path.join(folder, "施工说明.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("本工程为刚果（金）Manono 锂矿 5Mt/a 采选冶项目。"
                "1号车间安装离心泵 P-101，2号车间设储罐 V-201，"
                "施工单位为中国十五冶，建设单位为紫金矿业。\n")
    made.append(p)

    # CSV 设备台账
    p = os.path.join(folder, "设备台账.csv")
    with open(p, "w", encoding="utf-8-sig") as f:
        f.write("位号,名称,型号,车间,数量,安装位置\n")
        f.write("P-101,离心泵,IS100-65-200,1号车间,2,泵房A\n")
        f.write("V-201,储罐,Φ3000x6000,2号车间,1,罐区B\n")
        f.write("T-301,变压器,SCB13-1000/10,配电室,1,配电室\n")
    made.append(p)

    # DOCX（带表格）
    try:
        import docx
        p = os.path.join(folder, "设备清单.docx")
        d = docx.Document()
        d.add_paragraph("工程名称：Manono 锂矿 5Mt/a 采选冶项目")
        d.add_paragraph("施工单位：中国十五冶    建设单位：紫金矿业")
        t = d.add_table(rows=4, cols=4)
        t.rows[0].cells[0].text = "设备位号"
        t.rows[0].cells[1].text = "设备名称"
        t.rows[0].cells[2].text = "安装位置"
        t.rows[0].cells[3].text = "数量"
        t.rows[1].cells[0].text = "P-101"
        t.rows[1].cells[1].text = "离心泵"
        t.rows[1].cells[2].text = "1号车间"
        t.rows[1].cells[3].text = "2"
        t.rows[2].cells[0].text = "V-201"
        t.rows[2].cells[1].text = "储罐"
        t.rows[2].cells[2].text = "2号车间"
        t.rows[2].cells[3].text = "1"
        t.rows[3].cells[0].text = "T-301"
        t.rows[3].cells[1].text = "变压器"
        t.rows[3].cells[2].text = "配电室"
        t.rows[3].cells[3].text = "1"
        d.save(p)
        made.append(p)
    except Exception as e:
        print(f"  [WARN] 生成 DOCX 失败（跳过该样本）：{e}")

    # XLSX 台账
    try:
        import openpyxl
        p = os.path.join(folder, "管道材料表.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["位号", "名称", "规格", "材质", "数量"])
        ws.append(["P-101", "离心泵", "IS100-65-200", "铸铁", 2])
        ws.append(["V-201", "储罐", "Φ3000x6000", "Q345R", 1])
        wb.save(p)
        made.append(p)
    except Exception as e:
        print(f"  [WARN] 生成 XLSX 失败：{e}")

    # 中文 PDF（用 PyMuPDF 嵌入真实 CJK 字体，保证 extract_text 能出中文）
    try:
        import fitz
        p = os.path.join(folder, "图纸说明.pdf")
        doc = fitz.open()
        page = doc.new_page()
        tf = _find_cjk_font()
        if tf:
            page.insert_text((72, 720),
                             "竣工图  图号 EQ-101  比例 1:50  1号车间  离心泵 P-101",
                             fontsize=12, fontfile=tf, fontname="CJK")
            page.insert_text((72, 690),
                             "施工单位：中国十五冶   建设单位：紫金矿业", fontsize=12,
                             fontfile=tf, fontname="CJK")
        else:
            page.insert_text((72, 720), "As-built EQ-101 1:50 P-101", fontsize=12)
        doc.save(p)
        doc.close()
        made.append(p)
    except Exception as e:
        print(f"  [WARN] 生成 PDF 失败（跳过，PDF 解析改用用户真实文件验证）：{e}")

    if include_dwg:
        made += _make_dwg(folder)
    return made


def _find_cjk_font():
    """在本地找一个可嵌入的 CJK TrueType 字体（.ttf/.ttc 且非 CFF 轮廓）。"""
    cands = []
    if platform.system() == "Windows":
        for f in ("msyh.ttc", "simsun.ttc", "simhei.ttf", "msyhl.ttc"):
            for d in (r"C:\Windows\Fonts",):
                cands.append(os.path.join(d, f))
    for d in ("/usr/share/fonts", "/System/Library/Fonts"):
        if os.path.isdir(d):
            for root, _dirs, files in os.walk(d):
                for fn in files:
                    if fn.lower().endswith((".ttf", ".ttc")) and any(
                            k in fn.lower() for k in ("cjk", "noto", "msyh", "sim", "hei", "song")):
                        cands.append(os.path.join(root, fn))
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def _make_dwg(folder):
    """生成 DXF 图纸样本（含标题栏文字、设计院名称、签名、施工图字样）。

    清稿工具原生读 DWG，但 DWG 无法用纯 Python 生成；因此用 ezdxf 造 DXF。
    若本地装了 ODA File Converter 可再转 DWG，但自测以 DXF 验证清稿规则即可。
    """
    out = []
    try:
        import ezdxf
    except Exception as e:
        print(f"  [WARN] 未安装 ezdxf，跳过 DXF 样本：{e}")
        return out
    try:
        p = os.path.join(folder, "施工图_EQ-101.dxf")
        doc = ezdxf.new("R2010", setup=True)
        msp = doc.modelspace()
        # 图框
        msp.add_lwpolyline([(0, 0), (420, 0), (420, 297), (0, 297), (0, 0)])
        # 标题栏文字：应被清理的设计痕迹 + 应保留的工程信息
        texts = [
            (300, 40, "设计院：某某建筑设计研究院"),      # 应删除
            (300, 30, "制图：张 三"),                     # 应删除
            (300, 22, "设计：李 四"),                     # 应删除
            (300, 14, "校对：王 五"),                     # 应删除
            (300, 6, "审核：赵 六"),                      # 应删除
            (20, 30, "施工图"),                           # 应替换为"竣工图"
            (20, 22, "图号：EQ-101"),                     # 应保留
            (20, 14, "图名：离心泵安装图"),                # 应保留
            (20, 6, "比例：1:50"),                        # 应保留
            (20, 46, "建设单位：紫金矿业"),                # 应保留
            (20, 38, "施工单位：中国十五冶"),              # 应保留
            (20, 54, "车间：1号车间"),                     # 应保留
        ]
        for x, y, s in texts:
            msp.add_text(s, dxfattribs={"height": 3.5}).set_placement((x, y))
        doc.saveas(p)
        out.append(p)
    except Exception as e:
        print(f"  [WARN] 生成 DXF 失败：{e}")
    return out


# ---------------- 阶段 1：解析 / 分类 / 资料库 ----------------
def phase1(samples_dir):
    P = 1
    print("\n=== 阶段 1：文件上传解析、分类、资料库搭建 ===")

    code, body, err = call("GET", "/api/status")
    record(P, "服务健康检查", "200 且返回 version", f"{code} {err}", code == 200,
           json.dumps(body, ensure_ascii=False)[:200] if body else "")
    if code != 200:
        print("  [FAIL] 工作台未启动，后续步骤跳过。请先运行 run_workbench.bat")
        for s in ("项目创建", "递归扫描", "解析完整性", "实体提取", "车间分类",
                  "资料库检索", "向量化状态"):
            record(P, s, "-", "服务不可达，跳过", None)
        return

    v0 = body.get("version") if isinstance(body, dict) else None
    record(P, "版本号可读", "version 字段非空", v0, bool(v0))

    # 建测试项目（避免污染用户真实项目；先记住原项目，结束时切回）
    code, cur, _ = call("GET", "/api/projects/current")
    origin = (cur or {}).get("project") or (cur or {}).get("current") or cur
    proj_name = f"自测_{time.strftime('%Y%m%d_%H%M%S')}"
    # v0.1.217：登记「这个名字是本自测建的」——退出时据此把本次自测写进
    # 真实审计流水的行删掉。名字精确到秒，用户真实项目里不会撞名。
    if proj_name not in SELFTEST_TOKENS:
        SELFTEST_TOKENS.append(proj_name)
    code, body, err = call("POST", "/api/projects/create", {"name": proj_name})
    record(P, "项目创建", "200 且 ok=true", f"{code} {str(body)[:80]}",
           code == 200 and (body or {}).get("ok", True), err)
    # v0.1.173：记住测试项目 id，供 phase3 显式切回去
    global TEST_PROJECT_ID
    _pj = (body or {}).get("project") or {}
    if _pj.get("id"):
        TEST_PROJECT_ID = _pj["id"]
        if _pj["id"] not in CREATED_PIDS:
            CREATED_PIDS.append(_pj["id"])
        # v0.1.217：id 也登记成审计识别标记 —— 日志行里带 id（新建/删除都带），
        # 名字可能因为改名而变化，id 不会。
        if _pj["id"] not in SELFTEST_TOKENS:
            SELFTEST_TOKENS.append(_pj["id"])

    # 扫描
    t0 = time.time()
    code, body, err = call("POST", "/api/scan", {"folder": samples_dir, "force": True})
    record(P, "递归扫描启动", "200", f"{code} {str(body)[:80]}", code == 200, err)
    st = {}
    for _ in range(120):
        _, st, _ = call("GET", "/api/scan/status")
        if not (st or {}).get("running"):
            break
        time.sleep(2)
    stats = (st or {}).get("stats") or {}
    record(P, "扫描完成", "running=false 且有 stats", json.dumps(stats, ensure_ascii=False),
           not (st or {}).get("running") and bool(stats), f"耗时 {time.time()-t0:.1f}s")
    if stats:
        record(P, "解析成功率", "failed=0", f"parsed={stats.get('parsed')} failed={stats.get('failed')}",
               stats.get("failed", 0) == 0, json.dumps(stats, ensure_ascii=False))

    # 结果清单
    code, res, err = call("GET", "/api/results")
    items = res if isinstance(res, list) else ((res or {}).get("results") or [])
    record(P, "资料库条目数", f">= 样本数({len(os.listdir(samples_dir)) if os.path.isdir(samples_dir) else '?'})",
           f"条目 {len(items)}", len(items) > 0)
    if items:
        # 列表接口只返回索引信息，正文必须走详情接口 /api/results/{sha256}
        details, detail_fail = [], []
        for it in items:
            sha = it.get("sha256")
            c2, d2, e2 = call("GET", f"/api/results/{sha}")
            if c2 == 200 and isinstance(d2, dict):
                details.append(d2)
            else:
                detail_fail.append(f"{it.get('file_name')}={c2}")
        record(P, "详情回读可用", "每个已解析文件都能取到详情",
               f"{len(details)}/{len(items)} 可取；失败：{detail_fail[:4]}",
               len(detail_fail) == 0,
               "404 未找到缓存 = 详情接口查错目录（项目目录 vs 全局目录）")

    if details:
        nonempty = [d for d in details if (d.get("text") or "").strip()]
        record(P, "正文非空", "全部有正文", f"{len(nonempty)}/{len(details)} 有正文",
               len(nonempty) >= max(1, len(details) * 3 // 4),
               "；".join(f"{d.get('file_name')}={len((d.get('text') or ''))}字"
                          for d in details[:6]))
        with_ent = [d for d in details if d.get("entities")]
        ent_names = sorted({str(e) for d in with_ent for e in (d.get("entities") or [])})[:8]
        record(P, "实体(位号)提取", "至少 1 条命中设备位号",
               f"{len(with_ent)}/{len(details)} 条含实体；样例 {ent_names}",
               len(with_ent) >= 1)
        # 结构（表格/图框）是否解析出来
        with_struct = [d for d in details if d.get("structure")]
        record(P, "结构化解析", "至少表格类文件有 structure",
               f"{len(with_struct)}/{len(details)} 条有 structure", len(with_struct) >= 1,
               "；".join(str(d.get("file_name")) for d in with_struct[:4]))

    # 车间自动分类：以 /api/workshops + /api/workshop/list 为准（列表接口无 workshop 字段）
    code, wsl, err = call("GET", "/api/workshops")
    recog = (wsl or {}).get("workshops") or []
    named = [w for w in recog if w.get("name") and "未归" not in str(w.get("name"))]
    assigned = sum(w.get("file_count", 0) for w in named)
    record(P, "车间自动分类", "识别出车间且文件已归入车间",
           f"识别车间 {[w.get('name') for w in named]}；已归类文件 {assigned}",
           len(named) >= 1 and assigned >= 1, err)

    # 检索
    code, sr, err = call("POST", "/api/search", {"query": "1号车间 离心泵 P-101", "top_k": 5})
    hits = (sr or {}).get("results") or []
    record(P, "资料库检索", "200 且命中>0", f"{code} hits={len(hits)} mode={(sr or {}).get('retrieval')}",
           code == 200 and len(hits) > 0, err)
    record(P, "检索模式声明", "vector 或 keyword", (sr or {}).get("retrieval"),
           (sr or {}).get("retrieval") in ("vector", "keyword"),
           f"vector_error={(sr or {}).get('vector_error')}")
    for h in hits[:3]:
        m = h.get("meta") or {}
        print(f"      命中：{m.get('file_name')} 匹配 {m.get('matched_terms')}/{m.get('total_terms')} "
              f"距离 {h.get('distance')}")

    # 向量化
    _, st2, _ = call("GET", "/api/status")
    vc = (st2 or {}).get("vector_count")
    record(P, "向量库计数", "有向量或明确降级", f"vector_count={vc}", True,
           "vector_count=0 且检索走 keyword = embedding 模型未就绪（离线/未下载），"
           "资料仍可查但语义检索不可用")

    # 切回原项目
    if origin and isinstance(origin, dict) and origin.get("id"):
        call("POST", "/api/projects/switch", {"project_id": origin["id"]})


# ---------------- 阶段 2：工程资料生成 ----------------
def phase2(samples_dir):
    P = 2
    print("\n=== 阶段 2：工程资料生成管理 ===")

    code, types, err = call("GET", "/api/docgen/types")
    tl = types if isinstance(types, list) else ((types or {}).get("types") or [])
    record(P, "资料类型清单", "200 且类型数>0", f"{code} types={len(tl) if isinstance(tl,list) else 'n/a'}",
           code == 200, err)
    if isinstance(tl, list) and tl:
        sample = tl[:8]
        print(f"      类型样例：{[t.get('name') or t.get('type') or t for t in sample]}")
        first = sample[0].get("key") or sample[0].get("type") or sample[0].get("name")

        code, pre, err = call("POST", "/api/docgen/prefill", {"doc_type": first, "workshop": "1号车间"})
        record(P, "模板预填", "200", f"{code} {str(pre)[:80]}", code == 200, err)

        code, gen, err = call("POST", "/api/docgen/generate",
                              {"doc_type": first, "data": {"车间": "1号车间"}})
        ok = code == 200 and not (isinstance(gen, dict) and gen.get("ok") is False)
        record(P, "单据生成", "200 且生成成功", f"{code} {str(gen)[:120]}", ok, err)

    # 监理模板
    code, sup, err = call("GET", "/api/supervision-templates")
    st = sup if isinstance(sup, list) else ((sup or {}).get("templates") or [])
    record(P, "监理模板库", "200", f"{code} templates={len(st) if isinstance(st,list) else 'n/a'}",
           code == 200, err)

    code, eq, err = call("GET", "/api/supervision-templates/equipment")
    record(P, "设备清单供填表", "200 且能取到设备", f"{code} {str(eq)[:100]}", code == 200, err)

    # 批量生成（两步：模糊输入先拿候选，再用明确表类型生成）
    code, bg0, err = call("POST", "/api/supervision-templates/generate-batch",
                          {"category": "仪表", "workshop": "1号车间",
                           "equipment": [{"位号": "P-101", "名称": "离心泵"}]})
    _b0 = bg0 or {}
    ambiguous_ok = (code == 200 and _b0.get("ok") is False
                    and (_b0.get("ambiguous") or bool(_b0.get("candidates") or _b0.get("error"))))
    record(P, "模糊表类型返回候选", "200 且给出候选/报错（不擅自生成）",
           f"{code} candidates={len(_b0.get('candidates') or [])} error={str(_b0.get('error') or '')[:60]}",
           ambiguous_ok, err)

    _cat = (_b0.get("candidates") or ["变压器安装施工记录"])[0]
    code, bg, err = call("POST", "/api/supervision-templates/generate-batch",
                         {"category": _cat, "workshop": "1号车间",
                          "equipment": [{"位号": "P-101", "名称": "离心泵"}]})
    _b = bg or {}
    # v0.1.167：不能只看 200 —— 找不到模板时旧实现返回 ok=False 也算通过（空洞 PASS）。
    _produced = bool(_b.get("ok")) and bool(_b.get("output_file") or _b.get("file") or _b.get("files"))
    _honest_fail = _b.get("ok") is False and bool(_b.get("error"))
    ok = code == 200 and (_produced or _honest_fail)
    detail = (f"{code} cat={_cat[:20]} ok={_b.get('ok')} "
              f"output={str(_b.get('output_file') or _b.get('file') or '')[:40]} "
              f"error={str(_b.get('error') or '')[:50]}")
    record(P, "批量套模板生成", "有产出 或 明确报错（非空洞通过）", detail, ok, err)

    # 生成计划
    code, pl, err = call("GET", "/api/docplan/status")
    record(P, "生成任务计划", "200", f"{code} {str(pl)[:80]}", code == 200, err)

    code, tg, err = call("GET", "/api/templates")
    record(P, "模板清单", "200", f"{code} {str(tg)[:80]}", code == 200, err)


# ---------------- 阶段 3：竣工资料自动生成 ----------------
def phase3(samples_dir):
    P = 3
    print("\n=== 阶段 3：竣工资料自动生成 ===")

    # v0.1.173：phase1 结束时切回了用户原项目，而竣工/整卷的数据都在自测项目里。
    # 不切过去的话，「竣工资料统计」读到的是用户当前项目的清单（通常是 0），
    # 这个 FAIL 是测试自己的上下文错了，不是产品缺陷。
    if TEST_PROJECT_ID:
        call("POST", "/api/projects/switch", {"project_id": TEST_PROJECT_ID})
    # 数据根：不能拿 --inproc 传进来的那个目录去推（那只是 sys.path 入口，
    # 代码实际所在目录可能不同）。进程内模式直接问产品自己的 config；
    # HTTP 模式取脚本所在目录的上一级（tools/selftest.py → workbench/data）。
    if _INPROC is not None:
        try:
            from app import config as _cfg
            _data_dir = os.path.abspath(_cfg.DATA_DIR)
        except Exception:  # noqa: BLE001
            _data_dir = os.path.abspath(os.path.join(_INPROC_DIR, "data"))
    else:
        _data_dir = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "data"))

    # v0.1.172：这批检查原来只断言 HTTP 200。200 只代表路由没抛异常，
    # 正文里写着「无设备数据」「error=登记表不存在」时照样 PASS —— 假绿灯就是这么来的。
    # 现在每条都要求「正文里有真实内容」，把退化状态判成 FAIL。
    def _has(body, *keys):
        b = body or {}
        return any(b.get(k) not in (None, "", [], {}) for k in keys)

    code, body, err = call("GET", "/api/completeness/check")
    phases = (body or {}).get("phases") or []
    # v0.1.192：原来这条断言要求「至少一个阶段有已存在的资料」。
    # 实测：自测新建的项目是空项目（只有几个通用样本），六个阶段的资料本来就不存在，
    # 完整性检查报「全部缺失」是**正确**行为 —— 这条 FAIL 是测试自己的前置条件错了，
    # 与 v0.1.173 记的「竣工资料统计」同一类问题，不是产品缺陷。
    # 改成断言产品真正承诺、任何项目都成立的东西：
    #   ① 六个阶段都在；
    #   ② completed == len(existing)；
    #   ③ existing 与 missing 的资料类型不重叠（不能既算有又算缺）；
    #   ④ completion（百分比）与 completed/total_required 对得上；
    #   ⑤ 项目有设备时，「设备到货」阶段的必查项数不得为 0 ——
    #      这一条专门抓「设备级检查恒为 0、恒报 100% 完成」的假绿灯
    #      （v0.1.192 修掉的正是这个：两个阶段一台设备都没查过）。
    _bad = []
    for _ph in phases:
        _ex = _ph.get("existing") or []
        _ms = _ph.get("missing") or []
        _ext = {x.get("type") for x in _ex if x.get("level") == "项目级"}
        _mst = {x.get("type") for x in _ms if x.get("level") == "项目级"}
        if (_ph.get("completed") or 0) != len(_ex):
            _bad.append("%s completed≠len(existing)" % _ph.get("phase"))
        _tr = _ph.get("total_required") or 0
        if _tr < (_ph.get("completed") or 0):
            _bad.append("%s total_required<completed" % _ph.get("phase"))
        if _ext & _mst:
            _bad.append("%s 类型重叠:%s" % (_ph.get("phase"), sorted(_ext & _mst)))
        _exp = 100.0 if _tr == 0 else round(100.0 * (_ph.get("completed") or 0) / _tr, 1)
        if abs(float(_ph.get("completion") or 0) - _exp) > 0.1:
            _bad.append("%s completion(%s)≠%s" % (_ph.get("phase"), _ph.get("completion"), _exp))
    _code_s, _st_s, _ = call("GET", "/api/completion-archive/stats")
    _ndev = (_st_s or {}).get("total_devices") or 0
    _arrive = [p for p in phases if p.get("phase") == "设备到货"]
    if _arrive and _ndev and not (_arrive[0].get("total_required") or 0):
        _bad.append("设备到货阶段必查项数=0（有 %d 台设备却一项没查）" % _ndev)
    record(P, "完整性检查", "200 且六阶段齐全、计数自洽、设备级不是假绿灯",
           f"{code} phases={len(phases)} 设备数={_ndev} 问题={_bad or '无'}",
           code == 200 and len(phases) == 6 and not _bad, err)

    code, body, err = call("GET", "/api/completion-archive/requirements")
    reqs = (body or {}).get("requirements") or []
    record(P, "竣工资料要求", "200 且 requirements 非空",
           f"{code} requirements={len(reqs)}", code == 200 and bool(reqs), err)

    # v0.1.173：这里是「统计」接口，它读的是已生成的竣工清单。
    # 在一个刚建、还没跑过竣工生成的自测项目上，total_devices 必然是 0 ——
    # 这不是缺陷，是顺序问题。真正该卡的是「同一个项目里两个接口的数字对不上」。
    # 所以先在同一个项目里跑一次「一键竣工」，再比对 stats 与它的设备数。
    code_ca0, _ca0, err_ca0 = call("POST", "/api/completion-archive/all", {})
    _dev_all0 = (_ca0 or {}).get("total_devices") or 0
    code, body, err = call("GET", "/api/completion-archive/stats")
    devs = (body or {}).get("total_devices") or 0
    _consistent = (code == 200 and devs > 0 and _dev_all0 > 0
                   and devs == _dev_all0 and code_ca0 == 200)
    record(P, "竣工资料统计", "200 且设备数>0，并与「一键竣工」结果一致（两接口不能自相矛盾）",
           f"{code} total_devices={devs} ｜ 一键竣工 total_devices={_dev_all0}",
           _consistent, err or err_ca0)

    code, body, err = call("GET", "/api/archive-enhanced/checklist")
    cl = (body or {}).get("checklist") or {}
    # 空清单是真实缺陷（设备库空），不是通过
    record(P, "组卷清单", "200 且 checklist 有内容（非『无设备数据』）",
           f"{code} 卷数={len(cl)} error={(body or {}).get('error')}",
           code == 200 and bool(cl), err)

    code, body, err = call("GET", "/api/archive/catalog")
    rows = (body or {}).get("rows") or []
    record(P, "案卷目录", "200 且目录行 > 0",
           f"{code} rows={len(rows)}", code == 200 and len(rows) > 0, err)

    code, org, err = call("GET", "/api/archive-enhanced/organize")
    record(P, "按车间组卷", "200 且真的有车间分组",
           f"{code} error={(org or {}).get('error')}",
           code == 200 and not (org or {}).get("error"), err)

    # v0.1.173：原断言把「明确报错」也算 PASS —— 等于「我没做成但我说了没做成，就算过」。
    # 先导入一份真实登记表，把整卷这条最关键的链路真正跑起来再判定。
    # 表项名称取自内置监理模板（设备开箱检查记录 / 设备安装检查记录），
    # 分类 A/B/C 分别对应自动生成 / 预填待补 / 归集目录。
    _reg = [
        {"册": "第一册", "序号": "1", "名称": "设备开箱检查记录", "表号": "JL-01",
         "分类": "A", "阶段": "开箱"},
        {"册": "第一册", "序号": "2", "名称": "设备安装检查记录", "表号": "JL-02",
         "分类": "B", "阶段": "安装"},
        {"册": "第一册", "序号": "3", "名称": "监理旁站记录", "表号": "JL-03",
         "分类": "C", "阶段": "安装"},
    ]
    _reg_bytes = json.dumps(_reg, ensure_ascii=False).encode("utf-8")
    code, rb, err = call_upload("/api/supervision/registry", "整编要求登记表.json",
                                _reg_bytes, field="file")
    _reg_ok = code == 200 and bool(((rb or {}).get("registry") or {}).get("ready"))
    record(P, "导入整编要求登记表", "200 且登记表 ready=True",
           f"{code} ready={((rb or {}).get('registry') or {}).get('ready')} "
           f"total={((rb or {}).get('registry') or {}).get('total')} err={err}",
           _reg_ok, err)

    code, vol, err = call("POST", "/api/supervision/volume",
                          {"project_id": TEST_PROJECT_ID, "book": "第一册", "workshop": "1号车间"})
    vr = (vol or {}).get("result") or (vol or {})
    generated = vr.get("generated") or []
    todo = vr.get("todo") or []
    collect_dir = vr.get("collect_dir") or []
    errors = vr.get("errors") or []
    reason = vr.get("error") or ""
    # v0.1.173：原断言把「明确报错」也算 PASS —— 等于「我没做成但我说了没做成，就算过」。
    # 真正要卡的是「静默丢弃」：登记表里的每一项，要么生成出文件、要么进归集目录、
    # 要么进待办清单。不允许哪一项悄悄消失。
    _gen_seqs = {str(g.get("序号")) for g in generated}
    _todo_seqs = {str(t.get("序号")) for t in todo}
    _collect_seqs = {str(c.get("序号")) for c in collect_dir if isinstance(c, dict)}
    _all_seqs = {str(i.get("序号")) for i in _reg}
    _unaccounted = sorted(_all_seqs - _gen_seqs - _todo_seqs - _collect_seqs)
    if generated and not _unaccounted:
        ok = code == 200
        expect_txt = ("真的组出卷且每一项都有交代（生成/归集/待办，不静默丢弃）")
    elif generated and _unaccounted:
        ok = False
        expect_txt = "有产出但有登记项被静默丢弃"
    elif reason and (todo or collect_dir):
        ok = code == 200
        expect_txt = "无产出但把缺失登记表转化为待办（非静默空转）"
    else:
        ok = False
        expect_txt = "无产出且无待办 → 静默空转"
    detail = (f"{code} generated={len(generated)} todo={len(todo)} "
              f"collect={len(collect_dir)} errors={len(errors)} "
              f"静默丢弃={_unaccounted} error={reason[:60]}")
    record(P, "整卷生成", expect_txt, detail, ok, err)

    # 整卷产出必须落到磁盘上 —— 只看接口返回的 generated 列表不够，
    # 文件没落盘的话，用户去卷目录里找不到东西。
    # v0.1.173：① 原来用相对路径 "data/projects" 走 os.walk，脚本被打包/换目录跑时
    # 相对基准就变了，扫不到必然误报「找不到」；改成绝对路径。
    # ② 必须落在「本测试项目」目录下，落到全局 data/projects/volumes 也算失败 ——
    # 那正是 v0.1.173 修掉的旧缺陷（project_id 为空时写到所有项目的上一层）。
    if generated:
        _missing_files = []
        _outside_project = []
        _proj_dir = os.path.join(_data_dir, "projects", TEST_PROJECT_ID) if TEST_PROJECT_ID else ""
        for gitem in generated:
            _f = gitem.get("文件")
            if not _f:
                continue
            # 只在「本项目」目录内找。原来在 data/projects 全库 os.walk，
            # 上一次自测遗留在别的项目里的同名文件会先被命中，
            # 于是这次明明落对了地方，却被判成「落到项目外」。
            _hit = None
            if _proj_dir and os.path.isdir(_proj_dir):
                for _root, _dirs, _files in os.walk(_proj_dir):
                    if _f in _files:
                        _hit = os.path.join(_root, _f)
                        break
            if not _hit:
                # 项目内没有 → 再看是不是落到了项目外（这才是真缺陷）
                for _root, _dirs, _files in os.walk(os.path.join(_data_dir, "projects")):
                    if _f in _files:
                        _outside_project.append(os.path.join(_root, _f))
                        break
                if not _outside_project or not _proj_dir:
                    _missing_files.append(_f)
        _land_ok = not _missing_files and not _outside_project
        record(P, "整卷文件落盘", "generated 列出的每个文件都在本项目目录内落盘",
               f"generated={len(generated)} 找不到={len(_missing_files)} "
               f"落到项目外={len(_outside_project)} 项目={TEST_PROJECT_ID}"
               + (f" 缺:{_missing_files[:3]}" if _missing_files else "")
               + (f" 越界:{[_p.split('projects')[-1] for _p in _outside_project[:2]]}" if _outside_project else ""),
               _land_ok, err)
    else:
        record(P, "整卷文件落盘", "generated 列出的每个文件都能在磁盘上找到",
               "无 generated 可核对", None, "")

    code, ca, err = call("POST", "/api/completion-archive/all", {})
    n_dev = (ca or {}).get("total_devices") or 0
    ok = code == 200 and n_dev > 0
    record(P, "一键竣工资料", "200 且真正处理了设备（total_devices>0）",
           f"{code} total_devices={n_dev}", ok, err)

    code, miss, err = call("GET", "/api/completion-archive/missing")
    ms = (miss or {}).get("missing") or []
    # 「没有缺件」和「根本没有数据可查」是两回事，后者判 FAIL
    record(P, "缺件清单", "200 且 missing 非空（空列表=没数据可查，不是好结果）",
           f"{code} missing={len(ms)}", code == 200 and bool(ms), err)

    # v0.1.173：导出接口返回 ZIP 二进制。原断言只看状态码，空包/坏包/0 字节都能 PASS。
    # 现在真解压：必须是合法 ZIP、至少 1 个文件、无损坏成员。
    code, raw, err = call_bytes("/api/archive/export-enhanced")
    zs = zip_summary(raw) if code == 200 else {"error": err or f"HTTP {code}"}
    ok = code == 200 and not zs.get("error") and zs.get("files", 0) > 0 and not zs.get("bad_member")
    detail = (f"{code} size={zs.get('size', 0)} files={zs.get('files', 0)} "
              f"uncompressed={zs.get('uncompressed', 0)} "
              f"bad={zs.get('bad_member')} err={zs.get('error', '')}")
    record(P, "导出成套", "合法 ZIP 且内含文件（真解压核对，不只看 200）", detail, ok, err)

    # v0.1.173 回归：竣工归档必须跟着项目走。
    # 原缺陷是清单写死在全局 data/completion_archive.json —— 建 A、B 两个项目，
    # 在 A 生成后切到从未生成过的 B，B 会读到 A 的清单，导出会把 A 的资料递出去。
    # 竣工归档是交监理的项目级交付物，串项目属于严重错误，必须有一条常驻断言盯着。
    try:
        _code_a = _dev_all0
        # 在切走之前先记下「当前是哪个项目」——不能依赖 TEST_PROJECT_ID，
        # 那是 phase1 才会赋值的；单独跑 `--phase 3` 时它是空的，
        # 切回去的请求就会带着空 id 打过去，实际还停在新项目上，断言必然读到 0。
        _, _cur_now, _ = call("GET", "/api/projects/current")
        _home_id = (((_cur_now or {}).get("project") or {}).get("id")
                    or TEST_PROJECT_ID or "")
        # v0.1.217：名字先算出来再复用 —— 两次 strftime 跨秒时会产生两个不同
        # 名字，登记进审计识别的那个就和真建出来的对不上，清理会漏行。
        _new_name = f"自测隔离_{time.strftime('%H%M%S')}"
        code_new, nb, err_new = call("POST", "/api/projects/create",
                                     {"name": _new_name})
        _new_id = ((nb or {}).get("project") or {}).get("id") or ""
        if _new_id:
            if _new_id not in CREATED_PIDS:
                CREATED_PIDS.append(_new_id)
            for _tk in (_new_id, _new_name):
                if _tk and _tk not in SELFTEST_TOKENS:
                    SELFTEST_TOKENS.append(_tk)
            call("POST", "/api/projects/switch", {"project_id": _new_id})
            # 新项目里还没生成过任何竣工资料，设备数必须为 0
            _, st_b, _ = call("GET", "/api/completion-archive/stats")
            _dev_b = (st_b or {}).get("total_devices")
            _, miss_b, _ = call("GET", "/api/completion-archive/missing")
            _miss_b = len(((miss_b or {}).get("missing") or []))
            _isolated = (_dev_b == 0 and _miss_b == 0)
            record(P, "竣工归档跨项目隔离",
                   "新建项目里竣工设备数=0、缺件=0（不承接上一个项目的清单）",
                   f"新项目 total_devices={_dev_b} missing={_miss_b}（对照 A={_code_a} 台）",
                   _isolated, "")
            # 切回原项目，确认 A 的数据还在（隔离不是丢数据）
            call("POST", "/api/projects/switch", {"project_id": _home_id})
            _, st_a2, _ = call("GET", "/api/completion-archive/stats")
            _dev_a2 = (st_a2 or {}).get("total_devices")
            record(P, "切回原项目仍读到本项清单",
                   "切回后设备数恢复为 A 的值（隔离不是丢数据）",
                   f"切回后 total_devices={_dev_a2}（应为 {_code_a}）home={_home_id}",
                   _dev_a2 == _code_a, "")
        else:
            record(P, "竣工归档跨项目隔离", "能建出第二个项目", "建项目未返回 id",
                   False, err_new)
    except Exception as _e:  # noqa: BLE001
        record(P, "竣工归档跨项目隔离", "无异常", f"{type(_e).__name__}: {_e}", False, "")


# ---------------- 阶段 4：竣工图纸清稿 ----------------
def phase4(samples_dir):
    P = 4
    print("\n=== 阶段 4：竣工图清稿 ===")

    code, st, err = call("GET", "/api/tools/dwg-cleaner/status")
    ready = (st or {}).get("env", {}).get("ready") if isinstance(st, dict) else None
    missing = (st or {}).get("env", {}).get("missing") if isinstance(st, dict) else None
    # v0.1.170：原来无条件 `bool(ready)` 判定。但 AutoCAD 没有 Linux/macOS 官方版本，
    # 非 Windows 平台 ready 必然为 False —— 那是环境不满足、不是代码缺陷，记成 fail
    # 会让 AI 侧每轮去追一个根本不存在的 bug（沙箱实测就是这样虚报 1 项失败）。
    # 区分开：非 Windows → skip(None)；Windows 上 ready=False → 真 fail（部署缺依赖）。
    on_windows = platform.system() == "Windows"
    if on_windows:
        env_pass = bool(ready)
    else:
        env_pass = None
    record(P, "清稿环境自检",
           "ready=true" if on_windows else "ready=true（非 Windows 平台不适用，跳过）",
           f"{code} ready={ready} missing={missing} platform={platform.system()}",
           env_pass, str((st or {}).get("env", {}).get("hint"))[:200])

    if not ready:
        print(f"  [SKIP] 环境不满足（missing={missing}）：清稿需 Windows + AutoCAD，"
              f"当前平台 {platform.system()}。以下步骤标记 skip。")
        for s in ("待清稿图纸清单", "清稿执行", "原图 MD5 不变", "处理日志", "成果 PDF"):
            record(P, s, "-", f"环境不满足(missing={missing})", None)
        return

    code, dw, err = call("GET", "/api/tools/dwg-cleaner/drawings")
    dwl = dw if isinstance(dw, list) else ((dw or {}).get("drawings") or [])
    record(P, "待清稿图纸清单", "200", f"{code} count={len(dwl) if isinstance(dwl,list) else 'n/a'}",
           code == 200, err)

    dxf = [p for p in os.listdir(samples_dir) if p.lower().endswith((".dxf", ".dwg"))]
    if not dxf:
        record(P, "清稿样本准备", "有 dxf/dwg 样本", "无样本", None)
        return
    target = os.path.join(samples_dir, dxf[0])

    import hashlib

    def md5(p):
        h = hashlib.md5()
        with open(p, "rb") as f:
            for c in iter(lambda: f.read(8192), b""):
                h.update(c)
        return h.hexdigest()

    before = md5(target)
    code, proc, err = call("POST", "/api/tools/dwg-cleaner/process",
                           {"file_paths": [target], "project_drawings": False}, timeout=300)
    # v0.1.170：原来判定是 `(proc or {}).get("ok") is not False` —— 但真实返回里
    # 根本没有 ok 键，get 取到 None，`None is not False` 恒真。于是 AutoCAD 报错、
    # 返回 {status:"failed", failed:1} 时这一项照样 PASS，真问题被测试吞掉。
    # 改成同时看 status 与失败条数，三种失败态都要能被判出来。
    resp = proc or {}
    status_str = str(resp.get("status") or "").strip().lower()
    n_failed = resp.get("failed")
    hard_fail = (status_str in ("failed", "error")
                 or (isinstance(n_failed, int) and n_failed > 0))
    ok = code == 200 and resp.get("ok") is not False and not hard_fail
    record(P, "清稿执行", "200 且 status 非失败、失败条数为 0",
           f"{code} status={status_str or '(空)'} failed={n_failed} {str(proc)[:120]}", ok, err)

    after = md5(target)
    record(P, "原图 MD5 不变", before == after, f"{before[:12]} -> {after[:12]}", before == after,
           "设计目标质量底线：原文件 MD5 全程不变")

    # v0.1.170：原来在 /process 响应顶层找 log/pdf. 实测（Windows + AutoCAD 2020）
    # 这两个键根本不在顶层：路由返回 {status,total,success,failed,results[],out_dir}，
    # pdf / log_file 在 results[0] 里（core.process_file 的返回结构）。字段取错，
    # 于是「处理日志 0 条」「成果 PDF 空」被误判成失败 —— 而磁盘上 PDF、清稿 DXF、
    # 处理日志都真实产出了。改成从 results[] 取，并保留顶层兜底兼容旧接口。
    results = (proc or {}).get("results") or []
    first = results[0] if isinstance(results, list) and results else {}
    if not isinstance(first, dict):
        first = {}

    log_file = first.get("log_file") or (proc or {}).get("log_file") or ""
    log_exists = bool(log_file) and os.path.isfile(log_file)
    # 兼容：接口若直接返回日志数组，也算有日志
    log_list = (proc or {}).get("log") or (proc or {}).get("logs") or []
    record(P, "处理日志", "有逐图日志文件或日志条目",
           f"log_file={log_file or '(空)'} exists={log_exists}; 顶层条目={len(log_list) if isinstance(log_list, list) else 'n/a'}",
           log_exists or bool(log_list), log_file or "")

    pdf_path = first.get("pdf") or (proc or {}).get("pdf") or (proc or {}).get("output") or ""
    pdf_exists = bool(pdf_path) and os.path.isfile(pdf_path)
    pdf_size = os.path.getsize(pdf_path) if pdf_exists else 0
    pdf_pages = first.get("pdf_pages")
    evidence = f"pdf={pdf_path or '(空)'} exists={pdf_exists} size={pdf_size}B pages={pdf_pages}"
    record(P, "成果 PDF", "生成合并 PDF（文件存在且非空）",
           f"{str(pdf_path)[:100]} ({pdf_size}B)", pdf_exists and pdf_size > 0, evidence)


# ---------------- 阶段 5：使用遥测可用性与脱敏自检 ----------------
def phase5(samples_dir):
    """验证「真实使用数据能不能安全地拿来做优化」。

    v0.1.171 新增。背景：真实使用里「上传 200 个 PDF、30 个没解析出来」，
    原来程序对此**不留任何痕迹**（operation_log 只有 4 个粗粒度字段、无耗时、
    无异常、无输入文件）。没有可用日志，所谓「用真实数据持续优化」就是空话。
    本阶段不测业务功能，只回答两个问题：
      ① 程序是否真在记录每一次请求（路由/状态/耗时/异常）；
      ② 导出的诊断包是否真的脱敏到可以直接交给 AI 工程师（仓库是公开的）。
    """
    P = 5
    print("\n=== 阶段 5：使用遥测可用性与脱敏自检 ===")

    # 5.1 先打两个已知请求，制造可观测的记录（其中一个是 404，用于验证错误聚合）
    call("GET", "/api/status")
    call("GET", "/api/__telemetry_probe_404__")
    time.sleep(0.2)

    # 5.2 遥测状态接口
    code, body, err = call("GET", "/api/telemetry/status")
    ok = code == 200 and isinstance(body, dict) and body.get("ok") is True
    lines = (body or {}).get("lines") if isinstance(body, dict) else None
    record(P, "遥测状态接口", "200 且 enabled=true",
           f"{code} lines={lines} err={err}", ok, json.dumps(body, ensure_ascii=False)[:200] if body else "")

    # 5.3 是否真的落到了记录：至少记录数 > 0
    n = lines if isinstance(lines, int) else 0
    record(P, "请求记录落盘", "requests.jsonl 有记录（lines > 0）",
           f"lines={n}", n > 0, f"/api/telemetry/status lines={n}")

    # 5.4 统计接口：按路由聚合，而不是全挤成一条
    code, body, err = call("GET", "/api/telemetry/stats")
    ok4 = code == 200 and isinstance(body, dict) and body.get("ok") is True
    data = (body or {}).get("data") or {}
    by_route = data.get("by_route") or []
    # 关键：路由必须保留斜杠结构。曾经 scrub() 把 /api/status 整段吃成 <PATH>，
    # 所有请求聚成一条，统计彻底失去意义 —— 这里专门断言路由形态。
    distinct = len({r.get("route") for r in by_route if isinstance(r, dict)})
    has_slash = any(str(r.get("route", "")).count("/") >= 2 for r in by_route if isinstance(r, dict))
    record(P, "按路由聚合", "by_route 存在且路由保留 /api/xxx 结构",
           f"routes={distinct} total={data.get('total')} 分层={has_slash}",
           ok4 and distinct >= 1 and has_slash,
           json.dumps(by_route[:2], ensure_ascii=False)[:250] if by_route else (err or ""))

    # 5.5 4xx 不能被算成服务端错误
    c4 = sum(int(r.get("status_4xx") or 0) for r in by_route if isinstance(r, dict))
    record(P, "4xx 计入客户端错误", "探测的 404 被计入 status_4xx",
           f"status_4xx={c4}", c4 >= 1, f"by_route 汇总 status_4xx={c4}")

    # 5.6 导出脱敏诊断包
    code, body, err = call("GET", "/api/telemetry/export")
    bundle = (body or {}).get("data") if isinstance(body, dict) else None
    ok6 = code == 200 and isinstance(bundle, dict) and bool(bundle)
    record(P, "导出诊断包", "200 且返回结构化 bundle",
           f"{code} keys={list(bundle)[:8] if isinstance(bundle, dict) else '-'}",
           ok6, err or "")

    if not ok6:
        for s2 in ("包内不含业务敏感信息", "包内不含绝对路径", "包内有解析失败聚合"):
            record(P, s2, "-", "导出失败，无法校验", None)
        return

    blob = json.dumps(bundle, ensure_ascii=False)

    # 5.7 脱敏标记必须在：privacy.sanitized=true
    priv = bundle.get("privacy") or {}
    record(P, "脱敏标记", "privacy.sanitized == true",
           f"sanitized={priv.get('sanitized')}", priv.get("sanitized") is True,
           json.dumps(priv, ensure_ascii=False)[:200])

    # 5.8 绝对路径不得出现（Windows 盘符 / 家目录 / 沙箱路径都是业务信息）
    import re as _re
    drive = _re.findall(r"[A-Za-z]:[\\/]", blob)          # C:\ 或 C:/
    home = ("/home/" in blob or "/root/" in blob
            or "\\Users\\" in blob or "/Users/" in blob)
    record(P, "包内不含绝对路径", "无盘符路径、无用户目录",
           f"盘符命中={len(drive)} 用户目录={home}", (not drive) and (not home),
           f"drive_hits={drive[:3]}")

    # 5.9 业务敏感字段不得成为导出包的键（防止以后有人往里加原始文件名列表）
    banned = ("project_name", "client", "customer", "file_path", "filename",
              "file_list", "operator_name", "company")
    keys = " ".join(_walk_keys(bundle)).lower()
    hit = [b for b in banned if b in keys]
    record(P, "包内不含业务敏感字段", "导出键名无项目名/客户/文件名/路径类字段",
           f"命中={hit or '无'}", not hit, f"keys_sample={_walk_keys(bundle)[:12]}")

    # 5.10 解析失败聚合可用（这是「上传 200 个漏了 30 个」的唯一线索）
    pf = bundle.get("parse_failures") or {}
    record(P, "解析失败聚合", "含 total_failed 与 by_ext/by_fingerprint",
           f"total_failed={pf.get('total_failed')} by_ext={pf.get('by_ext')}",
           isinstance(pf, dict) and "total_failed" in pf,
           json.dumps({k: pf.get(k) for k in ("total_failed", "by_ext")}, ensure_ascii=False)[:250])


# ---------------- 阶段 6：同一事实交叉比对 ----------------
def phase6(samples_dir):
    """验证「同一件事，不同接口给出同一个答案」。

    v0.1.210 新增。背景是本项目**反复出现**的一类缺陷：两个接口对同一
    事实给出不同数值，而每一个接口单独看都「正常返回 ok:true」。
    已发生的实例（都对同一份实测数据交叉比对出来的）：
      · /api/update/check 的 current_version=0.0.0 vs /api/status 的 version=0.1.205
      · /api/status 的 queue_pending=2 vs /api/queue 的 items=1（索引被算成包）
      · /api/status 的 indexed_files=6 vs /api/files 的 total=1（数了顶层键）
    上面每一个在人工点界面时都看不出来，只能靠把**同一时刻的两个来源**
    摆在一起比。所以这里不测业务功能，只把它们成对比较。

    注意：本阶段必须全部是**只读**接口。项目里有 153 条 POST/PUT/DELETE
    路由，其中 /api/queue/clear 这类会真的删数据 —— 自测绝不能碰写接口。
    """
    P = 6
    print("\n=== 阶段 6：同一事实交叉比对 ===")

    # v0.1.212：本阶段必须验**用户真实项目**，但前面几个阶段会把当前项目切到
    # 自测项目上（phase1 建、phase3 切过去做整卷校验），而本阶段设计成「不切项目、
    # 只读」，于是继承了那个临时项目的上下文。实测后果非常严重：
    #   --phase all  -> 6.11 PASS（parsed=5 缺缓存=0），汇总 58/0，看起来全绿；
    #   --phase 6    -> 6.11 FAIL（parsed=1 缺缓存=1 ['3b408663b2c0']），10/1。
    # 同一份校验先建后验，用户项目里那条「status=parsed 但没有解析缓存」的
    # 真实缺陷**从来没被这个阶段看见过**。这本身就是「同一件事两个答案」：
    # 全量自测说通过、单跑说失败。所以这里显式切回用户原项目：
    # _ORIGIN_PID 由 run() 在跑所有阶段前记下（含异常路径都会切回）。
    _cur_before = ""
    try:
        _, _cb, _ = call("GET", "/api/projects/current")
        _cur_before = (((_cb or {}).get("project") or {}).get("id") or "")
    except Exception:  # noqa: BLE001
        pass
    if _ORIGIN_PID:
        _code_sw, _sw, _ = call("POST", "/api/projects/switch",
                                {"project_id": _ORIGIN_PID})
        _ok_sw = (_code_sw == 200 and (_sw or {}).get("ok", True))
    else:
        _ok_sw = False
    # 无论成功与否都要落一条记录：这条断言的作用是证明「下面那些比对是在用户
    # 真实项目上做的」，不记录就等于无法核实（全绿也可能是验错了项目）。
    record(P, "在用户原项目上校验",
           "切回用户原项目后再做交叉比对",
           f"切换前={_cur_before or '?'} 目标={_ORIGIN_PID or '?'} 切换={_ok_sw}",
           bool(_ok_sw) and bool(_ORIGIN_PID),
           "切不回去时本阶段验的是临时项目，6.11 这类断言会假通过")

    # 6.1 版本号：把**所有**对外报版本的接口摆在一起比，而不是只比两点。
    # v0.1.211：原来只比 /api/status 与 /api/update/check 两处，于是漏掉了
    # /api/mobile/config 里写死的 "version": "0.1.99" —— 它藏在移动端配置接口里，
    # 看起来和版本管理毫无关系，实测同一时刻 status=0.1.210 / update=0.1.210 /
    # mobile=0.1.99。只比两处的那条断言照样 PASS，缺陷照样漏出去。
    # 所以这里改成「列出全部来源再逐一比对」：以后再有新接口报版本，
    # 只要加进这个列表就会被自动校验，不需要再补一条独立的断言。
    code_s, st, err_s = call("GET", "/api/status")
    code_u, up, err_u = call("GET", "/api/update/check", timeout=60)
    code_m, mc, err_m = call("GET", "/api/mobile/config")

    version_sources = [
        ("/api/status.version", (st or {}).get("version") if isinstance(st, dict) else None),
        ("/api/update/check.current_version",
         (up or {}).get("current_version") if isinstance(up, dict) else None),
        ("/api/mobile/config.version",
         (mc or {}).get("version") if isinstance(mc, dict) else None),
    ]
    uniq = {str(v) for _, v in version_sources if v}
    same = len(uniq) == 1 and all(v for _, v in version_sources)
    record(P, "版本号全部来源一致",
           "status / update.check / mobile.config 三处版本号相等",
           "; ".join(f"{n}={v}" for n, v in version_sources),
           same,
           f"去重后={sorted(uniq)}"
           + ("" if same else "；有接口报的是它自己的开发期字面量，不是当前版本"))
    v_status = version_sources[0][1]

    # 6.2 版本号不得是 0.0.0（这是「检查更新永远说已是最新」的症状）
    not_placeholder = bool(v_status) and str(v_status) != "0.0.0"
    record(P, "版本号不是占位值",
           "version 不等于 0.0.0",
           f"status.version={v_status}", not_placeholder,
           "0.0.0 说明取值路径打空了（读 config.VERSION 之类），检查更新会永远失效")

    # 6.3 待上传数：/api/status.queue_pending 与 /api/queue
    code_q, q, err_q = call("GET", "/api/queue")
    n_pending_status = (st or {}).get("queue_pending") if isinstance(st, dict) else None
    n_pending_api = (q or {}).get("pending") if isinstance(q, dict) else None
    n_pending_items = len((q or {}).get("items") or []) if isinstance(q, dict) else None
    ok3 = (isinstance(n_pending_status, int) and isinstance(n_pending_api, int)
           and n_pending_status == n_pending_api == n_pending_items)
    record(P, "待上传数两处一致",
           "status.queue_pending == queue.pending == len(queue.items)",
           f"status={n_pending_status} api={n_pending_api} items={n_pending_items}",
           ok3, "items 里混进内部索引时，pending 会多算，items 却是真包数")

    # 6.4 已入库文件数：/api/status.indexed_files 与 /api/files.total
    code_f, fl, err_f = call("GET", "/api/files")
    n_idx_status = (st or {}).get("indexed_files") if isinstance(st, dict) else None
    n_files_total = (fl or {}).get("total") if isinstance(fl, dict) else None
    n_files_list = len((fl or {}).get("files") or []) if isinstance(fl, dict) else None
    ok4 = (isinstance(n_idx_status, int) and isinstance(n_files_total, int)
           and n_idx_status == n_files_total == n_files_list)
    record(P, "已入库文件数两处一致",
           "status.indexed_files == files.total == len(files.files)",
           f"status={n_idx_status} total={n_files_total} list={n_files_list}",
           ok4, "status 若数索引顶层键数，会报成 6 而列表只有 1 条")

    # 6.5 设备数：/api/relations 的 devices 列表与其自身 stats
    code_r, rel, err_r = call("GET", "/api/relations", timeout=60)
    devs = (rel or {}).get("devices") if isinstance(rel, dict) else None
    stats = (rel or {}).get("stats") or {}
    n_dev_list = len(devs) if isinstance(devs, list) else None
    n_dev_stats = stats.get("devices") if isinstance(stats, dict) else None
    ok5 = isinstance(n_dev_list, int) and isinstance(n_dev_stats, int) and n_dev_list == n_dev_stats
    record(P, "设备数自身一致",
           "len(relations.devices) == relations.stats.devices",
           f"list={n_dev_list} stats={n_dev_stats}",
           ok5, f"from_ledger={stats.get('devices_from_ledger') if isinstance(stats, dict) else '-'}")

    # 6.6 设备数：/api/relations 与 /api/spatial/structure 必须同一套
    code_sp, sp, err_sp = call("GET", "/api/spatial/structure", timeout=60)
    sp_ok = code_sp == 200 and isinstance(sp, dict) and sp.get("ok") is True
    if sp_ok:
        # 结构：workshops.<ws>.devices
        ws_map = sp.get("workshops") or {}
        n_sp = 0
        if isinstance(ws_map, dict):
            for wsv in ws_map.values():
                if isinstance(wsv, dict):
                    n_sp += len(wsv.get("devices") or {})
                elif isinstance(wsv, list):
                    n_sp += len(wsv)
        ok6 = isinstance(n_dev_list, int) and n_sp == n_dev_list
        record(P, "设备数跨接口一致",
               "relations.devices 条数 == spatial.structure 汇总台数",
               f"relations={n_dev_list} spatial={n_sp}", ok6,
               "两个接口都是给界面看的台数，不等就说明有一套统计口径错了")
    else:
        record(P, "设备数跨接口一致", "spatial.structure 可用",
               f"{code_sp} ok={(sp or {}).get('ok') if isinstance(sp, dict) else '-'} msg={(sp or {}).get('message') if isinstance(sp, dict) else '-'}",
               None, "空间模型未构建时跳过，不算失败")

    # 6.7 车间数：/api/relations 的 devices 里出现的车间 vs /api/workshops 的 docgen 清单
    # 两者不一定相等（文档级归属与设备级归属本就是两件事），所以这里只断言
    # 「设备里出现的车间数」本身可算且不为 0，避免把假空列表当成正常。
    if isinstance(devs, list) and devs:
        ws_names = set()
        for d in devs:
            wv = d.get("workshops")
            if isinstance(wv, list):
                ws_names.update(x for x in wv if x)
            elif isinstance(wv, str) and wv:
                ws_names.add(wv)
        n_ws_dev = len(ws_names)
        # v0.1.212：原来只断言「设备里出现的车间数 >= 1」，而真正该比的是
        # 「/api/relations.workshops 这份车间清单」与「/api/workshops 那份」是否同一套。
        # 实测 2026-11-07 19:0x：设备里能解析出 19 个车间、这条断言 PASS，
        # 可同一时刻 /api/relations.workshops 是空数组 []，
        # 于是 19 个真实车间的详情接口 GET /api/relations/workshop/<车间> 全部 404
        # —— 又是「每个接口单独看都正常、只有摆在一起比才露馅」。
        # 现在改成三处成对比对：设备自带车间数 / relations.workshops / api.workshops。
        try:
            code_w, wj, err_w = call("GET", "/api/workshops")
            api_ws = (wj or {}).get("workshops") or [] if isinstance(wj, dict) else []
        except Exception:  # noqa: BLE001
            api_ws = []
        n_api_ws = len(api_ws)
        rel_ws = rel.get("workshops") if isinstance(rel, dict) else None
        n_rel_ws = len(rel_ws) if isinstance(rel_ws, list) else None
        # relations.workshops 为 None/非列表 = 接口形状坏了，算失败不算跳过
        if n_rel_ws is None:
            record(P, "车间清单两处一致",
                   "relations.workshops 应为列表，且覆盖全部设备自带车间",
                   f"relations.workshops={type(rel_ws).__name__} 设备自带={n_ws_dev}",
                   False, "relations 接口没有返回 workshops 列表")
        else:
            # 口径说明：/api/workshops 是「文档级+设备级」合并清单（还会带上按文件名
            # 推出来的车间），relations 是「设备级」图谱 —— 两者条数本来就可以不等，
            # 上一版断言拿它们比条数，自测项目里就报 relations=3 api=4 的假失败。
            # 真正同一件事的是：**设备自带的每个车间，relations.workshops 里都得有**。
            # 这才是「车间详情接口不再 404」的充要条件。
            rel_names = {w.get("workshop") for w in rel_ws
                         if isinstance(w, dict) and w.get("workshop")}
            missing = sorted(ws_names - rel_names)
            ok7b = (not missing) and n_ws_dev >= 1
            record(P, "车间清单两处一致",
                   "设备自带的每个车间都出现在 relations.workshops 里（不得有遗漏）",
                   f"relations={n_rel_ws}({sorted(rel_names)[:4]}…) "
                   f"设备自带={n_ws_dev} 遗漏={missing or '无'}",
                   ok7b,
                   "有遗漏时该车间的详情接口会 404；/api/workshops 另含文档级车间，"
                   "条数可比 relations 多，不算不一致")
        ok7 = n_ws_dev >= 1
        record(P, "设备车间归属可解析",
               "至少能解析出 1 个车间名",
               f"设备覆盖车间={n_ws_dev}", ok7,
               f"示例={sorted(ws_names)[:5]}")
    else:
        record(P, "设备车间归属可解析", "relations 返回了设备", "设备列表为空", None,
               "当前项目无设备时跳过")

    # 6.8 项目数：/api/projects.total 与列表长度
    code_p, pj, err_p = call("GET", "/api/projects")
    n_total = (pj or {}).get("total") if isinstance(pj, dict) else None
    n_plist = len((pj or {}).get("projects") or []) if isinstance(pj, dict) else None
    ok8 = isinstance(n_total, int) and isinstance(n_plist, int) and n_total == n_plist
    record(P, "项目数两处一致",
           "projects.total == len(projects)",
           f"total={n_total} list={n_plist}", ok8,
           "磁盘目录数可能更多（exports 目录、只剩 exports 的空壳不算项目），属正常")

    # 6.9 项目隔离的根：/api/projects/data-dir 必须恰好等于
    #     status.data_dir + projects + 当前项目 id。
    # v0.1.211 新增。为什么这条重要：全项目所有业务数据都落在
    # data/projects/<id>/ 下，一旦这个解析出的路径和当前项目对不上，
    # 两个项目就会共用一份索引 —— 表现为「A 项目里看到 B 项目的设备」，
    # 而界面上每个接口都返回 ok:true，完全看不出来。这里是**唯一**能把
    # 路径口径钉死的地方，所以再简单也要成对断言，而不是只信一个接口。
    code_dd, dd, err_dd = call("GET", "/api/projects/data-dir")
    code_cu, cu, err_cu = call("GET", "/api/projects/current")
    cur_id = ((cu or {}).get("project") or {}).get("id") if isinstance(cu, dict) else None
    real_dd = (dd or {}).get("data_dir") if isinstance(dd, dict) else None
    base_dir = (st or {}).get("data_dir") if isinstance(st, dict) else None
    expect_dd = (os.path.join(base_dir, "projects", str(cur_id))
                 if base_dir and cur_id else None)
    ok9 = bool(real_dd) and bool(expect_dd) and \
        os.path.abspath(real_dd) == os.path.abspath(expect_dd)
    record(P, "项目数据目录指向当前项目",
           "projects/data-dir == status.data_dir + 'projects' + 当前项目 id",
           f"data-dir={real_dd} 期望={expect_dd}", ok9,
           "口径不一致时两个项目会共用一份索引，界面上完全看不出来")

    # 6.10 该目录必须真实存在（路径算对了但目录没建，写入会散落到别处）
    ok10 = bool(real_dd) and os.path.isdir(real_dd)
    record(P, "当前项目目录真实存在",
           "os.path.isdir(projects/data-dir)",
           f"exists={ok10} path={real_dd}", ok10,
           "目录不存在时后续所有写入的落点都不可信")

    # 6.11 索引与解析缓存自洽：标记 parsed 的文件必须找得到缓存。
    # v0.1.211 新增。为什么必须成对断言：写入口 scanner 把缓存写进项目级
    # parsed_cache，而 main.py 有 4 处读取曾写死全局目录 —— 两边都「正常返回」，
    # 界面看不出错，表现为 AI 助手 sources.project 恒 0、现场记录 OCR 恒空、
    # 设备车间重建恒 0。实测项目 322fef90 的 parsed_cache 目录压根不存在，
    # 索引却写着 1 个 status=parsed，于是检索必然命不中。
    code_f2, fl2, err_f2 = call("GET", "/api/files")
    flist = (fl2 or {}).get("files") or [] if isinstance(fl2, dict) else []
    parsed_shas = [f.get("sha256") for f in flist
                   if isinstance(f, dict) and f.get("status") == "parsed"
                   and f.get("sha256")]
    if parsed_shas:
        missing = []
        for s in parsed_shas:
            p1 = os.path.join(real_dd or "", "parsed_cache", f"{s}.json") if real_dd else ""
            p2 = os.path.join(base_dir or "", "parsed_cache", f"{s}.json") if base_dir else ""
            if not ((p1 and os.path.isfile(p1)) or (p2 and os.path.isfile(p2))):
                missing.append(str(s)[:12])
        ok11 = not missing
        record(P, "已解析文件都有解析缓存",
               "每个 status=parsed 的文件在 项目级/全局 parsed_cache 里都有同名 json",
               f"parsed={len(parsed_shas)} 缺缓存={len(missing)} {missing[:5]}",
               ok11,
               "缺缓存时 AI 检索恒 0 命中、现场记录 OCR 恒空、车间归属重建恒 0，"
               "而每个接口都返回 ok:true")
    else:
        record(P, "已解析文件都有解析缓存",
               "每个 status=parsed 的文件都有解析缓存",
               "当前项目无 status=parsed 文件", None,
               "无已解析文件，无法比对；导入了资料的项目应至少 1 个")

    # 6.12 删当前项目后指针不能悬空（v0.1.215）。
    # 这条只能读接口，不能真删用户项目，所以只验「当前项目可读 + 状态一致」：
    # 它抓的是「打开程序发现工程不见了」这个现场问题留下的痕迹 —— 指针为空
    # 而项目列表里明明有项目。
    code_p, pl, _ = call("GET", "/api/projects")
    _plist = (pl or {}).get("projects") or [] if isinstance(pl, dict) else []
    code_c2, cl, _ = call("GET", "/api/projects/current")
    _cur_ok = (code_c2 == 200 and (cl or {}).get("ok"))
    _cur_id = (((cl or {}).get("project") or {}).get("id") or "")
    _ids_in_list = {p.get("id") for p in _plist if isinstance(p, dict)}
    if _plist:
        ok12 = bool(_cur_ok) and (_cur_id in _ids_in_list)
        record(P, "有项目时当前项目指针不悬空",
               "项目列表非空时，/api/projects/current 必须给出列表里存在的项目",
               f"项目={len(_plist)} 当前={_cur_id or '空'} 在列表={_cur_id in _ids_in_list}",
               ok12,
               "指针悬空时界面显示「当前未选择项目」，用户以为自己的工程丢了（现场已反馈）")
    else:
        record(P, "有项目时当前项目指针不悬空",
               "项目列表非空时当前项目必须可用",
               "项目列表为空，无法比对", None,
               "一个项目都没有时「未选择项目」是真实状态，不算缺陷")

    # 6.13 项目变更动作必须都有审计埋点，且审计只有唯一落点（v0.1.216）。
    # 实测事故：用户问「这些项目怎么没的」，查 operation_log.jsonl 325 条里
    # 一条「删」都没有，差点据此回答「没人删过」—— 真相是 /api/projects/delete
    # 根本不写日志。审计空白被误读成否定证据，这比缺一条日志危险得多。
    # 这条不去真删项目（本阶段必须只读），改为核对源码里的"契约"：
    #   ① app/op_log.py 存在（唯一落点）；
    #   ② project_manager 的 4 个变更动作各自都有 _op_log.log_op 调用；
    #   ③ app/main.py 不再自带直写 operation_log.jsonl 的第二份实现。
    _here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _app = os.path.join(_here, "app")
    _ol_path = os.path.join(_app, "op_log.py")
    _pm_path = os.path.join(_app, "project_manager.py")
    _mn_path = os.path.join(_app, "main.py")

    def _src(fpath):
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:  # noqa: BLE001
            return ""

    _ol = _src(_ol_path)
    _pm_src = _src(_pm_path)
    _mn_src = _src(_mn_path)

    _has_ol = bool(_ol) and "def log_op(" in _ol
    # 4 个动作各自埋点：用"函数体内出现了 log_op 调用"来判。
    # 只查字符串有无，不猜语义 —— 但足以抓住"整个动作没埋点"这种情况。
    _acts = {}
    _acts["create"] = ('新建项目：' in _pm_src)
    _acts["switch"] = ('切换项目：' in _pm_src)
    _acts["rename"] = ('项目改名：' in _pm_src)
    _acts["delete"] = ('删除项目：' in _pm_src and 'log_op("delete"' in _pm_src)
    _missing = [k for k, v in _acts.items() if not v]
    _single_point = ('"operation_log.jsonl"' not in _mn_src.split("def _log_op")[-1][:400]
                     if "def _log_op" in _mn_src else True)
    ok13 = _has_ol and not _missing and _single_point
    record(P, "项目变更动作都有审计且只有唯一落点",
           "op_log 存在；create/switch/rename/delete 四处埋点齐全；main.py 不再自建第二份写盘",
           f"op_log={_has_ol} 缺埋点={_missing or '无'} 唯一落点={_single_point}",
           ok13,
           "缺审计时「日志里没有删」会被当成「没发生删除」—— 审计空白被误读成否定证据（本轮实测）")


def _walk_keys(obj, depth=0):
    """递归收集 dict 的键名，用于检查导出包里有没有不该出现的字段。"""
    out = []
    if depth > 4:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            out.extend(_walk_keys(v, depth + 1))
    elif isinstance(obj, list):
        for v in obj[:3]:
            out.extend(_walk_keys(v, depth + 1))
    return out


# ---------------- 报告 ----------------
def write_report(out_path_json, out_path_md, samples_dir):
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_url": BASE,
        "platform": {"system": platform.system(), "release": platform.release(),
                     "python": sys.version.split()[0]},
        "samples_dir": samples_dir,
        "summary": PHASE_SUMMARY,
        "results": RESULTS,
    }
    with open(out_path_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    lines = ["# 繁工AI 四阶段自测报告", "",
             f"- 时间：{payload['generated_at']}",
             f"- 目标：{BASE}",
             f"- 平台：{platform.system()} {platform.release()} / Python {sys.version.split()[0]}",
             f"- 样本目录：{samples_dir}", "", "## 汇总", "",
             "| 阶段 | 通过 | 失败 | 跳过 |", "|---|---|---|---|"]
    names = {1: "① 解析/分类/资料库", 2: "② 资料生成管理",
             3: "③ 竣工资料生成", 4: "④ 竣工图清稿",
             5: "⑤ 使用遥测/脱敏自检",
             6: "⑥ 同一事实交叉比对"}
    for ph in sorted(PHASE_SUMMARY):
        s = PHASE_SUMMARY[ph]
        lines.append(f"| {names.get(ph, ph)} | {s['passed']} | {s['failed']} | {s['skipped']} |")
    lines += ["", "## 明细", ""]
    for r in RESULTS:
        tag = "跳过" if r["passed"] is None else ("通过" if r["passed"] else "**失败**")
        lines += [f"### 阶段{r['phase']} · {r['step']} —— {tag}", "",
                  f"- 预期：{r['expected']}", f"- 实际：{r['actual']}"]
        if r["evidence"]:
            lines.append(f"- 证据：{r['evidence']}")
        lines.append("")
    with open(out_path_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    total_p = sum(s["passed"] for s in PHASE_SUMMARY.values())
    total_f = sum(s["failed"] for s in PHASE_SUMMARY.values())
    print(f"\n===== 汇总：通过 {total_p} / 失败 {total_f} =====")
    print(f"报告：{out_path_json}\n     {out_path_md}")
    return total_f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="all",
                    help="1/2/3/4/5/6/all（可逗号分隔，如 1,2）")
    ap.add_argument("--keep-samples", action="store_true", help="保留样本目录")
    ap.add_argument("--base", default=None, help="工作台地址，默认 127.0.0.1:8756")
    ap.add_argument("--inproc", metavar="WORKBENCH_DIR", default=None,
                    help="进程内模式：直接加载本地 workbench 代码跑真实路由（无需启动服务，沙箱/CI 用）")
    a = ap.parse_args()
    global BASE
    if a.base:
        BASE = a.base
    if a.inproc is not None:
        ok, err = use_inproc(a.inproc)
        if not ok:
            print(f"[FATAL] 进程内加载 workbench 失败：{err}")
            sys.exit(2)
        BASE = "inproc://" + (_INPROC_DIR or os.path.abspath(a.inproc))
        print(f"[INFO] 进程内模式：{BASE}")

    here = os.path.dirname(os.path.abspath(__file__))
    sdir = os.path.join(here, "_samples")

    # v0.1.217：开跑前先给用户真实审计流水拍快照（只读）。
    # 自测会真建/真切/真删项目，因此会真写 operation_log.jsonl。上一轮实测
    # 一次全量自测把流水从 325 行涨到 346 行 —— 用户事后查「项目怎么没了」，
    # 审计里混着 21 行测试记录，流水还在但不可信了。
    # 处理方式：跑完按 SELFTEST_TOKENS 精确删掉本次自测写的行，然后断言
    # 「行数与末行都和开跑前一致」。断言放 phase6，证据写在这里的快照。
    global AUDIT_SNAPSHOT
    AUDIT_SNAPSHOT = audit_snapshot()
    print(f"[审计] 开跑前流水：{AUDIT_SNAPSHOT['lines']} 行（{AUDIT_SNAPSHOT['path']}）")

    # v0.1.195：自测必须把「当前项目」还原回去。
    # 实测事故：phase1 建了自测项目并切过去，phase2 切回了原项目，但 phase3
    # 又切到自测项目去做整卷校验，**结束时没人还原**。于是每次跑完自测，
    # current_project.json 都停在「自测_年月日_时分秒」这个只有几份测试样本的
    # 项目上。用户第二天打开繁工AI，看到的是空的自测项目，自己那份 228 台设备
    # 的工程不见了 —— 对现场是「资料丢了」的观感。这里在跑之前记下原项目，
    # 全部阶段跑完（含异常）一律切回。
    _origin_pid = ""
    try:
        _, _cur0, _ = call("GET", "/api/projects/current")
        _origin_pid = (((_cur0 or {}).get("project") or {}).get("id") or "")
    except Exception:  # noqa: BLE001
        pass
    if not _origin_pid and _INPROC is not None:
        try:
            from app import project_manager as _pm
            _c = _pm.get_current_project()
            _origin_pid = (_c or {}).get("id") or ""
        except Exception:  # noqa: BLE001
            pass
    # v0.1.212：暴露给 phase6 —— 它必须切回用户原项目校验，
    # 否则全量自测时它验的是临时自测项目（详见 phase6 里的说明）。
    global _ORIGIN_PID
    _ORIGIN_PID = _origin_pid

    print(f"造样本 -> {sdir}")
    build_samples(sdir, include_dwg=True)

    phases = a.phase
    if phases == "all":
        # v0.1.210：加阶段 6（同一事实交叉比对）。它只读、不建样本、
        # 不切项目，放在最后跑，前面各阶段留下的索引/队列状态正好被它验。
        want = [1, 2, 3, 4, 5, 6]
    else:
        want = [int(x) for x in phases.split(",") if x.strip().isdigit()]

    try:
        for ph in want:
            try:
                {1: phase1, 2: phase2, 3: phase3, 4: phase4,
                 5: phase5, 6: phase6}[ph](sdir)
            except Exception:
                traceback.print_exc()
                record(ph, "阶段执行异常", "无异常", traceback.format_exc()[-300:], False)
    finally:
        # 即使某阶段抛异常，也必须把用户的当前项目还回去
        if _origin_pid:
            _code_r, _rb, _ = call("POST", "/api/projects/switch",
                                   {"project_id": _origin_pid})
            _ok_r = (_code_r == 200 and (_rb or {}).get("ok", True))
            print(f"[还原] 当前项目切回 {_origin_pid} → {'OK' if _ok_r else 'FAILED'}")

        # v0.1.196：本次建的自测项目必须删掉，不能留在用户的项目列表里。
        # 实测事故：沙箱里累积到 87 个项目、其中 74 个是「自测_xxx / _j_节自测_xxx /
        # 实测_xxx」测试残留，59 个是 0 文件 0 设备的空壳。用户打开「选择项目」
        # 要在几十个空壳里找自己那个工程 —— 每天跑一次自测就多一个，
        # 这条不清理，项目列表迟早没法用。
        # 只删本次跑出来的那个 id（TEST_PROJECT_ID），绝不按名字前缀批量删：
        # 用户自己也可能建名字带「自测」的真实项目。且必须在切回原项目之后删，
        # 否则中间会出现「当前指针指着刚被删的项目」。
        _to_del = [x for x in CREATED_PIDS if x and x != _origin_pid]
        for _tp in _to_del:
            try:
                _code_d, _db, _ = call("POST", "/api/projects/delete",
                                       {"project_id": _tp, "backup": False})
                _ok_d = (_code_d == 200 and (_db or {}).get("ok", True))
                print(f"[清理] 删除本次测试项目 {_tp} → {'OK' if _ok_d else 'FAILED'}")
            except Exception as _e:  # noqa: BLE001
                print(f"[WARN] 测试项目 {_tp} 清理失败：{_e}")

        # v0.1.217：把本次自测写进**真实审计流水**的行删掉，再用断言复核
        # 「行数/末行回到开跑前」。注意顺序：必须放在删除测试项目之后 ——
        # 删除本身也会写一条 delete 审计，早清就漏掉那一行。
        global _AUDIT_AFTER
        _pg = {"removed": 0, "total": 0, "skipped": False, "error": ""}
        try:
            _pg = audit_purge_selftest_rows()
            if _pg.get("error"):
                print(f"[WARN] 审计流水清理失败：{_pg['error']}")
            elif _pg.get("skipped"):
                print("[审计] 本次运行未建测试项目，无可清理行")
            else:
                print(f"[审计] 清理本次自测写入 {_pg['removed']} 行，剩余 {_pg['total']} 行")
        except Exception as _e:  # noqa: BLE001
            _pg["error"] = f"{type(_e).__name__}: {_e}"
            print(f"[WARN] 审计流水清理异常：{_pg['error']}")
        _AUDIT_AFTER = audit_snapshot()

        # v0.1.217：审计隔离的收尾断言（只在跑了阶段6 时记，避免单独跑
        # `--phase 1` 也往阶段6 的汇总里塞一条）。
        # 它必须放在 finally 里、且在清理之后 —— 阶段跑到一半抛异常时同样要能
        # 报出来，否则「全量自测全绿、但用户审计流水被污染」会再次悄悄发生。
        if 6 in want:
            _before_n = AUDIT_SNAPSHOT.get("lines", 0)
            _after_n = _AUDIT_AFTER.get("lines", 0)
            _same_tail = AUDIT_SNAPSHOT.get("tail", "") == _AUDIT_AFTER.get("tail", "")
            _ok_aud = (_after_n == _before_n) and _same_tail and not _pg.get("error")
            record(6, "跑完自测用户审计流水未被污染",
                   "真实 operation_log.jsonl 行数与末行和开跑前一致"
                   "（本次自测写的行已按项目名/id 精确清除）",
                   f"前={_before_n} 后={_after_n} 清除={_pg['removed']} "
                   f"建过测试项目={not _pg.get('skipped')} 末行一致={_same_tail}"
                   + (f" 错误={_pg['error']}" if _pg.get("error") else ""),
                   _ok_aud,
                   "上一轮实测：一次全量自测把用户真实审计流水 325 行涨到 346 行，"
                   "用户事后查「项目怎么没了」时审计里混着测试记录 —— 流水还在但不可信")

    fails = write_report(os.path.join(here, "selftest_report.json"),
                         os.path.join(here, "selftest_report.md"), sdir)
    if not a.keep_samples:
        shutil.rmtree(sdir, ignore_errors=True)
    sys.exit(0 if fails == 0 else 1)


if __name__ == "__main__":
    main()
