#!/usr/bin/env python3
"""v0.1.182 回归：模板注册在并发下必须幂等、不丢条目、不复制孤儿副本。

实测缺陷（紫金选矿厂真实台账，19 车间 / _VOLUME_WORKERS=3）：

  · 整卷跑完 data/templates 从 1697 个文件涨到 11085 个，其中 10985 个是孤儿副本
    （索引里查不到的重复拷贝），121 个被注册的模板与 templates_builtin 逐字节相同。
  · 同一次整卷里 12 个车间报「未找到表类型 X 的模板」，generated 从 36 掉到 11。

成因：`_load_template_index → append → _save_template_index` 是「读—改—写」，
三条路径（upload_template、_ensure_builtin_registered 里的两处）都没有互斥，
`_save_template_index` 也不是原子替换。并发下后写者覆盖先写者。

本测试用一个隔离的临时模板目录，反复并发调用，要求：
  ① 索引条目数稳定（不因并发减少）
  ② 模板目录文件数稳定（不因并发增加）
  ③ 索引始终可解析（不会读到半截 JSON）

用法：python3 tools/test_template_concurrency.py    退出码 0 = 全过
"""
import json
import os
import shutil
import sys
import tempfile
import threading

WB = os.environ.get("FANGONG_WB",
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WB)
os.environ.setdefault("FANGONG_NO_BROWSER", "1")

from app import template_engine as te  # noqa: E402

_PASS = [0]
_FAIL = []


def check(name, cond, detail=""):
    if cond:
        _PASS[0] += 1
        print(f"  [PASS] {name}")
    else:
        _FAIL.append(f"{name}  {detail}")
        print(f"  [FAIL] {name}  {detail}")


def main():
    tmpdir = tempfile.mkdtemp(prefix="tplconc_")
    # 隔离到临时目录，绝不碰真实模板库
    te.TEMPLATES_DIR = tmpdir
    te.TEMPLATE_INDEX_FILE = os.path.join(tmpdir, "template_index.json")

    # 造 12 个「内置模板」，每个内容不同，避免被同名复用逻辑合并
    src_dir = os.path.join(tmpdir, "_src")
    os.makedirs(src_dir, exist_ok=True)
    names = [f"内置模板_{i:02d}" for i in range(12)]
    paths = []
    for i, n in enumerate(names):
        p = os.path.join(src_dir, f"{n}.docx")
        with open(p, "wb") as f:
            f.write(b"PK\x03\x04FAKE-" + n.encode() + b"-" + b"x" * (100 + i))
        paths.append(p)

    ERROR = []

    def worker(idx):
        try:
            for _ in range(3):
                for p in paths:
                    nm = os.path.basename(p)[:-5]
                    te.upload_template(p, nm, f"监理确认表|{nm}", "并发测试")
        except Exception as e:  # noqa: BLE001
            ERROR.append(f"thread{idx}: {type(e).__name__}: {e}")

    print("=== 1. 8 线程并发注册 12 个模板 ===")
    ths = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()

    check("无线程抛异常", not ERROR, str(ERROR[:2]))

    try:
        idx = json.load(open(te.TEMPLATE_INDEX_FILE, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        check("索引可解析", False, f"{type(e).__name__}: {e}")
        idx = {"templates": []}
    else:
        check("索引可解析", True)

    items = idx.get("templates", [])
    got_names = {t.get("name") for t in items}
    check(f"条目数 == 12（实得 {len(items)}）", len(items) == 12, f"实得 {len(items)}")
    check("12 个名称全部在索引里", got_names == set(names),
          f"缺 {sorted(set(names) - got_names)}")
    check("无重名条目", len(got_names) == len(items),
          f"名称去重 {len(got_names)} vs 条目 {len(items)}")

    files = [f for f in os.listdir(tmpdir) if f.endswith((".docx", ".xlsx"))]
    check(f"模板目录只有 12 个副本（实得 {len(files)}）", len(files) == 12,
          f"实得 {len(files)}，多出 {len(files) - 12} 个孤儿副本")

    print("=== 2. 重复调用必须幂等（不再新增任何东西） ===")
    before_items, before_files = len(items), len(files)
    for p in paths:
        nm = os.path.basename(p)[:-5]
        te.upload_template(p, nm, f"监理确认表|{nm}", "重复测试")
    idx2 = json.load(open(te.TEMPLATE_INDEX_FILE, encoding="utf-8"))
    files2 = [f for f in os.listdir(tmpdir) if f.endswith((".docx", ".xlsx"))]
    check(f"条目数不变 {len(idx2['templates'])}/{before_items}",
          len(idx2["templates"]) == before_items)
    check(f"文件数不变 {len(files2)}/{before_files}", len(files2) == before_files)

    print("=== 3. 索引写入是原子替换（不留 tmp 文件） ===")
    leftovers = [f for f in os.listdir(tmpdir) if ".tmp." in f]
    check("无残留 tmp 文件", not leftovers, str(leftovers[:3]))

    shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    print(f"通过 {_PASS[0]} 项，失败 {len(_FAIL)} 项")
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
