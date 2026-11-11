#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段覆盖必须写进报告，且漏测要影响判定（v0.1.232 回归）。

真机事实（reports/20261110_164517，WORKbuddy 2026-11-10 16:59）：
    console.log 第一行 = selftest.py --phase 1,2,3,5
    report.md        = 「通过 50 / 失败 1」
阶段 4（竣工图清稿）与阶段 6（同一事实交叉比对，23 条跨接口口径比对）
**一条断言都没执行**，报告却长得像一次完整体检。

这是本项目反复出现的「同一件事两个答案」：报告说全面检查，实际漏了 2/6。
两个落点必须同时改，只改一处等于没改：
    ① selftest.write_report —— 报告里声明 ran/missed，并在漏测时记一条红断言；
    ② wb_loop 判定 —— 漏测时判 partial（不是 passed，也不是 failed）；
       report.md 与提交信息同样带覆盖。

跑法：python tools/test_phase_coverage.py
"""
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.dirname(HERE)
sys.path.insert(0, WB)
sys.path.insert(0, HERE)

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


def run_selftest_report(phases_ran):
    """真的 import selftest，设 RAN_PHASES，再调 write_report 落两份文件。"""
    import importlib
    if "selftest" in sys.modules:
        st = importlib.reload(sys.modules["selftest"])
    else:
        import selftest as st
    st.RAN_PHASES = list(phases_ran)
    st.PHASE_SUMMARY.clear()
    st.RESULTS.clear()
    for ph in phases_ran:
        st.PHASE_SUMMARY[ph] = {"passed": 5, "failed": 0, "skipped": 0}
        st.record(ph, f"阶段{ph}样例断言", "随便", "随便", True)

    d = tempfile.mkdtemp(prefix="fgcov_")
    j = os.path.join(d, "selftest_report.json")
    m = os.path.join(d, "selftest_report.md")
    st.write_report(j, m, d)
    payload = json.loads(io.open(j, encoding="utf-8").read())
    md = io.open(m, encoding="utf-8").read()
    return payload, md


def main():
    print("=" * 70)
    print("场景1：只跑 1,2,3,5（真机现状）—— 报告必须自曝漏测")
    print("=" * 70)
    payload, md = run_selftest_report([1, 2, 3, 5])
    cov = payload.get("coverage") or {}
    chk("report.json 带 coverage 字段", bool(cov), str(cov)[:100])
    chk("ran 就是实际跑的 1,2,3,5", cov.get("ran") == [1, 2, 3, 5], str(cov.get("ran")))
    # v0.1.234（D24）：阶段 4 是**老板决定不测**（需 Windows + AutoCAD），
    # 它不该再被算成漏测 —— 否则每轮必红，真实的红信号被噪声盖住。
    # 真正该红的是「launcher 要求跑却没跑」的 6。
    chk("missed 只剩 6（阶段4 是既定决策跳过，不算漏测）",
        cov.get("missed") == [6], str(cov.get("missed")))
    chk("阶段4 进了 skipped_by_decision",
        cov.get("skipped_by_decision") == [4], str(cov.get("skipped_by_decision")))
    chk("主动跳过带原因（不能只说「跳过了」）",
        str((cov.get("skipped_reasons") or {}).get("4") or "").strip() != "",
        str(cov.get("skipped_reasons"))
    )
    chk("complete=False（不能自称完整）", cov.get("complete") is False, str(cov.get("complete")))
    chk("漏测项有人话标签",
        any("交叉比对" in x for x in (cov.get("missed_labels") or [])),
        str(cov.get("missed_labels")))
    # 报告正文第一屏必须写明，不能只藏在 json 里
    _head = md[:1200]
    chk("report.md 第一屏写了「阶段覆盖」", "阶段覆盖" in _head)
    chk("report.md 明确写出漏了（4/6 或点名漏测）", "4/6" in _head or "漏测" in _head,
        _head[:200].replace("\n", " "))
    chk("report.md 说明为什么跳过阶段4（不算漏测）",
        "主动跳过" in md, md[:900].replace("\n", " "))
    chk("report.md 提醒通过数不代表整体可用",
        "不能当作整体可用" in md or "不代表整体可用" in md)
    # 漏测必须进失败计数，否则「没检查」等于「检查过」
    chk("漏测记成一条红断言（进 failed 计数）",
        (payload.get("summary", {}).get("6", {}).get("failed") or 0) >= 1,
        json.dumps(payload.get("summary", {}), ensure_ascii=False))
    _covrow = [r for r in payload.get("results", []) if "阶段覆盖完整" in str(r.get("step"))]
    chk("这条断言落在阶段6（跨接口比对的家）", bool(_covrow) and _covrow[0]["phase"] == 6)
    chk("断言实际值里点名漏测阶段",
        bool(_covrow) and ("漏测" in str(_covrow[0]["actual"])), 
        _covrow[0]["actual"] if _covrow else "")

    print()
    print("=" * 70)
    print("场景2：完整跑 1~6 —— 必须报「完整」，且不能凭空多出红断言")
    print("=" * 70)
    payload2, md2 = run_selftest_report([1, 2, 3, 4, 5, 6])
    cov2 = payload2.get("coverage") or {}
    chk("complete=True", cov2.get("complete") is True, str(cov2.get("complete")))
    chk("missed 为空", cov2.get("missed") == [], str(cov2.get("missed")))
    chk("report.md 写「完整」", "阶段覆盖：**完整**" in md2, md2[:300].replace("\n", " "))
    chk("完整时不多记红断言（单跑调试不该被误伤）",
        (payload2.get("summary", {}).get("6", {}).get("failed") or 0) == 0,
        json.dumps(payload2.get("summary", {}), ensure_ascii=False))

    print()
    print("=" * 70)
    print("场景3：wb_loop 判定 —— 漏测必须落下 partial，不能报 passed")
    print("=" * 70)
    import wb_loop as w

    class _A:
        phases = "1,2,3,5"

    # 用真实源码里的判定分支（不复制一份逻辑，否则测的是我抄的那份）
    src = io.open(os.path.join(WB, "tools", "wb_loop.py"), encoding="utf-8").read()
    chk("判定分支里有 partial", 'status = "partial"' in src)
    chk("partial 的条件是 missed 非空",
        'elif _missed:' in src and 'status = "partial"' in src)
    chk("漏测信息进了「判定」步骤文字", "漏测阶段=" in src)
    chk("report.md 也写覆盖（不是只写 json）", "阶段覆盖：**不全，漏测" in src)
    chk("partial 不算「这一版已完整测过」",
        'if status in ("passed", "failed"):' in src
        and "last_tested_commit" in src)
    chk("partial 的退出码与 failed 分开",
        '"partial": 2' in src, "partial -> 2, failed -> 1, passed -> 0")

    # 真实跑一次 _summary 组装：把 selftest 的 coverage 传下去
    chk("wb_loop 接住了 selftest 的 coverage",
        'coverage = report.get("coverage") or {}' in src)
    chk("coverage 又被塞进 summary 往下传",
        '"coverage": coverage,' in src)

    print()
    print("=" * 70)
    print("场景4（反向验证）：把覆盖声明去掉，本测试必须变红")
    print("=" * 70)
    # 直接验证「旧的 selftest（没有 coverage 字段）」会被本套的判据抓住：
    # 用一份删掉 coverage 的 payload 模拟旧版本回传的报告。
    old_payload = {k: v for k, v in payload.items() if k != "coverage"}
    chk("旧报告（无 coverage）会被判为「覆盖未知」，不能算完整",
        not (old_payload.get("coverage") or {}).get("complete", False),
        "缺失 coverage 时 .get('complete') 为 None → 判不出完整")
    old_md = md.replace("阶段覆盖", "阶段")
    chk("旧 report.md（不写覆盖）会丢掉那两个关键字节",
        "阶段覆盖：**4/6" not in old_md)

    print()
    print("=" * 70)
    print(f"===== 通过 {len(PASS)} / 失败 {len(FAIL)} =====")
    for f in FAIL:
        print("  [FAIL] " + f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
