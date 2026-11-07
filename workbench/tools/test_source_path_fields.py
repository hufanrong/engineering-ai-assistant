#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：源文件路径的「字段名口径」与「重解析是否真的执行」。

## 为什么有这个测试（v0.1.212）

实测（2026-11-07 19:2x，工作树 0.1.212，项目 322fef90）用户点「重解析」没反应，
顺着查下去是三个叠在一起的缺陷，每一个单独看都"接口正常返回"：

    ① 字段名口径分裂：扫描器写进索引的是 `file_path`，
       而 /api/files、/api/files/preview、/api/files/download、
       /api/files/reparse 全部只读 `source_path` —— 索引里根本没这个键。
       于是对**每一个**扫描入库的文件：
         reparse  -> {"ok":false,"error":"源文件不存在，无法重解析"}
         download -> {"ok":false,"error":"源文件不存在"}
         preview  -> {"ok":false,"error":"无预览内容"}
       而文件好端端躺在 data/uploads/ 里（实测 18031 字节）。

    ② 路径本身也可能过期：索引记的是 "..._<12位sha>_设备台账.xlsx"，
       磁盘上只有 1 个前缀和 6 个前缀的副本。只修字段名仍然找不到文件。

    ③ 即使路径找对了，reparse 的后台线程调 `_sc.index_result()` ——
       这个函数在 scanner 里**根本不存在**，AttributeError 被
       `except Exception: pass` 全吞，接口照样回「已加入重解析队列」。
       用户点一次重解析，一个字节都不会被处理，界面还显示成功。

本测试钉死四件事：
  [A] _fx_source_path 优先取存在的路径，字段名 source_path / file_path / path 都认
  [B] 索引路径过期时，按 sha 前缀在 uploads 里找回，且**必须全量 sha256 相等**
      才允许返回（前缀只是前 12 位，猜错会把别的文件递给用户）
  [C] reparse_file 真实存在、真实产出解析缓存、索引里写的是 file_path
  [D] 源码里不得再出现 `index_result` 这种不存在的函数调用

全部用**临时目录 + 合成数据**，不碰真实项目数据目录。
"""
import hashlib
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


def check(name, expect, actual, ok, note=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}  {actual}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  expect={expect} actual={actual}  {note}")


def main():
    global PASS, FAIL

    print("=" * 64)
    print("源文件路径字段口径 + 重解析执行 回归测试（v0.1.212）")
    print("=" * 64)

    from app import main as M
    from app import scanner as S
    from app import config as C

    tmp = tempfile.mkdtemp(prefix="fgpath_")
    try:
        # ---------- [A] 字段名三种写法都认，且只认真实存在的 ----------
        print("\n[A] _fx_source_path 认 source_path / file_path / path")
        good = os.path.join(tmp, "a.xlsx")
        with open(good, "wb") as f:
            f.write(b"x")
        check("A1 认 source_path", good, M._fx_source_path({"source_path": good}),
              M._fx_source_path({"source_path": good}) == good)
        check("A2 认 file_path（扫描器写的字段）", good,
              M._fx_source_path({"file_path": good}),
              M._fx_source_path({"file_path": good}) == good)
        check("A3 认 path", good, M._fx_source_path({"path": good}),
              M._fx_source_path({"path": good}) == good)
        # 关键：不存在的路径不得返回（否则下游 os.path.exists 才拦，字段值仍骗人）
        gone = os.path.join(tmp, "nope.xlsx")
        got = M._fx_source_path({"file_path": gone})
        check("A4 不存在的路径不返回", "", repr(got), got == "",
              "返回过期路径会让调用方误判「有这个文件」")
        # 目录不是文件也不该被当成源文件
        d = os.path.join(tmp, "adir")
        os.makedirs(d, exist_ok=True)
        gotd = M._fx_source_path({"file_path": d})
        check("A5 目录不当作源文件", "", repr(gotd), gotd == "")

        # ---------- [B] 索引路径过期 → 按 sha 前缀找回且全量校验 ----------
        print("\n[B] 按 sha 前缀找回，且必须全量 sha256 相等")
        content = b"ledger-bytes-12345"
        sha = hashlib.sha256(content).hexdigest()
        up = os.path.join(tmp, "uploads")
        os.makedirs(up, exist_ok=True)
        real = os.path.join(up, f"{sha[:12]}_设备台账.xlsx")
        with open(real, "wb") as f:
            f.write(content)
        # 指向一个不存在的旧路径，逼它走找回分支
        info = {"file_path": os.path.join(up, f"{sha[:12]}_{sha[:12]}_x.xlsx"),
                "sha256": sha}
        old_cache = dict(M._FX_SHA_CACHE)
        old_dir = getattr(C, "DATA_DIR", None)
        try:
            M._FX_SHA_CACHE.clear()
            C.DATA_DIR = tmp
            got = M._fx_source_path(info)
            check("B1 过期路径能按 sha 找回真实文件", real, got, got == real)

            # 同名前缀但内容不同 = 必须拒绝（不能拿别的文件当源文件）
            bad = os.path.join(up, f"{sha[:12]}_坏文件.xlsx")
            with open(bad, "wb") as f:
                f.write(b"totally-different")
            M._FX_SHA_CACHE.clear()
            got2 = M._fx_find_upload_by_sha(sha)
            check("B2 前缀相同但内容不同不得误用", real, got2, got2 == real,
                  "同名前缀不是同一份文件的证据")

            # 只有坏文件时（删掉真文件）必须返回空，而不是退而求其次
            os.remove(real)
            M._FX_SHA_CACHE.clear()
            got3 = M._fx_find_upload_by_sha(sha)
            check("B3 校验不过一律返回空", "", repr(got3), got3 == "",
                  "猜错会把别的资料递给用户")
        finally:
            M._FX_SHA_CACHE.clear()
            M._FX_SHA_CACHE.update(old_cache)
            if old_dir is not None:
                C.DATA_DIR = old_dir

        # ---------- [C] reparse_file 真实存在并能真的产出缓存 ----------
        print("\n[C] reparse_file 真实执行（不是返回一句「已加入队列」）")
        check("C1 scanner 里有 reparse_file", True, hasattr(S, "reparse_file"),
              hasattr(S, "reparse_file"),
              "原来 reparse 调的是根本不存在的 index_result")
        # 自己造一个最小 xlsx，不依赖 selftest 的 samples（那目录跑完就删了，
        # 依赖它会让这条断言在大多数时候静默跳过 —— 跳过等于没验）。
        src = os.path.join(tmp, "设备台账.xlsx")
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["设备位号", "设备名称", "规格型号", "数量", "车间"])
            ws.append(["T-001", "粗碎机", "PE-900", "1", "粗碎站"])
            wb.save(src)
        except Exception:  # noqa: BLE001
            src = ""
        if not src or not os.path.exists(src):
            check("C2 能造出测试样本", True, False, False, "openpyxl 不可用")
        else:
            tdir = os.path.join(tmp, "proj")
            os.makedirs(tdir, exist_ok=True)
            r = S.reparse_file(src, data_dir=tdir)
            check("C2 返回 status=parsed", "parsed", r.get("status"),
                  r.get("status") == "parsed", str(r.get("error"))[:80])
            cache = os.path.join(tdir, "parsed_cache", f"{r.get('sha256')}.json")
            check("C3 真的产出了解析缓存", True, os.path.exists(cache),
                  os.path.exists(cache), "缺少缓存时 AI 检索恒 0 命中")
            idxp = os.path.join(tdir, "index.json")
            idx = json.load(open(idxp, encoding="utf-8")) if os.path.exists(idxp) else {}
            rec = idx.get(r.get("sha256") or "", {})
            check("C4 索引写的是 file_path（与前端读取口径同源）", True,
                  ("file_path" in rec) or bool(idx),
                  ("file_path" in rec),
                  f"keys={sorted(rec.keys())[:6]}")

        # ---------- [C5] 测试不得污染用户的真实待上传队列 ----------
        print("\n[C5] 临时目录里重解析不得写进真实项目队列")
        from app import upload_queue as UQ
        old_q, old_l = UQ.QUEUE_DIR, UQ.LOG_PATH
        try:
            real_q = os.path.join(os.path.abspath(C.DATA_DIR), "uploads")
            # 真实队列目录 = 当前项目 upload_queue（不存在也算 0）
            from app import project_manager as PM
            _cur = PM.get_current_project() or {}
            _pid = _cur.get("id") or ""
            real_pq = (os.path.join(PM.get_project_data_dir(_pid), "upload_queue")
                       if _pid else "")
            n_before = (len([f for f in os.listdir(real_pq)
                             if f.endswith(".json") and not f.startswith("_")])
                        if real_pq and os.path.isdir(real_pq) else 0)
            tdir2 = os.path.join(tmp, "proj_q")
            os.makedirs(tdir2, exist_ok=True)
            srcq = os.path.join(tmp, "q.xlsx")
            try:
                import openpyxl
                _wb = openpyxl.Workbook()
                _wb.active.append(["设备位号"]); _wb.active.append(["Q-1"])
                _wb.save(srcq)
            except Exception:  # noqa: BLE001
                srcq = ""
            if srcq and os.path.exists(srcq):
                # v0.1.214：真实项目的车间归属必须在**调用之前**快照。
                # 第一版写在调用之后，before/after 都是「已污染」的同一份，
                # C8 于是恒 PASS —— 测试自己成了「同一件事两个答案」。
                real_wa = (os.path.join(PM.get_project_data_dir(_pid), "workshop_assign.json")
                           if _pid else "")
                _wa_before = {}
                if real_wa and os.path.isfile(real_wa):
                    try:
                        _wa_before = json.load(open(real_wa, encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        _wa_before = {}
                S.reparse_file(srcq, data_dir=tdir2)
                n_proj = (len([f for f in os.listdir(os.path.join(tdir2, "upload_queue"))
                               if f.endswith(".json") and not f.startswith("_")])
                          if os.path.isdir(os.path.join(tdir2, "upload_queue")) else 0)
                check("C5 包落在临时目录队列里", ">=1", n_proj, n_proj >= 1,
                      "否则说明 enqueue 没跟 data_dir 走")
                n_after = (len([f for f in os.listdir(real_pq)
                                if f.endswith(".json") and not f.startswith("_")])
                           if real_pq and os.path.isdir(real_pq) else 0)
                check("C6 真实项目队列条目数未变", n_before, n_after,
                      n_after == n_before,
                      "测试往用户真实队列写入 = 用户看到莫名的待上传文件")

                # v0.1.214：与 enqueue 同一类的第二处落点 —— 车间归属。
                # 实测事故：真实项目 322fef90 的 workshop_assign.json 22 条里
                # 21 条指向 /tmp/fgpath_*，全是单测样本；界面上「待人工确认」
                # 从 0 涨到 10，用户看到一堆自己没上传过的文件。
                _wa_tmp = os.path.join(tdir2, "workshop_assign.json")
                _wa_after = {}
                if real_wa and os.path.isfile(real_wa):
                    try:
                        _wa_after = json.load(open(real_wa, encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        _wa_after = {}
                _new = sorted(set(_wa_after) - set(_wa_before))
                check("C7 车间归属落在临时目录", "临时目录有 workshop_assign.json",
                      os.path.basename(_wa_tmp) if os.path.isfile(_wa_tmp) else "缺失",
                      os.path.isfile(_wa_tmp),
                      "分配没跟 data_dir 走时，它会写进当前项目而不是这里")
                # v0.1.214 反向验证时发现的第一版写法有漏洞：只比「键集合差异」。
                # 测试样本内容每次都一样 → sha 相同 → 键早就存在于真实项目里，
                # 于是 set 差为空、C8 照样 PASS，而它其实**覆盖写了**那条记录。
                # 判据改成按内容全等比较（含 ts 字段变化），才抓得住覆盖写入。
                _changed = sorted(k for k in _wa_after
                                  if _wa_before.get(k) != _wa_after.get(k))
                check("C8 真实项目车间归属未被新增或改写", "内容全等",
                      f"变更 {len(_changed)} 条 新增 {len(_new)} 条",
                      (_wa_after == _wa_before),
                      "测试往用户真实项目写车间归属 = 界面多出没上传过的待确认文件")
                # C9：真实项目里不该存在指向临时目录的车间归属记录。
                # 这是「已经发生的污染」的看门狗 —— 只看本次有没有新增，
                # 查不出上一轮已经写进去的垃圾。
                _tmpy = sorted(k for k, v in (_wa_after or {}).items()
                               if isinstance(v, dict)
                               and str(v.get("file_path") or "").startswith("/tmp/"))
                check("C9 真实项目无 /tmp 测试残留", "0 条",
                      f"{len(_tmpy)} 条", len(_tmpy) == 0,
                      "这些是单测写进用户项目的记录，会导致界面出现没上传过的待确认文件")
        finally:
            UQ.QUEUE_DIR, UQ.LOG_PATH = old_q, old_l

        # ---------- [D] 源码里不许再调不存在的函数 ----------
        print("\n[D] 源码里不得再调用不存在的 index_result")
        # 必须用 AST 查**真实调用**，不能用正则查文本：
        # 修复说明里必然出现 index_result 这个词（我们就是拿它当反面案例写的注释），
        # 正则会把注释也算成残留，测试就永远是假红。
        import ast
        hits = []
        for root, _dirs, files in os.walk(os.path.join(WB, "app")):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(root, fn)
                try:
                    tree = ast.parse(open(p, encoding="utf-8", errors="ignore").read())
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute) and node.attr == "index_result":
                        hits.append(f"{os.path.relpath(p, WB)}:{node.lineno}")
        check("D1 无 index_result 调用残留", "无", hits, not hits,
              "调不存在的函数 + except pass = 谎报成功")
        # 且 reparse 必须真的调 reparse_file
        mp = os.path.join(WB, "app", "main.py")
        txt = open(mp, encoding="utf-8", errors="ignore").read()
        check("D2 reparse 路由调用真实的 reparse_file", True,
              "reparse_file" in txt, "reparse_file" in txt)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n===== 通过 {PASS} / 失败 {FAIL} =====")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
