#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描心跳盲区 / 单文件超时 / 扫描启动竞态 回归（v0.1.234，D23 + D26）。

真机事实（WORKbuddy 2026-11-11 07:33，报告 reports/20261111_073324）：
    POST /api/scan → 200 ok:true
    之后 301 秒内 done=0/0、heartbeat 一次未刷新 → 自测判「卡死」
    07:48:28 done=46/63 仍在跑；07:53:02 done=63/63 完成
    合计 07:33:28 → 07:53:02 约 19.5 分钟

结论：扫描没死，它慢，而且前 301 秒完全不报进度。三个独立毛病：
    ① 心跳只覆盖「文件解析完成」这一刻（首个大文件整段在盲区里）；
    ② total 初始为 0，界面无法区分「在啃大文件」与「已经死了」；
    ③ 单文件无超时上限，一个文件卡住就拖死整轮。

D26 是同一片区域的另一个缺陷：/api/scan 先判 running → 置 False →
后台线程过一会才置 True，这个窗口里来的第二个 POST 不会被 409 拦住。

跑法：python tools/test_scan_heartbeat.py
"""
import io
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.dirname(HERE)
sys.path.insert(0, WB)
sys.path.insert(0, HERE)

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


def strip_comments(text):
    """只看代码行。

    本项目的教训：源码断言不剥注释会自欺 —— 注释里写着「用 mkstemp」就能让
    一条已经改坏的文件照样 PASS。
    """
    out = []
    for ln in text.splitlines():
        out.append(ln.split("#", 1)[0])
    return "\n".join(out)


def main():
    # ---- 提前确认模块可导入（坏代码要在这里就红，不要跑到一半才崩） ----
    import app.scanner as scanner

    print("=" * 70)
    print("场景1：心跳必须在「解析开始前」就刷，不能等文件解析完")
    print("=" * 70)
    src_sc = io.open(os.path.join(WB, "app", "scanner.py"), encoding="utf-8").read()
    code_sc = strip_comments(src_sc)

    chk("scanner 里存在带超时/心跳的解析入口 _parse_with_ticks",
        "def _parse_with_ticks(" in code_sc)
    chk("单文件解析有明确上限（PARSE_FILE_TIMEOUT_SEC）",
        "PARSE_FILE_TIMEOUT_SEC" in code_sc, 
        str(getattr(scanner, "PARSE_FILE_TIMEOUT_SEC", None)))
    # 判据要落在**扫描主循环**那一段：reparse_file / retry 走别的分支，
    # 它们是一次单文件操作，不需要扫描级心跳。所以截取 scan_folder 到
    # reparse_file 之间的代码再判，避免「同一函数别处还有调用」被误判成没改。
    _scan_body = code_sc.split("def scan_folder(")[1].split("def reparse_file(")[0]
    chk("扫描主循环里解析走的是带心跳/上限的入口（不是裸 parse_file）",
        "_parse_with_ticks(" in _scan_body and "parse_file(path)" not in _scan_body,
        "主循环里仍有裸调" if "parse_file(path)" in _scan_body else "已改")
    chk("扫描主循环里处理了超时分支（跳过并继续，不拖死整轮）",
        "_timed_out" in _scan_body and "timeouts" in _scan_body)

    # 真实调用：给一个会「卡住」的假解析器，验证心跳在解析过程中就有回调
    print()
    print("场景2：解析过程中（文件还没解析完）心跳必须已经在跳 —— 真跑，不是读源码")
    print("=" * 70)
    hb_times = []
    _orig_parse = scanner.parse_file

    def _slow_parse(path, *a, **kw):
        time.sleep(6.0)          # 模拟一个大文件（DWG/扫描件）
        return _orig_parse(path)

    scanner.parse_file = _slow_parse
    try:
        t0 = time.time()
        res, timed_out, err = scanner._parse_with_ticks(
            os.path.abspath(__file__), timeout=30,
            on_tick=lambda el: hb_times.append(time.time() - t0), tick_sec=1.0)
        chk("慢解析最终能返回（不被自己的超时误杀）",
            res is not None and not timed_out, f"timed_out={timed_out} err={err[:60]}")
        chk("**解析期间心跳至少跳了 2 次**（解析完才跳等于盲区仍在）",
            len(hb_times) >= 2, f"心跳 {len(hb_times)} 次: "
                                + ", ".join("%.1fs" % x for x in hb_times))
        chk("第一次心跳发生在解析完成之前（不是收尾才补一次）",
            bool(hb_times) and hb_times[0] < 6.0, f"首次 {hb_times[0] if hb_times else None}")
    finally:
        scanner.parse_file = _orig_parse

    print()
    print("=" * 70)
    print("场景3：单文件卡死不许拖死整轮 —— 超时后跳过、整轮仍能收尾")
    print("=" * 70)

    def _hung_parse(path, *a, **kw):
        time.sleep(60)           # 永远不返回（模拟卡死的解析器）
        return _orig_parse(path)

    scanner.parse_file = _hung_parse
    try:
        t0 = time.time()
        res, timed_out, err = scanner._parse_with_ticks(
            os.path.abspath(__file__), timeout=2, on_tick=None, tick_sec=0.5)
        cost = time.time() - t0
        chk("**卡死的解析会被判超时并返回**（不会无限等）",
            timed_out and res is None, f"timed_out={timed_out}")
        chk("超时后立刻返回（耗时接近上限，不是等满 60 秒）",
            cost < 10, f"耗时 {cost:.1f}s，上限 2s")
        chk("超时原因写得出来（能进失败清单与用户界面）",
            "超时" in (err or ""), err[:80])
    finally:
        scanner.parse_file = _orig_parse

    print()
    print("=" * 70)
    print("场景4：scan_folder 一进来就把 total 报出来（不能长期 done=0/0）")
    print("=" * 70)
    d = tempfile.mkdtemp(prefix="fgscan_")
    try:
        # 造 3 个可解析的样本 + 一个「慢」文件，看首条与解析前是否都有回调
        for i in range(3):
            p = os.path.join(d, f"a{i}.txt")
            io.open(p, "w", encoding="utf-8").write("繁工AI 扫描心跳测试 %d\n" % i)
        # 用 scanner 自己的 SUPPORTED_EXTS 判据确认这些文件会被枚举到
        calls = []

        def _cb(done, total, msg):
            calls.append((done, total, msg))

        # 让解析变慢，以便观察「解析中」阶段
        def _slow2(path, *a, **kw):
            time.sleep(1.0)
            return _orig_parse(path)

        scanner.parse_file = _slow2
        scanner.scan_folder(d, force=True, progress_cb=_cb,
                           data_dir=os.path.join(d, "_dd"))
    finally:
        scanner.parse_file = _orig_parse

    chk("扫描过程中有进度回调", bool(calls), f"{len(calls)} 次")
    first = calls[0] if calls else (0, 0, "")
    chk("**第一条回调就带上了 total**（不是 0/0）",
        first[1] >= 3, f"首条 done={first[0]} total={first[1]} msg={first[2][:40]}")
    chk("首条回调是「开始解析」，证明枚举已完成才进循环",
        "开始解析" in str(first[2]), str(first[2])[:60])
    chk("**解析开始前就有一条「解析中」回调**（心跳不再等到解析完）",
        any("解析中" in str(c[2]) for c in calls),
        "、".join(str(c[2])[:28] for c in calls[:4]))

    print()
    print("=" * 70)
    print("场景5：D26 —— 判 409 与占位必须在同一把锁里，且占位一定会释放")
    print("=" * 70)
    src_main = io.open(os.path.join(WB, "app", "main.py"), encoding="utf-8",
                       errors="replace").read()
    code_main = strip_comments(src_main)
    chk("main.py 有扫描启动锁", "_SCAN_START_LOCK" in code_main)
    # 断言的落点是 _claim_scan_slot 函数体：判「有没有在跑」必须在 with 锁之后，
    # 且函数返回 bool 让路由决定 409（路由里 if not _claim_scan_slot(): 409）。
    _cs_i = code_main.find("def _claim_scan_slot")
    chk("有 _claim_scan_slot 函数（判 409 与占坑合在一处）", _cs_i >= 0)
    if _cs_i >= 0:
        _cs_body = code_main[_cs_i:_cs_i + 900]
        _cs_body = _cs_body[: _cs_body.find("return True")] if "return True" in _cs_body else _cs_body
        chk("409 判定在 with _SCAN_START_LOCK 里（不是锁外裸判）",
            "with _SCAN_START_LOCK:" in _cs_body and
            _cs_body.find("with _SCAN_START_LOCK:") < _cs_body.find("if SCAN_STATUS.get"),
            "锁外裸判的话并发窗口还在")
        chk("路由用 _claim_scan_slot() 的返回值决定 409",
            "if not _claim_scan_slot()" in code_main and
            "HTTPException(409" in code_main)
    chk("占位字段独立存在（scan_slot），不依赖后台线程起来",
        '"scan_slot": True' in code_main)
    # 释放点有两处：正常收尾的 finally 是 status["scan_slot"] = False（字典赋值），
    # 线程起不来的兜底是 SCAN_STATUS.update({... "scan_slot": False})。
    # 两种写法都要算，只数字面量会漏掉 finally 那一处。
    import re as _re
    _rel = _re.findall(r'(?:\[\s*"scan_slot"\s*\]\s*=\s*False|"scan_slot"\s*:\s*False)', code_main)
    chk("finally 里释放占位（否则一次扫描后永远 409）",
        len(_rel) >= 2, f"释放点 {len(_rel)} 处")
    chk("线程起不来时也把占位还回去",
        "扫描线程启动失败" in src_main)

    # 真跑一次闸：模拟并发两个 POST 的判定函数
    print()
    print("=" * 70)
    print("场景6（真跑）：并发抢扫描坑，只能有一个成功")
    print("=" * 70)
    import threading
    got = {"ok": 0, "rejected": 0}
    lock = threading.Lock()

    try:
        from app import main as _m
    except Exception as e:  # noqa: BLE001
        chk("能导入 app.main（并发闸才测得成）", False, f"{type(e).__name__}: {e}")
        _m = None

    if _m is not None:
        # 纯多线程压测在 CPython 上抓不到这个竞态：GIL 保证「读完→写」之间只隔
        # 几字节码，实测有锁/无锁都是 1 抢到 / 39 被拒（见本轮日志），那是假守卫。
        # 改成把「判」与「占」之间的窗口**确定性放大**：用一个慢探针 dict，
        # get 读到 False 后先睡一会儿再返回（读到的仍是睡前的旧值）。
        #   · 有锁：睡发生在锁内，第二个线程被挡在锁外，醒来读到 True → 只能 1 个成功
        #   · 无锁：两线程都在睡、都拿着 False，醒来后都去占位 → 2 个都成功（原缺陷）
        class _SlowProbe(dict):
            """get 到 False 时先睡再返回旧值，把竞态窗口放到毫秒级。"""

            def get(self, k, d=None):
                v = dict.get(self, k, d)
                if v is False or v is None:
                    time.sleep(0.03)
                return v

        def _run_race(n=2):
            got = {"ok": 0, "rejected": 0}
            lk = threading.Lock()

            def w():
                if _m._claim_scan_slot() if hasattr(_m, "_claim_scan_slot") else False:
                    with lk:
                        got["ok"] += 1
                else:
                    with lk:
                        got["rejected"] += 1

            ts = [threading.Thread(target=w) for _ in range(n)]
            for th in ts:
                th.start()
            for th in ts:
                th.join()
            return got

        _real_status = _m.SCAN_STATUS
        try:
            _m.SCAN_STATUS = _SlowProbe({"running": False, "scan_slot": False})
            g2 = _run_race(2)
        finally:
            _m.SCAN_STATUS = _real_status

        chk("**窗口被放大的并发下只有 1 个抢到坑（无锁会 2 个都成功）**",
            g2["ok"] == 1 and g2["rejected"] == 1, str(g2))

        # 正常（不放大窗口）也跑一遍，确认常规并发下只有一个成功
        _m.SCAN_STATUS.clear()
        _m.SCAN_STATUS.update({"running": False, "scan_slot": False})
        g20 = _run_race(20)
        chk("20 个并发只有 1 个抢到扫描坑", g20["ok"] == 1 and g20["rejected"] == 19, str(g20))

        # 收尾必须放得开：占位释放后下一次还能抢到，否则就是「永久锁死」
        _m.SCAN_STATUS.update({"running": False, "scan_slot": False})
        _after = _m._claim_scan_slot() if hasattr(_m, "_claim_scan_slot") else False
        chk("释放占位后下一次又能抢到（不会永久锁死）", _after is True,
            f"再抢结果 {_after}")

    print()
    print("=" * 70)
    print("场景7：D19 —— 关向量库必须按目录边界判，不能字符串前缀误伤")
    print("=" * 70)
    from app import vector_store as vs

    class _FakeStore:
        def __init__(self, p):
            self._db_path = p
            self.closed = 0

        def close(self):
            self.closed += 1

    base = os.path.join(tempfile.mkdtemp(prefix="fgvs_"), "projects")
    p1 = os.path.join(base, "p1", "vector_db")
    p10 = os.path.join(base, "p10", "vector_db")
    s1, s10 = _FakeStore(p1), _FakeStore(p10)
    # 直接登记到真实注册表（用弱引用，与产品实现同一路径）
    vs._register(s1)
    vs._register(s10)
    n = vs.close_stores_under(os.path.join(base, "p1"))
    chk("**关 p1 不会误伤 p10**（字符串 startswith 会命中 p10）",
        s1.closed == 1 and s10.closed == 0,
        f"p1 关了 {s1.closed} 次，p10 关了 {s10.closed} 次")
    chk("返回真实的关闭个数", n >= 1, f"n={n}")
    chk("close() 关完把句柄字段清掉（否则下次 _get_collection 又长回来）",
        "self._collection = None" in strip_comments(
            io.open(os.path.join(WB, "app", "vector_store.py"), encoding="utf-8").read()))
    _pm_src = strip_comments(io.open(os.path.join(WB, "app", "project_manager.py"),
                                     encoding="utf-8", errors="replace").read())
    # 必须限定在**同一个函数体**里比对：文件里另一处（回收站路径）也有这个调用，
    # 用全文 rfind 会被它提前满足 —— 那就是「改一条路径等于两条都改了」的假通过。
    _rm = _pm_src.find("_safe_rmtree(project_dir)")
    _fn_lo = _pm_src.rfind("\ndef ", 0, _rm) if _rm > 0 else -1
    _fn_hi = _pm_src.find("\ndef ", _rm) if _rm > 0 else -1
    _fn = _pm_src[_fn_lo:_fn_hi] if (_rm > 0 and _fn_lo >= 0 and _fn_hi > _rm) else ""
    _rm_in = _fn.find("_safe_rmtree(project_dir)") if _fn else -1
    _cl_all = [m.start() for m in _re.finditer(r"close_stores_under\(project_dir\)", _fn)] if _fn else []
    # 两条路径（真删 / 仅移入回收站）各要一处，且都必须在 rmtree 之前。
    # 只数「有没有一处」会被另一条路径提前满足 —— 实测过这种假通过。
    chk("delete_project 内两条删除路径各有一处关闭，且都在 rmtree 之前",
        _rm_in > 0 and len(_cl_all) >= 2 and max(_cl_all) < _rm_in,
        f"函数内关闭 {len(_cl_all)} 处（{_cl_all}），rmtree@{_rm_in}")
    chk("仅删记录（移入回收站）那条路径也关了句柄",
        strip_comments(io.open(os.path.join(WB, "app", "project_manager.py"),
                               encoding="utf-8").read()).count("close_stores_under") >= 2)

    print()
    print("=" * 70)
    print(f"===== 通过 {len(PASS)} / 失败 {len(FAIL)} =====")
    for f in FAIL:
        print("  [FAIL] " + f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
