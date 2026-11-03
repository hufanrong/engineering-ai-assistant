#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.1.193 回归测试：车间下拉的数据源必须与台账一致（不能靠文件名猜）。

实测事故（真实项目 e75e857c，228 台设备，台账行内 19 个车间）：

  /api/workshops 返回 1 个车间 —— 「选矿厂」。
  这个「选矿厂」来自**设备台账的文件名**「设备台账_真实_选矿厂.xlsx」，
  由 workshop_assign 的 filename 推测规则得出，confidence 0.75。
  台账里真实存在的 19 个车间（粗碎站 / 磨浮车间 / 脱水车间 …）一个都没出现。

  同一个项目的 index.json 里 228 台设备**每台都带 workshop**，19 个车间俱在；
  整卷也按这 19 个车间正常出表（54 份 docx）。

  后果：前端「资料生成」的车间下拉（loadDocgenWorkshops，web/index.html:1970）
  只填得出「选矿厂」。用户按下拉选它，/api/docgen/prefill 实测
  devices=0、missing=5 项 → 生成的施工方案没有任何设备内容；
  而留空「全部车间」时 devices=60。**下拉里唯一的选项是错的，用户无从知道。**

判据（每条都对应一个错误实现会失败的地方）：

  T1 车间清单必须包含台账行里的真实车间（不得只剩文件名猜出来的那个）。
  T2 清单里不得出现「只由文件名推出、台账行里根本不存在」的车间。
  T3 每个列出的车间都能预填到设备（>0）—— 列出却查不到设备等于假选项。
  T4 台账无车间列时不得因此清空清单（回落到原有来源，而不是把一切判成空）。

跑法：python tools/test_workshop_source.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.main as M
from app import project_manager as pm

RESULTS = []


def check(name, cond, detail):
    RESULTS.append({"name": name, "passed": bool(cond), "detail": detail})
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}: {detail}")


def _make_project(devices, file_name, workshop_hint=""):
    """造一个项目：index.json 里放设备，workshop_assign 里放文件级车间归属。"""
    pid = "ws_src_test"
    ddir = os.path.join(pm.PROJECTS_ROOT, pid)
    os.makedirs(ddir, exist_ok=True)
    idx = {"files": {}, "devices": devices, "workshops": {}, "updated_at": "2026-01-01"}
    with open(os.path.join(ddir, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    with open(os.path.join(ddir, "project_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"id": pid, "name": "车间来源测试项目"}, f, ensure_ascii=False)
    sha = "sha_" + pid
    with open(os.path.join(ddir, "workshop_assign.json"), "w", encoding="utf-8") as f:
        json.dump({sha: {"sha256": sha, "file_name": file_name, "workshop": workshop_hint,
                         "source": "filename", "confidence": 0.75,
                         "candidates": [workshop_hint] if workshop_hint else [],
                         "file_path": "", "ts": "2026-01-01T00:00:00"}}, f, ensure_ascii=False)
    return pid, ddir


def _cleanup(ddir):
    import shutil
    try:
        shutil.rmtree(ddir)
    except Exception:  # noqa: BLE001
        pass


def run():
    print("=" * 62)
    print("v0.1.193 车间下拉数据源回归测试")
    print("=" * 62)

    # 与真实项目同形：台账文件名带「选矿厂」，行内 19 个车间
    real_ws = ["粗碎站", "磨浮车间", "脱水车间", "尾矿库", "重选车间"]
    devices = {}
    for i, w in enumerate(real_ws):
        for j in range(3):
            tag = "_no_tag_设备%d-%d|%s" % (i, j, w)
            devices[tag] = {"name": "设备%d-%d" % (i, j), "model": "", "quantity": "1",
                            "unit": "台", "weight": "", "workshop": w,
                            "source_file": "设备台账_真实_选矿厂.xlsx"}

    pid, ddir = _make_project(devices, "设备台账_真实_选矿厂.xlsx", workshop_hint="选矿厂")
    old_cur = getattr(M, "_CURRENT_PROJECT_ID", None)
    try:
        pm.set_current_project(pid) if hasattr(pm, "set_current_project") else None

        rows = M.get_workshops()
        names = [r["name"] for r in rows.get("workshops", [])]
        print(f"  车间清单：{names}")

        t1_missing = [w for w in real_ws if w not in names]
        check("T1 车间清单含台账真实车间", not t1_missing,
              f"应有 {len(real_ws)} 个，缺 {t1_missing or '无'}；实得 {names}")

        # T2：文件级车间必须保留 —— 修下拉不能靠「把文件名来的车间删掉」蒙过去，
        #     那会把已上传的台账文件从「资料管理」里藏起来（它在文件级归属上是对的：
        #     一份台账本来就是一整厂的文件）。
        keep = [r for r in rows.get("workshops", []) if r["name"] == "选矿厂"]
        check("T2 文件级车间仍保留（不靠删条目过检）",
              bool(keep) and keep[0].get("file_count", 0) > 0,
              f"选矿厂 file_count={keep[0].get('file_count') if keep else '缺失'}；"
              f"清单={names}")

        # T2b/T3：**资料生成下拉**只能列台账里真有设备的车间（那是拿去查设备预填的）
        dg = rows.get("docgen_workshops") or []
        bad_dg = [n for n in dg if n not in real_ws]
        check("T2b 资料生成下拉不含臆测车间", not bad_dg,
              f"实得 {dg}；不应出现 {bad_dg or '无'}")

        empty = []
        for n in dg:
            r = M._prefill_data(n, "施工方案")
            if not (r.get("devices") or []):
                empty.append(n)
        check("T3 每个车间都能预填设备", not empty,
              f"列了却查不到设备的车间：{empty or '无'}（共 {len(dg)} 个车间）")

        # T4：台账没有车间列（文件级也没有归属）时不能把清单清空
        no_ws_devices = {"t1": {"name": "设备1", "quantity": "1", "unit": "台", "workshop": ""}}
        pid2, ddir2 = _make_project(no_ws_devices, "无车间台账.xlsx", workshop_hint="")
        try:
            pm.set_current_project(pid2) if hasattr(pm, "set_current_project") else None
            rows2 = M.get_workshops()
            n2 = len(rows2.get("workshops", []))
            check("T4 台账无车间列不清空清单", n2 > 0,
                  f"实得 {n2} 个车间（不得因为台账没车间列就变空）")
        finally:
            _cleanup(ddir2)
    finally:
        _cleanup(ddir)
        if old_cur:
            try:
                pm.set_current_project(old_cur)
            except Exception:  # noqa: BLE001
                pass

    ok = sum(1 for r in RESULTS if r["passed"])
    bad = len(RESULTS) - ok
    print("-" * 62)
    print(f"结果：通过 {ok} / 失败 {bad}")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_workshop_source_report.json"), "w", encoding="utf-8") as f:
        json.dump({"total": len(RESULTS), "passed": ok, "failed": bad,
                   "results": RESULTS}, f, ensure_ascii=False, indent=2)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run())
