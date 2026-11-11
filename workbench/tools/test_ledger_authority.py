# -*- coding: utf-8 -*-
"""v0.1.236 回归测试：设备台账是车间名的权威清单。

用户 2026-11-11 追加指令原话：
    「在设备清单中已经给出多个车间了,里面已经包含实际的车间名称了,
      不要在生成其他乱七八糟的车间名字」

上一版（v0.1.235）解决的是「未审批的名字不能自动变成车间」，但那条规则仍允许
算法**猜出新名字**并把它挂进待审批队列 —— 用户不需要审一个显然不存在的东西。
本次口径：设备台账（index.json 的 devices，人填的 workshop 列）非空时，
它就是权威清单；台账里没有的名字一律不作数（不进正式清单、不进待审批队列）。

判据（每条都对应一个错误实现会失败的地方）：
    L1 台账车间能反查命中文件名（source=ledger，不再靠正则猜）
    L2 猜出来、台账里没有的名字 → workshop 为空（不成为车间）
    L3 猜出来的名字不进待审批队列（不让人去审不存在的东西）
    L4 /api/workshops 正式清单只含台账车间（非台账名被排除）
    L5 台账为空时退回旧逻辑（不得因为没台账就把一切判空）
    L6 人工确认过的名字即使不在台账里也保留（人显式点过头）
    L7 本测试未写用户真实项目目录 / 审计流水

跑法：python tools/test_ledger_authority.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.config as config  # noqa: E402

_REAL_DATA_DIR = config.DATA_DIR


def _snap_dir(root):
    snap = {}
    if not os.path.isdir(root):
        return snap
    for dp, dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            try:
                snap[p] = os.path.getsize(p)
            except OSError:
                pass
    return snap


def _snap_audit(path):
    snap = {"lines": 0, "tail": ""}
    if not os.path.isfile(path):
        return snap
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.strip():
                snap["lines"] += 1
                snap["tail"] = line.strip()
    return snap


# 必须先快照真实路径，再把 DATA_DIR 切走（切换后再读就是临时目录了）
_REAL_PROJECTS = os.path.join(_REAL_DATA_DIR, "projects")
_REAL_AUDIT = os.path.join(_REAL_DATA_DIR, "operation_log.jsonl")
_BEFORE_PROJ = _snap_dir(_REAL_PROJECTS)
_BEFORE_AUDIT = _snap_audit(_REAL_AUDIT)

_TMP = tempfile.mkdtemp(prefix="fg_ledger_auth_")
config.DATA_DIR = _TMP

import app.main as M            # noqa: E402
from app import project_manager as pm   # noqa: E402
from app import workshop_assign as wa   # noqa: E402

RESULTS = []

# 台账里的真实车间（用户设备清单里已经给出的）
LEDGER = ["磨浮车间", "粗碎站", "脱水车间", "尾矿库"]
# 算法会猜出来、但台账里根本没有的名字（用户点名骂过的那种）
DIRTY = "建宇建主减速机油站"
DIRTY2 = "件与件之间"


def check(name, cond, detail):
    RESULTS.append({"name": name, "passed": bool(cond), "detail": detail})
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}: {detail}")


def _mk_project(pid, devices=None, files=None):
    d = os.path.join(pm.PROJECTS_ROOT, pid)
    os.makedirs(d, exist_ok=True)
    idx = {"files": files or {}, "devices": devices or {}, "workshops": {},
           "updated_at": "2026-01-01"}
    with open(os.path.join(d, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    with open(os.path.join(d, "project_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"id": pid, "name": "台账权威测试"}, f, ensure_ascii=False)
    pm.set_current_project(pid, log=False)
    return d


def _reset(d):
    for fn in ("workshop_assign.json", "workshop_registry.json", "workshop_candidates.json"):
        p = os.path.join(d, fn)
        if os.path.isfile(p):
            os.remove(p)
    wa._REG_CACHE.clear()
    wa._LEDGER_CACHE.clear()


def _devices():
    dev = {}
    for i, w in enumerate(LEDGER):
        for j in range(2):
            dev["_no_tag_设备%d-%d|%s" % (i, j, w)] = {
                "name": "设备%d-%d" % (i, j), "model": "", "quantity": "1",
                "unit": "台", "weight": "", "workshop": w,
                "source_file": "设备台账_真实_选矿厂.xlsx"}
    return dev


def run():
    print("=" * 62)
    print("v0.1.236 设备台账是车间权威清单 回归测试")
    print("=" * 62)

    old = None
    try:
        c = pm.get_current_project()
        old = (c or {}).get("id")
    except Exception:  # noqa: BLE001
        old = None

    d = _mk_project("ledger_auth_test", _devices())
    _reset(d)

    # ---- L1：台账车间反查命中文件名 ----
    r1 = wa.assign_workshop("sha_led_1", "磨浮车间-设备布置图.dwg", "", {}, file_path="")
    check("L1 台账车间反查命中文件名（source=ledger）",
          r1.get("workshop") == "磨浮车间" and r1.get("source") == "ledger",
          "workshop=%r source=%r" % (r1.get("workshop"), r1.get("source")))

    # ---- L2：猜出来但台账没有的名字 → 不作车间 ----
    r2 = wa.assign_workshop("sha_dirty_1", "流程图.dwg", "%s 附近设两台泵" % DIRTY,
                            {}, file_path="")
    check("L2 台账里没有的猜测名不成为车间",
          not r2.get("workshop"),
          "workshop=%r source=%r（台账里有 %s）"
          % (r2.get("workshop"), r2.get("source"), LEDGER))

    # ---- L3：也不进待审批队列 ----
    _c = {x["name"] for x in wa.list_candidates()}
    check("L3 台账里没有的猜测名不进待审批队列",
          DIRTY not in _c and DIRTY2 not in _c,
          "candidates=%s" % sorted(_c))

    # 第二个脏名字同样作废
    r3 = wa.assign_workshop("sha_dirty_2", "说明.dwg", "%s 采用法兰连接" % DIRTY2,
                            {}, file_path="")
    check("L3b 第二个猜测名同样不成为车间、不进队列",
          not r3.get("workshop")
          and DIRTY2 not in {x["name"] for x in wa.list_candidates()},
          "workshop=%r candidates=%s"
          % (r3.get("workshop"), sorted(x["name"] for x in wa.list_candidates())))

    # ---- L4：/api/workshops 正式清单只含台账车间 ----
    w = M.get_workshops()
    names = [x["name"] for x in (w.get("workshops") or [])]
    check("L4 正式车间清单只含台账车间",
          all(n in LEDGER for n in names if n != "未归车间") and LEDGER[0] in names,
          "workshops=%s 台账=%s" % (names, LEDGER))
    check("L4c 台账存在时「未归车间」不作为车间出现在正式清单",
          "未归车间" not in names,
          "workshops=%s（未归车间不是车间，只是没有归属的占位分组）" % names)
    pend = [x["name"] for x in (w.get("pending_workshops") or [])]
    check("L4b 待审批区不含台账外的猜测名",
          DIRTY not in pend and DIRTY2 not in pend,
          "pending=%s" % pend)

    # ---- L6：人工确认过的名字即使不在台账里也保留 ----
    NOT_IN_LEDGER = "粗碎工段"
    wa.approve_workshop(NOT_IN_LEDGER, approved_by="user", note="人工确认的真实单元")
    w2 = M.get_workshops()
    n2 = [x["name"] for x in (w2.get("workshops") or [])]
    check("L6 人工确认过的名字即使不在台账里也保留",
          NOT_IN_LEDGER in n2,
          "workshops=%s（%s 是人工确认的）" % (n2, NOT_IN_LEDGER))

    # ---- L5：台账为空时退回旧逻辑 ----
    d2 = _mk_project("ledger_auth_empty", {}, None)
    _reset(d2)
    r5 = wa.assign_workshop("sha_txt_1", "磨浮车间说明.dwg", "", {}, file_path="")
    check("L5 台账为空时退回旧逻辑（不把一切判空）",
          r5.get("workshop") == "磨浮车间",
          "workshop=%r source=%r" % (r5.get("workshop"), r5.get("source")))
    w3 = M.get_workshops()
    check("L5b 无台账时猜测名进待审批区（仍不自动转正）",
          "磨浮车间" in [x["name"] for x in (w3.get("pending_workshops") or [])]
          and "磨浮车间" not in [x["name"] for x in (w3.get("workshops") or [])],
          "pending=%s workshops=%s"
          % ([x["name"] for x in (w3.get("pending_workshops") or [])],
             [x["name"] for x in (w3.get("workshops") or [])]))

    # ---- 收尾：不污染真实数据 ----
    try:
        if old:
            pm.set_current_project(old, log=False)
    except Exception:  # noqa: BLE001
        pass

    after = _snap_dir(_REAL_PROJECTS)
    check("L7 本测试未写用户真实项目目录", after == _BEFORE_PROJ,
          "快照一致" if after == _BEFORE_PROJ else "差异=%d 项" % (
              len(set(after) ^ set(_BEFORE_PROJ))))
    a2 = _snap_audit(_REAL_AUDIT)
    check("L7b 本测试未写用户真实审计流水",
          a2["lines"] == _BEFORE_AUDIT["lines"] and a2["tail"] == _BEFORE_AUDIT["tail"],
          "前=%s 后=%s" % (_BEFORE_AUDIT["lines"], a2["lines"]))

    ok = sum(1 for r in RESULTS if r["passed"])
    bad = len(RESULTS) - ok
    print("-" * 62)
    print("结果：通过 %d / 失败 %d" % (ok, bad))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_ledger_authority_report.json"), "w",
              encoding="utf-8") as f:
        json.dump({"total": len(RESULTS), "passed": ok, "failed": bad,
                   "results": RESULTS}, f, ensure_ascii=False, indent=2)
    try:
        import shutil
        shutil.rmtree(_TMP, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run())
