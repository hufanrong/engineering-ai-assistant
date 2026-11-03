#!/usr/bin/env python3
"""v0.1.197 回归：竣工清单的整份读改写必须原子、可并发。

实测事故（真实项目 e75e857c，228 台设备，POST /api/completion-archive/all 69 秒）：
    total_devices=222、failed_count=6，失败理由是
      FileNotFoundError: ... completion_archive.json.tmp -> completion_archive.json
      PermissionError:   Operation not permitted: ... completion_archive.json.tmp
两处根因：
  ① _save_archive 用**固定名字**的 path+".tmp"：两个线程同时写时，
     A rename 走了 .tmp，B 再 rename 报「不存在」；Windows 上 A 还持有句柄时
     B 直接 PermissionError（文件被占用）。现场表现为「一键竣工偶尔少几台设备」。
  ② 每台设备都做一次「读全量 → 改一条 → 写全量」，且读改写没有锁：
     后写的线程用自己那份**旧快照**整份覆盖，前面刚写进去的设备凭空消失
     （实测 6 路并发最终只剩 2 条 / 6 台丢了 4 台）。

用法：python3 tools/test_archive_concurrency.py   （退出码 0 = 全过）
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

WB = os.environ.get("FANGONG_WB",
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WB)
os.environ.setdefault("FANGONG_NO_BROWSER", "1")

from app import project_manager as pm  # noqa: E402
from app import completion_archive as ca  # noqa: E402

_PASS = [0]
_FAIL = []


def check(name, cond, detail=""):
    if cond:
        _PASS[0] += 1
        print(f"  [PASS] {name}")
    else:
        _FAIL.append(f"{name}  {detail}")
        print(f"  [FAIL] {name}  {detail}")


def _mkproj(tmp, pid, ndev=0):
    """造一个临时项目。"""
    pm.PROJECTS_ROOT = os.path.join(tmp, "projects")
    pm.CURRENT_PROJECT_FILE = os.path.join(tmp, "current_project.json")
    d = os.path.join(pm.PROJECTS_ROOT, pid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "project_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"id": pid, "name": pid}, f, ensure_ascii=False)
    with open(os.path.join(d, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"devices": {f"t{i}": {"tag": f"t{i}", "name": f"设备{i}",
                                       "workshop": "甲车间"}
                              for i in range(ndev)},
                   "files": {}, "workshops": {}}, f, ensure_ascii=False)
    with open(os.path.join(d, "file_level.json"), "w", encoding="utf-8") as f:
        json.dump({"files": {}}, f, ensure_ascii=False)
    with open(pm.CURRENT_PROJECT_FILE, "w", encoding="utf-8") as f:
        json.dump({"project_id": pid}, f)
    return d


def main():
    tmp = tempfile.mkdtemp(prefix="arch_cc_")
    _root, _cur = pm.PROJECTS_ROOT, pm.CURRENT_PROJECT_FILE
    try:
        print("\n[A] 并发写不得互相踩踏（固定 .tmp 名会 FileNotFound / PermissionError）")
        d = _mkproj(tmp, "a1")
        _orig = json.dump

        def _slow(*a, **k):
            # 放大 dump→replace 的窗口，模拟现场慢盘 / 机械硬盘 / 杀毒软件扫描。
            # 不放大时窗口太窄，缺陷命中率低 —— 现场那 6 台就是这么「偶尔」失败的。
            _orig(*a, **k)
            time.sleep(0.02)

        json.dump = _slow
        errs = []
        barrier = threading.Barrier(6)

        def w(i):
            try:
                barrier.wait()
                ca._update_archive(f"tag{i}", {"tag": f"tag{i}"})
            except Exception as e:  # noqa: BLE001
                errs.append(f"{type(e).__name__}: {str(e)[:80]}")

        ths = [threading.Thread(target=w, args=(i,)) for i in range(6)]
        [t.start() for t in ths]
        [t.join() for t in ths]
        json.dump = _orig

        check("并发 6 路写清单无一报错", not errs, f"{len(errs)} 个错误：{errs[:2]}")
        final = json.load(open(os.path.join(d, "completion_archive.json")))
        check("并发 6 路的写入全部保住（不能被旧快照整份覆盖）",
              len(final) == 6, f"最终 {len(final)} 条 / 期望 6 条")
        check("不残留临时文件",
              not [f for f in os.listdir(d) if f.endswith(".tmp")],
              str([f for f in os.listdir(d) if f.endswith(".tmp")]))

        print("\n[B] 统计必须说明自己是不是全的（残缺清单不能静默变小）")
        d2 = _mkproj(tmp, "a2", ndev=5)
        # 竣工清单只写 2 条，模拟此前被并发写毁坏的残缺文件
        with open(os.path.join(d2, "completion_archive.json"), "w", encoding="utf-8") as f:
            json.dump({f"t{i}": {"tag": f"t{i}", "completeness_percent": 0}
                       for i in range(2)}, f, ensure_ascii=False)
        st = ca.get_archive_stats()
        check("清单条目数如实返回", st.get("total_devices") == 2,
              f"实得 {st.get('total_devices')}")
        check("同时给出台账设备数（对照）", st.get("ledger_devices") == 5,
              f"实得 {st.get('ledger_devices')}")
        check("残缺时 stale 为 True", st.get("stale") is True,
              f"实得 {st.get('stale')}")
        check("残缺时给出可读告警（不能只有数字悄悄变小）",
              bool(st.get("warning")) and "2/5" in (st.get("warning") or ""),
              str(st.get("warning"))[:90])
        check("覆盖率为实数（2/5=0.4）", abs((st.get("coverage") or 0) - 0.4) < 1e-6,
              f"实得 {st.get('coverage')}")

        print("\n[C] 批量出全部设备：只写一次、不逐台往返")
        d3 = _mkproj(tmp, "a3", ndev=8)
        _writes = [0]
        _orig_save = ca._save_archive

        def _count_save(archive):
            _writes[0] += 1
            return _orig_save(archive)

        ca._save_archive = _count_save
        try:
            r = ca.generate_all_devices_archive()
        finally:
            ca._save_archive = _orig_save
        check("8 台设备全部算出（未因并发少台）",
              r.get("total_devices") == 8, f"实得 {r.get('total_devices')}")
        check("落盘次数为 1（不是每台一次整份读写）",
              _writes[0] == 1, f"实得 {_writes[0]} 次（8 台设备应只写 1 次）")
        check("批量结果确实落进了清单文件",
              len(json.load(open(os.path.join(d3, "completion_archive.json"))) ) == 8,
              "清单文件条目数与算出设备数不一致")
        st3 = ca.get_archive_stats()
        check("批量后统计与批量结果一致",
              st3.get("total_devices") == r.get("total_devices"),
              f"stats={st3.get('total_devices')} vs all={r.get('total_devices')}")
        check("批量后统计不再报残缺",
              st3.get("stale") is False, f"实得 {st3.get('stale')}")
    finally:
        pm.PROJECTS_ROOT, pm.CURRENT_PROJECT_FILE = _root, _cur
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "-" * 62)
    print(f"结果：通过 {_PASS[0]} / 失败 {len(_FAIL)} / 共 {_PASS[0] + len(_FAIL)}")
    for f in _FAIL:
        print(f"  FAIL: {f}")
    sys.exit(0 if not _FAIL else 1)


if __name__ == "__main__":
    main()
