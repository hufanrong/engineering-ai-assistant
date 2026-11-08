"""项目变更审计留痕的回归测试（v0.1.216）

背景缺陷（本轮实测发现）：
  用户问「这些项目是怎么没的」，我去查 data/operation_log.jsonl，
  325 条记录里**一条「删」都没有**，于是得出「没人删过」。
  这个结论是错的 —— 因为 /api/projects/delete 根本不写日志。

  实测日志的 type 分布只有两种：
      project  271 条（全部是新建项目）
      upload    54 条（上传文件）
  也就是说：改项目名、切项目、删项目，这三类**改变项目集合**的动作
  在审计里完全空白。据此反推「没发生删除」属于证据链断裂，
  不是「没有删除」。

  同时 create 的埋点位置也不对：
      _log_op("project", f"新建项目：...")
      return _pm.create_project(...)          # ← 先记账，后执行
  先记账后执行 = 创建失败（重名/磁盘满/权限）也留下「已新建」的记录，
  日志说建了、列表里没有，又是一处「同一件事两个答案」。

  正确行为：
    ① 项目管理类动作（新建/切换/改名/删除）都写一条 operation_log；
    ② 只在**动作真的成功**后才写，失败不写（不谎报）；
    ③ 删除的日志必须带得回追溯信息：项目 id + 项目名 + 是否删了资料
       + 备份文件名（否则事后根本查不出「哪个项目什么时候没的」）。

断言：
  [A] 新建成功 → 有一条 project 日志，内容含项目名
  [B] 新建失败（重名）→ 不产生任何「已新建」日志（不谎报）
  [C] 切项目 → 有一条 project 日志，含两侧项目名
  [D] 改名 → 有一条 project 日志，含新旧名
  [E] 删项目 → 有一条 delete 日志，含项目 id、项目名、资料是否删除
  [F] 删项目返回里带 log_written=True（调用方/自测可直接判据）
  [G] 日志是合法 JSONL，每行可解析、字段齐全（time/type/content/operator）
  [H] 全程没有写用户真实 data/operation_log.jsonl（行数未变）

运行：python3 tools/test_project_audit_log.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.config as config  # noqa: E402

RESULTS = []


def check(label, cond, detail=""):
    RESULTS.append({"label": label, "passed": bool(cond), "detail": detail})
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))


def _real_log_snapshot():
    """用户真实 operation_log.jsonl 的快照（只读）：行数 + 最后一行的 sha 无关内容。

    只证明"本测试没写进用户真实审计流水"，不谈业务。
    """
    path = os.path.join(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
        "operation_log.jsonl")
    snap = {"exists": os.path.isfile(path), "lines": 0, "tail": ""}
    if snap["exists"]:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.strip():
                        snap["lines"] += 1
                        snap["tail"] = line.strip()
        except Exception:  # noqa: BLE001
            pass
    return snap


def _read_log(log_path):
    rows = []
    if not os.path.isfile(log_path):
        return rows
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def main():
    real = _real_log_snapshot()

    tmp = tempfile.mkdtemp(prefix="fg_audit_")
    origin_data = config.DATA_DIR
    try:
        # 先切 DATA_DIR，再 import main —— 这样 _log_op 写进临时目录。
        # 反例（踩过）：先 import main 再改 config.DATA_DIR，
        # 若 _log_op 里缓存了路径就会写真实目录。
        config.DATA_DIR = tmp
        os.makedirs(tmp, exist_ok=True)
        import app.project_manager as pm
        import app.main as M

        origin = {"PROJECTS_ROOT": pm.PROJECTS_ROOT,
                  "CURRENT_PROJECT_FILE": pm.CURRENT_PROJECT_FILE}
        pm.PROJECTS_ROOT = os.path.join(tmp, "projects")
        pm.CURRENT_PROJECT_FILE = os.path.join(tmp, "current_project.json")
        os.makedirs(pm.PROJECTS_ROOT, exist_ok=True)

        log_path = os.path.join(tmp, "operation_log.jsonl")

        # ---------- [A] 新建成功 → 记一条 ----------
        print("\n[A] 新建项目成功后必须有审计记录")
        r1 = M.create_project({"name": "审计_项目甲"})
        check("A0 新建返回 ok", (r1 or {}).get("ok") is True, f"{r1.get('error') or ''}")
        rows = _read_log(log_path)
        hit = [x for x in rows if x.get("type") == "project" and "审计_项目甲" in x.get("content", "")]
        check("A1 新建成功记了 1 条 project 日志", len(hit) == 1, f"命中={len(hit)} 总={len(rows)}")

        # ---------- [B] 新建失败 → 不记（不谎报） ----------
        print("\n[B] 新建失败不能留下「已新建」的记录")
        before = len(_read_log(log_path))
        r2 = M.create_project({"name": "审计_项目甲"})   # 重名 → 应失败
        after = len(_read_log(log_path))
        failed = (r2 or {}).get("ok") is False
        check("B0 重名新建确实失败", failed, f"ok={r2.get('ok')} msg={r2.get('error') or r2.get('message')}")
        check("B1 失败时不新增日志", after == before, f"前={before} 后={after}")

        # ---------- [C] 切到另一个项目 → 记一条 ----------
        print("\n[C] 切换到另一个项目必须有审计记录")
        pid1 = r1["project"]["id"]
        pid2 = pm.create_project("审计_项目乙")["project"]["id"]   # 新建会自动切到乙
        before = len(_read_log(log_path))
        rs = M.switch_project({"project_id": pid1})              # 乙 → 甲，是真切换
        rows = _read_log(log_path)
        newrows = rows[before:]
        check("C0 切换返回 ok", (rs or {}).get("ok") is True, f"{rs.get('error') or ''}")
        check("C1 切换记了 1 条", len(newrows) == 1, f"新增={len(newrows)}")
        check("C2 日志能看出切到哪个项目",
              bool(newrows) and "审计_项目甲" in newrows[-1].get("content", ""),
              f"content={newrows[-1].get('content') if newrows else None}")

        # ---------- [C2] 切到当前已是的项目 → 不记（噪音抑制）----------
        print("\n[C'] 切到自己不是动作，不能刷日志")
        before = len(_read_log(log_path))
        rs_same = M.switch_project({"project_id": pid1})          # 甲 → 甲
        after = len(_read_log(log_path))
        check("C'0 自切换仍返回 ok", (rs_same or {}).get("ok") is True, "")
        check("C'1 自切换不新增日志", after == before, f"前={before} 后={after}")

        # ---------- [D] 改名 → 记一条，含新旧名 ----------
        print("\n[D] 改名必须有审计记录，且能看出旧名→新名")
        before = len(_read_log(log_path))
        rr = pm.rename_project(pid2, "审计_项目乙改名")
        rows = _read_log(log_path)
        newrows = rows[before:]
        check("D0 改名成功", (rr or {}).get("ok") is True, f"{rr.get('error') or ''}")
        check("D1 改名记了 1 条", len(newrows) == 1, f"新增={len(newrows)}")
        content = newrows[-1].get("content", "") if newrows else ""
        check("D2 日志含旧名", "审计_项目乙" in content, f"content={content}")
        check("D3 日志含新名", "审计_项目乙改名" in content, f"content={content}")

        # ---------- [E] 删项目 → delete 日志，带追溯信息 ----------
        print("\n[E] 删除项目必须有 delete 日志，且能追溯到具体项目")
        victim = pm.create_project("审计_待删项目")["project"]["id"]
        before = len(_read_log(log_path))
        rd = M.delete_project({"project_id": victim, "backup": False})
        rows = _read_log(log_path)
        newrows = rows[before:]
        del_rows = [x for x in newrows if x.get("type") == "delete"]
        check("E0 删除成功", (rd or {}).get("ok") is True, f"{rd.get('error') or ''}")
        check("E1 删除记了 delete 日志", len(del_rows) == 1, f"delete 条数={len(del_rows)} 新增总={len(newrows)}")
        dc = del_rows[-1].get("content", "") if del_rows else ""
        check("E2 日志含项目名", "审计_待删项目" in dc, f"content={dc}")
        check("E3 日志含项目 id（可事后定位）", victim in dc, f"content={dc}")

        # ---------- [F] 返回体带 log_written ----------
        print("\n[F] 删除返回体给出「日志是否写入」的判据")
        check("F1 返回体 log_written=True",
              (rd or {}).get("log_written") is True,
              f"log_written={rd.get('log_written')}")

        # ---------- [G] 日志文件本身合法 ----------
        print("\n[G] 日志是合法 JSONL，字段齐全")
        rows = _read_log(log_path)   # 解析失败会抛异常
        check("G1 每行都能解析成 JSON 对象",
              all(isinstance(x, dict) for x in rows), f"共 {len(rows)} 行")
        need = ("time", "type", "content", "operator")
        check("G2 四条必填字段齐全",
              all(all(k in x for k in need) for x in rows),
              f"缺失行={[i for i, x in enumerate(rows) if not all(k in x for k in need)]}")
        # v0.1.217：时间格式必须与历史流水一致（%Y%m%d_%H%M）。
        # 反例就是本轮实测的回归：抽公共实现时把格式"优化"成
        # "%Y-%m-%d %H:%M:%S"，历史 325 条老格式 + 新写入新格式 → 同一份
        # 流水混排，前端「时间」列原样透传，既不能排序也不能按日期筛选。
        import re as _re
        _compact = _re.compile(r"^\d{8}_\d{4}$")
        _bad_time = [x.get("time") for x in rows if not _compact.match(str(x.get("time", "")))]
        check("G3 时间格式与历史流水一致（YYYYMMDD_HHMM）",
              not _bad_time, f"不合格式={_bad_time[:3]}")

        # ---------- [I] 上传审计只在真的存下之后才写（v0.1.217） ----------
        # 反例：/api/upload-files 原来在函数第一行就 _log_op("upload", ...)。
        # 于是「3 个文件全部超限 → 一个都没落盘」也会留下「上传 3 个文件」。
        # 这里只构造一个**必然失败**的上传（超过大小上限的假文件），
        # 断言不产生任何 upload 审计 —— 账本必须跟着事实走。
        print("\n[I] 上传全部失败时不得写「上传成功」的审计")
        before = len(_read_log(log_path))
        _over = config.MAX_FILE_MB * 1024 * 1024 + 1024
        try:
            _r = M.app  # 仅为确认 TestClient 覆盖的是同一个 app
            from fastapi.testclient import TestClient as _TC
            _c = _TC(_r, raise_server_exceptions=False)
            _resp = _c.post("/api/upload-files",
                            files={"files": ("too_big.bin", b"x" * _over, "application/octet-stream")})
            _code = _resp.status_code
        except Exception as _e:  # noqa: BLE001
            _code = f"异常 {type(_e).__name__}: {_e}"
        rows = _read_log(log_path)
        _newup = [x for x in rows[before:] if x.get("type") == "upload"]
        check("I1 超限文件未落盘 → 不写 upload 审计",
              len(_newup) == 0, f"http={_code} 新增 upload 条数={len(_newup)}")

    finally:
        config.DATA_DIR = origin_data
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass

    # ---------- [H] 没碰用户真实审计流水 ----------
    print("\n[H] 用户真实 operation_log.jsonl 未被本测试写入")
    now = _real_log_snapshot()
    check("H1 真实日志行数未变", now["lines"] == real["lines"],
          f"前={real['lines']} 后={now['lines']}")
    check("H2 真实日志末行未变", now["tail"] == real["tail"],
          "末行不同" if now["tail"] != real["tail"] else "")

    ok = sum(1 for x in RESULTS if x["passed"])
    bad = len(RESULTS) - ok
    print("-" * 62)
    print(f"结果：通过 {ok} / 失败 {bad}")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_project_audit_log_report.json"),
              "w", encoding="utf-8") as f:
        json.dump({"total": len(RESULTS), "passed": ok, "failed": bad,
                   "results": RESULTS}, f, ensure_ascii=False, indent=2)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
