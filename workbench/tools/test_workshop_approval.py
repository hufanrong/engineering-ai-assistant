#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.1.235 回归测试：新建车间必须人工审批，自动推导只是候选。

用户 2026-11-11 原话（这就是验收标准）：
    「优化车间划分逻辑，在建立新车间时可以先将文件暂时归类进去，但是所有新建立的
      车间必须交由人工审批，人工确认该车间存在时，再正式建立该车间，否则就不要建立
      车间，哪有什么车间叫建宇建主减速机油站呢」

所以本测试不测「名字好不好听」（那是词表，永远追不上脏字），只测**权力边界**：

  T1  自动推导出的名字**不得**进入正式车间清单（list_by_workshop 里不能有它）。
  T2  文件仍然**可以**暂时归类（用户明确要求"可以先将文件暂时归类进去"）：
      记录里 workshop 有值，且出现在 list_pending_by_workshop 的分组里。
  T3  待审批队列能给出证据（命中次数 + 样本文件名），让人有依据判断。
  T4  人工 approve 之后才算正式车间：list_by_workshop 出现、registry 里 confirmed=True，
      且原先临时归入它的文件被转正（confirmed=True）。
  T5  人工 reject 之后**不建立车间**：不出现于清单、registry 记 rejected、
      文件退回未归车间（workshop=None）。
  T6  否决要"粘住"：同一份文件再次自动识别命中被否决的名字时，
      workshop 必须为空、candidates 里也不能有它 —— 否则下次扫描它就回来了，
      用户否决等于没否决（这是「脏名字自我强化」的收敛点）。
  T7  `_known_set()` 只认登记册：自动推导出的名字**没有资格**给别的文件做兜底命中。
      这是根因测试：旧实现从所有落盘记录里学车间，脏名字一次落盘就永久自我强化。
  T8  manual_assign（人工指定）本身就是人工确认：必须同时写 registry，
      否则会出现「文件已人工指定、车间在清单里仍待审批」的自相矛盾。
  T9  /api/workshops 只返回正式车间；候选进 pending_workshops，不混在一起。
  T10 /api/files/tree 的 L2 里不得出现未确认车间；候选进 tree["pending_workshops"]。

隔离：本测试全程在临时 DATA_DIR 里跑（config.DATA_DIR 必须在 import app.main
之前切走，PROJECTS_ROOT 是模块级常量）。收尾还要断言**用户真实项目目录与审计
流水一行没变** —— 上一轮就是因为「断言全绿但真实项目被写脏」才被发现的。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.config as config  # noqa: E402

_REAL_DATA_DIR = config.DATA_DIR
_REAL_DIRS = {}


def _snap_dir(path):
    """目录快照：条目名 + 大小 + mtime。用于证明测试没写真实项目。"""
    snap = {}
    if not os.path.isdir(path):
        return snap
    for root, _dirs, files in os.walk(path):
        for fn in files:
            p = os.path.join(root, fn)
            try:
                st = os.stat(p)
                snap[os.path.relpath(p, path)] = (st.st_size, st.st_mtime_ns)
            except OSError:
                snap[os.path.relpath(p, path)] = None
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


# 真实项目 + 真实审计流水的开工快照（**必须显式传真实路径**：
# 本模块马上就把 config.DATA_DIR 切到临时目录，之后再读它读到的是临时目录，
# 会得出「前=N 后=0」这种自欺欺人的数字）
_REAL_PROJECTS = os.path.join(_REAL_DATA_DIR, "projects")
_REAL_AUDIT_PATH = os.path.join(_REAL_DATA_DIR, "operation_log.jsonl")
_BEFORE_PROJ = _snap_dir(_REAL_PROJECTS)
_BEFORE_AUDIT = _snap_audit(_REAL_AUDIT_PATH)

_TMP_DATA = tempfile.mkdtemp(prefix="fg_ws_appr_")
config.DATA_DIR = _TMP_DATA            # 必须在 import app.main 之前

import app.main as M  # noqa: E402
from app import project_manager as pm  # noqa: E402
from app import workshop_assign as wa  # noqa: E402

RESULTS = []


def check(name, cond, detail):
    RESULTS.append({"name": name, "passed": bool(cond), "detail": detail})
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}: {detail}")


def _mk_project(pid="ws_appr_test", devices=None):
    ddir = os.path.join(pm.PROJECTS_ROOT, pid)
    os.makedirs(ddir, exist_ok=True)
    idx = {"files": {}, "devices": devices or {}, "workshops": {},
           "updated_at": "2026-01-01"}
    with open(os.path.join(ddir, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    with open(os.path.join(ddir, "project_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"id": pid, "name": "车间审批测试项目"}, f, ensure_ascii=False)
    pm.set_current_project(pid, log=False)
    return ddir


def _reset_assign(ddir):
    """清空车间归属/登记册/候选队列，让每个用例从干净状态开始。"""
    for fn in ("workshop_assign.json", "workshop_registry.json", "workshop_candidates.json"):
        p = os.path.join(ddir, fn)
        if os.path.exists(p):
            os.remove(p)
    wa._REG_CACHE.clear()


# 用户点名的那串脏名字，直接用真实形态（不是造一个"看起来像"的假名字）
DIRTY = "建宇建主减速机油站"
DIRTY2 = "件与件之间"
# 用户第一眼就能认出是真车间的（对照用）
REAL = "磨浮车间"


def run():
    print("=" * 62)
    print("v0.1.235 新建车间必须人工审批 回归测试")
    print("=" * 62)

    old_cur = None
    try:
        _c = pm.get_current_project()
        old_cur = _c.get("id") if _c else None
    except Exception:  # noqa: BLE001
        old_cur = None

    ddir = _mk_project()

    # ---------- 第一组：自动推导 → 只算候选 ----------
    _reset_assign(ddir)
    # 文件名带「磨浮车间」→ 自动推导应为「磨浮车间」
    r1 = wa.assign_workshop("sha_real_1", "磨浮车间-设备布置图.dwg", "", {}, file_path="")
    # 正文片段推导（模拟真实图纸正文里抠出来的句子碎片）。
    # 注意：每个文件只放**一个**脏名字 —— 两个以上会走 detect_workshop 的
    # 「多车间不强行归类」分支（source=content_multi, workshop=None），
    # 那是另一条合法路径，验不到本次要验的「单车间候选」路径。
    r2 = wa.assign_workshop("sha_dirty_1", "流程图.dwg",
                            "%s 附近设两台泵" % DIRTY, {}, file_path="")

    check("T1a 自动推导出的名字不进入正式车间清单",
          "磨浮车间" not in wa.list_by_workshop(),
          "list_by_workshop keys=%s" % sorted(wa.list_by_workshop().keys()))

    check("T1b 脏名字（%s）不进入正式车间清单" % DIRTY,
          DIRTY not in wa.list_by_workshop(),
          "list_by_workshop keys=%s" % sorted(wa.list_by_workshop().keys()))

    _pend = wa.list_pending_by_workshop()
    _rec2 = wa._load().get("sha_dirty_1") or {}
    check("T2 文件仍被暂时归类（用户要求：可以先将文件暂时归类进去）",
          bool(_rec2.get("workshop")) and _rec2.get("workshop") in _pend,
          "记录 workshop=%r，待审批分组 keys=%s" % (_rec2.get("workshop"), sorted(_pend.keys())))

    _cands = {c["name"]: c for c in wa.list_candidates()}
    _cc = _cands.get(DIRTY) or {}
    check("T3 待审批队列带证据（命中次数 + 样本文件名）",
          int(_cc.get("count") or 0) >= 1 and bool(_cc.get("samples")),
          "%s count=%s samples=%s" % (DIRTY, _cc.get("count"), _cc.get("samples")))

    # ---------- 第二组：approve 才转正 ----------
    _ap = wa.approve_workshop(DIRTY, approved_by="user", note="测试确认")
    check("T4a approve 后进入正式车间清单",
          DIRTY in wa.list_by_workshop(),
          "registry_saved=%s files_promoted=%s keys=%s"
          % (_ap.get("registry_saved"), _ap.get("files_promoted"),
             sorted(wa.list_by_workshop().keys())))
    check("T4b approve 后文件被转正（confirmed=True）",
          bool((wa._load().get("sha_dirty_1") or {}).get("confirmed")),
          "files_promoted=%s" % _ap.get("files_promoted"))
    check("T4c approve 后从待审批队列移除",
          DIRTY not in {c["name"] for c in wa.list_candidates()},
          "candidates=%s" % [c["name"] for c in wa.list_candidates()])

    # ---------- 第三组：reject 不建立 + 文件退回 ----------
    _rj = wa.reject_workshop(DIRTY, rejected_by="user", note="测试否决")
    check("T5a reject 后仍未建立（正式清单里没有它）",
          DIRTY not in wa.list_by_workshop(),
          "files_released=%s keys=%s" % (_rj.get("files_released"),
                                          sorted(wa.list_by_workshop().keys())))
    _rec5 = wa._load().get("sha_dirty_1") or {}
    check("T5b reject 后文件退回未归车间（workshop=None）",
          not _rec5.get("workshop"),
          "workshop=%r source=%r" % (_rec5.get("workshop"), _rec5.get("source")))
    check("T5c reject 被记录在登记册（rejected=True）",
          bool((wa._load_registry().get(DIRTY) or {}).get("rejected")),
          "registry[%s]=%s" % (DIRTY, wa._load_registry().get(DIRTY)))

    # ---------- 第四组：否决要粘住 ----------
    wa.assign_workshop("sha_dirty_1", "流程图.dwg", "%s 附近设两台泵" % DIRTY, {},
                       file_path="", force=True)
    _rec6 = wa._load().get("sha_dirty_1") or {}
    check("T6a 被否决的名字再次自动命中 → workshop 必须为空",
          not _rec6.get("workshop"),
          "workshop=%r source=%r" % (_rec6.get("workshop"), _rec6.get("source")))
    check("T6b 被否决的名字不得再出现在 candidates 里",
          DIRTY not in (_rec6.get("candidates") or []),
          "candidates=%s" % _rec6.get("candidates"))
    check("T6c 被否决的名字不回到待审批队列",
          DIRTY not in {c["name"] for c in wa.list_candidates()},
          "candidates=%s" % [c["name"] for c in wa.list_candidates()])

    # ---------- 第五组：根因 —— _known_set 只认登记册 ----------
    # 造一条「自动推导落盘、但从未审批」的记录，看它有没有资格给别的文件做兜底。
    wa.assign_workshop("sha_x_1", "随便.dwg", "", {}, file_path="")
    _m = wa._load()
    _m["sha_x_1"] = {"sha256": "sha_x_1", "file_name": "随便.dwg",
                     "workshop": "中矿堆", "source": "content",
                     "confidence": 0.55, "candidates": ["中矿堆"],
                     "file_path": "", "confirmed": False, "ts": "2026-01-01T00:00:00"}
    wa._save(_m)
    _ks = wa._known_set()
    check("T7 _known_set 不含未审批的自动推导名字",
          "中矿堆" not in _ks,
          "_known_set=%s" % sorted(_ks))

    # ---------- 第六组：manual_assign 即人工确认 ----------
    wa.manual_assign("sha_man_1", REAL, file_name="磨浮车间图.dwg")
    check("T8a manual_assign 同时写登记册（confirmed=True）",
          wa.is_workshop_confirmed(REAL),
          "registry[%s]=%s" % (REAL, wa._load_registry().get(REAL)))
    check("T8b manual_assign 后该车间进入正式清单",
          REAL in wa.list_by_workshop(),
          "keys=%s" % sorted(wa.list_by_workshop().keys()))

    # ---------- 第七组：接口口径 ----------
    _w = M.get_workshops()
    _names = [x["name"] for x in (_w.get("workshops") or [])]
    _pend_names = [x["name"] for x in (_w.get("pending_workshops") or [])]
    check("T9a /api/workshops 只正式车间（候选不进 workshops）",
          DIRTY not in _names,
          "workshops=%s" % _names)
    check("T9b /api/workshops 候选单独给 pending_workshops",
          DIRTY not in _pend_names,
          "pending=%s（被否决的名字不该出现）" % _pend_names)

    # 再造一个"没审批也没否决"的候选，确认它出现在 pending_workshops 里
    wa.assign_workshop("sha_cand_1", "图A.dwg", "%s 说明" % "相国四站", {}, file_path="")
    _w2 = M.get_workshops()
    _p2 = [x["name"] for x in (_w2.get("pending_workshops") or [])]
    _n2 = [x["name"] for x in (_w2.get("workshops") or [])]
    check("T9c 未审批的候选出现在 pending_workshops、且不在 workshops",
          "相国四站" in _p2 and "相国四站" not in _n2,
          "pending=%s workshops=%s" % (_p2, _n2))

    _t = M.files_tree()
    _tree = (_t or {}).get("tree") or {}
    _l2 = list((_tree.get("L2") or {}).keys())
    _tp = [x["name"] for x in (_tree.get("pending_workshops") or [])]
    check("T10a /api/files/tree 的 L2 不含未审批车间",
          "相国四站" not in _l2,
          "L2=%s" % _l2)
    check("T10b /api/files/tree 候选进 tree['pending_workshops']",
          "相国四站" in _tp,
          "pending_workshops=%s" % _tp)

    # ---------- 收尾断言：不污染用户真实项目 ----------
    try:
        pm.switch_project(old_cur) if old_cur else None
    except Exception:  # noqa: BLE001
        pass

    _after_proj = _snap_dir(_REAL_PROJECTS)
    _proj_ok = (_after_proj == _BEFORE_PROJ)
    _diff = ""
    if not _proj_ok:
        _added = sorted(set(_after_proj) - set(_BEFORE_PROJ))
        _removed = sorted(set(_BEFORE_PROJ) - set(_after_proj))
        _changed = sorted(k for k in set(_BEFORE_PROJ) & set(_after_proj)
                          if _BEFORE_PROJ[k] != _after_proj[k])
        _diff = f"新增={_added[:5]} 删除={_removed[:5]} 变更={_changed[:5]}"
    check("T11 本测试未写用户真实项目目录", _proj_ok, _diff or "快照完全一致")

    _after_audit = _snap_audit(_REAL_AUDIT_PATH)
    check("T12 本测试未写用户真实审计流水",
          _after_audit["lines"] == _BEFORE_AUDIT["lines"]
          and _after_audit["tail"] == _BEFORE_AUDIT["tail"],
          "前=%s 后=%s" % (_BEFORE_AUDIT["lines"], _after_audit["lines"]))

    ok = sum(1 for r in RESULTS if r["passed"])
    bad = len(RESULTS) - ok
    print("-" * 62)
    print(f"结果：通过 {ok} / 失败 {bad}")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_workshop_approval_report.json"), "w", encoding="utf-8") as f:
        json.dump({"total": len(RESULTS), "passed": ok, "failed": bad,
                   "results": RESULTS}, f, ensure_ascii=False, indent=2)
    try:
        import shutil as _sh
        _sh.rmtree(_TMP_DATA, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run())
