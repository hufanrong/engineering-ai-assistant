#!/usr/bin/env python3
"""只读接口不得改写项目元数据（v0.1.221）

实测缺陷（本轮发现，非推测）：
    md5(a02e757d6ad9761221084a9107b324cd)  updated_at=2026-11-10 01:12:22
    → 只调一次 GET /api/projects/current
    md5(e14438041e2e5edd6488c3b96d7ce38a)  updated_at=2026-11-10 01:15:16

也就是说用户「什么都没做，只是打开看了一下」，工程的最后修改时间就被改掉了。
根因：`update_project_stats()` 无条件写盘并刷新 updated_at，而它挂在
`GET /api/projects/current` 这个只读接口上（打开页面就会调）。

为什么这不只是「一个时间戳显示得不准」：
`_pick_successor_project()` 用 updated_at 挑「最近动过的项目」作为删除后的接任者
（v0.1.215 那段）。只要看一眼，接任顺序就可能被改掉 —— 删除 A 之后，
系统可能把「我刚看过一眼的 B」当成接任者，而不是「真正最近动过的 C」。
这正是本项目反复出现的「同一件事两个答案」：界面说这项目刚更新过，
磁盘上却没有任何实际变化。

四条断言：
  [A] 统计值没变时，update_project_stats 不写盘（字节级：md5 不变）
  [B] 统计值没变时，updated_at 不被刷新
  [C] 统计值真的变了时，必须写盘且刷新 updated_at（不能为了不写而漏记）
  [D] GET /api/projects/current 连调 3 次，真实项目文件一个字节都不变

[D] 走真实 HTTP 接口（不是只测函数层）：这是「只读接口」这个身份的证明，
函数层测不到「谁在调它」。

运行：python3 tools/test_readonly_no_write.py   （退出码 0 = 全过）
"""
import hashlib
import json
import os
import sys
import tempfile

WB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WB)
os.environ.setdefault("FANGONG_NO_BROWSER", "1")

import app.config as config  # noqa: E402
import app.project_manager as pm  # noqa: E402

PASS = [0]
FAIL = []


def check(cond, label, detail=""):
    if cond:
        PASS[0] += 1
        print(f"  [PASS] {label}")
    else:
        FAIL.append(f"{label} {detail}")
        print(f"  [FAIL] {label} {detail}")


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def read_meta(pid):
    return json.load(open(pm._get_project_meta_path(pid), encoding="utf-8"))


def main():
    tmp = tempfile.mkdtemp(prefix="ro_nowrite_")
    real_data = config.DATA_DIR
    real_root = pm.PROJECTS_ROOT
    real_cur = pm.CURRENT_PROJECT_FILE
    try:
        # 全程临时项目根，绝不碰用户真实项目
        config.DATA_DIR = tmp
        pm.PROJECTS_ROOT = os.path.join(tmp, "projects")
        pm.CURRENT_PROJECT_FILE = os.path.join(tmp, "current_project.json")
        os.makedirs(pm.PROJECTS_ROOT, exist_ok=True)

        pid = pm.create_project("只读不写测试")["project"]["id"]
        pm.set_current_project(pid)
        meta_path = pm._get_project_meta_path(pid)
        # create_project 给的初始统计
        m0 = read_meta(pid)
        h0 = md5(meta_path)
        u0 = m0.get("updated_at")

        print("\n[A] 统计值没变 → 不写盘（字节级）")
        r = pm.update_project_stats(pid,
                                    file_count=m0.get("file_count"),
                                    device_count=m0.get("device_count"),
                                    workshop_count=m0.get("workshop_count"))
        check(r.get("ok") is True, "返回 ok=True（刷新不算失败）", str(r)[:80])
        check(r.get("changed") is False, "返回值标明 changed=False", f"changed={r.get('changed')}")
        check(md5(meta_path) == h0, "meta 文件 md5 未变（一个字节都没写）",
              f"{h0} -> {md5(meta_path)}")

        print("\n[B] 统计值没变 → updated_at 不被刷新")
        m1 = read_meta(pid)
        check(m1.get("updated_at") == u0, "updated_at 保持原值",
              f"{u0} -> {m1.get('updated_at')}")

        print("\n[B2] 传 None（不指定统计）也算「没变」")
        r_none = pm.update_project_stats(pid)
        check(r_none.get("changed") is False, "全 None 时 changed=False",
              f"changed={r_none.get('changed')}")
        check(md5(meta_path) == h0, "全 None 时 md5 仍未变", md5(meta_path))

        print("\n[C] 统计值真的变了 → 必须写盘并刷新 updated_at")
        r2 = pm.update_project_stats(pid, file_count=99)
        check(r2.get("ok") is True and r2.get("changed") is True,
              "真变化时 changed=True", str(r2)[:80])
        m2 = read_meta(pid)
        check(m2.get("file_count") == 99, "新统计值已落盘", str(m2.get("file_count")))
        check(md5(meta_path) != h0, "文件确实被写了（md5 已变）")
        # updated_at 允许同一秒内相同，这里比的是「写盘后读回的 updated_at 不早于原值」
        check(str(m2.get("updated_at")) >= str(u0), "updated_at 未倒退",
              f"{u0} -> {m2.get('updated_at')}")

        print("\n[C2] 只改一项、其余项传 None 时，其余统计值不得被清掉")
        r3 = pm.update_project_stats(pid, device_count=5)
        m3 = read_meta(pid)
        check(m3.get("file_count") == 99, "未指定的 file_count 保持 99",
              str(m3.get("file_count")))
        check(m3.get("device_count") == 5, "指定的 device_count 已更新",
              str(m3.get("device_count")))

        print("\n[D] GET /api/projects/current 连调 3 次，项目文件不得变")
        # 用独立进程起真服务，避免污染本进程的模块级常量
        import subprocess
        port = 8798
        boot = os.path.join(tmp, "_boot_srv.py")
        with open(boot, "w", encoding="utf-8") as f:
            f.write(
                "import os, sys\n"
                f"sys.path.insert(0, {WB!r})\n"
                "import app.config as c\n"
                f"c.DATA_DIR = {tmp!r}\n"
                f"c.PORT = {port}\n"
                "os.environ.setdefault('FANGONG_NO_BROWSER','1')\n"
                "import app.project_manager as pm\n"
                f"pm.PROJECTS_ROOT = {os.path.join(tmp,'projects')!r}\n"
                f"pm.CURRENT_PROJECT_FILE = {os.path.join(tmp,'current_project.json')!r}\n"
                "from app import main\n"
                "main.run()\n"
            )
        log = open(os.path.join(tmp, "srv.log"), "wb")
        p = subprocess.Popen([sys.executable, boot], cwd=WB,
                             stdout=log, stderr=log, start_new_session=True)
        try:
            import time
            import urllib.request
            base = f"http://127.0.0.1:{port}"
            up = False
            for _ in range(60):
                try:
                    urllib.request.urlopen(base + "/api/status", timeout=3).read()
                    up = True
                    break
                except Exception:
                    time.sleep(0.5)
            check(up, "独立进程服务已就绪", f"port={port}")

            # 让服务端当前项目指到测试项目
            req = urllib.request.Request(
                base + "/api/projects/switch",
                data=json.dumps({"project_id": pid}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10).read()

            # 先「结算」一次：新建项目的初始统计（create_project 写的是 0/0/0）与
            # 实时算出的统计可能不同，这一次调用属于合法的「真变化」，允许它写盘。
            # 这里要验的是**重复读取**不得再写 —— 所以必须先把这个窗口关掉，
            # 否则会把「首次对齐」误判成缺陷（第一版就是这么假红的）。
            urllib.request.urlopen(base + "/api/projects/current", timeout=10).read()

            # v0.1.221：必须跨过秒边界再验。
            # updated_at 是 `%Y-%m-%d %H:%M:%S` 秒级精度，若结算与下面 3 次调用落在
            # 同一秒内，旧实现（无条件写盘）写回的时间戳与原来**字符全等**，
            # md5 也就不变 —— 于是缺陷被验成 PASS。反向验证时实测踩到：
            # 把 update_project_stats 改回旧的「无条件写盘」，D 段两条断言照样全绿。
            # 一条验不出缺陷的断言比没有断言更坏，它教人忽略红灯。
            time.sleep(1.2)
            h_before = md5(meta_path)
            u_before = read_meta(pid).get("updated_at")
            for _ in range(3):
                urllib.request.urlopen(base + "/api/projects/current", timeout=10).read()
            h_after = md5(meta_path)
            u_after = read_meta(pid).get("updated_at")
            check(h_after == h_before, "统计已结算后，3 次 GET /api/projects/current 仍不写盘",
                  f"{h_before} -> {h_after}")
            check(u_after == u_before, "3 次调用后 updated_at 未变",
                  f"{u_before} -> {u_after}")

            # 反向：真改了统计，接口应能反映（不能为了不写而让统计停在旧值）
            print("\n[D2] 统计真的变了时，接口返回的统计必须是新值")
            # 直接改 index.json 造一个统计变化，再让接口刷新
            idx_path = os.path.join(pm.get_project_data_dir(pid), "index.json")
            idx = json.load(open(idx_path, encoding="utf-8")) if os.path.isfile(idx_path) else {}
            idx.setdefault("devices", {})
            idx["devices"]["probe-dev"] = {"name": "测试设备", "workshop": "某车间"}
            json.dump(idx, open(idx_path, "w", encoding="utf-8"), ensure_ascii=False)
            body = json.loads(urllib.request.urlopen(
                base + "/api/projects/current", timeout=10).read().decode())
            cur = (body or {}).get("project") or {}
            check(cur.get("device_count") is not None,
                  "接口返回 device_count", f"device_count={cur.get('device_count')}")
            check(md5(meta_path) != h_before,
                  "真变化后 meta 被写（说明不是「一律不写」而是「变了才写」")
        finally:
            try:
                p.terminate()
            except Exception:
                pass
            log.close()
    finally:
        config.DATA_DIR = real_data
        pm.PROJECTS_ROOT = real_root
        pm.CURRENT_PROJECT_FILE = real_cur
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n结果：{PASS[0]} passed, {len(FAIL)} failed")
    for f in FAIL:
        print(f"  FAIL: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
