#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.1.180 回归测试：单位字段 + 通用表承接 + 材料车间跳过。

为什么单独写：这三条改动都会**改变整卷产出数量**，只看「跑通没报错」看不出对错。
每条用例都针对一个具体的错误实现会被判失败的判别点：

  T1 单位必须从台账落进设备索引 —— 旧实现在 extract_all_equipment 就没把单位带出来，
     判据：合并后设备的 unit 非空，且尾矿库全车间单位不是「台」。
  T2 未声明类型的设备必须被通用表承接 —— 旧实现在借用分支加了 `not queue` 前置，
     只要车间有任一声明类型设备在场，未覆盖设备一台都借不进，filled_count 恒为 0。
     判据：同一份 9 表模板下，只给「泵」「搅拌设备」两台设备，filled_count 必须 == 2。
  T3 每台设备只出一份 —— 「通用表承接」最容易引入的错误是按指纹重复出表。
     判据：3 台未覆盖设备 + 模板内 3 张同指纹表 → filled_count 必须恰好 == 3，不是 9。
  T4 材料车间不产设备记录 —— 尾矿库 4 行全是土工膜/HDPE 管（单位 m2/米），
     判据：这类车间应被标识为材料车间，不得进入设备出表链路。

跑法：python tools/test_ledger_units.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.equipment_merge as em
import app.supervision_templates as st

RESULTS = []


def check(name, cond, detail):
    RESULTS.append({"name": name, "passed": bool(cond), "detail": detail})
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}: {detail}")


TEMPLATE = os.path.join(st.BUILTIN_DIR, "监理模板_设备安装检查记录.docx")


def t1_units():
    """单位字段必须能从台账行一路带到合并后的设备条目。"""
    rows = [
        {"tag": "", "name": "HDPE土工膜", "model": "", "spec": "光面，1.5mm厚",
         "quantity": "1", "workshop": "尾矿库", "source_file": "台账.xlsx",
         "source_type": "excel", "version_ts": "", "row_index": 1, "unit": "m2",
         "fields": {}},
        {"tag": "", "name": "渣浆泵", "model": "TZJK-200MN-570TD", "spec": "",
         "quantity": "1", "workshop": "尾矿库", "source_file": "台账.xlsx",
         "source_type": "excel", "version_ts": "", "row_index": 2, "unit": "台",
         "fields": {}},
    ]
    merged = em.merge_equipment_list(rows)["merged"]
    units = {m.get("name"): m.get("unit", "") for m in merged}
    ok = units.get("HDPE土工膜") == "m2" and units.get("渣浆泵") == "台"
    check("T1 单位进入合并条目", ok, f"units={units}")


def t2_generic_carryover():
    """模板未声明类型的设备，必须被共用表承接。"""
    fill = {"单位工程": "测试", "车间": "总图", "分部工程": "设备安装"}
    devs = [{"tag": "", "name": "卧式离心泵", "model": "DFSS250-4/4", "dev_type": "泵"},
            {"tag": "", "name": "搅拌机", "model": "", "dev_type": "搅拌设备"}]
    groups = {}
    for d in devs:
        groups.setdefault(d["dev_type"], []).append(d)
    r = st._render_docx_by_workshop(TEMPLATE, fill, groups, "总图",
                                    logical_name="监理模板_设备安装检查记录")
    check("T2 通用表承接未声明类型", r.get("filled_count") == 2,
          f"filled_count={r.get('filled_count')} fallback={len(r.get('type_fallback') or [])}")


def t3_no_duplicate():
    """承接时每台设备只能出一份，不能按表格指纹重复。"""
    fill = {"单位工程": "测试", "车间": "总图", "分部工程": "设备安装"}
    devs = [{"tag": "", "name": "卧式离心泵A", "model": "X1", "dev_type": "泵"},
            {"tag": "", "name": "卧式离心泵B", "model": "X2", "dev_type": "泵"},
            {"tag": "", "name": "搅拌机C", "model": "X3", "dev_type": "搅拌设备"}]
    groups = {}
    for d in devs:
        groups.setdefault(d["dev_type"], []).append(d)
    r = st._render_docx_by_workshop(TEMPLATE, fill, groups, "总图",
                                    logical_name="监理模板_设备安装检查记录")
    check("T3 每台设备只出一份", r.get("filled_count") == 3,
          f"filled_count={r.get('filled_count')}（应为 3，重复出表会到 9/18）")


def t4_material_workshop():
    """材料车间（单位无「台/套/个/组」）应被判为材料车间。"""
    from app import supervision_integration as si
    fn = getattr(si, "is_material_workshop", None)
    if not fn:
        check("T4 材料车间判定函数存在", False, "supervision_integration.is_material_workshop 缺失")
        return
    check("T4 尾矿库判为材料车间",
          fn([{"name": "HDPE土工膜", "unit": "m2"}, {"name": "HDPE管", "unit": "米"}]),
          "4 行全为 m2/米")
    check("T4 总图不判为材料车间",
          not fn([{"name": "电动单梁起重机", "unit": "台"},
                  {"name": "卧式离心泵", "unit": "台"}]),
          "8 台设备单位=台")


def t5_registry_per_project():
    """登记表必须按 project_id 读，不能读「当前项目」的。

    实测事故（v0.1.180 修）：项目 A 传了真实登记表（设备安装册 3 项），
    但「当前项目」是登记表只有 3 项最小表的项目 B。
    generate_volume(A) 内部却走 _reg_file()（= 读当前项目 B），
    结果 A 的册名/条目数/归集数全被 B 的登记表覆盖 —— 跨项目串数据。
    判据：给两个项目放不同登记表，按 project_id=A 读到 A 的条目，按 B 读到 B 的。
    """
    import app.supervision_integration as si
    import app.project_manager as pm
    tmp = tempfile.mkdtemp(prefix="fg_reg_")
    root = os.path.join(tmp, "projects")
    os.makedirs(root, exist_ok=True)
    regA = [{"册": "设备安装", "序号": "1", "名称": "设备开箱检验记录", "分类": "A"},
            {"册": "设备安装", "序号": "2", "名称": "单机无负荷试运转记录", "分类": "A"}]
    regB = [{"册": "第一册", "序号": "1", "名称": "设备开箱检查记录", "分类": "A"}]
    for pid, reg in (("projA", regA), ("projB", regB)):
        os.makedirs(os.path.join(root, pid), exist_ok=True)
        with open(os.path.join(root, pid, "supervision_registry.json"), "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False)
    _old = pm.PROJECTS_ROOT
    pm.PROJECTS_ROOT = root
    try:
        a = si.load_registry("projA")
        b = si.load_registry("projB")
        ok = (len(a) == 2 and a[0].get("名称") == "设备开箱检验记录"
              and len(b) == 1 and b[0].get("名称") == "设备开箱检查记录")
        check("T5 登记表按项目隔离", ok,
              f"A={len(a)}条/首条={a[0].get('名称') if a else None} "
              f"B={len(b)}条/首条={b[0].get('名称') if b else None}")
    finally:
        pm.PROJECTS_ROOT = _old


def t6_todo_marks_generic():
    """待办清单必须逐条标出「使用通用表」，人工复核才找得到。

    用户决策原话：「允许通用表承接，每台设备只出一份，并在待办清单里
    标注「使用通用表」供人工复核」。判据：_render_todo 收到 type_fallback 时，
    文本里必须出现「使用通用表」，且设备名逐台列出。
    """
    import app.supervision_integration as si
    raw = [{"设备类型": "泵", "设备": "卧式离心泵", "借用表": "胶带输送机",
            "方式": "通用表承接"},
           {"设备类型": "搅拌设备", "设备": "搅拌槽", "借用表": "胶带输送机",
            "方式": "通用表承接"}]
    fb = [{"序号": "1", "名称": "设备安装检查记录", "借用情况": raw}]
    txt = si._render_todo([], [], [], [], fb, workshop="总图")
    has_phrase = "使用通用表" in txt
    has_devs = "卧式离心泵" in txt and "搅拌槽" in txt
    check("T6 待办标注使用通用表", has_phrase and has_devs,
          f"含「使用通用表」={has_phrase} 含设备名={has_devs}")


def t7_carry_with_same_type_present():
    """车间**同时**有承接表自身类型的设备时，未声明类型的设备也必须被承接。

    这是 T2 漏掉的真实场景：T2 只给了未覆盖类型（泵/搅拌设备），`not queue` 恰好成立。
    真实台账里 19 个车间中多数都有「胶带输送机」—— 而承接表本身就是胶带输送机表，
    于是 queue 非空 → 旧的 `not queue` 前置把承接整段跳过 → 大量设备落空。
    实测：脱水车间 19 台落空 15、重介质选矿车间 39 台落空 28。
    判据：给「胶带输送机 2 台」（承接表自身类型）+「泵 1 台」（未声明类型），
    泵必须被承接进来，且总 filled_count == 3（不多不少）。
    """
    import app.supervision_templates as st
    groups = {
        "胶带输送机": [{"name": "1#胶带输送机", "dev_type": "胶带输送机"},
                    {"name": "2#胶带输送机", "dev_type": "胶带输送机"}],
        "泵": [{"name": "卧式离心泵", "dev_type": "泵"}],
    }
    r = st._render_docx_by_workshop(TEMPLATE, {"车间": "脱水车间"}, groups, "脱水车间",
                                    logical_name="设备安装检查记录")
    named = [c.get("名称") for c in (r.get("covered_devices") or [])]
    ok = (r.get("filled_count") == 3 and "卧式离心泵" in named
          and len(r.get("uncovered_devices") or []) == 0)
    check("T7 同类型在场仍承接", ok,
          f"filled={r.get('filled_count')} 覆盖={named} "
          f"未覆盖={len(r.get('uncovered_devices') or [])}")


def main():
    print("=== v0.1.180 回归测试 ===")
    t1_units()
    t2_generic_carryover()
    t3_no_duplicate()
    t4_material_workshop()
    t5_registry_per_project()
    t6_todo_marks_generic()
    t7_carry_with_same_type_present()
    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"\n结果：通过 {passed} / 失败 {total - passed} / 共 {total}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_ledger_units_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"summary": {"passed": passed, "failed": total - passed}, "items": RESULTS},
                  f, ensure_ascii=False, indent=1)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
