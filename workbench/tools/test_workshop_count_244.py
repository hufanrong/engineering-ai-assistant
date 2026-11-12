# -*- coding: utf-8 -*-
"""v0.1.244 门禁：项目卡片的车间数必须与 /api/workshops 同源同值。

缺陷（实证）：真实项目台账里真实存在 19 个车间，/api/workshops 返回 19，
项目卡片 workshop_count 显示 0。根因是「合并只补一半」——车间清单并了台账车间，
统计口径没并。

断言（隔离目录跑，构造台账设备带车间名）：
  W1 统计里的车间数 == 车间清单里的车间数（核心守卫）
  W2 只有台账车间、没有文件级归属时，统计也必须数到（不得恒为 0）
  W3 未审批的自动推导名字不得进统计（用户指令：未确认不建车间）
  W4 已人工确认的车间必须计入统计
  W5 无台账、无确认时统计为 0，且不得抛错
"""
import json, os, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# v0.1.244：隔离必须放在 **import 之前** —— config.DATA_DIR / PROJECTS_ROOT /
# CURRENT_PROJECT_FILE 都是模块级常量，import 后再改就已经晚了
# （第一版就这么写的，测试自己把登记册写进了真实项目目录）。
_TMP = tempfile.mkdtemp(prefix="fg244_")

# v0.1.244：隔离必须落在**模块级常量**上，而且要在这些模块被 import 之前。
# 第一版只改了 config.DATA_DIR，但 project_manager 在被 import 时就把
# PROJECTS_ROOT / CURRENT_PROJECT_FILE 绑成了自己的模块级常量 —— 于是
# create_project() 照样把「车间数同源测试」建进了**真实** data/projects，
# 并往真实 operation_log.jsonl 写了一行「新建项目」。
# 这条教训与 MEMORY 里「隔离必须放在目录解析函数底层」同源：
# 要改的是**常量定义处**，不是调用前的一行赋值。
import app.config as _cfg
_cfg.DATA_DIR = _TMP
_cfg.PROJECTS_ROOT = os.path.join(_TMP, "projects")
_cfg.CURRENT_PROJECT_FILE = os.path.join(_TMP, "current_project.json")

import app.project_manager as _pm_mod
_pm_mod.PROJECTS_ROOT = _cfg.PROJECTS_ROOT
_pm_mod.CURRENT_PROJECT_FILE = _cfg.CURRENT_PROJECT_FILE
_pm_mod._config.DATA_DIR = _TMP

from app import main as M
from app import project_manager as pm
from app import workshop_assign as wa

# 真实数据基线（用于污染检测）
_REAL_LOG = os.path.join(ROOT, "data", "operation_log.jsonl")
_REAL_PROJECTS = os.path.join(ROOT, "data", "projects")


def _real_snapshot():
    log_lines = 0
    if os.path.exists(_REAL_LOG):
        with open(_REAL_LOG, "rb") as f:
            log_lines = sum(1 for _ in f)
    projs = sorted(os.listdir(_REAL_PROJECTS)) if os.path.isdir(_REAL_PROJECTS) else []
    return log_lines, projs

FAILS = []


def ck(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def main():
    global _REAL_SNAP
    _REAL_SNAP = _real_snapshot()
    # 建一个真实项目（用真实 API，形状与线上一致）
    created = pm.create_project(name="车间数同源测试", description="")
    pid = (created.get("project") or {}).get("id") or created.get("id")
    assert pid, created
    pdir = pm.get_project_data_dir(pid)
    os.makedirs(pdir, exist_ok=True)

    def write_ledger(devices):
        with open(os.path.join(pdir, "index.json"), "w", encoding="utf-8") as f:
            json.dump({"devices": devices, "files": {}}, f, ensure_ascii=False)

    def stat_ws():
        M._refresh_project_stats()
        cur = pm.get_current_project() or {}
        return cur.get("workshop_count")

    def list_ws():
        ws = M.get_workshops()
        return [r["name"] for r in (ws.get("workshops") or [])]

    pm.set_current_project(pid)

    # W2 / W1：只有台账车间（没有任何文件级归属）
    write_ledger({
        "D-1": {"name": "破碎机", "model": "PE600", "workshop": "破碎车间", "quantity": "1"},
        "D-2": {"name": "浮选机", "model": "XCF8", "workshop": "磨浮车间", "quantity": "2"},
        "D-3": {"name": "皮带机", "model": "TD75", "workshop": "磨浮车间", "quantity": "1"},
    })
    s = stat_ws()
    lst = list_ws()
    ck("W2 只有台账车间时统计也数得到（不得恒为 0）", s == 2, f"统计={s}")
    ck("W1 统计车间数 == 车间清单数", s == len(lst), f"统计={s} 清单={len(lst)} {lst}")

    # W3：未审批的自动推导名不得进统计/清单（用户指令：未确认不建车间）
    ck("W3 未审批自动名不进统计",
       not any(n in lst for n in ["建宇建主减速机油站", "选矿厂"]) and s == len(lst),
       f"统计={s} 清单={lst}")

    # W4：人工确认一个车间后必须计入统计
    wa.approve_workshop("人工确认车间", approved_by="test", note="门禁")
    s2 = stat_ws()
    lst2 = list_ws()
    ck("W4 人工确认的车间计入统计且与清单一致",
       s2 == len(lst2) and "人工确认车间" in lst2, f"统计={s2} 清单={len(lst2)}")

    # W5：空台账、无确认 -> 统计为 0，不抛错
    pm.set_current_project(pid)
    write_ledger({})
    wa._save_registry({})
    s3 = stat_ws()
    ck("W5 空数据时统计为 0 且不抛错", s3 == 0, f"统计={s3}")

    # 污染检测：真实审计流水与真实项目目录必须一字未变
    before_lines, before_projs = _REAL_SNAP
    after_lines, after_projs = _real_snapshot()
    ck("W6 真实审计流水未被污染", before_lines == after_lines,
       f"前={before_lines} 后={after_lines}")
    ck("W7 真实项目目录未被污染", before_projs == after_projs,
       f"前={len(before_projs)} 后={len(after_projs)}")

    shutil.rmtree(_TMP, ignore_errors=True)
    print("=" * 50)
    print(f"通过 {0 if FAILS else 'ALL'} / 失败 {len(FAILS)}" + (f"  {FAILS}" if FAILS else ""))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
