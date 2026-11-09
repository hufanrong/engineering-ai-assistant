#!/usr/bin/env python3
"""重跑整卷不得覆盖已填写的卷内文件（v0.1.222）

实测缺陷（本轮发现，非推测）：
    `app/supervision_integration.py::_generate_volume_impl` 里两处落盘都是
        os.replace(src, dst)
    **无条件覆盖**卷内同名文件。而登记表 6 条全是 B 类，B 类表就是留给
    现场人工填实测数据的。用户填完再点一次「一键整卷」（补台账、换模板、
    加车间都是常事），手填内容被静默销毁，接口照样返回 ok=True、
    generated 里照样记「已生成」—— 用户看不出自己填的表没了。

更讽刺的是 `_check_generated()` 早就写好了，但它只在 volume_status 里
用来显示「这一项已生成」，真正出卷的路径一次都没调过它。
「知道怎么判断」和「判断了」是两件事。

本测试守五条：
  [A] 卷内已有同名文件 + overwrite=False → 内容字节不变、返回 kept 记账
  [B] 卷内已有同名文件 + overwrite=True  → 确实被替换（不能为了不覆盖而漏重建）
  [C] 卷内没有同名文件 → 正常落盘，动作记为 created
  [D] 待办清单里必须写明「已保留 N 项」，否则用户只看「生成 0 个」会以为出错
  [E] kept 条目要能跨车间合并（多车间整卷时不能只剩首个车间的账）

运行：python3 tools/test_volume_no_overwrite.py   （退出码 0 = 全过）
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

WB = os.environ.get("FANGONG_WB",
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WB)
os.environ.setdefault("FANGONG_NO_BROWSER", "1")

from app import supervision_integration as si  # noqa: E402
import app.project_manager as pm  # noqa: E402

_PASS = [0]
_FAIL = []


def check(name, cond, detail=""):
    if cond:
        _PASS[0] += 1
        print(f"  [PASS] {name}")
    else:
        _FAIL.append(f"{name}  {detail}")
        print(f"  [FAIL] {name}  {detail}")


def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def _make_project(root, pid, workshop="测试车间"):
    """造一个最小可用项目：1 台设备 + 1 条 A 类登记项（能真出表）。"""
    pd = os.path.join(root, "projects", pid)
    os.makedirs(pd, exist_ok=True)
    with open(os.path.join(pd, "project_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"id": pid, "name": "覆盖保护测试", "created_at": "2026-11-10 00:00:00",
                   "updated_at": "2026-11-10 00:00:00", "file_count": 0,
                   "device_count": 1, "workshop_count": 1}, f, ensure_ascii=False)
    with open(os.path.join(pd, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"devices": {"L1": {"name": "胶带输送机", "model": "X",
                                      "workshop": workshop, "unit": "台", "quantity": "1"}},
                   "files": {}, "workshops": {workshop: {}}}, f, ensure_ascii=False)
    with open(os.path.join(pd, "supervision_registry.json"), "w", encoding="utf-8") as f:
        json.dump([{"册": "设备安装", "序号": "1", "名称": "设备安装记录",
                    "表号": "SH/T3503-J302", "分类": "A"}], f, ensure_ascii=False)
    return pd


def main():
    print("=" * 66)
    print("重跑整卷不得覆盖已填写的卷内文件（v0.1.222）")
    print("=" * 66)

    tmp = tempfile.mkdtemp(prefix="vol_noov_")
    _root, _cur = pm.PROJECTS_ROOT, pm.CURRENT_PROJECT_FILE
    pid = "noov_proj"
    ws = "测试车间"
    vol = os.path.join(tmp, "projects", pid, "volumes", "设备安装", ws)
    try:
        pm.PROJECTS_ROOT = os.path.join(tmp, "projects")
        pm.CURRENT_PROJECT_FILE = os.path.join(tmp, "current_project.json")
        _make_project(tmp, pid, ws)
        os.makedirs(vol, exist_ok=True)

        # ---------------- [A] 默认不覆盖 ----------------
        print("\n[A] 卷内已有同名文件 + overwrite=False → 保留原文件")
        target = os.path.join(vol, "1_设备安装记录.docx")
        # 模拟「用户已经填好的表」：写一段可辨识的字节（不必是合法 docx，
        # 这条测的是落盘策略，不是文档渲染）
        with open(target, "wb") as f:
            f.write(b"HAND-FILLED-DATA-DO-NOT-OVERWRITE")
        h_before = md5(target)
        size_before = os.path.getsize(target)

        r1 = si.generate_volume(pid, "设备安装", ws, overwrite=False)
        kept = (r1.get("kept") or [])
        check("接口返回 ok（保留不是失败）", bool(r1.get("ok")) or bool(kept),
              f"ok={r1.get('ok')}, kept={len(kept)}")
        check("kept 账里记了这 1 项", len(kept) >= 1, f"实得 {len(kept)} 项")
        check("kept 条目带序号/名称/文件",
              all(k.get("序号") and k.get("名称") and k.get("文件") for k in kept),
              str(kept[:1]))
        check("★ 卷内文件字节未变（人工填写内容保住了）",
              md5(target) == h_before and os.path.getsize(target) == size_before,
              f"md5 {h_before} -> {md5(target)}, size {size_before} -> {os.path.getsize(target)}")
        check("原文件内容仍是人工填写的那段字节",
              open(target, "rb").read() == b"HAND-FILLED-DATA-DO-NOT-OVERWRITE",
              open(target, "rb").read()[:40])

        # ---------------- [A2] 待办清单必须交代「已保留」 ----------------
        # 注意顺序：必须在**这一次产生 kept 账的运行之后**立刻核对。
        # 首版把这段放到 [C] 之后，而 [C] 清空了卷目录、重跑一遍没有任何保留项，
        # 于是待办清单当然不含「已保留」—— 断言测的是最后一次运行，不是要测的那次。
        print("\n[A2] 待办清单要写明保留了几项（否则用户以为整卷出错了）")
        todo_path = os.path.join(vol, "_待办清单.md")
        check("待办清单已写出", os.path.exists(todo_path),
              todo_path if os.path.exists(todo_path) else "缺失")
        if os.path.exists(todo_path):
            txt = open(todo_path, encoding="utf-8").read()
            check("★ 待办清单含「已保留」章节", "已保留" in txt, txt[:300])
            check("待办清单说明了保留原因（未覆盖）",
                  "未覆盖" in txt or "没有覆盖" in txt, "")
            check("待办清单给出了重建办法（覆盖已有文件）",
                  "覆盖已有文件" in txt, "")

        # ---------------- [B] 显式覆盖 ----------------
        print("\n[B] overwrite=True → 必须真的重建（不能为了不覆盖而漏重建）")
        r2 = si.generate_volume(pid, "设备安装", ws, overwrite=True)
        check("覆盖模式下不产生 kept 账", len(r2.get("kept") or []) == 0,
              f"kept={len(r2.get('kept') or [])}")
        check("★ 卷内文件已被重新生成（不再是人工填写的那段字节）",
              open(target, "rb").read() != b"HAND-FILLED-DATA-DO-NOT-OVERWRITE",
              f"size={os.path.getsize(target)}")
        check("重建后仍是可打开的 docx",
              open(target, "rb").read(4) == b"PK\x03\x04",
              open(target, "rb").read(4))

        # ---------------- [C] 无同名文件 → created ----------------
        print("\n[C] 卷内没有同名文件 → 正常落盘（不能因为怕覆盖就什么都不出）")
        full = si._generate_volume_impl(pid, "设备安装", ws, overwrite=False)
        # 用一个全新的空卷目录重跑，确认会落盘
        shutil.rmtree(vol, ignore_errors=True)
        os.makedirs(vol, exist_ok=True)
        r3 = si.generate_volume(pid, "设备安装", ws, overwrite=False)
        check("空卷下正常生成", len(r3.get("generated") or []) >= 1,
              f"generated={len(r3.get('generated') or [])}")
        check("空卷下没有 kept 账（无旧文件可保留）", len(r3.get("kept") or []) == 0,
              f"kept={len(r3.get('kept') or [])}")
        check("文件真的落到卷目录",
              os.path.exists(os.path.join(vol, "1_设备安装记录.docx")),
              str(os.listdir(vol))[:200])

        # ---------------- [E] kept 跨车间合并 ----------------
        print("\n[E] kept 必须参与跨车间合并（多车间整卷不能只剩首个车间的账）")
        check("kept 在 MERGE_LIST_KEYS 里",
              "kept" in si.MERGE_LIST_KEYS, str(si.MERGE_LIST_KEYS))
        fake = {
            "车间A": {"kept": [{"序号": "1", "名称": "设备安装记录", "文件": "1_x.docx"}]},
            "车间B": {"kept": [{"序号": "1", "名称": "设备安装记录", "文件": "1_x.docx"}]},
        }
        merged = si._merge_workshop_results(fake, ["车间A", "车间B"])
        check("★ 两个车间的 kept 都合并进来了（按车间区分）",
              len(merged.get("kept") or []) == 2,
              f"实得 {len(merged.get('kept') or [])} 项（1 项 = 被误判重复丢弃）")
        _ws = {k.get("_车间") for k in (merged.get("kept") or [])}
        check("合并后的 kept 行带车间标签", _ws == {"车间A", "车间B"}, str(_ws))

        # ---------------- [F] 落盘助手本身的分支 ----------------
        print("\n[F] _place_volume_file 四个分支")
        d = tempfile.mkdtemp(prefix="place_")
        try:
            dst = os.path.join(d, "t.docx")
            src = os.path.join(d, "s.docx")
            open(src, "wb").write(b"NEW")
            a1, _ = si._place_volume_file(dst, src, overwrite=False)
            check("无旧文件 → created", a1 == "created", a1)
            check("src 已被移动（不留副本在 exports）", not os.path.exists(src), src)

            open(src, "wb").write(b"NEWER")
            a2, _ = si._place_volume_file(dst, src, overwrite=False)
            check("有旧文件且不覆盖 → kept", a2 == "kept", a2)
            check("kept 时旧文件内容不变", open(dst, "rb").read() == b"NEW",
                  open(dst, "rb").read())
            check("kept 时新渲染的临时副本被清掉", not os.path.exists(src), src)

            open(src, "wb").write(b"NEWER")
            a3, _ = si._place_volume_file(dst, src, overwrite=True)
            check("显式覆盖 → replaced", a3 == "replaced", a3)
            check("replaced 后内容是新的", open(dst, "rb").read() == b"NEWER",
                  open(dst, "rb").read())

            a4, _ = si._place_volume_file(dst, os.path.join(d, "nope.docx"), overwrite=True)
            check("源文件不存在 → no_source（上层照旧记账，不抛异常）",
                  a4 == "no_source", a4)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    finally:
        pm.PROJECTS_ROOT, pm.CURRENT_PROJECT_FILE = _root, _cur
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 66)
    p, f = _PASS[0], len(_FAIL)
    print(f"合计：{p} PASS / {f} FAIL")
    if _FAIL:
        for x in _FAIL:
            print(f"  FAIL: {x}")
    print("=" * 66)
    return 0 if f == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
