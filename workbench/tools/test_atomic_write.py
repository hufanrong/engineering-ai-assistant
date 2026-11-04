#!/usr/bin/env python3
"""v0.1.199 回归：atomic_io 是全仓库唯一的 JSON 写盘实现，必须真的原子、可并发。

背景：v0.1.197 修竣工清单、v0.1.198 修扫描索引和上传队列，连着三处同源缺陷，
根因不是某个模块写错，而是「每个模块自己抄一遍落盘逻辑」。v0.1.199 把 69 处
直接 open+json.dump 统一收进 app/atomic_io.py。既然全仓只走这一个实现，
它本身就必须被单独测死 —— 否则一次改错等于全仓一起退回旧缺陷。

本文件守的不是「函数存在」，而是四个会真丢用户数据的性质：
  A. 写盘中途崩溃 → 磁盘上仍是**上一份完整文件**，不是半截 JSON
  B. 并发写同一路径 → 读方永远看到完整文件（不会读到写了一半的）
  C. path_lock 提供的是**同一把**锁（跨模块拿到同一路径必须是同一个对象，
     否则「读—改—写」的调用方各自锁各自的，等于没锁）
  D. sweep_orphan_tmp 只清本程序自己的旧临时文件，绝不碰用户的 .tmp
     和 1 小时内可能正在写的文件

用法：python3 tools/test_atomic_write.py   （退出码 0 = 全过）
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

from app import atomic_io as aio   # noqa: E402

_PASS = [0]
_FAIL = []


def check(name, cond, detail=""):
    if cond:
        _PASS[0] += 1
        print(f"  [PASS] {name}")
    else:
        _FAIL.append(f"{name}  {detail}")
        print(f"  [FAIL] {name}  {detail}")


class _Boom(Exception):
    pass


def _halfway_dump(obj, fp, **kw):
    s = json.dumps(obj, ensure_ascii=False, indent=kw.get("indent") or 2)
    fp.write(s[:len(s) // 2])
    raise _Boom("模拟写盘中途断电")


def part_a_crash_safe(tmp):
    """[A] 写盘中途崩溃：旧文件必须完整保留，不能留半截。"""
    print("\n[A] 写盘中途崩溃 → 旧文件仍完整")
    p = os.path.join(tmp, "a", "state.json")
    aio.write_json(p, {"files": {f"f{i}": f"s{i}" for i in range(3000)}}, indent=2)
    base = os.path.getsize(p)
    base_n = len(json.load(open(p, encoding="utf-8"))["files"])

    real = json.dump
    json.dump = _halfway_dump
    try:
        try:
            aio.write_json(p, {"files": {f"g{i}": "x" for i in range(3000)}}, indent=2)
            crashed = False
        except _Boom:
            crashed = True
    finally:
        json.dump = real

    check("写盘过程确实被打断", crashed)
    check("崩溃后文件大小未被截短", os.path.getsize(p) == base,
          f"原 {base} B → 现 {os.path.getsize(p)} B")
    try:
        got = json.load(open(p, encoding="utf-8"))
        ok_parse, n = True, len(got["files"])
    except Exception as e:                              # noqa: BLE001
        ok_parse, n = False, 0
        print(f"    解析失败：{type(e).__name__}: {str(e)[:60]}")
    check("崩溃后仍是合法 JSON", ok_parse)
    check(f"崩溃后仍读出原来完整的 {base_n} 条", ok_parse and n == base_n, f"实得 {n}")
    check("崩溃后自动清理了临时文件", aio._is_our_tmp("x.0123456789ab.tmp"))
    left = [f for f in os.listdir(os.path.dirname(p)) if f.endswith(".tmp")]
    check("崩溃后目录里没有残留 .tmp", left == [], f"残留 {left}")


def part_b_concurrent(tmp):
    """[B] 并发写同一路径：任何时刻读到的都必须是完整文件。"""
    print("\n[B] 并发写同一路径 → 读方永远看到完整文件")
    p = os.path.join(tmp, "b", "state.json")
    aio.write_json(p, {"files": {}}, indent=2)
    bad = []
    errs = []
    bar = threading.Barrier(10)

    def worker(k):
        try:
            payload = {"files": {f"f{i}": {"who": k} for i in range(800)}}
            bar.wait()
            for _ in range(4):
                aio.write_json(p, payload, indent=2)
                try:
                    with open(p, encoding="utf-8") as f:
                        json.load(f)
                except Exception as e:                 # noqa: BLE001
                    bad.append(f"{type(e).__name__}: {str(e)[:40]}")
        except Exception as e:                         # noqa: BLE001
            errs.append(f"{type(e).__name__}: {str(e)[:50]}")

    ths = [threading.Thread(target=worker, args=(k,)) for k in range(10)]
    [t.start() for t in ths]
    [t.join() for t in ths]

    check("10 线程 × 4 轮并发写：0 错误", not errs, f"{errs[:2]}")
    check("并发期间 0 次读到损坏文件", not bad, f"损坏 {len(bad)} 次：{bad[:2]}")
    fin = json.load(open(p, encoding="utf-8"))
    check("并发结束后是完整 800 条（不是拼凑的半份）",
          len(fin["files"]) == 800, f"实得 {len(fin['files'])}")
    left = [f for f in os.listdir(os.path.dirname(p)) if f.endswith(".tmp")]
    check("并发结束后无残留 .tmp", left == [], f"残留 {left}")


def part_c_lock_identity(tmp):
    """[C] path_lock：同一路径必须是同一个锁对象，否则「读—改—写」等于没锁。"""
    print("\n[C] path_lock 必须按路径唯一")
    p1 = os.path.join(tmp, "c", "state.json")
    p2 = os.path.join(tmp, "c", "..", "c", "state.json")     # 同一个文件的不同写法
    l1 = aio.path_lock(p1)
    l2 = aio.path_lock(p1)
    check("同一路径两次取锁：是同一个对象", l1 is l2, f"{id(l1)} vs {id(l2)}")
    l3 = aio.path_lock(p2)
    check("同一文件的不同写法（含 ..）：仍是同一个锁", l3 is l1,
          f"{id(l3)} vs {id(l1)}")
    other = aio.path_lock(os.path.join(tmp, "c", "other.json"))
    check("不同路径是不同锁（不会互相阻塞）", other is not l1)

    # 用这把锁做一次真并发读改写，验证条目一条不丢
    aio.write_json(p1, {"n": 0})
    lost = []

    def bump(k):
        lk = aio.path_lock(p1)
        with lk:
            d = aio.read_json(p1, {})
            time.sleep(0.01)
            aio.write_json(p1, {"n": d.get("n", 0) + 1})

    ths = [threading.Thread(target=bump, args=(k,)) for k in range(8)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    got = aio.read_json(p1, {}).get("n")
    check("8 线程持同一把锁做读改写：8 次自增全部生效", got == 8, f"实得 {got}")


def part_d_sweep(tmp):
    """[D] sweep_orphan_tmp：只清本程序自己的旧临时文件。"""
    print("\n[D] sweep_orphan_tmp 清理边界")
    root = os.path.join(tmp, "d")
    sub = os.path.join(root, "projects", "p1")
    os.makedirs(sub, exist_ok=True)

    def mk(name, age):
        p = os.path.join(sub, name)
        open(p, "w").write("{}")
        if age:
            os.utime(p, (time.time() - age, ) * 2)
        return p

    old_mk = mk("index.9kerptd6.tmp", 7200)       # 旧 mkstemp 遗留
    old_uu = mk("index.0123456789ab.tmp", 7200)   # write_json 命名
    new_mk = mk("index.abcdef12.tmp", 0)          # 1 小时内，可能在写
    new_uu = mk("meta.0123456789ab.tmp", 0)
    user1 = mk("我的备份.tmp", 7200)               # 用户自己的
    user2 = mk("报告.20261104.tmp", 7200)
    user3 = mk("draft.tmp", 7200)

    n = aio.sweep_orphan_tmp(root)
    check("清掉了 2 个孤儿临时文件", n == 2, f"实得 {n}")
    check("旧 mkstemp 遗留已清除", not os.path.exists(old_mk))
    check("旧 write_json 命名已清除", not os.path.exists(old_uu))
    check("1 小时内的新临时文件保留（可能在写）", os.path.exists(new_mk))
    check("1 小时内的新 uuid 临时文件保留", os.path.exists(new_uu))
    check("用户的 我的备份.tmp 保留", os.path.exists(user1))
    check("用户的 报告.20261104.tmp 保留", os.path.exists(user2))
    check("用户的 draft.tmp 保留", os.path.exists(user3))


def part_e_indent_preserved(tmp):
    """[E] 替换实现不能悄悄改变落盘格式（indent 语义必须与原来一致）。"""
    print("\n[E] indent 语义与原来一致")
    p = os.path.join(tmp, "e", "i2.json")
    aio.write_json(p, {"a": 1, "b": 2}, indent=2)
    txt = open(p, encoding="utf-8").read()
    check("indent=2 落盘带两空格缩进", '\n  "a"' in txt, f"实得 {txt[:40]!r}")

    p1 = os.path.join(tmp, "e", "i1.json")
    aio.write_json(p1, {"a": 1, "b": 2}, indent=1)
    t1 = open(p1, encoding="utf-8").read()
    check("indent=1 落盘带一空格缩进", '\n "a"' in t1, f"实得 {t1[:40]!r}")

    p0 = os.path.join(tmp, "e", "i0.json")
    aio.write_json(p0, {"a": 1, "b": 2}, indent=None)
    t0 = open(p0, encoding="utf-8").read()
    check("indent=None 落盘为紧凑单行（与原 json.dump 一致）", "\n" not in t0.strip(),
          f"实得 {t0[:40]!r}")

    # 中文不能被转义成 \\u
    pc = os.path.join(tmp, "e", "cn.json")
    aio.write_json(pc, {"车间": "磨浮车间"}, indent=2)
    check("中文按 ensure_ascii=False 原样落盘",
          "磨浮车间" in open(pc, encoding="utf-8").read())


def part_f_read_logged(tmp):
    """[F] read_json 读损坏文件必须留痕，不能无声兜底。"""
    print("\n[F] read_json 读损坏文件要留痕")
    p = os.path.join(tmp, "f", "bad.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write('{"a": 1, "b": ')      # 半截 JSON
    import io
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        got = aio.read_json(p, {"default": True})
    finally:
        sys.stdout = real
    check("损坏文件返回传入的默认值", got == {"default": True}, f"实得 {got}")
    check("损坏时打印了留痕", "读取失败" in buf.getvalue(), f"实得 {buf.getvalue()!r}")

    out = aio.read_json(os.path.join(tmp, "f", "nope.json"), None)
    check("文件不存在时安静返回默认值（不刷日志）", out is None)


def main():
    tmp = tempfile.mkdtemp(prefix="atomic_w_")
    print("=" * 62)
    print("v0.1.199 回归：atomic_io 原子写 / 锁唯一性 / 孤儿清扫")
    print("=" * 62)
    try:
        part_a_crash_safe(tmp)
        part_b_concurrent(tmp)
        part_c_lock_identity(tmp)
        part_d_sweep(tmp)
        part_e_indent_preserved(tmp)
        part_f_read_logged(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "-" * 62)
    print(f"结果：通过 {_PASS[0]} / 失败 {len(_FAIL)} / 共 {_PASS[0] + len(_FAIL)}")
    for f in _FAIL:
        print(f"  FAIL: {f}")
    sys.exit(0 if not _FAIL else 1)


if __name__ == "__main__":
    main()
