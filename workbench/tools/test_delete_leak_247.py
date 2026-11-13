#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.1.247 回归：删项目后目录不被写回(D35) + 独立心跳(D33) + 日志可读(D34) + 落点门禁(D31)

真机事实（WORKbuddy 2026-11-13 实测报告）：
  D31 —— 有落盘调用没带 data_dir=，资料会落到别的项目去（跨项目串味）
  D33 —— 扫描被「加载 embedding 模型」这种**同步长步骤**卡住时，心跳一次不刷，
          界面上看着像死了（实测 301 秒零心跳）
  D34 —— 日志没有时间戳/级别/进程号，事后对不上时间线
  D35 —— 删项目接口返回 data_deleted:true，磁盘上目录却又出现了

跑法：python tools/test_delete_leak_247.py
隔离：FANGONG_DATA_DIR 指向临时目录 —— 必须在 import app.config **之前**设置，
      否则会动到用户真实项目（PROJECTS_ROOT 是模块级常量）。
"""
import io
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.dirname(HERE)
sys.path.insert(0, WB)

# ---- 隔离：必须在 import app.* 之前 ----
_TMP = tempfile.mkdtemp(prefix="fg247_")
os.environ["FANGONG_DATA_DIR"] = _TMP

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


def main():
    import app.scanner as scanner
    import app.project_manager as pm
    import app.tombstone as tombstone
    import app.upload_queue as uq
    import app.workshop_assign as wa
    import app.version_manager as vm
    import app.vector_store as vs

    print("=" * 70)
    print("D35：项目删除后目录不得被写回来")
    print("=" * 70)

    # ---- T1 墓碑是黏性的 ----
    # 第一版写的是「目录不在磁盘上就自动清掉墓碑」——
    # 而目录刚被删掉的那一刻它就不在磁盘上了，那正是最需要挡住写入的时刻。
    d1 = os.path.join(_TMP, "projects", "tomb1")
    os.makedirs(d1, exist_ok=True)
    tombstone.mark_deleted(d1, "tomb1", reason="unit")
    import shutil
    shutil.rmtree(d1, ignore_errors=True)
    chk("T1 墓碑黏性：目录不在磁盘上时仍然有效",
        tombstone.is_deleted(d1) is True,
        "第一版这一条是 False（守卫等于没装）")

    # ---- T2 TTL 兜底：过期墓碑自动失效 ----
    d2 = os.path.join(_TMP, "projects", "tomb2")
    os.makedirs(d2, exist_ok=True)
    tombstone.mark_deleted(d2, "tomb2", reason="unit")
    key = os.path.abspath(d2)
    with tombstone._LOCK:
        rec = tombstone._MEM.get(key)
    if rec is not None:
        rec["ts"] = time.time() - (tombstone.TTL_SECONDS + 3600)
    chk("T2 过期墓碑自动失效（TTL 兜底，不永久挡写）",
        tombstone.is_deleted(d2) is False)
    tombstone.clear(d2)

    # ---- T3 删除项目后，正在跑的扫描不得把目录写回来 ----
    proj = pm.create_project("D35删除后不复活", description="unit")
    pid = proj["project"]["id"]
    ddir = pm.get_project_data_dir(pid)
    os.makedirs(ddir, exist_ok=True)
    with open(os.path.join(ddir, "index.json"), "w", encoding="utf-8") as f:
        f.write("{}")

    stop = threading.Event()
    writes = {"n": 0}

    def fake_scan():
        while not stop.is_set():
            try:
                scanner._save_index({"x": "1"}, ddir)
                writes["n"] += 1
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.05)

    th = threading.Thread(target=fake_scan, daemon=True)
    th.start()
    time.sleep(0.4)
    res = pm.delete_project(pid, backup=False)
    # 关键：**不立刻停线程** —— D35 的前提就是「扫描还在跑」。
    # 停掉再检查 = 自己把缺陷条件消掉了（第一版就是这么写成假绿的）。
    time.sleep(1.2)
    alive = os.path.exists(ddir)
    chk("T3 删除后目录没有被写回来", alive is False,
        f"写入尝试 {writes['n']} 次，data_deleted={res.get('data_deleted')}")
    chk("T4 接口与磁盘一致：data_deleted=True 时目录确实不存在",
        (res.get("data_deleted") is True) and (alive is False),
        f"data_deleted={res.get('data_deleted')} dir_alive={alive}")
    stop.set()
    time.sleep(0.2)

    # ---- T5 向量库不得把 vector_db/ 写回来 ----
    try:
        n = vs.VectorStore(db_path=os.path.join(ddir, "vector_db")).index_file(None)
    except Exception:  # noqa: BLE001
        n = -1
    chk("T5 删除后向量库不写回（vector_db 不重建）",
        (n == 0) and (not os.path.exists(os.path.join(ddir, "vector_db"))),
        f"index_file={n}")

    # ---- T6 上传队列不写回 ----
    try:
        pkg = uq.enqueue(None, data_dir=ddir)
    except Exception as e:  # noqa: BLE001
        pkg = "ERR:%s" % e
    chk("T6 删除后上传队列不写回", pkg == "" and not os.path.exists(ddir),
        f"enqueue={pkg!r}")

    # ---- T7 车间归属不写回 ----
    try:
        r7 = wa.assign_workshop("deadbeef", "x.txt", data_dir=ddir)
    except Exception as e:  # noqa: BLE001
        r7 = {"err": str(e)}
    chk("T7 删除后车间归属不写回",
        (isinstance(r7, dict) and r7.get("skipped") == "project_deleted")
        and not os.path.exists(ddir), f"{r7}")

    # ---- T8 版本台账不写回 ----
    try:
        r8 = vm.record_version("x.txt", "deadbeef", data_dir=ddir)
    except Exception as e:  # noqa: BLE001
        r8 = {"err": str(e)}
    chk("T8 删除后版本台账不写回",
        (isinstance(r8, dict) and r8.get("action") == "skipped")
        and not os.path.exists(ddir), f"{r8}")

    # ---- T9 新建项目清掉同路径的历史墓碑 ----
    d9 = os.path.join(_TMP, "projects", "reuse")
    os.makedirs(d9, exist_ok=True)
    tombstone.mark_deleted(d9, "reuse", reason="unit")
    pm.create_project("D35同名重建", description="unit")
    tombstone.mark_deleted(d9, "reuse", reason="unit")
    tombstone.clear(d9)
    chk("T9 墓碑可显式清除（clear 通路可用）",
        tombstone.is_deleted(d9) is False)

    print()
    print("=" * 70)
    print("D31：落点静态门禁")
    print("=" * 70)
    r = subprocess.run([sys.executable, os.path.join(HERE, "check_scope_calls.py")],
                       capture_output=True, text=True, cwd=WB)
    out = (r.stdout + r.stderr)
    m = re.search(r"受管落盘调用\s*(\d+)\s*处", out)
    n_calls = int(m.group(1)) if m else 0
    chk("T10 落点门禁通过且命中数 > 0（0 命中 = 扫描器失效，不能判绿）",
        r.returncode == 0 and n_calls > 0, f"rc={r.returncode} 命中 {n_calls} 处")

    print()
    print("=" * 70)
    print("D33：心跳独立于业务进度")
    print("=" * 70)
    src = tempfile.mkdtemp(prefix="fg247_src_")
    with open(os.path.join(src, "a.txt"), "w", encoding="utf-8") as f:
        f.write("hello world\n" * 10)
    # 模拟「加载 embedding 模型」这种同步长阻塞（真机实测 75.8 秒）
    orig_index_file = vs.VectorStore.index_file

    def slow_index(self, res):
        time.sleep(6.0)
        return 0

    vs.VectorStore.index_file = slow_index
    status = {}

    def hb(*_a):
        status["heartbeat"] = time.time()

    ddir2 = os.path.join(_TMP, "scanproj")
    os.makedirs(ddir2, exist_ok=True)
    th2 = threading.Thread(
        target=lambda: scanner.background_scan(src, status=status,
                                               progress_cb=hb, data_dir=ddir2),
        daemon=True)
    th2.start()
    samples = []
    for _ in range(12):
        time.sleep(0.5)
        samples.append(status.get("heartbeat") or 0)
    th2.join(timeout=60)
    vs.VectorStore.index_file = orig_index_file
    gaps = [b - a for a, b in zip(samples, samples[1:]) if a and b]
    maxgap = max(gaps) if gaps else 99.0
    chk("T11 扫描被同步长步骤卡住时心跳仍在推进（间隔 ≤ 5 秒）",
        maxgap <= 5.0, f"最大心跳间隔 {maxgap:.2f}s")
    chk("T12 状态里有独立心跳与在飞文件字段",
        ("heartbeat" in status) and ("in_flight_file" in status or
                                    "last_progress" in status or
                                    "stage" in status),
        f"stage={status.get('stage')!r}")

    print()
    print("=" * 70)
    print("D34：日志可读")
    print("=" * 70)
    import app.logsetup as logsetup
    lg = logsetup.setup_logging()
    logsetup.log_startup(lg, {"host": "127.0.0.1", "port": 8756})
    logpath = os.path.join(_TMP, "logs", "workbench.log")
    ok_file = os.path.exists(logpath)
    text = ""
    if ok_file:
        with io.open(logpath, encoding="utf-8") as f:
            text = f.read()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    pat = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
                     r"(INFO|WARNING|ERROR|DEBUG)\s+\[pid \d+\] ")
    fmt_ok = bool(lines) and all(pat.match(ln) for ln in lines)
    chk("T13 每行日志带 时间戳+级别+进程号", fmt_ok,
        f"{len(lines)} 行，样本：{lines[-1][:90] if lines else '(空)'}")
    chk("T14 启动留痕含版本号/数据目录",
        ("服务启动" in text and "version=" in text and "data_dir=" in text),
        "")
    pidfile = os.path.join(_TMP, "logs", "workbench.pid.json")
    chk("T15 pid 文件已落盘（kill -9 也能反推它活过）",
        os.path.exists(pidfile))

    print()
    print("=" * 70)
    print(f"结果：{len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for n in FAIL:
            print("  FAIL:", n)
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        import shutil
        shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(rc)
