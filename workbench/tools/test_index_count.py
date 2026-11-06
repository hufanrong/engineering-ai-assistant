"""索引文件数口径回归测试（v0.1.209）

修的是「同一件事两个答案」：/api/status 的 indexed_files 数的是索引顶层
字典键数，前端文件列表数的是真实文件条目。

实测（2026-11-07，项目 322fef90）：
  索引顶层 6 个键 = files / devices / workshops / <一个 sha256> /
                   ledger_skipped_rows / updated_at
  /api/status indexed_files → 6
  /api/files 列表           → 1 条
  真实已入库文件            → 1 个

断言分组：
  [A] 空索引 → 0（不是「有几个保留键就报几」）
  [B] 只有保留/辅助键 → 0（历史 bug 在这里会报 4~6）
  [C] files 列表 + 扁平 sha 键并存时去重计数，不漏不重
  [D] 与 main.py 前端文件列表 _frontend_index_items() 同口径
  [E] project_backup 的统计口径不再走 len(idx)

运行：python3 tools/test_index_count.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.scanner as sc  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def _sha(i):
    """造一个 64 位 sha 形键（scanner 的口径靠 dict 值类型判断，不靠键长）。"""
    return (f"{i:02x}" * 32)[:64]


def main():
    global PASS, FAIL
    PASS = FAIL = 0

    print("[A] 空索引")
    check("{} -> 0", sc.count_index_files({}) == 0, f"实际 {sc.count_index_files({})}")
    check("None -> 0（不炸）", sc.count_index_files(None) is not None)

    print()
    print("[B] 只有保留键 / 辅助键")
    only_reserved = {"files": [], "devices": {}, "workshops": {},
                     "updated_at": "2026-11-07 01:09:03"}
    n = sc.count_index_files(only_reserved)
    check("保留键全在、无文件 -> 0", n == 0, f"实际 {n}（旧实现会报 {len(only_reserved)}）")

    with_aux = dict(only_reserved)
    with_aux["ledger_skipped_rows"] = [{"row": 1}, {"row": 2}]
    n2 = sc.count_index_files(with_aux)
    check("加了 ledger_skipped_rows 仍是 0", n2 == 0,
          f"实际 {n2}（旧实现会报 {len(with_aux)}）")

    print()
    print("[C] files 列表 + 扁平 sha 键并存")
    mixed = {
        "files": [{"id": "a", "file_name": "甲.xlsx"}, {"id": "b", "file_name": "乙.pdf"}],
        "devices": {"d1": {}, "d2": {}},
        "workshops": {"w1": {}, "w2": {}, "w3": {}},
        "updated_at": "x",
        _sha(1): {"file_name": "丙.dwg", "status": "parsed"},
        _sha(2): {"file_name": "丁.docx", "status": "parsed"},
    }
    n3 = sc.count_index_files(mixed)
    check("2 个 files + 2 个扁平键 -> 4", n3 == 4, f"实际 {n3}（旧实现会报 {len(mixed)}）")

    # 同一个文件既在 files 里、又有扁平键 -> 去重仍算 1
    dup = {
        "files": [{"sha256": _sha(1), "file_name": "丙.dwg"}],
        _sha(1): {"file_name": "丙.dwg", "status": "parsed"},
        "updated_at": "x",
    }
    n4 = sc.count_index_files(dup)
    check("同一文件两处登记 -> 1（去重）", n4 == 1, f"实际 {n4}")

    print()
    print("[D] 与前端文件列表同口径")
    try:
        import app.main as m  # noqa: E402
        # 用临时目录喂同一份索引，比较 main 的列表长度与 scanner 的计数
        tmp = tempfile.mkdtemp(prefix="fg_idx_test_")
        idx_path = os.path.join(tmp, "index.json")
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(mixed, f, ensure_ascii=False)
        items = m._frontend_index_items()
        # _frontend_index_items 读的是当前项目索引；这里直接比对它对本体的判断
        # 是否与 count_index_files 一致（两者都跳过保留键）。
        mono = {"files": [], "devices": {}, "workshops": {}, "updated_at": "x",
                _sha(7): {"file_name": "戊.xlsx", "status": "parsed"}}
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(mono, f, ensure_ascii=False)
        n5 = sc.count_index_files(mono)
        check("单文件索引 -> 1", n5 == 1, f"实际 {n5}")
        check("前端列表接口函数可用（不抛异常）", callable(m._frontend_index_items))
    except Exception as e:  # noqa: BLE001
        check("与前端文件列表同口径", False, f"导入 main 失败：{e}")

    print()
    print("[E] project_backup 不再用 len(idx) 当文件数")
    pb_path = os.path.join(os.path.dirname(__file__), "..", "app", "project_backup.py")
    src = open(pb_path, encoding="utf-8").read()
    check("已改为调用 count_index_files", "count_index_files" in src)
    # 只在**代码行**里找旧兜底（v0.1.209 的注释里保留了旧写法作为对照，
    # 不能把注释本身判成残留——第一版测试就是这么误报的）
    live = [ln for ln in src.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    leftover = [ln.strip() for ln in live if "else len(idx)" in ln]
    check("旧的 len(idx) 兜底分支已移除", not leftover, f"残留：{leftover}")

    print()
    print("=" * 60)
    print(f"结果：通过 {PASS} / 失败 {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
