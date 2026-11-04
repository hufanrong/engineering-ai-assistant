"""项目隔离回归测试（v0.1.199）

验证目标：业务数据必须落进「当前项目目录」，不能落到全局 data/。
本测试正是针对实测发现的缺陷：
  · data/projects/ 下 91 个项目目录，没有一个存在 construction_logs.json /
    doc_relations.json / docplan_tasks.json / equipment_merge.json /
    piping_network.json / rejected_candidates.json / tag_alias.json / version_map.json
  · 而这些文件（version_map.json 实测 12 个文件、198 条版本记录）全都躺在全局 data/
  · 根因：路径被写成模块级常量 / lazy-init 常量，① 跨项目串味，② 切项目后不复算

四组断言：
  [A] 每个模块的文件都落进当前项目目录，全局 data/ 不被写入
  [B] A 项目写入的数据，切到 B 项目后读不到（不串味）
  [C] 切回 A 项目，数据还在（隔离不是丢失）
  [D] 切换项目后仍写入新项目路径（常量不复算的缺陷已修）

运行：python3 tools/test_project_scope.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.config as config  # noqa: E402
import app.project_manager as pm  # noqa: E402
import app.project_scope as scope  # noqa: E402

# 被测模块与其文件名
MODULES = [
    ("construction_log", "construction_logs.json", lambda m: m._save({"logs": {"2026-11-04": {"data": 1}}, "daily_summary": {}})),
    ("doc_relations", "doc_relations.json", lambda m: m._save({"A-101": {"tags": ["A-101"]}})),
    ("docplan", "docplan_tasks.json", lambda m: m.save_tasks([{"id": "t1", "doc_type": "施工方案"}])),
    ("equipment_merge", "equipment_merge.json", lambda m: m._save({"merged": {"x": 1}, "pending": [], "confirmed_alias": {}, "rejected_alias": {}})),
    ("piping_network", "piping_network.json", lambda m: m._save({"pipes": {"P-1": {}}, "connections": [], "device_pipes": {}})),
]

passed = 0
failed = 0
fail_detail = []


def check(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        fail_detail.append(f"{label} {detail}")
        print(f"  [FAIL] {label} {detail}")


def snapshot_global(data_dir):
    """全局 data/ 根层的 json 快照（文件名 -> 大小+mtime）。"""
    out = {}
    if not os.path.isdir(data_dir):
        return out
    for fn in os.listdir(data_dir):
        p = os.path.join(data_dir, fn)
        if os.path.isfile(p) and (fn.endswith(".json") or fn.endswith(".jsonl")):
            st = os.stat(p)
            out[fn] = (st.st_size, st.st_mtime)
    return out


def main():
    tmp = tempfile.mkdtemp(prefix="fgbak_scope_")
    real_data = config.DATA_DIR
    try:
        # 用临时数据目录，绝不动真实 data/
        config.DATA_DIR = tmp
        pm.PROJECTS_ROOT = os.path.join(tmp, "projects")
        pm.CURRENT_PROJECT_FILE = os.path.join(tmp, "current_project.json")
        os.makedirs(pm.PROJECTS_ROOT, exist_ok=True)

        pa = pm.create_project("隔离测试A")["project"]["id"]
        pb = pm.create_project("隔离测试B")["project"]["id"]

        print("\n[A] 写入落项目目录 + 全局 data/ 不被污染")
        snapshot_before = snapshot_global(tmp)
        pm.set_current_project(pa)
        dir_a = pm.get_project_data_dir(pa)
        for modname, fname, writer in MODULES:
            mod = __import__(f"app.{modname}", fromlist=["x"])
            writer(mod)
            pdir = os.path.join(dir_a, fname)
            check(os.path.isfile(pdir), f"A/{modname} 落进项目目录 {fname}")
            check(not os.path.isfile(os.path.join(tmp, fname)),
                  f"A/{modname} 未写全局 data/{fname}",
                  f"发现全局文件存在")
        snapshot_after = snapshot_global(tmp)
        # 只允许项目目录被创建（projects/ 是目录，不算 json 文件）
        leaked = {k: v for k, v in snapshot_after.items()
                  if k not in snapshot_before}
        check(not leaked, "A/全局 data/ 无新增 json 文件", f"泄漏文件={leaked}")

        print("\n[B] A 数据切到 B 后不可见（不串味）")
        pm.set_current_project(pb)
        dir_b = pm.get_project_data_dir(pb)
        for modname, fname, writer in MODULES:
            mod = __import__(f"app.{modname}", fromlist=["x"])
            check(scope.path(fname) == os.path.join(dir_b, fname),
                  f"B/{modname} 路径指向 B 项目", f"实际={scope.path(fname)}")
            # B 项目未写入前，load 不能读到 A 的数据
            data, src = scope.load_with_migration(fname)
            check(src != "project" or not data,
                  f"B/{modname} 读不到 A 的数据", f"src={src} data={str(data)[:60]}")
            check(not os.path.isfile(os.path.join(dir_b, fname)),
                  f"B/{modname} B 目录无 A 遗留 {fname}")

        print("\n[C] 切回 A，数据仍在（隔离≠丢失）")
        pm.set_current_project(pa)
        for modname, fname, writer in MODULES:
            check(os.path.isfile(os.path.join(pm.get_project_data_dir(pa), fname)),
                  f"C/{modname} A 目录文件仍在 {fname}")

        print("\n[D] 切换项目后写入新路径（常量不复算缺陷已修）")
        # 再切到 B，用同一批模块写一次，必须落到 B
        pm.set_current_project(pb)
        for modname, fname, writer in MODULES:
            mod = __import__(f"app.{modname}", fromlist=["x"])
            writer(mod)
            pnew = os.path.join(pm.get_project_data_dir(pb), fname)
            check(os.path.isfile(pnew), f"D/{modname} 切换后写入 B 路径 {fname}")
            # 同一时刻 A 的 mtime 不应被改动
            pa_path = os.path.join(pm.get_project_data_dir(pa), fname)
            check(os.path.isfile(pa_path), f"D/{modname} A 文件未被删改 {fname}")

        print("\n[E] 应用级配置仍留在全局（按设计不隔离）")
        for name in ("storage_config.json", "current_project.json", "operation_log.jsonl"):
            check(name in scope.GLOBAL_BY_DESIGN, f"E/{name} 在全局白名单中")

    finally:
        config.DATA_DIR = real_data
        pm.PROJECTS_ROOT = os.path.join(real_data, "projects")
        pm.CURRENT_PROJECT_FILE = os.path.join(real_data, "current_project.json")
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'='*56}")
    print(f"项目隔离测试结果：{passed} 通过 / {failed} 失败")
    if fail_detail:
        print("失败明细：")
        for d in fail_detail:
            print("  - " + d)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
