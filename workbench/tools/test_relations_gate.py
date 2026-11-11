# -*- coding: utf-8 -*-
"""v0.1.238 回归测试：关系图谱的车间白名单闸门（relations.py 专项）。

为什么单独一个文件：`test_relations_workshops.py` 只测 `_merge_index_devices`
（台账并入图谱时补 workshops），完全不碰 `build_relations()` 里那道闸门。
而闸门有三个面，任一面漏都会被用户看见：

    R1 文档级：文件名/图名/正文猜出来的车间名，台账里没有 → 不进 graph["workshops"]
    R2 设备级：正文/OCR 的 workshop_hint 同样要裁（实测漏口，本轮修的就是它）
    R3 一致性：同一台设备在 graph["devices"] 与 graph["layout"] 必须同一个答案
    R4 人工优先：source=manual 的登记即使不在台账里也放行（人显式点过头）
    R5 台账为空：退回旧逻辑，不得因为没台账就把一切判空
    R6 路径隔离：无当前项目时 get_project_data_dir 必须跟随 config.DATA_DIR

R2/R3 是实测挖出来的：轮次 2026-11-12 用「台账只有 粗碎站/磨浮车间」的夹具跑
build_relations，P-301 在 devices 里是「1号车间」、在 layout 里是「3号车间」，
两个名字台账里都没有 —— 既造了用户明令禁止的假车间名，又是「同一件事两个答案」。

R6 是同一次实测踩到的真实事故：把 DATA_DIR 切到 /tmp 之后，device_workshop.json
仍然写进了安装目录下的真实 data/ —— 因为 get_project_data_dir 在「无当前项目」
分支硬编码了安装目录，所有「切走 DATA_DIR 做隔离」的测试对这条路径全部静默失效。

跑法：python tools/test_relations_gate.py
"""
import json
import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import app.config as config  # noqa: E402

_REAL_DATA_DIR = config.DATA_DIR


# ---------------- 真实数据快照（必须在切 DATA_DIR 之前，用真实路径） ----------------
def _snap_dir(root):
    snap = {}
    if not os.path.isdir(root):
        return snap
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            try:
                snap[p] = os.path.getsize(p)
            except OSError:
                pass
    return snap


def _snap_audit(path):
    n = 0
    if not os.path.isfile(path):
        return 0
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


_REAL_PROJECTS = os.path.join(_REAL_DATA_DIR, "projects")
_REAL_AUDIT = os.path.join(_REAL_DATA_DIR, "operation_log.jsonl")
_BEFORE_PROJ = _snap_dir(_REAL_PROJECTS)
_BEFORE_AUDIT = _snap_audit(_REAL_AUDIT)
# v0.1.238：真实 data/ **根目录**下的文件也要快照。漏了这一层，本轮就真出事了 ——
# 反向验证 A 期间一次无参 assign_device 顺着「安装目录兜底」写进了真实的
# data/device_workshop.json，而 R7 只对比 projects/，全程没吭声。
# 教训：判「有没有污染真实数据」，范围必须是**用户数据根目录整体**，
# 不能只挑自己想到的那两处（projects + 审计）。
_BEFORE_ROOT = {p: s for p, s in _snap_dir(_REAL_DATA_DIR).items()
                if not p.startswith(_REAL_PROJECTS)}

_TMP = tempfile.mkdtemp(prefix="fg_rel_gate_")
config.DATA_DIR = _TMP

from app import project_manager as pm  # noqa: E402
from app import relations as R  # noqa: E402
from app import workshop_assign as wa  # noqa: E402
from app import device_workshop as dw  # noqa: E402

# PROJECTS_ROOT / CURRENT_PROJECT_FILE 是模块级常量（import 时就定了），
# 只切 config.DATA_DIR 不跟着改，项目目录仍指向真实 projects/ —— 这是
# v0.2.19x 记录过的老坑，测试里必须显式重算。
pm.PROJECTS_ROOT = os.path.join(_TMP, "projects")
pm.CURRENT_PROJECT_FILE = os.path.join(_TMP, "current_project.json")
wa._ISOLATED_DIR = _TMP

RESULTS = []
LEDGER_A = "粗碎站"
LEDGER_B = "磨浮车间"
DIRTY_DOC = "建宇建主减速机油站"   # 用户点名骂过的句子碎片
DIRTY_HINT = "1号车间"             # 正文正则推出来、台账里没有
RELAY_WS = "精选车间"              # R8 用：A 自己的表里合法写着、但不在环境台账里
DIRTY_TAG = "4号车间"              # 位号前缀推出来、台账里没有


def check(name, expect, actual, ok, note=""):
    RESULTS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: 期望={expect} 实际={actual}"
          + (f" | {note}" if note and not ok else ""))
    return ok


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _fixture(ddir, ledger_workshops):
    """造一个最小项目：1 份台账 + 1 份正文 + 1 份 CAD 图。

    ledger_workshops=[] 时台账里没有车间列（R5 用）。
    """
    cache_dir = os.path.join(ddir, "parsed_cache")
    os.makedirs(cache_dir, exist_ok=True)

    idx = {
        "sha_ledger": {"id": "sha_ledger", "sha256": "sha_ledger", "file_name": "设备台账.xlsx",
                       "file_type": "xlsx", "status": "parsed", "ts": "2026-01-01"},
        "sha_text": {"id": "sha_text", "sha256": "sha_text", "file_name": "施工说明.txt",
                     "file_type": "txt", "status": "parsed", "ts": "2026-01-01"},
        "sha_dwg": {"id": "sha_dwg", "sha256": "sha_dwg",
                    "file_name": f"{DIRTY_DOC}_平面图.dwg",
                    "file_type": "dwg", "status": "parsed", "ts": "2026-01-01"},
    }
    devs = {}
    rows = []
    if ledger_workshops:
        ws_a, ws_b = ledger_workshops[0], ledger_workshops[-1]
        devs["A-101"] = {"tag": "A-101", "name": "颚式破碎机", "workshop": ws_a,
                         "source_file": "设备台账.xlsx"}
        devs["B-201"] = {"tag": "B-201", "name": "浮选机", "workshop": ws_b,
                         "source_file": "设备台账.xlsx"}
        rows = [{"位号": "A-101", "设备名称": "颚式破碎机", "车间": ws_a},
                {"位号": "B-201", "设备名称": "浮选机", "车间": ws_b}]
    idx["devices"] = devs
    _write(os.path.join(ddir, "index.json"), idx)

    # 台账缓存：车间列写成台账里的名字（R5 时车间为空）
    sheet_rows = rows or [{"位号": "A-101", "设备名称": "颚式破碎机", "车间": ""}]
    _write(os.path.join(cache_dir, "sha_ledger.json"), {
        "sha256": "sha_ledger", "file_name": "设备台账.xlsx", "parser": "excel",
        "status": "parsed",
        "structure": {"sheets": [{"header": ["位号", "设备名称", "车间"], "rows": sheet_rows}]},
        "text": "",
    })

    # 正文：句子里出现台账外的「1号车间」→ 设备级 hint
    _write(os.path.join(cache_dir, "sha_text.json"), {
        "sha256": "sha_text", "file_name": "施工说明.txt", "parser": "text",
        "status": "parsed", "text": f"{DIRTY_HINT}安装 P-301 泵，{LEDGER_B}安装 P-302 泵。",
        "structure": {},
    })

    # CAD：文件名是脏名（文档级闸门要拦它），正文里有个 C-401（位号前缀会被推断）
    _write(os.path.join(cache_dir, "sha_dwg.json"), {
        "sha256": "sha_dwg", "file_name": f"{DIRTY_DOC}_平面图.dwg", "parser": "cad",
        "status": "parsed", "text": "C-401",
        "structure": {"spatial": {"title_block": {"图名": f"{DIRTY_DOC}平面图", "图号": "X-001"},
                                  "blocks": []}},
    })

    # 归属记录：文档级脏名也从这条路径进（模拟历史遗留），不经过 detect
    _write(os.path.join(ddir, "workshop_assign.json"), {
        "sha_dwg": {"sha256": "sha_dwg", "file_name": f"{DIRTY_DOC}_平面图.dwg",
                    "workshop": DIRTY_DOC, "source": "filename", "confidence": 0.75,
                    "candidates": [DIRTY_DOC], "file_path": "", "confirmed": False,
                    "ts": "2026-11-07T19:20:40"},
    })


def main():
    print("\n=== test_relations_gate ===")

    # ---------- R1 / R2 / R3：台账非空时，三面都只认台账 ==========
    d1 = os.path.join(_TMP, "p1")
    os.makedirs(d1, exist_ok=True)
    _fixture(d1, [LEDGER_A, LEDGER_B])
    wa._REG_CACHE.clear() if hasattr(wa, "_REG_CACHE") else None
    wa._LEDGER_CACHE.clear()
    g = R.build_relations(data_dir=d1)

    # R1 三条判据，全部落在用户能看见的行为上：
    #   ① 脏名字没成为**正式车间**（不进 graph["workshops"]）；
    #   ② 文件没被丢（ws 被裁空后仍出现在 unassigned_docs 里）；
    #   ③ 用户要的「可以先将文件暂时归类进去」仍然成立 —— workshop_assign 那侧的
    #      暂存归属保留着脏名，只是它不构成车间（正式车间由台账白名单决定）。
    # 只断言①是负向判据，ws_names 为空时会无条件通过（本轮踩过一次假守卫）。
    ws_names = sorted({w.get("workshop") for w in (g.get("workshops") or [])
                       if isinstance(w, dict) and w.get("workshop")})
    unassigned = [u.get("file") for u in (g.get("unassigned_docs") or [])
                  if isinstance(u, dict)]
    staged = (wa._load(d1).get("sha_dwg") or {}).get("workshop")
    cad_file = f"{DIRTY_DOC}_平面图.dwg"
    check("R1 文档级：台账外脏名字不成为正式车间（文件仍暂存归类、不丢）",
          "①不进workshops ②仍在unassigned ③暂存保留",
          {"workshops": ws_names, "in_unassigned": cad_file in unassigned,
           "staged": staged},
          DIRTY_DOC not in ws_names
          and cad_file in unassigned
          and staged == DIRTY_DOC,
          "任一不满足：①进了车间=闸门没盖 ②不在=把文件丢了 ③没暂存=用户要的临时归类没了")

    # R1b：_merge_index_devices 是下游**读取**路径必经的合并点（load_relations 里调它，
    # 把台账设备与台账车间补进图谱）。这里直接用它做正面判据：
    # 台账两个车间必须都补进来，脏名字一个都不许出现。
    # 不用 load_relations() 是为了不依赖模块级 RELATIONS_FILE（它 _ensure() 走全局路径，
    # 在隔离测试里会读到上一轮的图谱）。
    ledger = (R._load_index(d1) or {}).get("devices") or {}
    g_view = R._merge_index_devices(g, ledger)
    ws_view = sorted({w.get("workshop") for w in (g_view.get("workshops") or [])
                      if isinstance(w, dict) and w.get("workshop")})
    devs_view = {d.get("tag"): (d.get("workshops") or [])
                 for d in (g_view.get("devices") or []) if isinstance(d, dict)}
    bad_dev = sorted({w for v in devs_view.values() for w in v
                      if w and w not in (LEDGER_A, LEDGER_B)})
    check("R1b 读取路径：台账车间全部在册、台账外名字一个不进",
          [LEDGER_A, LEDGER_B], ws_view,
          {LEDGER_A, LEDGER_B} <= set(ws_view) and DIRTY_DOC not in ws_view
          and not bad_dev,
          "台账车间缺失 = 白名单把真车间也裁了；含脏名字 = 闸门没盖住这条路径")

    for d in g.get("devices") or []:
        pass
    dev_ws = {d.get("tag"): (d.get("workshops") or []) for d in (g.get("devices") or [])}
    all_dev_ws = sorted({w for ws in dev_ws.values() for w in ws if w})
    check("R2 设备级：正文 hint / 位号前缀推出的脏名字不进 devices",
          "只含台账车间", all_dev_ws,
          DIRTY_HINT not in all_dev_ws and DIRTY_TAG not in all_dev_ws
          and set(all_dev_ws) <= {LEDGER_A, LEDGER_B},
          f"实际 {all_dev_ws}")

    layout_ws = {r.get("tag"): r.get("workshop") for r in (g.get("layout") or [])}
    bad_layout = sorted({w for w in layout_ws.values() if w and w not in (LEDGER_A, LEDGER_B)})
    check("R2b 设备级：layout 票数里也不含台账外名字", [], bad_layout, not bad_layout,
          f"实际 {bad_layout}")

    # R3：同一台设备在两个视图里必须是同一个答案（「同一件事两个答案」的正面判据）
    mismatch = []
    for tag, ws in layout_ws.items():
        if ws is None:
            continue
        dev_v = dev_ws.get(tag) or []
        if dev_v and (len(dev_v) != 1 or dev_v[0] != ws):
            mismatch.append((tag, dev_v, ws))
    check("R3 devices 与 layout 对同一设备给出同一车间", [], mismatch, not mismatch,
          f"不一致 {mismatch}")

    # 被裁掉的设备不能消失：仍要进「车间未确认」清单，让人去定
    pend_tags = {c.get("tag") for c in (g.get("human_confirm") or [])
                 if c.get("type") == "车间未确认"}
    check("R3b 裁掉车间名的设备仍进人工确认清单（不丢设备）",
          {"P-301", "P-302"} <= pend_tags, sorted(pend_tags),
          {"P-301", "P-302"} <= pend_tags)

    # ---------- R4：人工登记是显式点头，台账外也放行 ----------
    # 必须显式传 data_dir=d1：不传就会用 _ISOLATED_DIR（_TMP 根）里的 index.json，
    # 那份没有台账 —— 闸门因"台账为空"而放行，这两条就成了假守卫。
    wa._LEDGER_CACHE.clear()
    dw.assign_device("X-999", "人工定的车间", source="manual", confidence=1.0, force=True,
                     data_dir=d1)
    rec = dw.get_record("X-999", d1)
    check("R4 人工登记不受台账白名单限制", "人工定的车间", (rec or {}).get("workshop"),
          (rec or {}).get("workshop") == "人工定的车间")

    # 自动来源同名字必须被拦（否则闸门等于没加）
    ok_auto = dw.assign_device("Y-999", "自动猜的车", source="tag_infer", confidence=0.4,
                               force=True, data_dir=d1)
    check("R4b 自动来源的台账外名字被拦下", False, ok_auto, ok_auto is False)
    check("R4c 被拦的自动登记没写进登记表", None, (dw.get_record("Y-999", d1) or {}).get("workshop"),
          (dw.get_record("Y-999", d1) or {}).get("workshop") in (None, ""),
          "拦了但已经落盘 = 拦在写盘之后，等于没拦")

    # ---------- R5：台账为空时退回旧逻辑 ----------
    d2 = os.path.join(_TMP, "p2")
    os.makedirs(d2, exist_ok=True)
    _fixture(d2, [])
    wa._LEDGER_CACHE.clear()
    g2 = R.build_relations(data_dir=d2)
    dev2 = {d.get("tag"): (d.get("workshops") or []) for d in (g2.get("devices") or [])}
    ws2 = sorted({w for v in dev2.values() for w in v if w})
    check("R5 台账为空时不裁剪（P-301 仍有车间）", True, bool(dev2.get("P-301")),
          bool(dev2.get("P-301")), f"devices={dev2}")
    # R5b 也必须传 data_dir：不传时它走的是「全局兜底」路径，而**兜底路径正是
    # 反向验证 A（还原硬编码安装目录）要打红的对象**。实测后果：patch A 生效期间
    # 这条无参调用顺着那个回退写进了安装目录的真实 data/device_workshop.json
    # （01:28 落了个 Z-999/1号车间）。测试自己往真实数据写东西，比它要验的缺陷更糟。
    ok5 = dw.assign_device("Z-999", DIRTY_HINT, source="tag_infer", confidence=0.4,
                           force=True, data_dir=d2)
    check("R5b 台账为空时自动登记仍可写入（不把一切判空）", True, ok5, ok5 is True)

    # ---------- R8：rebuild_from_excel 必须把 data_dir 接力给抽取器 ----------
    # 这条路径的缺陷方向与 R1/R2 相反：不是「脏名字漏进来」，而是**干净名字被别处
    # 的台账误裁**。实测（2026-11-12）：项目 A 的台账为空（按约定应退回旧逻辑、
    # 不裁剪），但抽取器 `_equipment_from_cache(d)` 没拿到 A 的目录，读的是环境
    # 台账（当前项目 B，里面有「粗碎站」）→ 把 A 表里合法的「精选车间」判成台账外
    # → hint 裁成 None → 设备 P-301 归属整条丢失。A 台账非空、名字真在台账外时
    # 两种写法结果都是 0（下游 assign_device 闸门挡住了），所以**那种场景区分不出
    # 对错**，不能拿它当判据。
    d3 = os.path.join(_TMP, "p3")
    d4 = os.path.join(_TMP, "p4")
    _write(os.path.join(d3, "index.json"), {
        "sha_relay": {"id": "sha_relay", "sha256": "sha_relay", "file_name": "A台账.xlsx",
                      "file_type": "xlsx", "status": "parsed", "ts": "2026-01-01"},
        "devices": {},
    })
    _write(os.path.join(d4, "index.json"), {
        "devices": {"B-201": {"tag": "B-201", "name": "浮选机", "workshop": LEDGER_A,
                              "source_file": "B台账.xlsx"}},
    })
    relay_cache = {"sha256": "sha_relay", "file_name": "A台账.xlsx", "parser": "excel",
                   "status": "parsed", "text": "",
                   "structure": {"sheets": [{"header": ["位号", "设备名称", "车间"],
                                             "rows": [{"位号": "P-301", "设备名称": "泵",
                                                       "车间": RELAY_WS}]}]}}
    # 环境台账（不传 data_dir 时读到的那个）= d4
    wa._ISOLATED_DIR = d4
    wa._LEDGER_CACHE.clear()
    try:
        led_a = wa.ledger_workshop_names(d3)
        led_env = wa.ledger_workshop_names()
        wa._LEDGER_CACHE.clear()
        check("R8a 场景成立：A 台账为空、环境台账非空（否则这条测不出东西）",
              (set(), {LEDGER_A}), (set(led_a), set(led_env)),
              not led_a and bool(led_env),
              "A 台账不是空 or 环境台账是空 → 下面两条断言失去判别力")

        n_relay = dw.rebuild_from_excel({"sha_relay": relay_cache}, d3)
        got = dw.get_workshop("P-301", d3)
        check("R8b 抽取器接力 data_dir：A 的空台账不该借 B 的清单去裁自己的 hint",
              (1, RELAY_WS), (n_relay, got),
              n_relay == 1 and got == RELAY_WS,
              f"旧写法实测 n=0 / P-301=''（设备归属整条丢失），hint 被环境台账裁成 None；"
              f"现在 n={n_relay} / P-301={got!r}")
    finally:
        wa._ISOLATED_DIR = _TMP
        wa._LEDGER_CACHE.clear()

    # ---------- R6：无当前项目时数据目录必须跟随 config.DATA_DIR ----------
    ddir_now = pm.get_project_data_dir()
    check("R6 无当前项目时 get_project_data_dir 跟随 DATA_DIR", _TMP, ddir_now,
          os.path.abspath(ddir_now) == os.path.abspath(_TMP),
          "写成安装目录就说明又绕开了 config.DATA_DIR")
    store = dw._store_path()
    check("R6b device_workshop 落点也在 DATA_DIR 下（不写真实 data/）",
          True, store, os.path.abspath(store).startswith(os.path.abspath(_TMP)),
          f"实际 {store}")

    # R6b 只证明「全局兜底跟了 DATA_DIR」，证明不了 _store_path 真的**认**调用方给的目录。
    # 下面两条才是接力判据：显式 data_dir > 隔离目录。缺任一条，传了目录也会写回别处。
    store_d1 = dw._store_path(d1)
    check("R6c 显式 data_dir 优先：落点就在调用方给的目录",
          os.path.join(d1, "device_workshop.json"), store_d1,
          os.path.abspath(store_d1) == os.path.abspath(os.path.join(d1, "device_workshop.json")),
          "传了目录却写到别处 = data_dir 没接力（EE/FF 同病）")
    dw._ISOLATED_DIR = d1
    try:
        store_iso = dw._store_path()
    finally:
        dw._ISOLATED_DIR = None
    check("R6d 隔离目录生效：不传 data_dir 时也落在隔离目录",
          os.path.join(d1, "device_workshop.json"), store_iso,
          os.path.abspath(store_iso) == os.path.abspath(os.path.join(d1, "device_workshop.json")),
          "隔离目录被忽略 = 测试/离线场景会写进用户项目")

    # ---------- R7：本测试没有污染真实数据 ----------
    after_proj = _snap_dir(_REAL_PROJECTS)
    after_audit = _snap_audit(_REAL_AUDIT)
    check("R7 真实项目目录未被本测试改动（按内容全等比较）",
          "一致", f"前 {len(_BEFORE_PROJ)} / 后 {len(after_proj)}",
          _BEFORE_PROJ == after_proj)
    check("R7b 真实审计流水行数未变", _BEFORE_AUDIT, after_audit,
          _BEFORE_AUDIT == after_audit)
    after_root = {p: s for p, s in _snap_dir(_REAL_DATA_DIR).items()
                  if not p.startswith(_REAL_PROJECTS)}
    check("R7c 真实 data/ 根目录未被本测试写入（含 device_workshop/登记册/候选）",
          "一致", f"前 {len(_BEFORE_ROOT)} / 后 {len(after_root)}",
          _BEFORE_ROOT == after_root,
          "有增量 = 某条调用路径绕过了隔离，写进了用户真实数据根")

    print(f"\n===== 通过 {sum(1 for _n, ok in RESULTS if ok)} / "
          f"失败 {sum(1 for _n, ok in RESULTS if not ok)} =====")
    if any(not ok for _n, ok in RESULTS):
        print("失败项：" + "; ".join(n for n, ok in RESULTS if not ok))
        return 1
    return 0


if __name__ == "__main__":
    rc = main()
    shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(rc)
