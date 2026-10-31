#!/usr/bin/env python3
"""v0.1.182 回归：整卷（多车间）合并后的聚合计数必须等于逐车间合计。

实测缺陷（紫金选矿厂真实台账，19 车间 228 设备）：

    指标             逐车间合计   整卷 API   差
    generated        36          33       漏 3
    todo             21          24       多 3
    skipped          2           0        漏 2
    tf_batch         36          2        漏 34

三个成因（都在原内联合并块里）：
  ① `_merged = _r` 直接引用第一车间结果对象；
  ② 去重 key 缺「列表名」，`generated`/`todo_fields`/`type_fallback` 同车间同序号
     同名且都无「原因」→ 撞键整批丢弃；
  ③ `if not _r.get(_k): continue` 使「首车间该键为空」时该键永远建不出来。

本测试用构造数据直接命中 ①②③，不依赖真实台账，可在任何机器秒级跑完。
用法：python3 tools/test_merge_agg.py   （退出码 0 = 全过）
"""
import json
import os
import sys

WB = os.environ.get("FANGONG_WB",
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WB)
os.environ.setdefault("FANGONG_NO_BROWSER", "1")

from app import supervision_integration as si  # noqa: E402

KEYS = si.MERGE_LIST_KEYS

_PASS = [0]
_FAIL = []


def check(name, cond, detail=""):
    if cond:
        _PASS[0] += 1
        print(f"  [PASS] {name}")
    else:
        _FAIL.append(f"{name}  {detail}")
        print(f"  [FAIL] {name}  {detail}")


def per_ws_total(results, key):
    return sum(len((results.get(w) or {}).get(key) or []) for w in results)


def build_fixture():
    """三个车间，故意让它们同时踩中三个缺陷。

    车间 A（首个车间）：generated 有 2 条、skipped_device_forms **为空**
    车间 B：每条登记项都同时产出 generated + todo_fields + type_fallback
           —— 三种行的 (序号,名称) 完全相同，且都没有「原因」
    车间 C：只有 skipped_device_forms（材料车间）+ todo
    """
    a = "1号车间"
    b = "2号车间"
    c = "尾矿库"
    res = {
        a: {
            'ok': True,
            'generated': [
                {'序号': '1', '名称': '设备开箱检验记录', '文件': '1_设备开箱检验记录.docx'},
                {'序号': '2', '名称': '单机无负荷试运转记录', '文件': '2_单机无负荷试运转记录.docx'},
            ],
            'todo': [{'序号': '3', '名称': '设备安装检查记录', '原因': '无匹配模板，需人工确认表类型'}],
            'errors': [],
            'collect_dir': [],
            'todo_fields': [],
            'empty_shells': [],
            'skipped_device_forms': [],          # ← 缺陷③：首车间此键为空
            'type_fallback': [],
        },
        b: {
            'ok': True,
            'generated': [
                {'序号': '1', '名称': '设备开箱检验记录', '文件': '1_设备开箱检验记录.docx'},
                {'序号': '2', '名称': '单机无负荷试运转记录', '文件': '2_单机无负荷试运转记录.docx'},
            ],
            'todo': [{'序号': '3', '名称': '设备安装检查记录', '原因': '无匹配模板，需人工确认表类型'}],
            'errors': [],
            'collect_dir': [],
            # ← 缺陷②：与 generated 同序号同名，无「原因」
            'todo_fields': [
                {'序号': '1', '名称': '设备开箱检验记录', '待补字段': ['供货厂家', '施工单位']},
                {'序号': '2', '名称': '单机无负荷试运转记录', '待补字段': ['施工图号']},
            ],
            'empty_shells': [],
            'skipped_device_forms': [],
            # ← 缺陷②：同样与 generated 撞 (序号,名称)
            'type_fallback': [
                {'序号': '1', '名称': '设备开箱检验记录',
                 '借用情况': [{'设备': '介质桶1', '借用表': '胶带输送机', '方式': '通用表承接'}]},
                {'序号': '2', '名称': '单机无负荷试运转记录',
                 '借用情况': [{'设备': '渣浆泵1', '借用表': '离心泵', '方式': '通用表承接'}]},
            ],
        },
        c: {
            'ok': True,
            'generated': [],
            'todo': [{'序号': '1', '名称': '设备开箱检验记录',
                      '原因': '该车间台账 4 行全为材料（单位：m2、米），非设备，已跳过设备类表单',
                      '_skip_material': True}],
            'errors': [],
            'collect_dir': [],
            'todo_fields': [],
            'empty_shells': [],
            'skipped_device_forms': [
                {'序号': '1', '名称': '设备开箱检验记录',
                 '原因': '该车间台账 4 行全为材料（单位：m2、米），非设备，已跳过设备类表单'},
                {'序号': '2', '名称': '单机无负荷试运转记录',
                 '原因': '该车间台账 4 行全为材料（单位：m2、米），非设备，已跳过设备类表单'},
            ],
            'type_fallback': [],
        },
    }
    return res, [a, b, c]


def main():
    res, wss = build_fixture()

    print("=== 1. 聚合计数 = 逐车间合计（逐键逐车间） ===")
    merged = si._merge_workshop_results(res, wss)
    for k in KEYS:
        want = per_ws_total(res, k)
        got = len(merged.get(k) or [])
        check(f"{k} 合计 {got}/{want}", got == want,
              f"整卷 {got}，逐车间合计 {want}")

    print("=== 2. 每行都带 _车间，且归属正确 ===")
    for k in KEYS:
        for row in (merged.get(k) or []):
            if not isinstance(row, dict):
                continue
            check(f"{k} 行带 _车间", bool(row.get('_车间')), f"row={row}")

    print("=== 3. 不能污染首车间原始结果（缺陷①） ===")
    first = wss[0]
    orig_gen = len(res[first]['generated'])
    check("首车间 generated 未被合并污染",
          len(res[first]['generated']) == orig_gen,
          f"原 {orig_gen} 现 {len(res[first]['generated'])}")
    check("首车间对象未被塞 by_workshop",
          'by_workshop' not in res[first],
          "合并把 by_workshop 写进了调用方对象")

    print("=== 4. by_workshop 覆盖每个车间 ===")
    bw = merged.get('by_workshop') or {}
    check("by_workshop 车间数", len(bw) == len(wss), f"{len(bw)}/{len(wss)}")
    for w in wss:
        r = res[w]
        exp = {'generated': len(r['generated']), 'errors': len(r['errors']),
               'todo': len(r['todo'])}
        check(f"by_workshop[{w}]", bw.get(w) == exp, f"得 {bw.get(w)} 期望 {exp}")

    print("=== 5. 真正重复的行仍要去重（同车间同列表同内容） ===")
    dup = {
        'X': {'ok': True, 'generated': [
            {'序号': '1', '名称': 'A', '文件': 'x.docx'},
            {'序号': '1', '名称': 'A', '文件': 'x.docx'},
        ], 'todo': [], 'errors': [], 'collect_dir': [], 'todo_fields': [],
            'empty_shells': [], 'skipped_device_forms': [], 'type_fallback': []},
    }
    m2 = si._merge_workshop_results(dup, ['X'])
    check("同内容重复行被去重 1/2", len(m2['generated']) == 1, f"得 {len(m2['generated'])}")

    print("=== 6. 空输入不炸 ===")
    m3 = si._merge_workshop_results({}, [])
    check("空输入", all(m3.get(k) == [] for k in KEYS) and m3.get('by_workshop') == {},
          json.dumps({k: len(m3.get(k) or []) for k in KEYS}))

    print()
    print(f"通过 {_PASS[0]} 项，失败 {len(_FAIL)} 项")
    if _FAIL:
        print("失败明细：")
        for f in _FAIL:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
