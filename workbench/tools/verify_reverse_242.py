# -*- coding: utf-8 -*-
"""v0.1.242 反向验证：把每处修复改回旧写法，确认对应断言真的变红。

不做这步就只是「N 项全过」，证明不了断言有效 —— 前面几轮踩过的假红/假守卫
（负向断言在空结果下恒真、断言写错对象）都是靠这一步才发现的。
"""
import io
import os
import subprocess
import sys

WB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EM = os.path.join(WB, "app", "equipment_merge.py")
REL = os.path.join(WB, "app", "relations.py")
TEST = os.path.join(WB, "tools", "test_device_identity_242.py")


def run_test():
    p = subprocess.run([sys.executable, TEST], cwd=WB, capture_output=True, text=True)
    out = p.stdout + p.stderr
    failed = [ln.strip() for ln in out.splitlines() if "[FAIL]" in ln]
    names = []
    for ln in failed:
        n = ln.replace("[FAIL]", "").strip()
        names.append(n.split()[0] if n else "?")
    return p.returncode, names


def case(title, path, fixed, broken, expect_red):
    src = io.open(path, encoding="utf-8").read()
    assert fixed in src, f"[{title}] 找不到要被替换的现有代码，案例失效"
    io.open(path, "w", encoding="utf-8").write(src.replace(fixed, broken, 1))
    try:
        rc, reds = run_test()
    finally:
        io.open(path, "w", encoding="utf-8").write(src)
    hit = [n for n in expect_red if n in reds]
    ok = bool(rc != 0 and hit)
    print(f"[{'OK  ' if ok else 'INVALID'}] {title}  rc={rc} 变红={reds}")
    print(f"        期望变红 {expect_red} / 命中 {hit}")
    return ok


def main():
    all_ok = True

    # A 空名仍然拼出身份 → N1a / N1a2 / N1b 必须红
    all_ok &= case(
        "A 空名照旧拼身份（去掉空名短路）", EM,
        '''    _name = _n(name)
    if not _name:
        return ""
    return "|".join([
        _n(workshop),
        _name,
        _n(model).upper(),
    ])''',
        '''    return "|".join([
        _n(workshop),
        _n(name),
        _n(model).upper(),
    ])''',
        ["N1a", "N1a2", "N1b"],
    )

    # B 空身份可以被查出来 → N2 必须红
    all_ok &= case(
        "B find_by_identity 不挡空身份", EM,
        '''    key = identity_key(name, workshop, model)
    if not key:
        # v0.1.242：空身份（名称缺失）不做任何匹配。否则传空名会把所有空名行
        # 当成「同一台设备」一起返回 —— 凭空断言比查不到更糟。
        return []''',
        '''    key = identity_key(name, workshop, model)''',
        ["N2"],
    )

    # C 数量跨单位相加 → N4f 必须红（并把 N4e 一起带红）
    all_ok &= case(
        "C 数量跨单位直接相加（回到单值 total）", EM,
        '''            "total_qty": (list(unit_sums.values())[0] if len(unit_sums) == 1 else None),
            "unit": (list(unit_sums)[0] if len(unit_sums) == 1 else None),
            "qty_by_unit": unit_sums,''',
        '''            "total_qty": sum(by_unit.values()),
            "unit": (list(unit_sums)[0] if len(unit_sums) == 1 else None),
            "qty_by_unit": unit_sums,''',
        ["N4f"],
    )

    # D 目录解析回退到全局 data → N4a / N4b 必须红（真实数据在 projects/<pid>）
    all_ok &= case(
        "D _index_dir 忽略当前项目（回落到 config.DATA_DIR）", EM,
        '''    if data_dir:
        return data_dir
    try:
        from . import project_manager as _pm''',
        '''    if data_dir:
        return data_dir
    return config.DATA_DIR
    try:
        from . import project_manager as _pm''',
        ["N4a", "N4b"],
    )

    # E relations 不接线 → N6a/N6b 必须红
    all_ok &= case(
        "E relations 不登记身份冲突（只写函数不接线）", REL,
        '''        for _c in _em.identity_conflicts(ddir):''',
        '''        for _c in []:''',
        ["N6a"],
    )

    # F layout 不补齐 → N7a / N7b 必须红
    all_ok &= case(
        "F 合并路径不补 layout（回到只补 devices/workshops）", REL,
        '        layout_list.append({\n            "tag": tag,',
        '        _skip_layout = True\n        if _skip_layout:\n            continue\n        layout_list.append({\n            "tag": tag,',
        ["N7a", "N7b"],
    )

    # 还原后必须全绿（否则说明恢复没做干净）
    rc, reds = run_test()
    print(f"\n[还原后] rc={rc} 红={reds}")
    if rc != 0:
        all_ok = False

    print("\n===== 反向验证 " + ("全部通过" if all_ok else "存在问题") + " =====")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
