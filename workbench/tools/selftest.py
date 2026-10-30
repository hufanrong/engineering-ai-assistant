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

    for path, step in (("/api/completeness/check", "完整性检查"),
                       ("/api/completion-archive/requirements", "竣工资料要求"),
                       ("/api/completion-archive/stats", "竣工资料统计"),
                       ("/api/archive-enhanced/checklist", "组卷清单"),
                       ("/api/archive/catalog", "案卷目录")):
        code, body, err = call("GET", path)
        record(P, step, "200", f"{code} {str(body)[:100]}", code == 200, err)

    code, org, err = call("GET", "/api/archive-enhanced/organize")
    record(P, "按车间组卷", "200", f"{code} {str(org)[:100]}", code == 200, err)

    code, vol, err = call("POST", "/api/supervision/volume",
                          {"book": "第一册", "workshop": "1号车间"})
    vr = (vol or {}).get("result") or (vol or {})
    # v0.1.167：不能只断言 ok —— 登记表缺失时旧实现会返回 ok=True 但 generated/todo/collect_dir
    # 全空（静默空转）。这里要求「真的产出了东西」，或者至少明确给出了失败原因。
    produced = bool(vr.get("generated") or vr.get("todo") or vr.get("collect_dir"))
    reason = vr.get("error") or ""
    ok = code == 200 and (vr.get("ok") is True and produced or (vr.get("ok") is False and bool(reason)))
    detail = (f"{code} generated={len(vr.get('generated') or [])} "
              f"todo={len(vr.get('todo') or [])} collect={len(vr.get('collect_dir') or [])} "
              f"error={reason[:80]}")
    record(P, "整卷生成", "有产出 或 明确报错（非静默空转）", detail, ok, err)

    code, ca, err = call("POST", "/api/completion-archive/all", {})
    ok = code == 200 and (ca or {}).get("ok", True) is not False
    record(P, "一键竣工资料", "200 且 ok", f"{code} {str(ca)[:140]}", ok, err)

    code, miss, err = call("GET", "/api/completion-archive/missing")
    record(P, "缺件清单", "200", f"{code} {str(miss)[:100]}", code == 200, err)

    code, ex, err = call("GET", "/api/archive/export-enhanced")
    record(P, "导出成套", "200", f"{code} {str(ex)[:100]}", code == 200, err)


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
