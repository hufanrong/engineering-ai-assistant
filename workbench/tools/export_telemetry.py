#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出「真实使用诊断包」· 给用户/现场同事一键用。

为什么要这个脚本：
    真实使用里的问题（「上传 200 个 PDF、30 个没解析出来」）只有程序自己知道，
    用户事后复述不了。程序已经在 v0.1.171 起记录每次请求（路由/状态/耗时/异常），
    但让用户去浏览器里手敲 /api/telemetry/export 再复制 JSON，等于没做。

它做什么：
    1. 找本地工作台（默认 http://127.0.0.1:8756，可用 --base 改）。
    2. 调 /api/telemetry/export 取脱敏诊断包，落成
       telemetry_export_YYYYmmdd_HHMM.json（放在脚本同目录）。
    3. 顺手取 /api/telemetry/stats，在屏幕上打印「最慢的接口 / 报错最多的接口」，
       让用户提交前就能一眼看出这轮跑了什么。
    4. 明确告诉用户这个文件可以直接传，因为它**已经脱敏**（无项目名/客户/地址/
       文件名/绝对路径）。

不要做什么：
    不要把原始日志（data/telemetry/requests.jsonl）直接拿去分享。仓库是公开的，
    里面有项目名、客户单位、矿区地点、设备位号和本机绝对路径 —— 那是业务资料，
    不是日志。凡是要传出去的，一律用本脚本导出的包。

用法：
    python export_telemetry.py                  # 增量（自上次导出之后的新增）
    python export_telemetry.py --full           # 全部历史
    python export_telemetry.py --base http://127.0.0.1:8756
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BASE = os.environ.get("FANGONG_BASE", "http://127.0.0.1:8756")


def _get(base, path, timeout=30):
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE, help="工作台地址，默认 127.0.0.1:8756")
    ap.add_argument("--full", action="store_true", help="导出全部历史（默认只导出自上次导出后的新增）")
    ap.add_argument("--out", default="", help="输出文件路径（默认放在脚本同目录）")
    a = ap.parse_args()

    try:
        st = _get(a.base, "/api/telemetry/status")
    except urllib.error.HTTPError as e:
        print(f"[失败] {a.base}/api/telemetry/status 返回 {e.code}")
        print("       这个版本还没有遥测接口（v0.1.171 起才有）。先更新程序再试。")
        return 2
    except Exception as e:
        print(f"[失败] 连不上工作台：{type(e).__name__}: {e}")
        print(f"       确认程序已启动，且地址是 {a.base}（可用 --base 指定别的端口）")
        return 2

    lines = st.get("lines")
    print(f"[信息] 遥测已记录 {lines} 条请求；水位：{st.get('watermark') or '（无，首次导出）'}")

    q = "/api/telemetry/export?" + ("full=true" if a.full else "full=false")
    try:
        resp = _get(a.base, q)
    except Exception as e:
        print(f"[失败] 导出接口出错：{type(e).__name__}: {e}")
        return 3

    bundle = (resp or {}).get("data")
    if not isinstance(bundle, dict) or not bundle:
        print(f"[失败] 导出返回为空：{str(resp)[:200]}")
        return 3

    ts = time.strftime("%Y%m%d_%H%M")
    out = a.out or os.path.join(HERE, f"telemetry_export_{ts}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=1)
    size = os.path.getsize(out)

    req = bundle.get("requests") or {}
    pf = bundle.get("parse_failures") or {}
    print("")
    print(f"[完成] 已导出 {out}  ({size} B)")
    print(f"       统计窗口：{(bundle.get('window') or {}).get('from')} → "
          f"{(bundle.get('window') or {}).get('to')}")
    print(f"       请求总数：{req.get('total')}")
    print(f"       解析失败：{pf.get('total_failed')} 条，类型分布 {pf.get('by_ext')}")

    slow = req.get("slow_routes") or []
    if slow:
        print("       最慢接口（p95 / 最大）：")
        for r in slow[:5]:
            print(f"         - {r.get('route')}  n={r.get('n')} "
                  f"p95={r.get('p95_ms')}ms max={r.get('max_ms')}ms")
    errs = bundle.get("errors") or []
    if errs:
        print("       报错最多（已聚合为指纹）：")
        for e in errs[:5]:
            print(f"         - {e.get('fingerprint')}  ×{e.get('count')}")
    else:
        print("       本窗口无异常记录。")

    print("")
    print("这个文件已经脱敏（无项目名/客户/地点/文件名/绝对路径），可以直接回传。")
    print(f"文件位置：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
