#!/usr/bin/env python3
"""隔离复现探针：把真实 65 个样本文件扫进**临时 DATA_DIR**，记录每个文件的开始/结束时刻。

为什么单独写这个：
  自测 20261113_040421 阶段1 出现「扫描 356.8s 完成、done=0/63、心跳停 301s、索引 0 条、
  向量 0 条」——13 条断言里 12 条都是从这里扇出的。要靠纯读代码定位不可靠，
  所以把同一条链路拉到单独进程里跑，带时间戳打印每一 tick。

隔离保证：
  · FANGONG_DATA_DIR 指向临时目录 → 当前项目、索引、队列、版本台账全部落在临时目录；
  · 源目录只读（只枚举文件，不写）；
  · 全程不动真实项目目录（脚本末尾会核对真实数据的 mtime 前后一致）。

用法：python tools/probe_scan_hang.py [源目录] [最长秒数]
"""
import io
import json
import os
import sys
import tempfile
import time

WB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(WB, "data", "uploads")
BUDGET = int(sys.argv[2]) if len(sys.argv) > 2 else 240

TMP = tempfile.mkdtemp(prefix="fgprobe_")
os.environ["FANGONG_DATA_DIR"] = TMP
os.environ.setdefault("FANGONG_NO_BROWSER", "1")

sys.path.insert(0, WB)

T0 = time.time()


def log(msg):
    print("[%7.1fs] %s" % (time.time() - T0, msg), flush=True)


REAL = os.path.join(WB, "data", "uploads")


def snap(src):
    out = {}
    for root, _d, fs in os.walk(src):
        for f in fs:
            p = os.path.join(root, f)
            try:
                out[p] = os.path.getsize(p)
            except OSError:
                pass
    return out


def main():
    log("临时 DATA_DIR=%s" % TMP)
    log("源目录=%s" % SRC)
    log("真实源目录快照（前后对比，证明只读）: %d 个文件" % len(snap(SRC)))

    from app import project_manager as pm
    from app import scanner

    pid = "probe01"
    d = os.path.join(pm.PROJECTS_ROOT, pid)
    os.makedirs(d, exist_ok=True)
    with io.open(os.path.join(d, "project_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"id": pid, "name": pid}, f, ensure_ascii=False)
    with io.open(pm.CURRENT_PROJECT_FILE, "w", encoding="utf-8") as f:
        json.dump({"project_id": pid}, f, ensure_ascii=False)
    log("临时项目=%s  解析超时阈值=%ss" % (d, getattr(scanner, "PARSE_FILE_TIMEOUT_SEC", "?")))

    last = {"t": time.time(), "msg": ""}
    gap = []

    def cb(done, total, msg):
        now = time.time()
        gap.append((now - last["t"], msg))
        last["t"] = now
        log("cb done=%s/%s  %s   (距上次回调 %.1fs)" % (done, total, msg, gap[-1][0]))
        if now - T0 > BUDGET:
            raise SystemExit("超预算退出")

    log("开始 scan_folder ...")
    t = time.time()
    try:
        stats = scanner.scan_folder(SRC, force=True, progress_cb=cb, data_dir=d)
        log("scan_folder 返回 rc=%s 耗时 %.1fs" % (json.dumps(stats, ensure_ascii=False), time.time() - t))
    except BaseException as e:  # noqa: BLE001
        log("scan_folder 抛异常 %s: %s 耗时 %.1fs" % (type(e).__name__, e, time.time() - t))

    idx_p = os.path.join(d, "index.json")
    log("index.json 存在=%s 条数=%s" % (
        os.path.exists(idx_p),
        len((json.load(io.open(idx_p, encoding="utf-8")).get("files") or {})) if os.path.exists(idx_p) else "-"))
    big = sorted([(g, m) for g, m in gap], reverse=True)[:5]
    log("最长回调空档 TOP5: %s" % [(round(g, 1), m[:30]) for g, m in big])
    a, b = snap(SRC), snap(SRC)
    log("源目录前后一致=%s" % (a == b))
    log("结束")


main()
