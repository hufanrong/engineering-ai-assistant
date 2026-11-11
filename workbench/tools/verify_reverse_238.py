# -*- coding: utf-8 -*-
"""反向验证：把 v0.1.238 的四处修复逐一改回旧写法，确认 test_relations_gate.py
对应的断言变红，且红的理由对（不是崩在别处、不是被别的断言挡掉）。

每轮：备份 → 打补丁 → 跑测试 → 记录 FAIL 项集合 → 还原 → 校验还原一致。
"""
import os
import re
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(BASE, "tools", "test_relations_gate.py")
BACK = "/tmp/keep238"

CASES = []


def case(name, rel, old, new, expect_red):
    CASES.append({"name": name, "rel": rel, "old": old, "new": new, "expect": expect_red})


# ---- 1) project_manager：还原硬编码安装目录兜底 ----
case(
    "A 还原 get_project_data_dir 硬编码安装目录",
    "app/project_manager.py",
    """        return _config.DATA_DIR""",
    """        default_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data"
        )
        return default_dir""",
    ["R6"],
)

# ---- 2) relations：去掉设备级出口闸门 ----
case(
    "B 去掉 _veto_device_hints 出口闸门",
    "app/relations.py",
    """    return _veto_device_hints(out, data_dir)""",
    """    return out""",
    ["R2", "R2b", "R3"],
)

# ---- 3) device_workshop：去掉 assign_device 的台账闸门 ----
case(
    "C 去掉 assign_device 台账闸门",
    "app/device_workshop.py",
    """    if source != "manual":
        try:
            from . import workshop_assign as _wa""",
    """    if False:
        try:
            from . import workshop_assign as _wa""",
    ["R4b", "R4c"],
)

# ---- 4) workshop_assign._dir_for：还原「隔离优先」顺序 ----
case(
    "D 还原 _dir_for 隔离优先于显式 data_dir",
    "app/workshop_assign.py",
    """    if data_dir:
        return data_dir
    if _ISOLATED_DIR:
        return _ISOLATED_DIR""",
    """    if _ISOLATED_DIR:
        return _ISOLATED_DIR
    if data_dir:
        return data_dir""",
    ["R2", "R3", "R4b"],
)

# ---- 5) device_workshop：还原 _store_path 不认 data_dir ----
case(
    "E 还原 _store_path 忽略 data_dir/隔离",
    "app/device_workshop.py",
    """    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "device_workshop.json")
    if _ISOLATED_DIR:
        os.makedirs(_ISOLATED_DIR, exist_ok=True)
        return os.path.join(_ISOLATED_DIR, "device_workshop.json")
    try:""",
    """    if False:
        pass
    try:""",
    ["R6c", "R6d"],
)

# ---- 6) device_workshop.rebuild_from_excel：抽取器不接力 data_dir ----
# 这处的缺陷方向是「干净名字被别处的台账误裁」（与 B/C 的脏名字漏入相反）。
case(
    "F 还原 rebuild_from_excel 抽取器不接力 data_dir",
    "app/device_workshop.py",
    """                eqs = _extract(d, data_dir)""",
    """                eqs = _extract(d)""",
    ["R8b"],
)

FAIL_NAME = re.compile(r"^  \[FAIL\] (.+?):")


def run_test():
    p = subprocess.run([sys.executable, TOOLS], cwd=BASE, capture_output=True, text=True)
    reds = []
    for line in p.stdout.splitlines():
        m = FAIL_NAME.match(line)
        if m:
            reds.append(m.group(1))
    return p.returncode, reds, p.stdout


def main():
    print("=== 反向验证：每处修复改回旧写法后必须变红 ===")
    all_ok = True
    for c in CASES:
        path = os.path.join(BASE, c["rel"])
        orig = open(path, encoding="utf-8").read()
        if c["old"] not in orig:
            print(f"[SKIP] {c['name']}: 锚点没匹配上（patch 本身失效）")
            all_ok = False
            continue
        patched = orig.replace(c["old"], c["new"], 1)
        if patched == orig:
            print(f"[SKIP] {c['name']}: 替换没有生效")
            all_ok = False
            continue
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(patched)
            rc, reds, out = run_test()
            hit = [e for e in c["expect"] if any(e in r for r in reds)]
            miss = [e for e in c["expect"] if not (any(e in r for r in reds))]
            ok = rc != 0 and not miss and bool(hit)
            print(f"[{'PASS' if ok else 'FAIL'}] {c['name']}: rc={rc} 变红={reds}")
            if not ok:
                print(f"        期望变红 {c['expect']}，缺 {miss}")
                print(out[-1600:])
                all_ok = False
        finally:
            with open(path, "w", encoding="utf-8") as f:
                f.write(orig)
            same = open(path, encoding="utf-8").read() == orig
            if not same:
                print(f"[ERROR] {c['rel']} 还原失败！")
                all_ok = False

    # 还原后再跑一次，必须回到全绿（断言数不写死，避免加断言就得改这里）
    rc, reds, out = run_test()
    green = rc == 0 and not reds
    print(f"[{'PASS' if green else 'FAIL'}] 收尾 全部还原后回到全绿: rc={rc} 红={reds}")
    if not green:
        all_ok = False
        print(out[-2000:])
    print("===== 反向验证 " + ("全部通过" if all_ok else "有问题") + " =====")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
