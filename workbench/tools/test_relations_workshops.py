"""test_relations_workshops.py —— 台账设备并入图谱时，车间清单必须一起补齐。

缺陷（v0.1.212 修）：_merge_index_devices() 只补 devices 与 stats，从不重建
graph["workshops"]。而 build_relations() 是唯一会建 workshops 的地方，只导入台账、
没跑图纸关联时图谱是 _blank_graph()，workshops 恒为 []。实测后果：
  /api/workshops 报 19 个车间，同一时刻 /api/relations.workshops 是 []，
  19 个真实车间的 GET /api/relations/workshop/<车间> 全部 404。

本测试全部用**构造数据**，不读任何真实项目数据（教训：测试不要在真实目录上做
备份-清空-恢复，中途异常会导致真实数据丢失）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) if False else None
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import relations as R  # noqa: E402

PASS = []
FAIL = []


def check(name, expect, actual, ok, note=""):
    (PASS if ok else FAIL).append(name)
    tag = "[PASS]" if ok else "[FAIL]"
    print(f"  {tag} {name}: 期望={expect} 实际={actual}" + (f" | {note}" if note and not ok else ""))
    return ok


def blank():
    return {"stats": {}, "workshops": [], "devices": [], "human_confirm": []}


LEDGER = {
    "T-1": {"name": "颚式破碎机", "workshop": "粗碎站", "source_file": "a.xlsx", "quantity": "1"},
    "T-2": {"name": "胶带输送机", "workshop": "粗碎站", "source_file": "a.xlsx", "quantity": "2"},
    "T-3": {"name": "渣浆泵", "workshop": "磨浮车间", "source_file": "a.xlsx", "quantity": "3"},
    "T-4": {"name": "无车间设备", "workshop": "", "source_file": "a.xlsx", "quantity": "1"},
}


def main():
    print("\n=== test_relations_workshops ===")

    # A 空图谱 + 台账设备 -> workshops 必须被补齐（这正是 404 的根因）
    g = R._merge_index_devices(blank(), LEDGER)
    ws = g.get("workshops") or []
    names = sorted(w.get("workshop") for w in ws if isinstance(w, dict))
    check("A1 车间清单被补齐", ["磨浮车间", "粗碎站"], names, names == ["磨浮车间", "粗碎站"])

    # A2 只有台账的设备不进车间清单（workshop 为空的不该造出一个空名车间）
    check("A2 空车间名未进清单", 2, len(ws), len(ws) == 2,
          "workshop 为空") 

    # A3 每个车间的设备数与真实设备条数一致（粗碎站 2 台、磨浮车间 1 台）
    cnt = {w.get("workshop"): w.get("device_count") for w in ws}
    check("A3 车间设备数正确", {"粗碎站": 2, "磨浮车间": 1}, cnt,
          cnt == {"粗碎站": 2, "磨浮车间": 1})

    # A4 不臆造业务值：zone 留 None、docs 留空、source 标 ledger
    w0 = next((w for w in ws if w.get("workshop") == "粗碎站"), None)
    if w0 is None:
        # 反向验证时会走到这里：车间清单是空的，后续断言无从取值。
        # 必须记成失败而不是抛异常 —— 抛异常会让汇总数字不完整，
        # 看起来像「测试崩了」而不是「测试抓住了缺陷」。
        check("A4 不臆造 zone/docs 并标 source", "存在粗碎站车间", "车间清单为空", False,
              "车间清单没有粗碎站，说明补齐逻辑没生效")
        check("A5 tags 为真实位号", ["T-1", "T-2"], "无车间可取", False, "同上")
        check("A6 stats.workshops 与实际条数一致", len(ws), (g.get("stats") or {}).get("workshops"),
              (g.get("stats") or {}).get("workshops") == len(ws))
        w0 = {"zone": None, "docs": [], "source": None, "tags": None}
    else:
        ok4 = w0.get("zone") is None and (w0.get("docs") == []) and w0.get("source") == "ledger"
        check("A4 不臆造 zone/docs 并标 source", "zone=None docs=[] source=ledger",
              f"zone={w0.get('zone')} docs={w0.get('docs')} source={w0.get('source')}", ok4)
        # A5 tags 里放的是真实位号，且排序稳定
        check("A5 tags 为真实位号", ["T-1", "T-2"], w0.get("tags"), w0.get("tags") == ["T-1", "T-2"])
        # A6 stats.workshops 与实际条数一致
        check("A6 stats.workshops 与实际条数一致", len(ws), (g.get("stats") or {}).get("workshops"),
              (g.get("stats") or {}).get("workshops") == len(ws))

    # B 已有车间（图纸关联出来的）不得被覆盖，只校准设备数
    g2 = blank()
    g2["workshops"] = [{"workshop": "粗碎站", "zone": {"x": 100, "y": 200},
                        "docs": [{"file": "dwg.dwg"}], "tags": ["D-9"],
                        "doc_count": 1, "device_count": 1, "source": "drawing"}]
    g2["devices"] = [{"tag": "D-9", "workshops": ["粗碎站"]}]
    g3 = R._merge_index_devices(g2, LEDGER)
    w1 = next((w for w in g3["workshops"] if w["workshop"] == "粗碎站"), None)
    if w1 is None:
        check("B1 已有车间 zone/source/docs 不被覆盖", "存在粗碎站车间", "被丢掉了", False,
              "已有车间被吞，说明合并顺序有问题")
        check("B2 已有车间设备数按真实条数校准", 3, None, False, "同上")
    else:
        ok_b = (w1.get("zone") == {"x": 100, "y": 200} and w1.get("source") == "drawing"
                and w1.get("doc_count") == 1)
        check("B1 已有车间 zone/source/docs 不被覆盖", "保持原样",
              f"zone={w1.get('zone')} source={w1.get('source')} doc_count={w1.get('doc_count')}", ok_b)
        # 粗碎站此时真实设备 = D-9 + T-1 + T-2 = 3 台
        check("B2 已有车间设备数按真实条数校准", 3, w1.get("device_count"),
              w1.get("device_count") == 3)

    # C 无台账时不改动（不能因为没台账就把已有车间清空）
    g4 = {"stats": {"workshops": 1}, "workshops": [{"workshop": "X", "docs": []}],
          "devices": [], "human_confirm": []}
    g5 = R._merge_index_devices(g4, {})
    check("C1 无台账时车间清单不变", 1, len(g5.get("workshops") or []),
          len(g5.get("workshops") or []) == 1)

    # D 幂等：同一输入连续两次调用，车间条数不翻倍
    g6 = R._merge_index_devices(blank(), LEDGER)
    n1 = len(g6["workshops"])
    g7 = R._merge_index_devices(g6, LEDGER)
    check("D1 连续调用不重复追加车间", n1, len(g7["workshops"]), len(g7["workshops"]) == n1)

    print(f"\n===== 通过 {len(PASS)} / 失败 {len(FAIL)} =====")
    if FAIL:
        print("失败项：" + "; ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
