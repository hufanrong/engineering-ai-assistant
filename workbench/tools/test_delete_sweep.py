#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.1.240 回归测试：删项目时目录被占用（Windows WinError 32）必须让项目从列表消失。

真机事故（WORKbuddy 报告 20261111_170414，results[74]）：

  「尝试删 2 个，已消失 1 个，仍在列表 1 个，
    错误=…PermissionError: [WinError 32] …\\vector_db\\<uuid>\\data_level0.bin」

  用户视角是「点了删除没反应，再点还报错」——项目既进不去（资料删了一半）
  也出不去（删不掉）。比「删一半」更糟：残骸卡在列表里。

根因（已由真机对照实验定性）：chromadb 的 PersistentClient 打开后不释放
vector_db/<uuid>/data_level0.bin，服务进程自己攥着它；Windows 没有
unlink-on-open，rmtree 必然 WinError 32。「重启服务后同一个请求原样再发一次
就成功」正是这个根因的反证。

v0.1.240 的处置原则是**意图优先于文件锁**：
  · 删不干净时把 project_meta.json 挪到 _detached/（同盘改名，不需要被占用
    的那个句柄），list_projects()/get_project() 读不到 → 项目立刻从界面消失；
  · 目录整体留在原地 + 登记进 pending_project_sweep.json；
  · 下次启动 sweep_pending_deletes() 补删干净。

判据（每条都对应一个错误实现会失败的地方）：

  S1 场景成立：删之前项目确实在列表里（否则 S3「不在列表」恒真、测不出东西）
  S2 删不干净时返回 ok=True + pending_sweep=True + data_deleted=False
  S3 项目不再出现在 list_projects() 里，而**未删的项目仍在**（正负成对）
  S4 get_project() 返回 None（唯一入口断掉，不是只从列表过滤）
  S5 元数据可找回：_detached/<id>/project_meta.json 内容与删前一致
  S6 目录与资料留在原地（没有静默丢数据）
  S7 登记表里有这个 id 和它的真实目录
  S8 当前项目指针不悬空（删的是当前项目时切到接任者）
  S9 审计流水落下一条 delete，且写明「已从列表移除 / 待清理」
  S10 启动续删：sweep_pending_deletes() 把目录删干净、登记表移除
  S11 续删幂等：再调一次 checked=0、不报错
  S12 反向：目录删得干净时不走摘除、不留登记（行为与 v0.1.239 一致）
  S13 摘除失败时退回原样报错（不能把「没做的事」说成做了）
  S14 真实 data/ 未被污染（内容全等，不是键集合差）
  S15 真实审计流水行数未变

跑法：python tools/test_delete_sweep.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.config as config  # noqa: E402

# 同 test_workshop_source.py：先切 config.DATA_DIR 到临时目录，**再** import
# app.main / app.project_manager —— PROJECTS_ROOT / CURRENT_PROJECT_FILE 都是
# 模块级常量，import 时机决定了它们指向哪里。
_REAL_DATA_DIR = config.DATA_DIR


def _snap_audit(path):
    n = 0
    if not os.path.isfile(path):
        return 0
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


# 运行期日志：由**正在跑的服务进程**（本轮 pid 3018）持续追加，
# 与本测试无关，也无法被隔离（服务读的是真实 DATA_DIR）。
# 只排除这两个明确的追加型日志，别的一律照比 —— 排除范围过宽就等于
# 把「真实数据可能被污染」这条断言废掉。
_RUNTIME_LOGS = {
    os.path.join("telemetry", "requests.jsonl"),
    "workbench.log",
}


def _snap_real_tree(root):
    """真实 data/ 的快照（**内容全等**口径，不是键集合差）。

    v0.1.238 的教训：键集合差抓不住「覆盖写」——同一条记录被改写，
    键没变、内容变了，差集恒为空。这里对每个文件取 sha256。
    """
    snap = {}
    if not os.path.isdir(root):
        return snap
    for dirpath, dirnames, filenames in os.walk(root):
        # projects/ 目录本身单独用条目数比较（删/建项目是本次业务，不该算污染）
        rel = os.path.relpath(dirpath, root)
        if rel == "projects" or rel.startswith("projects" + os.sep):
            dirnames[:] = []
            continue
        for fn in filenames:
            if os.path.join(rel, fn) in _RUNTIME_LOGS:
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p, "rb") as f:
                    snap[os.path.relpath(p, root)] = hashlib.sha256(f.read()).hexdigest()
            except Exception:
                snap[os.path.relpath(p, root)] = "<unreadable>"
    return snap


def _count_projects_dir(root):
    p = os.path.join(root, "projects")
    if not os.path.isdir(p):
        return 0
    return len(os.listdir(p))


_REAL_AUDIT_PATH = os.path.join(_REAL_DATA_DIR, "operation_log.jsonl")
_REAL_AUDIT_LINES = _snap_audit(_REAL_AUDIT_PATH)
_REAL_TREE_BEFORE = _snap_real_tree(_REAL_DATA_DIR)
_REAL_PROJ_ENTRIES_BEFORE = _count_projects_dir(_REAL_DATA_DIR)

_TMP_DATA = tempfile.mkdtemp(prefix="fg_delsweep_")
config.DATA_DIR = _TMP_DATA            # 必须在 import app.project_manager 之前

from app import project_manager as pm  # noqa: E402
from app import vector_store as vs    # noqa: E402

RESULTS = []


def check(name, expect, actual, cond, note=""):
    RESULTS.append({"name": name, "passed": bool(cond),
                    "expect": expect, "actual": actual})
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    print(f"        期望={expect!r} 实际={actual!r}")
    if note:
        print(f"        {note}")


def _mk_project(pid, name, file_count=0, device_count=0):
    d = os.path.join(pm.PROJECTS_ROOT, pid)
    os.makedirs(d, exist_ok=True)
    meta = {"id": pid, "name": name, "description": "", "client": "", "location": "",
            "created_at": "2026-01-01 00:00:00", "updated_at": "2026-01-01 00:00:00",
            "file_count": file_count, "device_count": device_count,
            "workshop_count": 0, "status": "active"}
    with open(os.path.join(d, "project_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    # 造一份「资料」：证明删不干净时它没有被静默丢掉
    with open(os.path.join(d, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"files": [{"sha": "s1"}], "devices": {}, "workshops": {}}, f,
                  ensure_ascii=False)
    os.makedirs(os.path.join(d, "vector_db"), exist_ok=True)
    with open(os.path.join(d, "vector_db", "data_level0.bin"), "wb") as f:
        f.write(b"\x00" * 64)
    return d


def _set_current(pid):
    os.makedirs(os.path.dirname(pm.CURRENT_PROJECT_FILE), exist_ok=True)
    with open(pm.CURRENT_PROJECT_FILE, "w", encoding="utf-8") as f:
        json.dump({"project_id": pid}, f)


def _read_sweep():
    p = pm._sweep_file_path()
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _audit_lines_since(n_before):
    """读临时目录里的审计流水（本测试的 DATA_DIR 就是 _TMP_DATA）。"""
    p = os.path.join(_TMP_DATA, "operation_log.jsonl")
    if not os.path.isfile(p):
        return []
    out = []
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                out.append(json.loads(s))
            except Exception:
                out.append({"raw": s})
    return out[n_before:]


def main():
    print("=" * 78)
    print("v0.1.240 删项目：被占用时从列表摘除 + 下次启动续删")
    print(f"临时 DATA_DIR = {_TMP_DATA}")
    print("=" * 78)

    # 造两个项目：替身（要被删的当前项目）+ 接任者
    surv_dir = _mk_project("keep_surv", "幸存项目", file_count=3, device_count=5)
    vic_dir = _mk_project("del_victim", "待删项目", file_count=2, device_count=4)
    _set_current("del_victim")
    _audit_n0 = len(_audit_lines_since(0))

    # ---------- S1 场景成立 ----------
    ids_before = [p["id"] for p in pm.list_projects()]
    check("S1 场景成立：删之前项目在列表里",
          True, "del_victim" in ids_before,
          "del_victim" in ids_before and os.path.isdir(vic_dir),
          "否则 S3 的「不在列表」恒真，测不出任何东西")

    # ---------- S2/S3 模拟 WinError 32：rmtree 必失败一次 ----------
    real_rmtree = pm._safe_rmtree
    state = {"n": 0}

    def _locked_rmtree(path, retries=3, delay=0.5):
        state["n"] += 1
        if state["n"] == 1 and path == vic_dir:
            return False, ("PermissionError: [WinError 32] 另一个程序正在使用此文件，"
                           "进程无法访问。: '…\\\\vector_db\\\\"
                           "del_victim\\\\data_level0.bin'")
        return real_rmtree(path, retries=retries, delay=delay)

    pm._safe_rmtree = _locked_rmtree
    try:
        res = pm.delete_project("del_victim")
    finally:
        pm._safe_rmtree = real_rmtree

    check("S2 删不干净：ok=True + pending_sweep=True + data_deleted=False",
          (True, True, False),
          (res.get("ok"), res.get("pending_sweep"), res.get("data_deleted")),
          res.get("ok") is True and res.get("pending_sweep") is True
          and res.get("data_deleted") is False,
          "用户点了删除就是意图明确，不该因为文件被占用一直挂在列表里")

    ids_after = [p["id"] for p in pm.list_projects()]
    check("S3 项目从列表消失，且幸存项目仍在（正负成对）",
          ([], ["keep_surv"]),
          ([x for x in ids_after if x == "del_victim"],
           [x for x in ids_after if x == "keep_surv"]),
          "del_victim" not in ids_after and "keep_surv" in ids_after,
          "只查「不在列表」在「列表整个空了」时也会通过")

    check("S4 get_project 返回 None（唯一入口断掉，不只是列表过滤）",
          None, pm.get_project("del_victim"),
          pm.get_project("del_victim") is None)

    det_path = os.path.join(os.path.dirname(pm.PROJECTS_ROOT), "_detached",
                            "del_victim", "project_meta.json")
    ok_meta = os.path.isfile(det_path)
    got_meta = None
    if ok_meta:
        with open(det_path, "r", encoding="utf-8") as f:
            got_meta = json.load(f)
    check("S5 元数据可找回（_detached/<id>/project_meta.json 与删前一致）",
          ("del_victim", "待删项目"),
          ((got_meta or {}).get("id"), (got_meta or {}).get("name")),
          ok_meta and (got_meta or {}).get("id") == "del_victim"
          and (got_meta or {}).get("name") == "待删项目",
          f"路径={det_path}")

    check("S6 资料留在原地，没有静默丢数据",
          (True, True),
          (os.path.isdir(vic_dir), os.path.isfile(os.path.join(vic_dir, "index.json"))),
          os.path.isdir(vic_dir) and os.path.isfile(os.path.join(vic_dir, "index.json")),
          "目录与 index.json 都还在；register 的是「目录」而不是「内容」")

    sweep = _read_sweep()
    check("S7 登记表里有该 id 与真实目录",
          ("del_victim", vic_dir),
          ((sweep or [{}])[0].get("id"), (sweep or [{}])[0].get("dir"))
          if isinstance(sweep, list) and sweep else (sweep, None),
          isinstance(sweep, list) and len(sweep) == 1
          and sweep[0].get("id") == "del_victim" and sweep[0].get("dir") == vic_dir,
          "登记表必须与 projects/ 同级，否则会被 list_projects 当成项目")

    cur = pm.get_current_project()
    check("S8 当前项目指针不悬空（切到接任者）",
          "keep_surv", (cur or {}).get("id"),
          (cur or {}).get("id") == "keep_surv",
          "删的是当前项目时必须先挑接任者，否则界面显示「未选择项目」")

    logs = _audit_lines_since(_audit_n0)
    del_logs = [x for x in logs if x.get("type") == "delete"]
    check("S9 审计落下 delete，且写明「已从列表移除 / 待清理」",
          (True, True),
          (len(del_logs), bool(del_logs and "已从列表移除" in str(del_logs[-1].get("content")))),
          len(del_logs) == 1
          and "已从列表移除" in str(del_logs[-1].get("content"))
          and "待清理" in str(del_logs[-1].get("content")),
          f"delete 条数={len(del_logs)}；log_written={(res or {}).get('log_written')}")

    # ---------- S10 启动续删 ----------
    rep = pm.sweep_pending_deletes()
    check("S10 续删：目录删干净、登记表移除",
          (1, 1, 0, False, False),
          (rep.get("checked"), rep.get("removed"), rep.get("left"),
           os.path.isdir(vic_dir), os.path.isfile(pm._sweep_file_path())),
          rep.get("checked") == 1 and rep.get("removed") == 1 and rep.get("left") == 0
          and not os.path.isdir(vic_dir) and not os.path.isfile(pm._sweep_file_path()),
          "下次启动时占用句柄已消失，这一支就该真正删干净")

    rep2 = pm.sweep_pending_deletes()
    check("S11 续删幂等：再调一次 checked=0、不报错",
          (True, 0, 0),
          (rep2.get("ok"), rep2.get("checked"), rep2.get("removed")),
          rep2.get("ok") is True and rep2.get("checked") == 0
          and rep2.get("removed") == 0)

    # ---------- S12 反向：删得干净时不走摘除 ----------
    d3 = _mk_project("del_clean", "能删干净的项目")
    _set_current("del_clean")
    r3 = pm.delete_project("del_clean")
    ids3 = [p["id"] for p in pm.list_projects()]
    check("S12 反向：删得干净时不摘除、不留登记（与 v0.1.239 一致）",
          (True, True, False, None, False),
          (r3.get("ok"), r3.get("data_deleted"), r3.get("pending_sweep"),
           _read_sweep(), os.path.isdir(d3)),
          r3.get("ok") is True and r3.get("data_deleted") is True
          and not r3.get("pending_sweep") and _read_sweep() is None
          and not os.path.isdir(d3) and "del_clean" not in ids3,
          "这一支必须保持原行为：能删就真删，不能顺带留登记")

    # ---------- S13 摘除失败 → 退回原样报错 ----------
    d4 = _mk_project("del_nodetach", "摘除会失败的项目")
    _set_current("del_nodetach")
    real_detach = pm._detach_project_meta

    def _detach_fail(pid):
        return False

    pm._detach_project_meta = _detach_fail
    pm._safe_rmtree = lambda *a, **k: (False, "PermissionError: [WinError 32] 模拟")
    try:
        r4 = pm.delete_project("del_nodetach")
    finally:
        pm._detach_project_meta = real_detach
        pm._safe_rmtree = real_rmtree
    ids4 = [p["id"] for p in pm.list_projects()]
    check("S13 摘除失败 → 退回原样报错（不把没做的事说成做了）",
          (False, True, "del_nodetach"),
          (r4.get("ok"), r4.get("partial_delete"),
           "del_nodetach" in ids4),
          r4.get("ok") is False and r4.get("partial_delete") is True
          and "del_nodetach" in ids4,
          "元数据都移不走时确实什么也没做成，必须如实报错")

    # ---------- S14/S15 真实数据未污染 ----------
    after_tree = _snap_real_tree(_REAL_DATA_DIR)
    added = sorted(set(after_tree) - set(_REAL_TREE_BEFORE))
    removed = sorted(set(_REAL_TREE_BEFORE) - set(after_tree))
    changed = sorted(k for k in set(after_tree) & set(_REAL_TREE_BEFORE)
                     if after_tree[k] != _REAL_TREE_BEFORE[k])
    check("S14 真实 data/ 未被污染（内容全等，不是键集合差）",
          ([], [], []), (added, removed, changed),
          not added and not removed and not changed,
          "覆盖写不改键集合，只改内容 —— 必须按 sha256 比")

    real_lines = _snap_audit(_REAL_AUDIT_PATH)
    real_proj = _count_projects_dir(_REAL_DATA_DIR)
    check("S15 真实审计流水行数与真实 projects 条目数未变",
          (_REAL_AUDIT_LINES, _REAL_PROJ_ENTRIES_BEFORE),
          (real_lines, real_proj),
          real_lines == _REAL_AUDIT_LINES and real_proj == _REAL_PROJ_ENTRIES_BEFORE,
          f"审计 {_REAL_AUDIT_LINES}→{real_lines}，projects {_REAL_PROJ_ENTRIES_BEFORE}→{real_proj}")

    passed = sum(1 for r in RESULTS if r["passed"])
    failed = len(RESULTS) - passed
    print()
    print("=" * 78)
    print(f"结果：通过 {passed} / 失败 {failed}（共 {len(RESULTS)} 条）")
    print("=" * 78)

    try:
        shutil.rmtree(_TMP_DATA)
    except Exception:
        pass
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
