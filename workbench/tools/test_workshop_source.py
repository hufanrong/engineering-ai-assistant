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
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.config as config  # noqa: E402

# v0.1.217：本测试会真的建项目、真的切当前项目、真的写审计流水。
# 原来它直接在用户真实 data/projects 里建 ws_src_test 并切过去 ——
# 实测后果（本轮抓到的）：① 用户真实 operation_log.jsonl 被写进 8 行
# 「切换项目：… → 车间来源测试项目」；② 一旦中途异常，_cleanup 与还原
# 都可能执行不到，指针就停在刚被删的项目上（界面显示「当前未选择项目」）。
# 手法与 test_project_audit_log 一致：先切 config.DATA_DIR 到临时目录，
# **再** import app.main —— PROJECTS_ROOT / CURRENT_PROJECT_FILE 都是
# 模块级常量，import 时机决定了它们指向哪里。
_REAL_AUDIT_SNAPSHOT = {"lines": 0, "tail": ""}


def _snap_real_audit(path=None):
    """审计流水快照（只读）：行数 + 末行。

    path 必须显式传入**真实**路径 —— 本模块很早就把 config.DATA_DIR 切到
    临时目录了，收尾时再读 config.DATA_DIR 读到的是临时目录里的流水，
    断言会变成「前=333 后=3」这种自欺欺人的数字（实测踩过）。
    """
    p = path or os.path.join(config.DATA_DIR, "operation_log.jsonl")
    snap = {"lines": 0, "tail": ""}
    if not os.path.isfile(p):
        return snap
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.strip():
                snap["lines"] += 1
                snap["tail"] = line.strip()
    return snap


_REAL_DATA_DIR = config.DATA_DIR
_REAL_AUDIT_PATH = os.path.join(_REAL_DATA_DIR, "operation_log.jsonl")
_REAL_AUDIT_SNAPSHOT = _snap_real_audit(_REAL_AUDIT_PATH)
_TMP_DATA = tempfile.mkdtemp(prefix="fg_ws_src_")
config.DATA_DIR = _TMP_DATA            # 必须在 import app.main 之前

import app.main as M  # noqa: E402
from app import project_manager as pm  # noqa: E402

RESULTS = []


def check(name, cond, detail):
    RESULTS.append({"name": name, "passed": bool(cond), "detail": detail})
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}: {detail}")


def _make_project(devices, file_name, workshop_hint="", pid="ws_src_test"):
    """造一个项目：index.json 里放设备，workshop_assign 里放文件级车间归属。

    pid 必须可传（v0.1.194）：原来写死 "ws_src_test"，T4 再调一次就把主项目的
    index.json **覆盖**了、随后 _cleanup 又把目录删掉，导致后面的 T5 查不到
    任何设备（实测 T5 报 total=0）。同一个测试里造两个项目必须用两个 id。
    """
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

    # v0.1.195：原项目必须从 current_project.json 读，不能从 M._CURRENT_PROJECT_ID 取。
    # 实测事故：app/main.py 里根本没有 _CURRENT_PROJECT_ID 这个变量（grep 全仓 0 命中），
    # getattr 永远返回 None，于是 finally 里 `if old_cur:` 从不成立 —— 还原代码写了
    # 但从来没执行过。更糟的是这个测试切到 ws_src_test，随后 _cleanup 又把这个项目
    # **删掉**，current_project.json 就指向一个不存在的 id：
    #   {"project_id": "ws_src_test", "project_name": "车间来源测试项目"}
    # 用户打开界面看到的是「当前未选择项目，请先新建或选择项目」——等于自己的工程不见了。
    try:
        _oc = pm.get_current_project()
        old_cur = (_oc or {}).get("id") or ""
        _oc_name = (_oc or {}).get("name") or ""
    except Exception:  # noqa: BLE001
        old_cur, _oc_name = "", ""
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
        pid2, ddir2 = _make_project(no_ws_devices, "无车间台账.xlsx", workshop_hint="",
                                    pid="ws_src_test_empty")
        try:
            pm.set_current_project(pid2) if hasattr(pm, "set_current_project") else None
            rows2 = M.get_workshops()
            n2 = len(rows2.get("workshops", []))
            check("T4 台账无车间列不清空清单", n2 > 0,
                  f"实得 {n2} 个车间（不得因为台账没车间列就变空）")
        finally:
            _cleanup(ddir2)

        # T5/T6：v0.1.194 —— 台账车间**没有上传资料**，点开卡片不能只剩「暂无文件」。
        # 实测真实项目 20 张卡片里 19 张是这种，「中矿堆」台账里有 13 台设备，
        # 原来点进去什么都看不到。新增 /api/workshop/devices 按车间取台账设备。
        pm.set_current_project(pid) if hasattr(pm, "set_current_project") else None
        d_mufu = M.workshop_devices("磨浮车间")
        check("T5 台账车间能查到设备清单", (d_mufu.get("total") or 0) > 0,
              f"磨浮车间 total={d_mufu.get('total')}，首台={(d_mufu.get('devices') or [{}])[0].get('name')}")

        # T6：不存在的车间必须老实返回 0，不能把全厂设备倒出去（否则界面上
        #     任何名字都能点出一堆设备，用户会以为归属是乱分的）
        d_bad = M.workshop_devices("不存在的车间XYZ")
        check("T6 未知车间返回 0 台（不倒全厂）", (d_bad.get("total") or 0) == 0,
              f"total={d_bad.get('total')}")
    finally:
        _cleanup(ddir)
        # 还原必须落在 _cleanup 之后：先删测试项目，再切回原项目，
        # 否则中间会存在「指针指着刚被删的项目」的一瞬间。
        if old_cur:
            try:
                pm.set_current_project(old_cur)
                print(f"  [还原] 当前项目已切回 {old_cur}（{_oc_name}）")
            except Exception as _e:  # noqa: BLE001
                print(f"  [WARN] 当前项目还原失败：{_e}")

    # T7：还原之后，current_project.json 必须指向一个**真实存在、能读出来**的项目。
    # 只断言「调过 set_current_project」不够——实测过的坑是这个测试把指针留在
    # ws_src_test 上，而该目录已被 _cleanup 删掉，界面于是显示「当前未选择项目」。
    if old_cur:
        try:
            _now = pm.get_current_project()
        except Exception:  # noqa: BLE001
            _now = None
        check("T7 测试结束后当前项目可用（不指向已删除项目）",
              bool(_now) and _now.get("id") == old_cur,
              f"原项目={old_cur}，测试后=({(_now or {}).get('id')}, "
              f"{(_now or {}).get('name')})")

    # v0.1.217：本测试已改为在临时 DATA_DIR 里跑，收尾必须证明
    # 「用户真实审计流水一行没多、末行没变」—— 这是它以前污染过的证据。
    try:
        _now_a = _snap_real_audit(_REAL_AUDIT_PATH)
        _audit_ok = (_now_a["lines"] == _REAL_AUDIT_SNAPSHOT["lines"]
                     and _now_a["tail"] == _REAL_AUDIT_SNAPSHOT["tail"])
        check("T8 本测试未写用户真实审计流水",
              _audit_ok,
              f"前={_REAL_AUDIT_SNAPSHOT['lines']} 后={_now_a['lines']}")
    except Exception as _e:  # noqa: BLE001
        check("T8 本测试未写用户真实审计流水", False, f"{type(_e).__name__}: {_e}")

    # 临时数据目录用完即删，不留残骸
    try:
        import shutil as _sh
        _sh.rmtree(_TMP_DATA, ignore_errors=True)
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
