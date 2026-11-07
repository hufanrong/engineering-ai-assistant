"""删除当前项目后「当前项目指针」的回归测试（v0.1.215）

背景缺陷：
  project_manager.delete_project() 在删掉「当前项目」时，只做了一件事 ——
  os.remove(CURRENT_PROJECT_FILE)，指针直接消失。

  后果链（都是实测踩过的）：
    ① 用户删掉自己的项目后，下次打开程序 / 刷新页面，看到的是
       「当前未选择项目，请先新建或选择项目」，等于自己的工程不见了；
    ② 即使同一次会话里，前端 loadProjects() 重新拉 /api/projects/current
       拿到 ok:false，界面所有统计归零、上传区变灰；
    ③ 自测（tools/selftest.py）启动时如果读不到当前项目，_ORIGIN_PID 就是空，
       阶段⑥ 会落一条 `目标=?` 的 FAIL —— 那条断言本意是「证明比对是在用户
       真实项目上做的」，却因为指针丢了而永远证不了，全量自测出现 58/1。

  正确行为：删掉当前项目时，指针应该自动跳到「另一个还有资料的项目」；
  只有当**一个项目都不剩**时，才允许进入「未选择项目」状态（那时它是真的
  没有项目可选，不是把用户的项目弄丢了）。

断言：
  [A] 还有别的项目（其中一个是带资料的）→ 指针跳到带资料的那个
  [B] 只剩空壳项目 → 指针跳到某一个未被删的项目（不悬空）
  [C] 一个项目都不剩 → 指针文件被移除，状态=未选择项目（合法）
  [D] 删的不是当前项目 → 指针原样不动
  [E] delete_data=False（资料进回收站）路径同样自动跳转
  [F] 返回体带 switched_to，message 里写明跳到了哪个项目
  [G] 全程没有碰用户真实 data/（真实项目列表与 current_project.json 未变）

运行：python3 tools/test_delete_project_pointer.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.config as config  # noqa: E402
import app.project_manager as pm  # noqa: E402

RESULTS = []


def check(label, cond, detail=""):
    RESULTS.append({"label": label, "passed": bool(cond), "detail": detail})
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))


def _real_snapshot():
    """用户真实数据目录的快照：项目目录清单 + current_project.json 内容。

    只读，用来证明本测试没有污染真实工程（自测自己也可能成为
    「同一件事两个答案」：测试自称跑在临时目录，实际写进了用户项目）。
    """
    snap = {"projects": [], "current": None}
    try:
        if os.path.isdir(pm.PROJECTS_ROOT):
            snap["projects"] = sorted(os.listdir(pm.PROJECTS_ROOT))
    except Exception:  # noqa: BLE001
        pass
    try:
        if os.path.isfile(pm.CURRENT_PROJECT_FILE):
            with open(pm.CURRENT_PROJECT_FILE, "r", encoding="utf-8") as f:
                snap["current"] = f.read()
    except Exception:  # noqa: BLE001
        snap["current"] = "<读取失败>"
    return snap


def main():
    real = _real_snapshot()

    tmp = tempfile.mkdtemp(prefix="fgdelptr_")
    origin = {"DATA_DIR": config.DATA_DIR,
              "PROJECTS_ROOT": pm.PROJECTS_ROOT,
              "CURRENT_PROJECT_FILE": pm.CURRENT_PROJECT_FILE}
    try:
        config.DATA_DIR = tmp
        pm.PROJECTS_ROOT = os.path.join(tmp, "projects")
        pm.CURRENT_PROJECT_FILE = os.path.join(tmp, "current_project.json")
        os.makedirs(pm.PROJECTS_ROOT, exist_ok=True)

        def cur_id():
            c = pm.get_current_project()
            return (c or {}).get("id") or ""

        def cur_name():
            c = pm.get_current_project()
            return (c or {}).get("name") or ""

        # ---------- [A] 有带资料的项目时，跳到它 ----------
        print("\n[A] 删当前项目 → 指针跳到「还有资料」的那个项目")
        a_empty = pm.create_project("A_空壳")["project"]["id"]
        b_data = pm.create_project("B_有资料")["project"]["id"]
        c_cur = pm.create_project("C_当前")["project"]["id"]
        pm.update_project_stats(b_data, file_count=5, device_count=228)
        pm.update_project_stats(c_cur, file_count=1, device_count=3)
        pm.set_current_project(c_cur)
        check("A0 前置：当前项目=C", cur_id() == c_cur, f"实际={cur_id()}")

        r = pm.delete_project(c_cur, backup=False, delete_data=True)
        check("A1 删除返回 ok", r.get("ok") is True, f"{r.get('error') or ''}")
        check("A2 指针不悬空：指向 B（有资料的那个）",
              cur_id() == b_data, f"实际={cur_id()}({cur_name()}) 期望={b_data}")
        check("A3 不跳到只有空壳的 A", cur_id() != a_empty, f"实际={cur_id()}")
        check("A4 返回体记录 switched_to",
              isinstance(r.get("switched_to"), dict)
              and r["switched_to"].get("id") == b_data,
              f"switched_to={r.get('switched_to')}")
        check("A5 message 写明已切换到哪个项目",
              "B_有资料" in (r.get("message") or ""), f"message={r.get('message')}")

        # ---------- [B] 只剩空壳项目 → 也要跳，不能悬空 ----------
        print("\n[B] 只剩空壳项目 → 跳到未被删的某个项目（不悬空）")
        pm.delete_project(b_data, backup=False, delete_data=True)  # 删的是当前项目 → 应跳到 A
        check("B1 删掉当前项目后仍有当前项目", bool(cur_id()), f"实际={cur_id() or '空'}")
        check("B2 指针指向 A_空壳", cur_id() == a_empty, f"实际={cur_id()}")

        # ---------- [C] 一个都不剩 → 合法地进入「未选择项目」 ----------
        print("\n[C] 删到只剩 0 个项目 → 指针文件被移除（合法）")
        pm.delete_project(a_empty, backup=False, delete_data=True)
        check("C1 当前项目为空", cur_id() == "", f"实际={cur_id() or '空'}")
        check("C2 指针文件已移除", not os.path.isfile(pm.CURRENT_PROJECT_FILE),
              f"存在={os.path.isfile(pm.CURRENT_PROJECT_FILE)}")
        check("C3 项目列表确实为空",
              len(pm.list_projects()) == 0, f"剩 {len(pm.list_projects())} 个")

        # ---------- [D] 删的不是当前项目 → 指针不动 ----------
        print("\n[D] 删非当前项目 → 指针原样不动")
        d1 = pm.create_project("D1_当前")["project"]["id"]
        d2 = pm.create_project("D2_非当前")["project"]["id"]
        pm.set_current_project(d1)
        _before = cur_id()
        r = pm.delete_project(d2, backup=False, delete_data=True)
        check("D1 返回 ok", r.get("ok") is True, f"{r.get('error') or ''}")
        check("D2 指针仍是 D1", cur_id() == d1, f"实际={cur_id()} 之前={_before}")
        check("D3 未误报 switched_to", not r.get("switched_to"),
              f"switched_to={r.get('switched_to')}")

        # ---------- [E] 资料进回收站的路径同样要跳 ----------
        print("\n[E] delete_data=False（资料移入回收站）也要自动跳转")
        e1 = pm.create_project("E1_当前")["project"]["id"]
        e2 = pm.create_project("E2_留任")["project"]["id"]
        pm.update_project_stats(e2, file_count=2)
        pm.set_current_project(e1)
        r = pm.delete_project(e1, backup=False, delete_data=False)
        check("E1 返回 ok（资料已保留）", r.get("ok") is True and r.get("data_deleted") is False,
              f"{r.get('error') or r.get('data_deleted')}")
        check("E2 指针跳到 E2", cur_id() == e2, f"实际={cur_id()}")
        check("E3 资料进了回收站（没被真删）",
              bool(r.get("recycled_to")) and os.path.isdir(r.get("recycled_to") or ""),
              f"recycled_to={r.get('recycled_to')}")

        # ---------- [F] 自测口径：删完后 /api/projects/current 对应的读取路径可用 ----------
        print("\n[F] 删除后「读当前项目」这条路径仍然可用")
        c = pm.get_current_project()
        check("F1 get_current_project() 返回真实项目（不是指向已删 id 的空壳）",
              bool(c) and c.get("id") == e2, f"实际={(c or {}).get('id')}")
        check("F2 该项目的目录真实存在",
              os.path.isdir(pm._get_project_dir(e2)), pm._get_project_dir(e2))

        # ---------- [H] 启动自愈：指针已丢（历史遗留机器）也要救回来 ----------
        print("\n[H] ensure_current_project() 启动自愈")
        h1 = pm.ensure_current_project()
        check("H1 指针正常时不误改", h1.get("healed") is False
              and (h1.get("project") or {}).get("id") == e2,
              f"healed={h1.get('healed')} project={(h1.get('project') or {}).get('id')}")

        # 模拟 v0.1.214 及之前删当前项目留下的状态：指针文件被删、项目还在
        if os.path.isfile(pm.CURRENT_PROJECT_FILE):
            os.remove(pm.CURRENT_PROJECT_FILE)
        check("H2 前置：指针已丢", pm.get_current_project() is None, "")
        h2 = pm.ensure_current_project()
        check("H3 指针丢失 → 自动指回一个有资料的项目",
              h2.get("healed") is True
              and (h2.get("project") or {}).get("id") == e2,
              f"healed={h2.get('healed')} project={(h2.get('project') or {}).get('id')}")
        check("H4 自愈后指针文件真实写回",
              os.path.isfile(pm.CURRENT_PROJECT_FILE), "")
        check("H5 自愈后读当前项目可用",
              (pm.get_current_project() or {}).get("id") == e2,
              f"实际={(pm.get_current_project() or {}).get('id')}")
        h3 = pm.ensure_current_project()
        check("H6 自愈幂等（第二次不重复动作）",
              h3.get("healed") is False, f"healed={h3.get('healed')}")

        # 指针指向一个不存在的项目（手工删目录 / 迁移数据目录）
        with open(pm.CURRENT_PROJECT_FILE, "w", encoding="utf-8") as f:
            json.dump({"project_id": "no_such_pid", "project_name": "已消失"},
                      f, ensure_ascii=False)
        check("H7 前置：指针指向已不存在项目",
              pm.get_current_project() is None, "")
        h4 = pm.ensure_current_project()
        check("H8 指针指向已删项目 → 自动改指有效项目",
              h4.get("healed") is True
              and (h4.get("project") or {}).get("id") == e2,
              f"healed={h4.get('healed')} project={(h4.get('project') or {}).get('id')}")

        # 一个项目都没有时，不许凭空造项目，也不许硬写一个不存在的指针
        for _pid in [x["id"] for x in pm.list_projects()]:
            pm.delete_project(_pid, backup=False, delete_data=False)
        if os.path.isfile(pm.CURRENT_PROJECT_FILE):
            os.remove(pm.CURRENT_PROJECT_FILE)
        check("H9 前置：项目列表为空", len(pm.list_projects()) == 0,
              f"剩 {len(pm.list_projects())} 个")
        h5 = pm.ensure_current_project()
        check("H10 无项目时不动作（未选择是真实状态）",
              h5.get("healed") is False and h5.get("project") is None,
              f"healed={h5.get('healed')} project={h5.get('project')}")
        check("H11 无项目时不伪造指针文件",
              not os.path.isfile(pm.CURRENT_PROJECT_FILE), "")

    finally:
        config.DATA_DIR = origin["DATA_DIR"]
        pm.PROJECTS_ROOT = origin["PROJECTS_ROOT"]
        pm.CURRENT_PROJECT_FILE = origin["CURRENT_PROJECT_FILE"]
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass

    # ---------- [G] 全程没碰用户真实数据 ----------
    print("\n[G] 用户真实数据目录未被本测试改动")
    now = _real_snapshot()
    check("G1 真实项目目录清单未变", now["projects"] == real["projects"],
          f"前 {len(real['projects'])} 个 / 后 {len(now['projects'])} 个")
    check("G2 真实 current_project.json 内容未变", now["current"] == real["current"],
          "内容不同" if now["current"] != real["current"] else "")

    ok = sum(1 for x in RESULTS if x["passed"])
    bad = len(RESULTS) - ok
    print("-" * 62)
    print(f"结果：通过 {ok} / 失败 {bad}")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_delete_project_pointer_report.json"),
              "w", encoding="utf-8") as f:
        json.dump({"total": len(RESULTS), "passed": ok, "failed": bad,
                   "results": RESULTS}, f, ensure_ascii=False, indent=2)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
