#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：解析缓存（parsed_cache）的「读写同口径」。

## 为什么有这个测试（v0.1.211）

本项目反复出现的一类缺陷是「同一件事两个答案」：同一个 `parsed_cache`
有两条取值路径，两边都「正常返回」，于是人工点界面完全看不出错。

实测（2026-11-07 13:1x，工作树 0.1.210，项目 322fef90）：

    写入口 scanner._save_parsed_cache() → _get_data_dir() → 项目级
            data/projects/<id>/parsed_cache/
    读取口 main.py 里 6 处写死 config.DATA_DIR/parsed_cache（全局）

后果链条：
  · AI 助手降级关键词检索 search_keyword() 以 vector_db 的同级目录
    作为 parsed_cache —— 即项目级。项目级缓存读不到，于是
    sources.project 恒为 0；verify_ai.js 实测 4 项 FAIL。
  · 现场记录 OCR 回写、OCR 文本收集、设备车间重建、聊天记录摘要
    同样读不到项目缓存，全部静默返回空。

本测试钉死三件事：
  [A] 读取候选目录必须「项目级在前、全局在后」且去重
  [B] 查找逻辑本身正确：缓存放在任一候选目录里都要能被找到
      （用**临时目录 + 合成数据**验证，不依赖真实项目状态 ——
       真实数据的自洽性由 selftest 阶段⑥ 断言，单元测试不能因为
       用户数据坏了就长期报红）
  [C] 源码里不得再有写死的全局 parsed_cache 读取路径
      （只允许 _parsed_cache_dirs 内部那一处兜底）
  [D] 写入口与读入口指向同一数据目录

全部只读，不写真实数据目录。
"""
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.dirname(HERE)
sys.path.insert(0, WB)

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


def main():
    global PASS, FAIL

    print("=" * 60)
    print("解析缓存口径回归测试（v0.1.211）")
    print("=" * 60)

    from app import main as M
    from app import config as C

    # ---------- [A] 候选目录顺序与去重 ----------
    print("\n[A] _parsed_cache_dirs() 顺序与去重")
    dirs = M._parsed_cache_dirs()
    check("返回非空列表", isinstance(dirs, list) and len(dirs) >= 1, f"dirs={dirs}")

    expect_global = os.path.abspath(os.path.join(C.DATA_DIR, "parsed_cache"))
    last = os.path.abspath(dirs[-1])
    check("全局目录在最后（兜底）", last == expect_global,
          f"last={last} expect={expect_global}")

    ab = [os.path.abspath(d) for d in dirs]
    check("无重复条目", len(ab) == len(set(ab)), f"{ab}")

    try:
        from app import project_manager as pm
        cur = pm.get_current_project()
    except Exception:  # noqa: BLE001
        cur = None
    if cur and cur.get("id"):
        pdir_pc = os.path.abspath(
            os.path.join(pm.get_project_data_dir(cur["id"]), "parsed_cache"))
        check("项目级目录排在首位", ab[0] == pdir_pc,
              f"first={ab[0]} expect={pdir_pc}")
    else:
        print("  [SKIP] 无当前项目，跳过「项目级优先」检查")

    # ---------- [B] 查找逻辑（临时目录 + 合成数据，不碰真实数据） ----------
    print("\n[B] _find_parsed_cache 查找逻辑")
    tmp = tempfile.mkdtemp(prefix="fg_pc_test_")
    try:
        good_sha = "a" * 64
        other_sha = "b" * 64

        # 只有全局目录里有 → 必须找得到（兜底路径有效）
        g_dir = os.path.join(tmp, "global", "parsed_cache")
        os.makedirs(g_dir, exist_ok=True)
        with open(os.path.join(g_dir, f"{good_sha}.json"), "w", encoding="utf-8") as f:
            json.dump({"sha256": good_sha, "file_name": "x.xlsx"}, f)

        # 用 monkeypatch 把候选目录指向临时目录
        orig = M._parsed_cache_dirs
        M._parsed_cache_dirs = lambda: [g_dir]

        got = M._find_parsed_cache(good_sha)
        check("缓存只在全局目录时能找到",
              got is not None and os.path.isfile(got),
              f"got={got}")

        # 不存在的 sha → 必须返回 None，不能抛出
        miss = M._find_parsed_cache(other_sha)
        check("缓存不存在时返回 None 且不抛异常", miss is None, f"got={miss}")

        # 项目级也有同名文件时，项目级必须优先命中
        p_dir = os.path.join(tmp, "project", "parsed_cache")
        os.makedirs(p_dir, exist_ok=True)
        with open(os.path.join(p_dir, f"{good_sha}.json"), "w", encoding="utf-8") as f:
            json.dump({"sha256": good_sha, "file_name": "x.xlsx", "from": "project"}, f)
        M._parsed_cache_dirs = lambda: [p_dir, g_dir]
        got2 = M._find_parsed_cache(good_sha)
        which = os.path.dirname(os.path.dirname(os.path.dirname(got2))) if got2 else ""
        check("项目级优先于全局命中",
              got2 is not None and os.path.dirname(got2) == p_dir,
              f"got={got2} 期望目录={p_dir}")

        M._parsed_cache_dirs = orig
        check("monkeypatch 已还原", M._parsed_cache_dirs is orig, "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------- [C] 源码里不得再有写死的全局读取 ----------
    print("\n[C] 源码不得写死全局 parsed_cache 读取路径")
    src_path = os.path.join(WB, "app", "main.py")
    src = open(src_path, encoding="utf-8").read()
    lines = src.splitlines()

    allowed_markers = ('dirs.append(os.path.join(config.DATA_DIR, "parsed_cache"))',)
    offenders = []
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith("#"):
            continue
        if 'config.DATA_DIR, "parsed_cache"' not in ln:
            continue
        if any(a in ln for a in allowed_markers):
            continue
        offenders.append(f"L{i}: {s[:90]}")
    check("除统一兜底外无其它硬编码全局读取",
          not offenders, f"残留 {len(offenders)} 处：{offenders}")

    check("读取统一走 _parsed_cache_dirs()",
          src.count("_parsed_cache_dirs()") >= 2,
          f"出现次数={src.count('_parsed_cache_dirs()')}")
    check("按 sha 查找统一走 _find_parsed_cache()",
          src.count("_find_parsed_cache(") >= 2,
          f"出现次数={src.count('_find_parsed_cache(')}")

    # ---------- [D] 写入口与读入口同源 ----------
    print("\n[D] 写入口与读入口指向同一数据目录")
    try:
        from app import scanner as sc
        write_dir = os.path.abspath(os.path.join(sc._get_data_dir(), "parsed_cache"))
        read_first = os.path.abspath(M._parsed_cache_dirs()[0])
        check("scanner 写入目录 == 读取首选目录",
              write_dir == read_first,
              f"写入={write_dir} 读取首选={read_first}")
    except Exception as e:  # noqa: BLE001
        print(f"  [SKIP] 无法解析数据目录：{e}")

    print("\n" + "=" * 60)
    print(f"结果：通过 {PASS} / 失败 {FAIL}")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
