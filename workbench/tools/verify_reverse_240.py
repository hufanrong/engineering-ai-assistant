#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.1.240 反向验证：把两处修复分别改回旧写法，确认测试变红**且红得对**。

规则（沿用 v0.1.238/239 的教训）：
  · 「N 项全过」不足以证明测试有效，必须有一条判据在修复被还原时失败；
  · 红的原因必须是这条修复本身，不是崩在别处；
  · 第一次写这个脚本时把 old/new 方向搞反了（把「修复」又装回去），
    于是两个用例都「rc=0 全绿」—— 那不是测试有效，是脚本没生效。
    现在语义固定为：case(标题, 文件, **源码里现在存在**的片段, 替换成的旧写法)。

用例：
  A) delete_project 删不干净 → 退回 v0.1.239「只报错」分支
     期望变红：S2 / S3 / S4 / S5 / S7 / S10
  B) project_backup 备份目录改回 `__file__` 写死安装目录
     期望变红：S14（真实 data/backups 多出 .fgbak）

跑法：python tools/verify_reverse_240.py
"""
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PM = os.path.join(ROOT, "app", "project_manager.py")
PB = os.path.join(ROOT, "app", "project_backup.py")
TEST = os.path.join(HERE, "test_delete_sweep.py")

# 反向验证会把备份写进真实目录（那正是 B 要证明的缺陷），所以每次跑完必须清掉
# 本轮自造项目产生的 .fgbak —— 名字严格匹配，绝不误删用户资产。
_REAL_BAK = os.path.join(ROOT, "data", "backups")
_BAK_MARK = ("待删项目", "摘除会失败的项目", "能删干净的项目")

CASES = []


def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def _clean_real_backups():
    """删掉本轮自测写进真实 backups 的包（严格按项目名匹配）。"""
    n = 0
    for p in glob.glob(os.path.join(_REAL_BAK, "*.fgbak")):
        base = os.path.basename(p)
        if any(m in base for m in _BAK_MARK):
            try:
                os.remove(p)
                n += 1
            except Exception:
                pass
    return n


def run_test():
    p = subprocess.run([sys.executable, TEST], cwd=ROOT,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=180)
    out = p.stdout
    reds = re.findall(r"\[FAIL\] (\S+)", out)
    passed = len(re.findall(r"\[PASS\] \S+", out))
    return p.returncode, passed, reds, out


def case(title, path, fixed_snippet, broken_snippet, expect_red):
    """把源码里**现在存在**的 fixed_snippet 换成 broken_snippet（=还原修复）。"""
    src = read(path)
    if fixed_snippet not in src:
        CASES.append({"title": title, "ok": False,
                      "detail": f"找不到修复片段（源码可能已变）：{fixed_snippet[:70]!r}"})
        print(f"[FAIL] {title}: 找不到修复片段，无法还原")
        print(f"        片段={fixed_snippet[:70]!r}")
        return
    backup = src
    try:
        write(path, src.replace(fixed_snippet, broken_snippet, 1))
        rc, passed, reds, out = run_test()
    finally:
        write(path, backup)
        _clean_real_backups()
    hit = [r for r in reds if r in expect_red]
    missing = [r for r in expect_red if r not in reds]
    ok = rc != 0 and bool(hit) and not missing
    CASES.append({"title": title, "ok": ok,
                  "detail": f"rc={rc} 通过={passed} 红={reds} 命中={hit} 缺={missing}"})
    print(f"[{'PASS' if ok else 'FAIL'}] {title}")
    print(f"        rc={rc} 通过={passed} 红={reds}")
    if missing:
        print(f"        应红未红：{missing}")


def main():
    print("=" * 78)
    print("v0.1.240 反向验证")
    print("=" * 78)

    _clean_real_backups()
    rc0, p0, red0, _ = run_test()
    print(f"[基准] 修复在位：rc={rc0} 通过={p0} 红={red0}")
    if rc0 != 0:
        print("基准不绿，反向验证无意义 —— 先修测试")
        _clean_real_backups()
        return 1

    # ---- A) 删不干净时不摘除，退回「只报错」 ----
    fixed_a = """        _detached = False
        try:
            _detached = _detach_project_meta(project_id)
        except Exception:  # noqa: BLE001
            _detached = False"""
    broken_a = """        _detached = False
        try:
            pass
        except Exception:  # noqa: BLE001
            _detached = False"""
    case("A 还原 delete_project：删不干净时只报错、不摘除不登记",
         PM, fixed_a, broken_a, ["S2", "S3", "S4", "S5", "S7", "S10"])

    # ---- B) 备份目录改回 __file__ 写死安装目录 ----
    # 只替换 return 那两行（最短且唯一），不碰 docstring（转义容易对不上）
    fixed_b = """    from . import config as _config
    return os.path.join(_config.DATA_DIR, "backups")"""
    broken_b = """    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "backups")"""
    case("B 还原 project_backup：备份目录写死安装目录（不跟随 DATA_DIR）",
         PB, fixed_b, broken_b, ["S14"])

    # ---- 收尾 ----
    _clean_real_backups()
    rc1, p1, red1, _ = run_test()
    green = (rc1 == 0 and not red1)
    print(f"[{'PASS' if green else 'FAIL'}] 收尾 全部还原后回到全绿: rc={rc1} 通过={p1} 红={red1}")

    bad = [c for c in CASES if not c["ok"]]
    print()
    print("=" * 78)
    if bad or not green:
        print(f"反向验证未通过：{len(bad)} 个用例无效 / 收尾不绿")
        return 1
    print("===== 反向验证 全部通过 =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
