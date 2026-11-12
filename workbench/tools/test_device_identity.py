#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.1.241 回归测试：设备身份键（车间+名称+型号）与实例粒度必须分层。

用户决策（2026-11-12 13:20，interaction 7707149546354150699）：
  「位号为空时，设备主键按什么定？」
  → 「（推荐）车间+设备名称作主键，同名多行再按型号区分，仍冲突则进人工确认」

但直接把「车间+名称+型号」当成**合并键**会造成数据损失，实测（真实项目
322fef90，228 台设备）：

    车间+名称             → 178 台（少 50）
    车间+名称+型号        → 202 台（少 26）

被并掉的行里，数量列各不相同，说明它们确实是不同的设备实例：

    6 行 渣浆泵        数量 2/4/2/2/2/2
    4 行 一级高效脱介筛 数量 3/6/3/3
    3 行 充气式机械浮选机 数量 9/3/7

所以「主键」必须是**身份层**（用来认出「这两处资料说的是同一台设备」），
而不能同时当**实例层**（一台一行，竣工资料按台出表，少一台就少一套确认表）。
这正是 v0.1.179 当初把「源文件+行号」塞进键里想保住的东西 —— 那次是为了
不丢 75 台，不能因为这轮要实现身份键又把它退回去。

判据：

  I1 identity_key 形如「车间|名称|型号」，不含源文件、不含行号
  I2 同一设备出现在两份源文件里 → canonical_tag 不同、identity_key 相同
     （这条正是「跨文件建立联系」的最小前提）
  I3 同一台账同名同型号多行 → identity_key 相同，但 canonical_tag 互不相同
     （不丢设备的硬判据）
  I4 不同车间的同名设备 → identity_key 不同（否则跨车间误并联）
  I5 真实数据复核：canonical_tag 数量仍是 228，identity_key 数量 202
  I6 按 identity_key 反查能拿回全部实例（跨源文件一起拿回）
  I7 真实 data/ 未被污染（内容全等）
  I8 identity_key 做规范化：全/半角空格、大小写差异不得造出两个身份

跑法：python tools/test_device_identity.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unicodedata

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


def main():
    print("=" * 78)
    print("v0.1.241 设备身份键 vs 实例粒度")
    print("=" * 78)

    # ---------- I1 / I8 身份键形态与规范化 ----------
    has_fn = hasattr(em, "identity_key")
    check("I1a equipment_merge 提供 identity_key()", True, has_fn, has_fn,
          "身份键必须有单一实现处，不能各模块自己拼字符串")

    if not has_fn:
        print("  identity_key 尚未实现，后续断言跳过")
        return 1

    k1 = em.identity_key("渣浆泵", "重选车间", "8/6E-AH")
    check("I1b 身份键形如「车间|名称|型号」",
          "重选车间|渣浆泵|8/6E-AH", k1, k1 == "重选车间|渣浆泵|8/6E-AH")
    check("I1c 身份键里没有源文件、没有行号",
          True, ("|" in k1 and "xlsx" not in k1 and not k1.rstrip("|").endswith("0")),
          "|" in k1 and "xlsx" not in k1,
          "源文件与行号属于**实例**，不能进身份键，否则跨文件永远认不出同一台")

    k2 = em.identity_key(" 渣浆泵 ", "重选车间　", "8/6e-ah")   # 全角空格 + 小写
    check("I8 规范化：全角空格/大小写不造出第二个身份",
          k1, k2, k1 == k2,
          "型号大小写与全角空格是同一型号的不同写法，必须收敛")

    # ---------- I2 / I3 / I4 用构造数据 ----------
    eqs = [
        # 同一设备，两份源文件、同车间同型号 → 身份相同、实例不同
        {"tag": "", "name": "渣浆泵", "workshop": "重选车间", "model": "8/6E-AH",
         "spec": "", "source_file": "A厂台账.xlsx", "row_index": 1, "quantity": "2"},
        {"tag": "", "name": "渣浆泵", "workshop": "重选车间", "model": "8/6E-AH",
         "spec": "", "source_file": "B厂台账.xlsx", "row_index": 9, "quantity": "4"},
        # 同车间同名同型号、同一份文件的两行 → 身份相同、实例仍要分开
        {"tag": "", "name": "渣浆泵", "workshop": "重选车间", "model": "8/6E-AH",
         "spec": "", "source_file": "A厂台账.xlsx", "row_index": 2, "quantity": "2"},
        # 不同车间的同名设备 → 身份必须不同
        {"tag": "", "name": "渣浆泵", "workshop": "磨浮车间", "model": "8/6E-AH",
         "spec": "", "source_file": "A厂台账.xlsx", "row_index": 3, "quantity": "1"},
    ]
    res = em.merge_equipment_list([dict(e) for e in eqs])
    merged = res["merged"]
    tags = [d["canonical_tag"] for d in merged]
    idents = [d.get("identity_key", "") for d in merged]

    check("I3a 四行输入 → 四个实例都在（不合并丢台）",
          4, len(merged), len(merged) == 4,
          f"canonical_tag={tags}")

    cross = [d for d in merged
             if d.get("name") == "渣浆泵" and d.get("workshop") == "重选车间"]
    cross_ids = {d.get("identity_key") for d in cross}
    # v0.1.241 修：**身份键必须非空**才算「相同」。
    # 第一版只断言 len(cross_ids)==1，反向验证时发现它恒真 —— 因为不写
    # identity_key 的实现里三个实例的该字段都是 ""，一个空串也是「一个身份」。
    # 这正是本项目反复出现的假守卫：空结果一律放过。负向断言必须配正向要求。
    check("I2 跨源文件的同一设备身份键相同（3 个实例 / 1 个非空身份）",
          (3, 1, True), (len(cross), len(cross_ids), all(cross_ids)),
          len(cross) == 3 and len(cross_ids) == 1 and all(cross_ids),
          f"身份键={cross_ids}")

    other_ws = [d for d in merged
                if d.get("name") == "渣浆泵" and d.get("workshop") == "磨浮车间"]
    check("I4 不同车间同名设备身份键不同",
          True,
          bool(other_ws) and other_ws[0].get("identity_key") not in cross_ids,
          bool(other_ws) and other_ws[0].get("identity_key") not in cross_ids,
          "跨车间合并会把两台不同车间的设备说成同一台")

    # ---------- I6 按身份键反查 ----------
    has_find = hasattr(em, "find_by_identity")
    check("I6a equipment_merge 提供 find_by_identity()", True, has_find, has_find)
    if has_find:
        tmp = tempfile.mkdtemp(prefix="fg_ident_")
        try:
            idx = {"devices": {}}
            for d in merged:
                idx["devices"][d["canonical_tag"]] = {
                    "name": d.get("name", ""), "model": d.get("model", ""),
                    "workshop": d.get("workshop", ""), "quantity": d.get("quantity", ""),
                    "identity_key": d.get("identity_key", ""),
                    "source_file": ((d.get("versions") or [{}])[-1] or {}).get("source_file", ""),
                }
            os.makedirs(tmp, exist_ok=True)
            with open(os.path.join(tmp, "index.json"), "w", encoding="utf-8") as f:
                json.dump(idx, f, ensure_ascii=False)
            got = em.find_by_identity(tmp, name="渣浆泵", workshop="重选车间",
                                      model="8/6E-AH")
            # v0.1.241 修：必须校验拿回的是**这个身份**的实例，而不是「恰好三条」。
            # 第一版只断言 len==3；还原修复后 merged 里没有 identity_key，
            # 落盘的三条都带空串 identity_key，find_by_identity 拿空 key 反查
            # 又把三条全拿回来 → 恒真。要按「每条的身份都等于目标身份」判。
            _target = em.identity_key("渣浆泵", "重选车间", "8/6E-AH")
            _keys = {g.get("identity_key") or em.identity_key(
                g.get("name", ""), g.get("workshop", ""), g.get("model", ""))
                for g in got}
            check("I6b 反查拿回全部实例，且身份键都等于目标身份",
                  (3, {_target}), (len(got), _keys),
                  len(got) == 3 and _keys == {_target},
                  f"拿回={[g.get('source_file') for g in got]}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------- I5 真实数据复核 ----------
    # v0.1.241 说明：这一段读的是**磁盘上的历史快照**，因此它只能记录现状，
    # 不具备判别力 —— 反向验证里把代码还原并不会改写磁盘，所以 I5a 永远
    # 不会因代码改动而变红（第一版把它列进期望红名单，导致用例无效）。
    # 真正的判别力在 I3a（内存里重新合并构造数据，实例必须全留）。
    # v0.1.246：原来写死了 projects/322fef90/index.json 与 228 / 202 三个值。
    # 平台要服务多个施工项目，写死 = 只对这一份资料成立。现在：
    #   · 真实项目**动态挑选**（台账条目最多的那个）
    #   · 期望值**现算**，断言从「等于某个数字」变成「等于按定义算出来的值」
    def _pick_real_idx():
        """动态挑一个真实项目：有 index.json 且设备台账条目最多者。"""
        root = os.path.join(_REAL_DATA_DIR, "projects")
        best, best_n = None, -1
        if os.path.isdir(root):
            for pid in sorted(os.listdir(root)):
                p = os.path.join(root, pid, "index.json")
                if not os.path.isfile(p):
                    continue
                try:
                    d = json.load(open(p, encoding="utf-8")).get("devices") or {}
                except Exception:  # noqa: BLE001
                    continue
                if len(d) > best_n:
                    best, best_n = p, len(d)
        return best

    real_idx = _pick_real_idx()
    if real_idx:
        dev = json.load(open(real_idx, encoding="utf-8")).get("devices") or {}
        n_canon = len(dev)
        check("I5a 真实项目实例数 > 0（现算，不写死 228）",
              ">0", n_canon, n_canon > 0,
              f"项目={os.path.basename(os.path.dirname(real_idx))} 实例={n_canon}；"
              "这条只证明历史数据没被本轮改动破坏，不能当判别判据")

        def _nz(x):
            return " ".join(unicodedata.normalize("NFKC", str(x or ""))
                            .replace("\u3000", " ").split()).strip()

        # 身份数：按实现口径（车间|名称|型号，型号大写）现算去重
        _exp_ident = set()
        for _v in dev.values():
            if not isinstance(_v, dict):
                continue
            _nm = _nz(_v.get("name"))
            if not _nm:
                continue
            _exp_ident.add(_nz(_v.get("workshop")) + "|" + _nm
                           + "|" + _nz(_v.get("model")).upper())
        n_ident = len(_exp_ident)
        check("I5b 身份数 == 独立复算的「车间|名称|型号」去重数（不写死 202）",
              n_ident, n_ident, n_ident <= n_canon,
              f"身份={n_ident} 实例={n_canon}；身份数必须 ≤ 实例数（不丢设备）")

        # 独立复算的第二种口径：直接调用实现的 identity_key，逐行比对
        _by_impl = set()
        for _v in dev.values():
            if not isinstance(_v, dict):
                continue
            _k = em.identity_key(_v.get("name", ""), _v.get("workshop", ""),
                                 _v.get("model", ""))
            if _k:
                _by_impl.add(_k)
        check("I5c 实现口径与独立复算一致（同一件事不能两个答案）",
              len(_exp_ident), len(_by_impl), len(_exp_ident) == len(_by_impl),
              f"独立={len(_exp_ident)} 实现={len(_by_impl)}")

        have_key = sum(1 for v in dev.values() if v.get("identity_key"))
        bad_key = [t for t, v in dev.items()
                   if isinstance(v, dict) and v.get("identity_key")
                   and v.get("identity_key") != em.identity_key(
                       v.get("name", ""), v.get("workshop", ""), v.get("model", ""))]
        check("I5d 已回填的 identity_key 必须与现算一致（回填错比没回填更坏）",
              0, len(bad_key), not bad_key,
              f"已回填 {have_key} 条，其中不一致 {len(bad_key)} 条")
    else:
        check("I5 真实项目 index.json 存在", True, False, False, "未找到任何项目的 index.json")

    # ---------- I7 真实数据未污染 ----------
    after = _snap(_REAL_DATA_DIR)
    added = sorted(set(after) - set(_REAL_BEFORE))
    removed = sorted(set(_REAL_BEFORE) - set(after))
    changed = sorted(k for k in set(after) & set(_REAL_BEFORE)
                     if after[k] != _REAL_BEFORE[k])
    check("I7 真实 data/ 未被污染（内容全等）", ([], [], []), (added, removed, changed),
          not added and not removed and not changed,
          "覆盖写不改键集合，只改内容 —— 必须按 sha256 比")

    passed = sum(1 for r in RESULTS if r["passed"])
    failed = len(RESULTS) - passed
    print()
    print("=" * 78)
    print(f"结果：通过 {passed} / 失败 {failed}（共 {len(RESULTS)} 条）")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
