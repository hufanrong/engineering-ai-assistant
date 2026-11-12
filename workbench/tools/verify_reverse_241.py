#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.1.241 反向验证：把身份键修复改回旧写法，确认测试变红**且红得对**。

用例：
  A) merge 结果不写 identity_key（退回「只有 canonical_tag 一层」）
     期望变红：I2（跨源文件身份不同）、I4、I6b
  B) 把身份键当合并键用（这正是用户答案的字面读法，也是本轮的陷阱）
     期望变红：I2/I3（实例被合并、丢台）、I5a（真实项目不再是 228）
  C) identity_key 不做 NFKC / 全角空格规范化
     期望变红：I8

赢法：反向验证必须让「修复被还原」这件事真的发生，且红的原因指向该修复本身。
第一次写这类脚本时曾把 old/new 方向搞反（把修复又装回去），两个用例都「全绿」——
那不是测试有效，是脚本没生效。所以这里语义固定为：
    case(标题, 文件, **源码里现在存在**的片段, 替换成的旧写法, 期望变红的断言名)

跑法：python tools/verify_reverse_241.py
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

EM = os.path.join(ROOT, "app", "equipment_merge.py")
TEST = os.path.join(HERE, "test_device_identity.py")

CASES = []


def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def run_test():
    p = subprocess.run([sys.executable, TEST], cwd=ROOT,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=180)
    reds = re.findall(r"\[FAIL\] (\S+)", p.stdout)
    passed = len(re.findall(r"\[PASS\] \S+", p.stdout))
    return p.returncode, passed, reds, p.stdout


def case(title, path, fixed, broken, expect_red):
    src = read(path)
    if fixed not in src:
        CASES.append({"title": title, "ok": False,
                      "detail": f"找不到修复片段：{fixed[:70]!r}"})
        print(f"[FAIL] {title}: 找不到修复片段，无法还原")
        print(f"        片段={fixed[:70]!r}")
        return
    try:
        write(path, src.replace(fixed, broken, 1))
        rc, passed, reds, out = run_test()
    finally:
        write(path, src)
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
    print("v0.1.241 反向验证")
    print("=" * 78)

    rc0, p0, red0, _ = run_test()
    print(f"[基准] 修复在位：rc={rc0} 通过={p0} 红={red0}")
    if rc0 != 0:
        print("基准不绿，反向验证无意义")
        return 1

    # ---- A) 不写 identity_key（只剩实例键一层） ----
    fixed_a = """            merged[tag] = {
                "canonical_tag": tag,
                # v0.1.241：身份键与实例键并列落库。身份用来跨文件认出同一台设备，
                # 实例键保证一台一行不丢设备（见 identity_key() 处的长注释）。
                "identity_key": identity_key(eq.get("name", ""),
                                             eq.get("workshop", ""),
                                             eq.get("model", "")),"""
    broken_a = """            merged[tag] = {
                "canonical_tag": tag,"""
    # 期望红名单里**故意不含 I6b**：find_by_identity 在索引缺 identity_key 时
    # 会按 name/workshop/model 现算兜底（这是有意的兼容设计，否则历史索引全都
    # 查不到），所以「不写该字段」不会让 I6b 变红。第一版把 I6b 列进来，
    # 结果用例被判无效 —— 那是脚本对判据理解错了，不是测试无效。
    # A 的真实判别力在 I2（身份键必须非空且唯一）与 I4（跨车间不许同身份）。
    case("A 还原：merge 结果不写 identity_key（只剩实例键）",
         EM, fixed_a, broken_a, ["I2", "I4"])

    # ---- B) 把身份键当合并键（用户答案的字面读法 = 本轮陷阱） ----
    # 还原成「tag = 车间|名称|型号」：这会让跨文件同名同型号的多行并成一台，
    # 也正是实测「少 26 台」的写法。
    fixed_b = """            tag = (f"{PLACEHOLDER_TAG_PREFIX}"
                   f"{eq.get('name', '')}|{eq.get('workshop', '')}|{eq.get('model', '')}"
                   f"|{eq.get('spec', '')}|{eq.get('source_file', '')}"
                   f"|{eq.get('row_index', '')}")"""
    broken_b = """            tag = identity_key(eq.get('name', ''), eq.get('workshop', ''),
                               eq.get('model', ''))"""
    case("B 还原：把身份键当合并键用（丢失设备实例）",
         EM, fixed_b, broken_b, ["I3a", "I2", "I6b"])

    # ---- C) 身份键不做规范化 ----
    fixed_c = """    def _n(s):
        s = unicodedata.normalize("NFKC", str(s or ""))
        s = s.replace("\\u3000", " ")
        return " ".join(s.split()).strip()"""
    broken_c = """    def _n(s):
        return str(s or "")"""
    case("C 还原：identity_key 不做 NFKC/全角空格规范化",
         EM, fixed_c, broken_c, ["I8"])

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
