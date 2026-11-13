#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.1.249 / D37 回归：语义模型不可用**不得阻塞扫描**，且逃生通道必须真实存在。

缺陷来源（WORKbuddy 真机报告 20261113_040421，status=failed，通过 57 / 失败 12）：
    阶段①「扫描按时结束」失败：done 一直 0/63、心跳停 301s → 判定卡死，
    紧接着 11 条下游断言全红（资料库 0 条 / 检索 TimeoutError /
    竣工 total_devices=0 / 组卷「无设备数据」/ 缺件清单空 …）。
    **12 条红是同一条因** —— 扫描没走完，下游全都读到「0 台设备」。

根因：scanner.scan_folder → store.index_file() → VectorStore._get_model()
      → 本地无缓存 → 回退**联网下载 470MB 模型，且没有任何超时**，
      而这段阻塞在 `_parse_with_ticks`（120s 单文件超时）**之外**。
      附带根因：模型是**实例级**缓存，每个 VectorStore 各 load 一次（真机 75.8s/次）。

本门禁盯五件事：
    1. **有界**：模型加载/下载必须有上限 —— 等不到就降级，绝不挂死。
    2. **不重试轰炸**：确认不可用后，后续文件立刻降级，
       不再每个文件重复发起 470MB 下载（一次卡死 → 63 次卡死）。
    3. **扫描照常完成**：模型不可用时资料库**照常入库**，并**留痕**降级原因
       （否则统计里只有 vectorized=0，分不清「没内容」还是「模型没就绪」）。
    4. **逃生通道真实存在**：程序一直提示「可在设置里关闭语义检索」，
       而此前项目里根本没有这个开关 —— 现在开关真的能关掉并被扫描尊重。
    5. **模型共享**：多个 VectorStore 实例只 load 一次（不再 63×75.8s）。

跑法：python tools/test_semantic_degrade_249.py
隔离：FANGONG_DATA_DIR 指向临时目录 —— 必须在 import app.config **之前**设置。
"""
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.dirname(HERE)
sys.path.insert(0, WB)

# ---- 隔离：必须在 import app.* 之前 ----
_TMP = tempfile.mkdtemp(prefix="fg249_")
os.environ["FANGONG_DATA_DIR"] = _TMP

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


# --------------------------------------------------------------------------
# 假 sentence_transformers：复刻真机现场
#   · local_files_only=True → 抛异常（本地没缓存模型）
#   · 不带该参数 → **阻塞**（模拟 huggingface.co 不可达，下载卡死）
# --------------------------------------------------------------------------
_RELEASE = threading.Event()   # 测试收尾时把假下载线程放行
_CALLS = []                    # 记录每次构造调用


def _install_fake(local_cache_ok=False):
    """装一个假的 sentence_transformers 模块，返回调用记录列表。"""
    _CALLS.clear()

    class _FakeModel:
        def encode(self, docs, **kw):
            return [[0.0] * 4 for _ in docs]

    class SentenceTransformer:
        def __init__(self, name, local_files_only=False, **kw):
            _CALLS.append({"name": name, "local_only": bool(local_files_only)})
            if local_files_only:
                if local_cache_ok:
                    self._m = _FakeModel()
                    return
                raise OSError("本地无缓存模型")
            # 模拟「下载 470MB 卡死」：等到测试收尾才放行
            _RELEASE.wait(600)

        def encode(self, docs, **kw):
            return [[0.0] * 4 for _ in docs]

    import types
    mod = types.ModuleType("sentence_transformers")
    mod.SentenceTransformer = SentenceTransformer
    sys.modules["sentence_transformers"] = mod
    return _CALLS


def _reset_vs():
    """把向量库的进程级状态清回初始（每个用例都要从同一起点跑）。"""
    import app.vector_store as vs
    vs._SHARED_MODEL = None
    vs._MODEL_BLOCKED = False
    vs._MODEL_BLOCKED_REASON = ""
    vs._MODEL_DOWNLOADING = False
    vs._MODEL_DOWNLOAD_EVENT = threading.Event()


def _download_attempts():
    """真正发起过「联网下载」的次数（local_files_only 的不算）。"""
    return len([c for c in _CALLS if not c["local_only"]])


def main():
    import app.config as config
    import app.vector_store as vs
    import app.scanner as scanner
    import app.settings as settings

    print("=" * 72)
    print("D37：语义模型不可用不得阻塞扫描（v0.1.249）")
    print("=" * 72)

    # 把模型等待上限压到 2 秒 —— 真机是 90 秒，测试里等不起，
    # 但**性质相同**：都验证「等不到就降级、扫描继续」。
    old_timeout = config.EMBED_MODEL_LOAD_TIMEOUT_SEC
    config.EMBED_MODEL_LOAD_TIMEOUT_SEC = 2

    try:
        # ================================================================
        print("\n[A] 语义检索关闭：完全不碰模型")
        # ================================================================
        _reset_vs()
        _install_fake(local_cache_ok=False)
        settings.set_semantic_enabled(False)
        vs._SHARED_MODEL = None
        try:
            vs.VectorStore(db_path=os.path.join(_TMP, "vdb"))._get_model()
            chk("A1 关闭后 _get_model 应当拒绝（抛 ModelUnavailable）", False, "居然返回了模型")
        except vs.ModelUnavailable as e:
            chk("A1 关闭后 _get_model 抛 ModelUnavailable", True, str(e)[:60])
        except Exception as e:  # noqa: BLE001
            chk("A1 关闭后 _get_model 抛 ModelUnavailable", False, f"抛的是 {type(e).__name__}")
        chk("A2 关闭时一次模型加载都不该发生", len(_CALLS) == 0, f"实际调用 {len(_CALLS)} 次")

        # A3/A4/A5：扫描本身要**尊重**这个开关。
        # 此前 scanner 里那道守卫（关闭 → 跳过向量化）没有任何断言覆盖 ——
        # 守卫被删掉，门禁照样全绿。
        src_off = os.path.join(_TMP, "src_off")
        os.makedirs(src_off, exist_ok=True)
        with open(os.path.join(src_off, "关闭开关资料.txt"), "w", encoding="utf-8") as f:
            f.write("本文件用于验证关闭语义检索时扫描会跳过向量化。设备位号 P-402，型号 M300。\n" * 20)
        ddir_off = os.path.join(_TMP, "projects", "sem249off")
        os.makedirs(ddir_off, exist_ok=True)
        with open(os.path.join(ddir_off, "index.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        res_off = {}

        def _run_scan_off():
            try:
                res_off["stats"] = scanner.scan_folder(src_off, data_dir=ddir_off)
            except BaseException as e:  # noqa: BLE001
                res_off["err"] = f"{type(e).__name__}: {e}"

        th_off = threading.Thread(target=_run_scan_off, daemon=True)
        th_off.start()
        th_off.join(30)
        if th_off.is_alive():
            chk("A3 关闭语义检索后扫描仍能完成", False, "扫描 30s 未结束")
        else:
            chk("A3 关闭语义检索后扫描仍能完成", "err" not in res_off,
                str(res_off.get("err", ""))[:100])
            st_off = res_off.get("stats") or {}
            chk("A4 关闭后扫描跳过向量化（尊重开关）",
                (st_off.get("vector_skipped_disabled") or 0) >= 1,
                f"vector_skipped_disabled={st_off.get('vector_skipped_disabled')}")
        chk("A5 关闭后整轮扫描一次模型加载都不该发生", len(_CALLS) == 0,
            f"实际调用 {len(_CALLS)} 次")
        settings.set_semantic_enabled(True)

        # ================================================================
        print("\n[B] 模型本地无缓存 + 网络不可达：有界降级")
        # ================================================================
        _reset_vs()
        _install_fake(local_cache_ok=False)
        t0 = time.time()
        m = vs._load_model_bounded(timeout=2)
        dt = time.time() - t0
        chk("B1 加载有上限：到点返回 None 而不是挂死", m is None, f"耗时 {dt:.1f}s")
        chk("B2 到点就返回（不超过上限的 2 倍）", dt < 10, f"耗时 {dt:.1f}s")
        chk("B3 降级原因可读且是中文", bool(vs.model_status()["reason"]),
            vs.model_status()["reason"][:60])

        # ================================================================
        print("\n[C] 熔断闩：不可用后不再反复下载")
        # ================================================================
        before = _download_attempts()
        for _ in range(5):
            vs._load_model_bounded(timeout=2)
        after = _download_attempts()
        chk("C1 熔断后再调 5 次不应新增下载尝试", after == before,
            f"下载尝试 {before} -> {after}")
        chk("C2 熔断后返回 None（继续降级）", vs._load_model_bounded(timeout=2) is None)

        # ================================================================
        print("\n[D] 扫描不被模型拖死（真跑一次扫描）")
        # ================================================================
        _reset_vs()
        _install_fake(local_cache_ok=False)
        src = os.path.join(_TMP, "src")
        os.makedirs(src, exist_ok=True)
        with open(os.path.join(src, "设备资料.txt"), "w", encoding="utf-8") as f:
            f.write("本文件用于验证模型不可用时扫描仍能完成。设备位号 P-301，型号 M200。\n" * 20)
        pid = "sem249"
        ddir = os.path.join(_TMP, "projects", pid)
        os.makedirs(ddir, exist_ok=True)
        with open(os.path.join(ddir, "index.json"), "w", encoding="utf-8") as f:
            f.write("{}")

        result = {}

        def _run_scan():
            try:
                result["stats"] = scanner.scan_folder(src, data_dir=ddir)
            except BaseException as e:  # noqa: BLE001
                result["err"] = f"{type(e).__name__}: {e}"

        th = threading.Thread(target=_run_scan, daemon=True)
        th.start()
        # **有界 join**：把旧写法（无超时下载）放回去时，扫描线程会挂死，
        # 这里必须判红而不是让整个测试卡住 —— 「测试挂住」不是可用的失败信号。
        th.join(60)
        finished = not th.is_alive()
        chk("D1 模型卡死时扫描仍在有界时间内收尾", finished,
            "扫描线程 60s 未结束（旧行为：卡在下载模型）")
        if finished and "err" in result:
            chk("D2 扫描无异常", False, result["err"][:120])
        else:
            chk("D2 扫描无异常", "err" not in result, str(result.get("err", ""))[:120])

        stats = result.get("stats") or {}
        chk("D3 降级被留痕（vector_degraded=True）", stats.get("vector_degraded") is True,
            f"stats.vector_degraded={stats.get('vector_degraded')}")
        chk("D4 降级原因可读", bool(stats.get("vector_degraded_reason")),
            str(stats.get("vector_degraded_reason"))[:80])
        # 资料库**照常入库** —— 这是本条缺陷最关键的后果面：
        # 旧行为下扫描卡死 → 资料库 0 条 → 下游 11 条断言全红。
        idx = scanner._load_index(ddir)
        n_files = scanner.count_index_files(idx)
        chk("D5 模型不可用时资料库照常入库", n_files >= 1, f"入库 {n_files} 个文件")
        chk("D6 扫描统计里 parsed>0", (stats.get("parsed") or 0) >= 1,
            f"parsed={stats.get('parsed')}")

        # ================================================================
        print("\n[E] 模型进程级共享：多个实例只 load 一次")
        # ================================================================
        _reset_vs()
        _install_fake(local_cache_ok=True)
        s1 = vs.VectorStore(db_path=os.path.join(_TMP, "vdb1"))
        s2 = vs.VectorStore(db_path=os.path.join(_TMP, "vdb2"))
        try:
            s1._get_model()
            s2._get_model()
            n_load = len(_CALLS)
            chk("E1 两个实例只 load 一次模型", n_load == 1, f"实际 load {n_load} 次")
        except Exception as e:  # noqa: BLE001
            chk("E1 两个实例只 load 一次模型", False, f"{type(e).__name__}: {e}")

        # ================================================================
        print("\n[F] 逃生通道真实存在（开关真的生效）")
        # ================================================================
        settings.set_semantic_enabled(False)
        raw = settings.get_settings()
        chk("F1 开关状态落盘可读回", raw.get("semantic_enabled") is False, str(raw))
        p = os.path.join(config.DATA_DIR, "settings.json")
        chk("F2 设置文件真的写在磁盘上", os.path.isfile(p), p)
        _reset_vs()
        _install_fake(local_cache_ok=False)
        try:
            vs.VectorStore(db_path=os.path.join(_TMP, "vdb3"))._get_model()
            chk("F3 关闭后拒绝加载模型", False, "居然加载成功了")
        except vs.ModelUnavailable:
            chk("F3 关闭后拒绝加载模型", True)
        settings.set_semantic_enabled(True)

        # ================================================================
        print("\n[G] 前端有入口 + 接口存在（防止「后端有、前端没有」的半交付）")
        # ================================================================
        idx_html = os.path.join(WB, "web", "index.html")
        with open(idx_html, "r", encoding="utf-8") as f:
            html = f.read()
        chk("G1 页面里有语义开关的调用", "api/settings" in html,
            f"html 里 api/settings 出现 {html.count('api/settings')} 次")
        import app.main as main_mod
        paths = set(getattr(main_mod.app, "routes", []) and
                    [getattr(r, "path", "") for r in main_mod.app.routes])
        chk("G2 GET /api/settings 路由存在", "/api/settings" in paths)
        # 注意：不能写成 `... in paths or True` —— paths 是**路由路径**集合，
        # 里面永远不会有响应字段名，`or True` 会让这条恒绿、什么也没测。
        settings.set_semantic_enabled(True)
        _reason = main_mod._vector_degraded_reason()  # noqa: SLF001
        chk("G3 降级原因函数返回非空中文", bool(str(_reason or "").strip()),
            f"reason={_reason!r}")
        import inspect
        src_status = inspect.getsource(main_mod.status)
        chk("G4 /api/status 含 semantic_enabled 字段", "semantic_enabled" in src_status)
        chk("G5 /api/status 含 vector_degraded_reason 字段",
            "vector_degraded_reason" in src_status)

        # ================================================================
        print("\n[H] 状态必须说得出「为什么没就绪」")
        # ================================================================
        # 「就绪=false」与「原因为空」并存 = 界面只能显示「没反应」，
        # 用户分不清是「文件没内容」还是「模型没加载出来」。
        _reset_vs()
        _install_fake(local_cache_ok=False)
        settings.set_semantic_enabled(True)
        before_calls = len(_CALLS)
        st = vs.model_status()
        chk("H1 没就绪时必须给出可读的中文原因",
            bool(str(st.get("reason") or "").strip()),
            f"reason={st.get('reason')!r}")
        chk("H2 原因里要说明已降级",
            "降级" in str(st.get("reason") or ""),
            f"reason={st.get('reason')!r}")
        chk("H4 查原因不得触发模型加载（否则每次查状态都等 75 秒）",
            len(_CALLS) == before_calls,
            f"探测多调了 {len(_CALLS) - before_calls} 次构造")
        settings.set_semantic_enabled(False)
        st_off = vs.model_status()
        chk("H3 用户自己关的，原因要说明是用户关的",
            "关闭" in str(st_off.get("reason") or ""),
            f"reason={st_off.get('reason')!r}")
        settings.set_semantic_enabled(True)
        src_update = inspect.getsource(main_mod.update_settings)
        chk("H5 开开关后要真的去预热（不能只写个开关）",
            "warmup" in src_update,
            "已检查 POST /api/settings 是否触发预热")

    finally:
        _RELEASE.set()
        config.EMBED_MODEL_LOAD_TIMEOUT_SEC = old_timeout
        try:
            import app.settings as st
            st.set_semantic_enabled(True)
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(_TMP, ignore_errors=True)

    print("\n" + "=" * 72)
    print(f"结果：通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print("  FAIL:", f)
    print("=" * 72)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
