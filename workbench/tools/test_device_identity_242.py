#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.1.242 回归：身份键的两个「凭空断言」边界。

v0.1.241 落了 identity_key（车间|名称|型号）。在真实项目 322fef90 复核时
发现两处会把「不知道」说成「是同一台」的写法：

  N1 空名行会伪造身份：228 台里 13 行名称为空（台账合并单元格/换行造成），
     按「车间||型号」拼键会让同车间空名行落到同一身份上 —— 凭空断言
     「这两台是同一台」。名称是身份的必要条件，空名必须返回空身份。

  N2 空身份可以被「查」出来：find_by_identity(name="") 若不挡，
     会把所有空名行当同一台设备一起返回。

  N3 用户决策后半句「仍冲突则进人工确认」未落地：型号为空且同车间同名称
     多实例时（实测 14 组 / 39 台），既分不开也合不掉，必须登记到
     human_confirm，由人决定是合并还是补型号。

判据：

  N1a 空名 → 空身份（不论车间、型号怎么给）
  N1b 空名空型号的两行不会被算成同一身份（真实数据里存在这种行）
  N2  find_by_identity 传空名返回 []（不能返回一堆）
  N3a identity_conflicts 只报「型号为空且多实例」，型号齐的不报
  N3b 冲突登记里带齐 tags / 数量合计 / 车间 / 名称
  N3c 名称为空的行进 nameless_devices，不混进 identity_conflicts
  N4  真实数据：身份冲突 14 组 / 涉及 39 台 / 空名 13 行（现状记录）
  N5  真实 data/ 未被污染（内容全等）
  N6  relations 的 human_confirm 里真的出现这两类登记（防「只写函数不接线」）

跑法：python3 tools/test_device_identity_242.py
"""
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.config as config  # noqa: E402

_REAL_DATA_DIR = config.DATA_DIR


def _snap(root):
    s = {}
    if not os.path.isdir(root):
        return s
    for dp, dn, fn in os.walk(root):
        rel = os.path.relpath(dp, root)
        if rel == "projects" or rel.startswith("projects" + os.sep):
            dn[:] = []
            continue
        for f in fn:
            if os.path.join(rel, f) in ("telemetry/requests.jsonl", "workbench.log"):
                continue
            p = os.path.join(dp, f)
            try:
                s[os.path.relpath(p, root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
            except Exception:
                s[os.path.relpath(p, root)] = "<unreadable>"
    return s


_REAL_BEFORE = _snap(_REAL_DATA_DIR)

from app import equipment_merge as em  # noqa: E402

RESULTS = []


def check(name, expect, actual, cond, note=""):
    RESULTS.append({"name": name, "passed": bool(cond)})
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    print(f"        期望={expect!r} 实际={actual!r}")
    if note:
        print(f"        {note}")


def _write_index(tmp, devices):
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"devices": devices}, f, ensure_ascii=False)


def main():
    print("=" * 78)
    print("v0.1.242 身份键边界：空名不伪造身份 + 仍冲突进人工确认")
    print("=" * 78)

    # ---------- N1 空名不伪造身份 ----------
    check("N1a 空名 → 空身份（车间/型号给了也不拼）", "", em.identity_key("", "重选车间", "8/6E-AH"),
          em.identity_key("", "重选车间", "8/6E-AH") == "")
    check("N1a2 只有空白字符也算空名", "", em.identity_key("   ", "重选车间", "X1"),
          em.identity_key("   ", "重选车间", "X1") == "",
          "台账里空格/全角空格占位很常见，不能当有效名称")

    empty_rows = [
        {"tag": "t1", "name": "", "workshop": "粗碎站", "model": ""},
        {"tag": "t2", "name": "", "workshop": "粗碎站", "model": ""},
    ]
    k = {em.identity_key(r["name"], r["workshop"], r["model"]) for r in empty_rows}
    check("N1b 同车间两行都空名空型号 → 不落到同一身份", {""}, k, k == {""},
          "两行都返回空身份，即「都认不出」，而不是「都是同一台」。"
          "若这里返回同一个非空键，就是凭空断言两台是同一台")

    # ---------- N2 空身份查不出来 ----------
    tmp = os.path.join(tempfile.gettempdir(), "tg242_identity")
    _write_index(tmp, {
        "_no_tag_a": {"name": "", "workshop": "粗碎站", "model": "", "quantity": "1"},
        "_no_tag_b": {"name": "", "workshop": "粗碎站", "model": "", "quantity": "1"},
        "P-101": {"name": "渣浆泵", "workshop": "重选车间", "model": "8/6E-AH", "quantity": "2"},
    })
    got = em.find_by_identity(tmp, name="", workshop="粗碎站", model="")
    check("N2 传空名反查 → 返回空列表（不能把空名行当成一台设备）", [], got, got == [],
          f"实际返回 {len(got)} 条；空身份必须挡掉，否则「查不到」变成「查出一堆」")

    # 正常身份仍能查到
    ok = em.find_by_identity(tmp, name="渣浆泵", workshop="重选车间", model="8/6E-AH")
    check("N2b 正常身份反查仍可用", 1, len(ok), len(ok) == 1 and ok[0].get("canonical_tag") == "P-101")

    # ---------- N3 冲突登记 ----------
    _write_index(tmp, {
        # 型号为空且两行同名同车间 → 冲突
        "c1": {"name": "渣浆泵", "workshop": "重选车间", "model": "", "quantity": "2", "source_file": "台账.xlsx"},
        "c2": {"name": "渣浆泵", "workshop": "重选车间", "model": "", "quantity": "4", "source_file": "台账.xlsx"},
        # 型号齐 → 能区分，不算冲突
        "d1": {"name": "一级脱介筛", "workshop": "重介质选矿车间", "model": "A", "quantity": "3", "source_file": "台账.xlsx"},
        "d2": {"name": "一级脱介筛", "workshop": "重介质选矿车间", "model": "B", "quantity": "6", "source_file": "台账.xlsx"},
        # 单实例、型号空 → 没有冲突对象
        "e1": {"name": "浮选机", "workshop": "磨浮车间", "model": "", "quantity": "9", "source_file": "台账.xlsx"},
        # 空名 → 进「名称缺失」，不混进冲突
        "f1": {"name": "", "workshop": "粗碎站", "model": "G6-51", "quantity": "1", "source_file": "台账.xlsx"},
    })
    conf = em.identity_conflicts(tmp)
    names = [c.get("name") for c in conf]
    check("N3a 只报「型号为空且多实例」", ["渣浆泵"], names, names == ["渣浆泵"],
          "型号齐的同名设备能区分，不算冲突；单实例没有冲突对象")

    c0 = conf[0] if conf else {}
    check("N3b 冲突登记字段齐全（tags/数量/车间/名称）", True,
          bool(c0.get("tags")) and c0.get("total_qty") == 6 and c0.get("workshop") == "重选车间",
          bool(c0.get("tags")) and c0.get("total_qty") == 6 and c0.get("workshop") == "重选车间",
          f"实际 {c0}")
    check("N3b2 冲突登记带两条实例 tag（合并与否由人决定）", 2,
          len(c0.get("tags") or []), len(c0.get("tags") or []) == 2)

    nameless = em.devices_missing_name(tmp)
    check("N3c 空名行进 devices_missing_name，不混进 identity_conflicts",
          ["f1"], [n.get("tag") for n in nameless], [n.get("tag") for n in nameless] == ["f1"],
          "两类问题修法不同：缺名要补名，缺型号要定合并/补型号，不能混在一个清单里")

    # ---------- N6 接线：human_confirm 里真的出现 ----------
    import app.relations as R  # noqa: E402
    src = open(R.__file__, encoding="utf-8").read()
    check("N6a relations 里真的调用了 identity_conflicts", True,
          "identity_conflicts" in src, "identity_conflicts" in src,
          "只写函数不接线 = 界面永远看不到，等于没做（本项目反复出现的半交付）")
    check("N6b relations 里真的调用了 nameless_devices", True,
          "devices_missing_name" in src, "devices_missing_name" in src)

    # ---------- N4 真实数据现状 ----------
    real_dir = em._index_dir(None)
    print(f"        真实项目数据目录: {os.path.basename(real_dir)}")
    real_conf = em.identity_conflicts(real_dir)
    real_nl = em.devices_missing_name(real_dir)
    check("N4a 真实项目身份冲突组数", 14, len(real_conf), len(real_conf) == 14,
          f"涉及设备 {sum(len(c.get('tags') or []) for c in real_conf)} 台")
    # 数量合计必须分单位：混着加会把 kg 和台加成一个没有意义的数
    mixed = [c for c in real_conf if len(c.get("qty_by_unit") or {}) > 1]
    check("N4c 真实数据里没有跨单位冲突组（现状记录，非守卫）", 0, len(mixed), len(mixed) == 0,
          "实测「水源取水/螺旋焊接钢管」数量 705901.5 + 526149 单位 kg，"
          "与台数相加会得出 1232163 这种毫无意义的数字")

    # 上面这条在真实数据上恒为真（样本里本来就没有跨单位组），是现状记录不是守卫。
    # 真正能测出「跨单位相加」的，是下面这条构造数据断言。
    _write_index(tmp, {
        "m1": {"name": "螺旋焊接钢管", "workshop": "水源取水", "model": "", "quantity": "705901.5", "unit": "kg", "source_file": "台账.xlsx"},
        "m2": {"name": "螺旋焊接钢管", "workshop": "水源取水", "model": "", "quantity": "526149", "unit": "kg", "source_file": "台账.xlsx"},
        "m3": {"name": "混合单位件", "workshop": "磨浮车间", "model": "", "quantity": "3", "unit": "台", "source_file": "台账.xlsx"},
        "m4": {"name": "混合单位件", "workshop": "磨浮车间", "model": "", "quantity": "120", "unit": "kg", "source_file": "台账.xlsx"},
    })
    c_mix = {c["name"]: c for c in em.identity_conflicts(tmp)}
    steel = c_mix.get("螺旋焊接钢管") or {}
    check("N4e 同类单位仍能给出合计（kg 合并为 1232050.5）", 1232050.5,
          steel.get("total_qty"), steel.get("total_qty") == 1232050.5,
          "705901.5 + 526149 = 1232050.5")
    mixed1 = c_mix.get("混合单位件") or {}
    check("N4f 跨单位组不给单一合计（台与 kg 不相加）", None,
          mixed1.get("total_qty"), mixed1.get("total_qty") is None,
          f"实际 qty_by_unit={mixed1.get('qty_by_unit')}；"
          "若这里给出 123 就是把「台」和「kg」加在了一起")
    check("N4b 真实项目空名行数", 13, len(real_nl), len(real_nl) == 13,
          "这些行在台账里就是空名，补名后身份键才算完整")

    # ---------- N7 layout 与 devices 必须是同一个答案 ----------
    # 缺陷实证：GET /api/relations 报 228 台 / 19 车间，同一时刻
    # GET /api/relations/layout 报 items 0 —— 合并逻辑只补 devices 与 workshops，
    # 从不补 layout（「同一件事两个答案」在合并路径上的复现）。
    import app.relations as RR  # noqa: E402
    ledger = json.load(open(os.path.join(real_dir, "index.json"), encoding="utf-8"))["devices"]
    gg = RR._blank_graph()
    merged_g = RR._merge_index_devices(gg, ledger)
    dev_n = len(merged_g.get("devices") or [])
    lay_rows = [r for r in (merged_g.get("layout") or []) if isinstance(r, dict)]
    lay_tags = {r.get("tag") for r in lay_rows}
    dev_tags_with_ws = {d.get("tag") for d in (merged_g.get("devices") or [])
                        if isinstance(d, dict) and any(w for w in (d.get("workshops") or []))}
    check("N7a layout 覆盖所有有车间归属的设备（不空着）", len(dev_tags_with_ws),
          len(lay_tags), lay_tags == dev_tags_with_ws,
          f"设备 {dev_n} 台 / 有车间归属 {len(dev_tags_with_ws)} 台 / layout {len(lay_tags)} 条")
    check("N7b layout 非空（原来恒为 0）", True, len(lay_rows) > 0, len(lay_rows) > 0)

    _mismatch = []
    for r in lay_rows:
        ws = r.get("workshop")
        if ws is None:
            continue
        d = next((x for x in (merged_g.get("devices") or [])
                  if isinstance(x, dict) and x.get("tag") == r.get("tag")), None)
        if not d:
            continue
        dws = [w for w in (d.get("workshops") or []) if w]
        if dws and (len(dws) != 1 or dws[0] != ws):
            _mismatch.append((r.get("tag"), dws, ws))
    check("N7c layout 与 devices 对同一设备给出同一车间", [], _mismatch[:5], not _mismatch,
          "这一条正是本项目反复查的「同一件事两个答案」的正面判据")

    # ---------- N5 真实数据未污染 ----------
    after = _snap(_REAL_DATA_DIR)
    diff = sorted(set(after) ^ set(_REAL_BEFORE)) + sorted(
        k for k in set(after) & set(_REAL_BEFORE) if after[k] != _REAL_BEFORE[k])
    check("N5 真实 data/ 未被污染（内容全等）", [], diff[:6], not diff,
          f"变化 {len(diff)} 处")

    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["passed"])
    print()
    print(f"结果：通过 {passed} / 失败 {total - passed}（共 {total} 条）")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
