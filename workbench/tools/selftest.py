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
    code, body, err = call("POST", "/api/projects/create", {"name": proj_name})
    record(P, "项目创建", "200 且 ok=true", f"{code} {str(body)[:80]}",
           code == 200 and (body or {}).get("ok", True), err)
    # v0.1.173：记住测试项目 id，供 phase3 显式切回去
    global TEST_PROJECT_ID
    _pj = (body or {}).get("project") or {}
    if _pj.get("id"):
        TEST_PROJECT_ID = _pj["id"]

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
    filled = [ph for ph in phases if ph.get("existing")]
    record(P, "完整性检查", "200 且至少一个阶段有已存在的资料",
           f"{code} phases={len(phases)} 有资料的阶段={len(filled)}", code == 200 and bool(filled), err)

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
        code_new, nb, err_new = call("POST", "/api/projects/create",
                                     {"name": f"自测隔离_{time.strftime('%H%M%S')}"})
        _new_id = ((nb or {}).get("project") or {}).get("id") or ""
        if _new_id:
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
             5: "⑤ 使用遥测/脱敏自检"}
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
                    help="1/2/3/4/5/all（可逗号分隔，如 1,2）")
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
    print(f"造样本 -> {sdir}")
    build_samples(sdir, include_dwg=True)

    phases = a.phase
    if phases == "all":
        want = [1, 2, 3, 4, 5]
    else:
        want = [int(x) for x in phases.split(",") if x.strip().isdigit()]

    for ph in want:
        try:
            {1: phase1, 2: phase2, 3: phase3, 4: phase4, 5: phase5}[ph](sdir)
        except Exception:
            traceback.print_exc()
            record(ph, "阶段执行异常", "无异常", traceback.format_exc()[-300:], False)

    fails = write_report(os.path.join(here, "selftest_report.json"),
                         os.path.join(here, "selftest_report.md"), sdir)
    if not a.keep_samples:
        shutil.rmtree(sdir, ignore_errors=True)
    sys.exit(0 if fails == 0 else 1)


if __name__ == "__main__":
    main()
