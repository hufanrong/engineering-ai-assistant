#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目备份/恢复完整性（v0.1.218）

为什么有这条测试
----------------
本轮实测（2026-11-09 07:0x）发现：`project_backup.BACKUP_ITEMS` 是一份 9 项白名单，
而项目数据目录里真实存在 19 类业务数据。导出项目的备份包里**没有**
`generated_docs/`（当前 10 个项目里合计 178 份 docx），也没有
`doc_relations.json` / `construction_logs.json` / `workshop_assign.json` /
`equipment_merge.json` / `supervision_registry.json` / `file_level.json` /
`upload_log.jsonl` / `volumes/` / `.node_id` / `upload_queue/`。

后果不是"少打包一个文件"，而是**删除或恢复项目会静默丢成果**：
  · `delete_project()` 的删除前自动备份走的就是 `backup_before_delete()`
    → `export_project()`，同一个白名单；
  · `import_project()` 解压时按 zip 内实际条目恢复，备份里没有的就永远没有。
实测证据（临时 DATA_DIR，造 1 份 uploads + 1 份 generated_docs + 1 份 exports）：
  导出包内条目 = ['backup_meta.json', 'exports/导出_test.docx', 'uploads/台账.xlsx', ...]
  含 generated_docs = []
  导入后 generated_docs 文件数 = 0，而 uploads / exports 都在。

这与本项目反复出现的母题同源：**"项目里有什么"存在两套口径** ——
备份清单认为项目只有 9 类东西，磁盘上实际有 19 类，两边都返回 ok:true。

判据（本测试）
--------------
B1 项目目录里存在的每一类业务数据，都必须进备份包（不能靠子集白名单漏掉）
B2 生成文档（generated_docs/）必须进包且恢复后仍在
B3 恢复后的文件内容与原始文件逐字节一致
B4 覆盖模式下导入，原有 generated_docs 不能被"清空"逻辑顺手删掉
B5 目录里新增的未知数据目录也必须进包（防止下次又漏一类）

隔离：本测试全程在临时 DATA_DIR 里跑，不碰用户真实 data/。
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.config as config  # noqa: E402

_REAL_DATA_DIR = config.DATA_DIR
_TMP_DATA = tempfile.mkdtemp(prefix="fg_bak_")
config.DATA_DIR = _TMP_DATA  # 必须在 import app.main / project_manager 之前

from app import project_manager as pm  # noqa: E402
import app.project_backup as pb  # noqa: E402

pm.PROJECTS_ROOT = os.path.join(_TMP_DATA, "projects")
pm.CURRENT_PROJECT_FILE = os.path.join(_TMP_DATA, "current_project.json")
pb.BACKUP_DIR = os.path.join(_TMP_DATA, "backups")
os.makedirs(pb.BACKUP_DIR, exist_ok=True)

PASS = 0
FAIL = 0
FAILED = []


def check(step, ok, evidence=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {step}" + (f": {evidence}" if evidence else ""))
    else:
        FAIL += 1
        FAILED.append(step)
        print(f"  [FAIL] {step}" + (f": {evidence}" if evidence else ""))


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _new_project(name):
    r = pm.create_project(name)
    pid = r.get("id") or (r.get("project") or {}).get("id")
    return pid, pm.get_project_data_dir(pid)


def _seed(ddir):
    """造一份"有代表性的完整项目"：覆盖备份清单内外各若干类。"""
    os.makedirs(os.path.join(ddir, "uploads"), exist_ok=True)
    with open(os.path.join(ddir, "uploads", "台账.xlsx"), "wb") as f:
        f.write(b"PK" + b"a" * 200)
    # 生成文档（备份清单原来漏掉的那一类）
    gd = os.path.join(ddir, "generated_docs", "施工方案")
    os.makedirs(gd, exist_ok=True)
    with open(os.path.join(gd, "繁工AI_施工方案_test.docx"), "wb") as f:
        f.write(b"PK" + b"b" * 300)
    gd2 = os.path.join(ddir, "generated_docs", "安全技术交底记录")
    os.makedirs(gd2, exist_ok=True)
    with open(os.path.join(gd2, "繁工AI_安全技术交底记录_test.docx"), "wb") as f:
        f.write(b"PK" + b"c" * 400)
    # 导出件
    os.makedirs(os.path.join(ddir, "exports"), exist_ok=True)
    with open(os.path.join(ddir, "exports", "导出_test.docx"), "wb") as f:
        f.write(b"PK" + b"d" * 100)
    # 业务 JSON（清单里原来也没有的几类）
    for fn, payload in [
        ("doc_relations.json", {"施工方案/x.docx": {"doc_id": "施工方案/x.docx", "source": "generated"}}),
        ("construction_logs.json", {"logs": [{"date": "2026-11-09", "content": "浇筑"}]}),
        ("workshop_assign.json", {"选矿厂": {"files": ["a.xlsx"]}}),
        ("equipment_merge.json", {"devices": {"球磨机": {"count": 3}}}),
        ("supervision_registry.json", {"registry": {"仪表回路试验记录": ["1号车间"]}}),
        ("file_level.json", {"abc": {"level": "L2", "workshop": "选矿厂"}}),
        ("tag_alias.json", {"位号A": "位号B"}),
        ("version_map.json", {"台账.xlsx": [{"sha256": "e" * 64, "status": "parsed", "ts": "2026-11-09"}]}),
    ]:
        with open(os.path.join(ddir, fn), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    with open(os.path.join(ddir, "upload_log.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-11-09T07:00:00", "action": "enqueue", "result": "ok"}, ensure_ascii=False) + "\n")
    with open(os.path.join(ddir, ".node_id"), "w", encoding="utf-8") as f:
        f.write("node-abc\n")
    # 归档卷
    os.makedirs(os.path.join(ddir, "volumes", "第一卷"), exist_ok=True)
    with open(os.path.join(ddir, "volumes", "第一卷", "卷内目录.docx"), "wb") as f:
        f.write(b"PK" + b"f" * 120)
    # 解析缓存 / 索引（清单里本来就有，用作对照）
    os.makedirs(os.path.join(ddir, "parsed_cache"), exist_ok=True)
    with open(os.path.join(ddir, "parsed_cache", "abc.json"), "w", encoding="utf-8") as f:
        json.dump({"text": "示例"}, f, ensure_ascii=False)
    with open(os.path.join(ddir, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"files": [], "devices": {}, "workshops": {}}, f, ensure_ascii=False)


def _listing(ddir):
    """列出项目目录里实际存在的条目（文件相对路径 / 目录名），排除项目备份目录本身。"""
    items = set()
    for name in os.listdir(ddir):
        p = os.path.join(ddir, name)
        if os.path.isdir(p):
            items.add(name)
        else:
            items.add(name)
    return items


def main():
    print("=" * 62)
    print("项目备份/恢复完整性（v0.1.218）")
    print("=" * 62)
    print(f"临时 DATA_DIR: {_TMP_DATA}")

    pid, ddir = _new_project("备份完整性")
    check("P1 测试项目建好", bool(pid and os.path.isdir(ddir)), f"pid={pid}")
    _seed(ddir)

    # ---------- B1/B2：备份包必须覆盖项目目录里的每一类数据 ----------
    print("\n[B] 备份完整性")
    r = pb.export_project(pid)
    check("B0 导出成功", r.get("ok") is True, str(r.get("error") or r.get("output_file")))
    bpath = r.get("output_path") or ""
    import zipfile
    with zipfile.ZipFile(bpath) as zf:
        names = zf.namelist()
    arc_dirs = {n.split("/")[0] for n in names if not n.startswith("backup_meta")}
    disk_items = {n for n in _listing(ddir) if n not in ("index.json",)} | {"index.json"}
    # 允许 zip 里用目录名表示（文件类条目会以文件名出现）
    missing = sorted(x for x in disk_items if x not in arc_dirs and not any(n.endswith(x) for n in names))
    check("B1 项目目录里每一类数据都进备份包",
          not missing, f"漏掉={missing[:6]} 包内顶层={sorted(arc_dirs)[:6]}")

    gen_in_zip = [n for n in names if n.startswith("generated_docs/")]
    check("B2 生成文档进备份包", len(gen_in_zip) >= 2, f"generated_docs 条目={len(gen_in_zip)} 个")

    # ---------- B3：恢复后逐字节一致 ----------
    r2 = pb.import_project(bpath, new_project_name="恢复完整性")
    check("B3a 导入成功", r2.get("ok") is True, str(r2.get("error") or r2.get("mode")))
    npid = r2.get("project_id") or (r2.get("project") or {}).get("id")
    ndir = pm.get_project_data_dir(npid) if npid else ""
    src_gen = os.path.join(ddir, "generated_docs")
    dst_gen = os.path.join(ndir, "generated_docs")
    src_files = {}
    for root, _, files in os.walk(src_gen):
        for f in files:
            p = os.path.join(root, f)
            src_files[os.path.relpath(p, src_gen)] = sha(p)
    dst_files = {}
    for root, _, files in os.walk(dst_gen):
        for f in files:
            p = os.path.join(root, f)
            dst_files[os.path.relpath(p, dst_gen)] = sha(p)
    same_set = set(src_files) == set(dst_files)
    same_content = same_set and all(src_files[k] == dst_files[k] for k in src_files)
    check("B3b 恢复后生成文档齐全", same_set,
          f"源={len(src_files)} 恢复后={len(dst_files)} 缺={sorted(set(src_files)-set(dst_files))[:3]}")
    check("B3c 恢复后生成文档逐字节一致", same_content,
          f"比较 {len(src_files)} 个文件，不一致={[k for k in src_files if src_files.get(k)!=dst_files.get(k)][:3]}")

    for fn in ["doc_relations.json", "construction_logs.json", "workshop_assign.json",
               "version_map.json", "file_level.json", "upload_log.jsonl", "tag_alias.json"]:
        sp = os.path.join(ddir, fn)
        dp = os.path.join(ndir, fn)
        check(f"B3d 恢复后 {fn} 存在且一致",
              os.path.isfile(dp) and sha(sp) == sha(dp),
              f"存在={os.path.isfile(dp)}")

    # 归档卷
    sp = os.path.join(ddir, "volumes", "第一卷", "卷内目录.docx")
    dp = os.path.join(ndir, "volumes", "第一卷", "卷内目录.docx")
    check("B3e 恢复后归档卷齐全", os.path.isfile(dp) and sha(sp) == sha(dp),
          f"存在={os.path.isfile(dp)}")

    # ---------- B4：覆盖模式不能顺手清掉生成文档 ----------
    print("\n[B4] 覆盖模式导入")
    r3 = pb.import_project(bpath, overwrite_project_id=pid)
    check("B4a 覆盖导入成功", r3.get("ok") is True, str(r3.get("error") or r3.get("mode")))
    gen_after = os.path.join(ddir, "generated_docs")
    n_after = sum(len(f) for _, _, f in os.walk(gen_after))
    check("B4b 覆盖导入后生成文档仍在", n_after >= 2, f"覆盖后 generated_docs 文件数={n_after}")

    # ---------- B5：未知的新目录也要进包（防止下次再漏一类） ----------
    print("\n[B5] 未知新目录")
    nd_unknown = os.path.join(ddir, "some_new_feature_dir")
    os.makedirs(nd_unknown, exist_ok=True)
    with open(os.path.join(nd_unknown, "x.bin"), "wb") as f:
        f.write(b"new" * 10)
    r4 = pb.export_project(pid, os.path.join(pb.BACKUP_DIR, "recheck.fgbak"))
    with zipfile.ZipFile(r4["output_path"]) as zf:
        n4 = zf.namelist()
    check("B5 未知新目录也进备份包",
          any(x.startswith("some_new_feature_dir/") for x in n4),
          f"条目={[x for x in n4 if 'some_new' in x]}")

    print("\n" + "=" * 62)
    print(f"汇总：通过 {PASS} / 失败 {FAIL}")
    if FAILED:
        print("失败项：" + "；".join(FAILED))
    print("=" * 62)

    try:
        shutil.rmtree(_TMP_DATA, ignore_errors=True)
    except Exception:
        pass
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
