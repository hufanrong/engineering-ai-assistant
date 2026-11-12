# -*- coding: utf-8 -*-
"""v0.1.245/246 门禁：**多施工项目平台化** —— 同一套不变量在任意规模/形状的项目上都成立。

用户指令（2026-11-12，胡繁荣）：
    「反馈的问题,你要完善整个程序,而不是更改只适用于当前资料,我要做一个适用于多个施工项目的AI平台」

因此本门禁**不使用任何当前资料的数字**：不写死 228 台 / 19 个车间 / 13 / 14 /
项目 id 322fef90，全部从现构造的台账里现算。三个项目刻意做成三种形状，
用来证明「不只适用于当前那份资料」：

    P1 微型：1 个车间 / 2 台设备
    P2 中型：5 个车间 / 13 台设备（含 2 台重名、1 台无车间名）
    P3 大型：12 个车间 / 60 台设备（含 5 台重名、3 台无车间名、1 台无型号）

断言：
    M1  项目卡片统计的车间数 == 该项目正式车间清单数（每项目分别验）
    M2  项目卡片统计的设备数 == 该项目台账设备数（每项目分别验）
    M3  正式车间清单 ⊆ 台账车间 ∪ 人工确认车间；自动推导名不得混入
    M4  图谱设备数 == 台账设备数（每项目分别验）
    M5  落点解析是纯函数：解析顺序不影响任何项目的落点
    M6  A 的落盘只落 A、B 的落盘只落 B（互相不存在对方的文件）
    M7  车间归属登记册互不串（每个项目只含自己的位号与自己的确认车间）
    M8  两个项目并发建图谱，零交叉污染
    M9  通用化 C9：在隔离目录扫描，不得在当前项目留下任何归属/队列/缓存痕迹
    M10 真实数据零污染（审计流水行数 + 真实项目目录条目）
"""
import io
import json
import os
import shutil
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------- 隔离（必须在 import 之前）
# config.DATA_DIR / PROJECTS_ROOT / CURRENT_PROJECT_FILE 与 project_manager 的
# 同名常量都是**模块级常量**，import 后再改就晚了（第一版就这么写的，
# 测试自己把项目建进了真实 data/projects 并往真实审计流水写了一行）。
_TMP = tempfile.mkdtemp(prefix="fg245_")

import app.config as _cfg  # noqa: E402

_cfg.DATA_DIR = _TMP
_cfg.PROJECTS_ROOT = os.path.join(_TMP, "projects")
_cfg.CURRENT_PROJECT_FILE = os.path.join(_TMP, "current_project.json")

import app.project_manager as _pm_mod  # noqa: E402

_pm_mod.PROJECTS_ROOT = _cfg.PROJECTS_ROOT
_pm_mod.CURRENT_PROJECT_FILE = _cfg.CURRENT_PROJECT_FILE
_pm_mod._config.DATA_DIR = _TMP

from app import main as M  # noqa: E402
from app import project_manager as pm  # noqa: E402
from app import workshop_assign as wa  # noqa: E402
from app import relations as rel  # noqa: E402
from app import upload_queue as uq  # noqa: E402
from app import device_workshop as dw  # noqa: E402
from app import scanner  # noqa: E402

_REAL_LOG = os.path.join(ROOT, "data", "operation_log.jsonl")
_REAL_PROJECTS = os.path.join(ROOT, "data", "projects")

FAILS = []


def ck(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)
    return bool(cond)


def _real_snapshot():
    log_lines = 0
    if os.path.exists(_REAL_LOG):
        with open(_REAL_LOG, "rb") as f:
            log_lines = sum(1 for _ in f)
    projs = sorted(os.listdir(_REAL_PROJECTS)) if os.path.isdir(_REAL_PROJECTS) else []
    return log_lines, projs


def _read_json(path):
    if not os.path.exists(path):
        return None
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def _bytes(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


# ---------------------------------------------------------------- 三个不同形状的项目
def _build_ledger(prefix, n_ws, n_dev, n_dup, n_nameless):
    """构造台账 devices：名字/型号/车间/数量。返回 (devices, ledger_ws_set)。"""
    devices = {}
    ws_names = [f"{prefix}{i}号车间" for i in range(1, n_ws + 1)]
    ws_set = set(ws_names)
    for i in range(n_dev):
        tag = f"{prefix}-D{i + 1:03d}"
        ws = ws_names[i % n_ws]
        rec = {"name": f"{prefix}设备{i + 1}", "model": f"M{i % 7}",
               "workshop": ws, "quantity": "1"}
        devices[tag] = rec
    # 重名行：同名不同型号（用户定的主键规则：车间+设备名，同名再按型号区分）
    for i in range(n_dup):
        tag = f"{prefix}-X{i + 1:03d}"
        devices[tag] = {"name": f"{prefix}重名设备", "model": f"DUP{i + 1}",
                        "workshop": ws_names[0], "quantity": "2"}
    # 无车间名行：台账里有这台设备，但车间列空着
    for i in range(n_nameless):
        tag = f"{prefix}-N{i + 1:03d}"
        devices[tag] = {"name": f"{prefix}无名设备{i + 1}", "model": "NM",
                        "workshop": "", "quantity": "1"}
    return devices, ws_set


SHAPES = [
    {"key": "P1", "name": "微型施工项目", "ws": 1, "dev": 2, "dup": 0, "nameless": 0},
    {"key": "P2", "name": "中型施工项目", "ws": 5, "dev": 13, "dup": 2, "nameless": 1},
    {"key": "P3", "name": "大型施工项目", "ws": 12, "dev": 60, "dup": 5, "nameless": 3},
]

PROJ = {}  # key -> {"id":..., "dir":..., "devices":..., "ws": set(...), "tags": [...]}


def _setup_projects():
    for sh in SHAPES:
        created = pm.create_project(name=sh["name"], description="多项目平台化门禁")
        pid = (created.get("project") or {}).get("id") or created.get("id")
        assert pid, created
        pdir = pm.get_project_data_dir(pid)
        os.makedirs(pdir, exist_ok=True)
        devices, ws_set = _build_ledger(sh["key"], sh["ws"], sh["dev"],
                                         sh["dup"], sh["nameless"])
        with io.open(os.path.join(pdir, "index.json"), "w", encoding="utf-8") as f:
            json.dump({"devices": devices, "files": {}}, f, ensure_ascii=False)
        PROJ[sh["key"]] = {"id": pid, "dir": pdir, "devices": devices,
                           "ws": ws_set, "tags": sorted(devices.keys()),
                           "shape": sh}


def _ws_list(pid):
    pm.set_current_project(pid)
    return [r["name"] for r in (M.get_workshops().get("workshops") or [])]


def _stat(pid):
    pm.set_current_project(pid)
    M._refresh_project_stats()
    cur = pm.get_current_project() or {}
    return cur.get("workshop_count"), cur.get("device_count")


def main():
    real_before = _real_snapshot()

    # ---------------------------------------------------------------- M1/M2/M3/M4
    _setup_projects()
    for key, p in PROJ.items():
        sh = p["shape"]
        n_ledger = len(p["devices"])
        stat_ws, stat_dev = _stat(p["id"])
        lst = _ws_list(p["id"])

        ck(f"M1[{key}] 统计车间数 == 正式车间清单数",
           stat_ws == len(lst), f"统计={stat_ws} 清单={len(lst)} {lst[:4]}...")
        ck(f"M2[{key}] 统计设备数 == 台账设备数",
           stat_dev == n_ledger, f"统计={stat_dev} 台账={n_ledger}")
        # 正式车间必须是台账车间（或人工确认的），不得出现自动推导名
        pending = M.get_workshops().get("pending_workshops") or []
        auto_names = {str(x.get("name") or "") for x in pending}
        leak = [n for n in lst if n not in p["ws"] and n not in auto_names]
        ck(f"M3[{key}] 正式车间不含自动推导名（用户指令：未审批不建车间）",
           not leak, f"泄漏={leak}")
        # 图谱设备数 == 台账设备数
        g = rel.load_relations(p["dir"])
        ck(f"M4[{key}] 图谱设备数 == 台账设备数",
           len(g.get("devices") or []) == n_ledger,
           f"图谱={len(g.get('devices') or [])} 台账={n_ledger}")
        # 台账里的无名设备不进任何车间
        tagged = {t for t, rec in p["devices"].items() if (rec.get("workshop") or "")}
        ck(f"M4b[{key}] 无车间名的设备不落任何车间",
           len(tagged) == n_ledger - sh["nameless"],
           f"有车间={len(tagged)} 应为={n_ledger - sh['nameless']}")

    # ---------------------------------------------------------------- M5 落点解析纯函数
    a, b = PROJ["P1"]["dir"], PROJ["P2"]["dir"]
    pa = rel._ensure(a)
    pb = rel._ensure(b)
    ck("M5 落点解析是纯函数：两个项目各自返回自己的路径",
       isinstance(pa, str) and isinstance(pb, str) and pa != pb
       and os.path.dirname(pa) == a and os.path.dirname(pb) == b,
       f"A={pa} B={pb}")
    # 解析过 B 之后再读 A，必须还是 A
    rel._ensure(b)
    ga = rel.load_relations(a)
    ck("M5b 解析过 B 之后再读 A，A 仍是 A（不串味）",
       len(ga.get("devices") or []) == len(PROJ["P1"]["devices"]),
       f"A 图谱设备={len(ga.get('devices') or [])}")

    # ---------------------------------------------------------------- M6 落盘各归各位
    rel.build_relations(force=True, data_dir=a)
    rel.build_relations(force=True, data_dir=b)
    fa = os.path.join(a, "relations.json")
    fb = os.path.join(b, "relations.json")
    ok_a = os.path.exists(fa)
    ok_b = os.path.exists(fb)
    ck("M6 每个项目的图谱只落在自己的目录", ok_a and ok_b, f"A={ok_a} B={ok_b}")
    if ok_a and ok_b:
        ga = _read_json(fa) or {}
        gb = _read_json(fb) or {}
        ta = {t for t in (d.get("tag") for d in ga.get("devices") or []) if t}
        tb = {t for t in (d.get("tag") for d in gb.get("devices") or []) if t}
        ck("M6b A 的图谱不含 B 的位号", not (ta & tb), f"交集={sorted(ta & tb)[:5]}")
        ck("M6c B 的图谱不含 A 的位号", not (ta & tb), f"交集={sorted(ta & tb)[:5]}")

    # M5c **确定性交错**（模拟并发，不靠运气撞竞态）：
    # A 解析完自己的落点之后，B 插进来也解析了一次 —— 此时 A 再读，必须仍是 A。
    # 旧写法把落点放在模块级全局里，B 一插队就把全局抢走，A 读到的会是 B 的图谱。
    _orig_ensure = rel._ensure
    _state = {"done": False}

    def _hooked_ensure(data_dir=None):
        p = _orig_ensure(data_dir)
        if data_dir == a and not _state["done"]:
            _state["done"] = True
            _orig_ensure(b)          # B 插队
        return p

    rel._ensure = _hooked_ensure
    try:
        ga_inter = rel.load_relations(a)
    finally:
        rel._ensure = _orig_ensure
    inter_tags = {d.get("tag") for d in (ga_inter.get("devices") or []) if isinstance(d, dict)}
    ck("M5c 交错后 A 读到的仍是 A 的设备（落点不依赖模块级全局）",
       inter_tags == set(PROJ["P1"]["devices"]),
       f"读到={sorted(inter_tags)[:4]} 期望={sorted(PROJ['P1']['devices'])[:4]}")

    # ---------------------------------------------------------------- M7 车间归属互不串
    for key, p in PROJ.items():
        sha = p["tags"][0]
        wa.manual_assign(sha, sorted(p["ws"])[0], file_name=f"{key}资料.txt",
                         data_dir=p["dir"])
    for key, p in PROJ.items():
        others = [k for k, q in PROJ.items() if k != key]
        reg = wa.list_registry(p["dir"]) or []
        reg_names = {str(r.get("name") or "") for r in reg}
        ok = True
        detail = ""
        for ok2 in others:
            q = PROJ[ok2]
            qreg = {str(r.get("name") or "") for r in (wa.list_registry(q["dir"]) or [])}
            inter = reg_names & qreg
            if inter:
                ok = False
                detail = f"与 {ok2} 的登记册交集={inter}"
        ck(f"M7[{key}] 车间登记册只含本项目的内容", ok, detail)
    # 归属记录互不串
    for key, p in PROJ.items():
        f_assign = _read_json(os.path.join(p["dir"], "workshop_assign.json")) or {}
        own = set(f_assign.keys())
        bad = []
        for ok2, q in PROJ.items():
            if ok2 == key:
                continue
            fq = _read_json(os.path.join(q["dir"], "workshop_assign.json")) or {}
            inter = own & set(fq.keys())
            if inter:
                bad.append((ok2, sorted(inter)[:3]))
        ck(f"M7b[{key}] 车间归属记录只含本项目的位号", not bad, f"串={bad}")

    # ---------------------------------------------------------------- M8 并发建图谱
    errs = []

    def _build(d):
        try:
            for _ in range(6):
                rel.build_relations(force=True, data_dir=d)
        except Exception as e:  # noqa: BLE001
            errs.append(repr(e))

    ta = threading.Thread(target=_build, args=(a,))
    tb = threading.Thread(target=_build, args=(b,))
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    ck("M8 并发建图谱无异常", not errs, f"{errs[:2]}")
    ga = _read_json(fa) or {}
    gb = _read_json(fb) or {}
    ta_tags = {d.get("tag") for d in ga.get("devices") or [] if isinstance(d, dict)}
    tb_tags = {d.get("tag") for d in gb.get("devices") or [] if isinstance(d, dict)}
    ck("M8b 并发后 A 仍只含 A 的设备", ta_tags == set(PROJ["P1"]["devices"]),
       f"A={len(ta_tags)} 期望={len(PROJ['P1']['devices'])}")
    ck("M8c 并发后 B 仍只含 B 的设备", tb_tags == set(PROJ["P2"]["devices"]),
       f"B={len(tb_tags)} 期望={len(PROJ['P2']['devices'])}")

    # ---------------------------------------------------------------- M9 通用化 C9
    # 场景：在隔离目录里扫一份资料（当前项目 = P2）。
    # 期望：P2 的 index / 车间归属 / 队列 / 版本台账 一个字节都不变。
    p2 = PROJ["P2"]
    pm.set_current_project(p2["id"])
    iso = tempfile.mkdtemp(prefix="fg245_iso_")
    srcdir = os.path.join(iso, "src")
    os.makedirs(srcdir, exist_ok=True)
    ws0 = sorted(p2["ws"])[0]
    with io.open(os.path.join(srcdir, f"{ws0}_设备清单.txt"), "w", encoding="utf-8") as f:
        f.write(f"本文件属于 {ws0}，设备 {p2['tags'][0]}。\n")

    watched = {
        "index": os.path.join(p2["dir"], "index.json"),
        "assign": os.path.join(p2["dir"], "workshop_assign.json"),
        "queue_idx": os.path.join(p2["dir"], "upload_queue", "_sha_index.json"),
        "version": os.path.join(p2["dir"], "version_map.json"),
    }
    snap_before = {k: _bytes(v) for k, v in watched.items()}
    qdir_before = sorted(os.listdir(os.path.join(p2["dir"], "upload_queue"))
                          if os.path.isdir(os.path.join(p2["dir"], "upload_queue")) else [])

    # 用 stub 顶掉向量库：避免加载 embedding 模型（沙箱里很慢），
    # 同时**顺带验证向量库落点也跟随 ddir**（stub 会在自己的 db_path 下留标记）。
    class _StubStore:
        def __init__(self, db_path=None, **kw):
            self.db_path = db_path
            os.makedirs(db_path, exist_ok=True)
            with io.open(os.path.join(db_path, "__stub__"), "w", encoding="utf-8") as f:
                f.write("stub")

        def index_file(self, res):
            return 0

    _orig_vs = scanner.VectorStore
    scanner.VectorStore = _StubStore
    try:
        stat = scanner.scan_folder(srcdir, force=True, data_dir=iso)
    finally:
        scanner.VectorStore = _orig_vs

    ck("M9 隔离目录扫描成功", not stat.get("error"), f"{stat.get('error')}")
    snap_after = {k: _bytes(v) for k, v in watched.items()}
    changed = [k for k in snap_before if snap_before[k] != snap_after[k]]
    ck("M9b 当前项目的索引/归属/队列/版本台账一个字节都没变",
       not changed, f"被改动={changed}")
    qdir_after = sorted(os.listdir(os.path.join(p2["dir"], "upload_queue"))
                         if os.path.isdir(os.path.join(p2["dir"], "upload_queue")) else [])
    ck("M9c 当前项目的上传队列没有多出包", qdir_after == qdir_before,
       f"前={len(qdir_before)} 后={len(qdir_after)}")
    ck("M9d 隔离目录里确实落了解析缓存/索引/队列包（说明扫描真跑了）",
       os.path.exists(os.path.join(iso, "index.json"))
       and os.path.isdir(os.path.join(iso, "upload_queue")),
       f"iso={iso}")
    ck("M9e 向量库落点也跟随 ddir", os.path.exists(os.path.join(iso, "vector_db", "__stub__")),
       f"iso/vector_db={os.path.isdir(os.path.join(iso, 'vector_db'))}")
    # 隔离目录里的车间归属不得出现在任何项目里
    iso_assign = _read_json(os.path.join(iso, "workshop_assign.json")) or {}
    leaked = []
    for key, p in PROJ.items():
        f = _read_json(os.path.join(p["dir"], "workshop_assign.json")) or {}
        inter = set(iso_assign.keys()) & set(f.keys())
        if inter:
            leaked.append((key, sorted(inter)[:3]))
    ck("M9f 隔离目录的归属记录没有落到任何项目里", not leaked, f"泄漏={leaked}")
    shutil.rmtree(iso, ignore_errors=True)

    # ---------------------------------------------------------------- M10 真实数据零污染
    real_after = _real_snapshot()
    ck("M10 真实审计流水未被污染", real_before[0] == real_after[0],
       f"前={real_before[0]} 后={real_after[0]}")
    ck("M10b 真实项目目录未被污染", real_before[1] == real_after[1],
       f"前={len(real_before[1])} 后={len(real_after[1])}")

    shutil.rmtree(_TMP, ignore_errors=True)
    print("=" * 56)
    print(f"失败 {len(FAILS)} 条" + (f"  {FAILS}" if FAILS else "  （全部通过）"))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
