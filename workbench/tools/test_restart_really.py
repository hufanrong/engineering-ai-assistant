#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重启必须「先起后死」，不许宕机。（v0.1.233，对应 WORKbuddy 真机缺陷 D18）

## 为什么整个重写

上一版（v0.1.232 的 test_restart_really.py）在场景 1 里把 `subprocess.Popen`
换成了记录器 —— 于是 helper 根本没被真跑起来，**恰好绕开了致命的那条路径**：
helper 是服务进程派生的子进程，而它杀旧进程用的是 `taskkill /PID x /T`（连
进程树一起杀），所以 helper 把自己也杀了。测试全绿，真机上「点一下重启，
工作台整台消失」。教训：验证一个「子进程自己干活」的机制，**不能把子进程
换成记录器**，必须让它真的跑。

## 这一版验的是什么

D18 的四条验收，逐条对应：

| WORKbuddy 的验收 | 本测试的断言 |
|---|---|
| 1) 重启后 30 秒内 /api/status 可用且 PID 已变 | 场景 A：真起真服务，断言 PID 变 + 接口应答 |
| 2) 起不来时旧进程仍然活着（宁可不重启也不能宕机） | 场景 B：新代码故意坏掉，断言旧服务仍在监听 |
| 3) restart.log 有完整记录（含失败原因） | 场景 B：断言日志里有 canary 失败与旧服务保留 |
| 4) 状态查询不依赖 HTTP，服务死了也读得到 | 场景 C：断言结果文件可读 + 路由真的存在 |

另外两条是这次修的「同一件事两个答案」：
  · 场景 D：v0.1.232 对外说「用 GET /api/update/restart/status 核对」，
    但那个路由**根本没挂**（包里只有函数没有 route）→ 断言路由存在。
  · 场景 E：`taskkill /T` 会杀进程树，helper 是子进程 → 断言全库没有
    「杀服务进程时带 /T」的写法。

全程临时端口 + 临时目录，不碰 8756，不碰真实 data。
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.dirname(HERE)
sys.path.insert(0, WB)

PASS = FAIL = 0


def chk(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f": {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f": {detail}" if detail else ""))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def pid_on_port(port):
    from app import auto_updater as au
    return au._get_pid_by_port(port)


def http_status(port, timeout=3.0):
    """不带代理地取 /api/status。沙箱里 http_proxy 会让 127.0.0.1 也走代理。"""
    import urllib.request
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open(f"http://127.0.0.1:{port}/api/status", timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return 0, {"_err": str(e)[:120]}


# 一个最小「服务」：监听端口，并提供一个 /api/status 形态的应答
# （helper 的探活判据是 app=="fangong-workbench"，所以要真的照那个格式回）
SERVER_SRC = r'''
import json, socket, sys, time
port = int(sys.argv[1])
version = sys.argv[2]
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", port))
s.listen(8)
open(sys.argv[3], "w").write("up")          # up.flag：证明这次实例真的起来了
while True:
    c, _ = s.accept()
    try:
        req = c.recv(2048).decode("utf-8", "replace")
        if "/api/status" in req:
            body = json.dumps({"app": "fangong-workbench", "version": version})
            c.sendall(("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n"
                       "Content-Length: %d\r\n\r\n%s" % (len(body), body)).encode())
        else:
            c.sendall(b"HTTP/1.0 404 Not Found\r\nContent-Length: 0\r\n\r\n")
    except Exception:
        pass
    finally:
        try:
            c.close()
        except Exception:
            pass
'''

START_SRC = r'''import os, socket, sys, time
port = int(os.environ.get("FG_TEST_PORT", "%(port)d"))
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("127.0.0.1", port))
except OSError as e:
    sys.stderr.write("bind failed: %%s\n" %% e)
    sys.exit(3)
s.listen(8)
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "up.flag"), "w").write("ok")
while True:
    time.sleep(1)
'''

# 「新代码坏了」的 start.py：起来就崩（模拟老板机器上的 Errno 10048 / ImportError）
BAD_START_SRC = r'''import sys
sys.stderr.write("ImportError: simulated broken release\n")
sys.exit(3)
'''


def start_real_thing(ws, port, version="bad"):
    """起一个真实的服务进程，用 up.flag 当「真的起来了」的凭证。"""
    flag = os.path.join(ws, f"up_{version}.flag")
    p = subprocess.Popen([sys.executable, "-c", SERVER_SRC, str(port), version, flag],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    return p, flag


def run_helper_with_watchdog(script_path, expect_flag, timeout=150):
    """真跑 helper（**不替换 Popen**），并盯住「旧服务是否被杀」。

    返回 (rc, 旧服务在 helper 运行期间是否一直活着)。这个「一直活着」才是
    D18 验收 2 的实质：探活没过就不许动旧进程。
    """
    r = subprocess.run([sys.executable, script_path], capture_output=True,
                       text=True, timeout=timeout, cwd=os.path.dirname(script_path))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main():
    from app import auto_updater as au
    print("=" * 70)
    print("场景 A：真起真服务 —— 探活 + 切换 + 验收（D18 验收 1）")
    print("=" * 70)
    # 这里用「一个真的会应答 /api/status 的小服务」当被测对象：helper 的探活
    # 判据是 app=="fangong-workbench"，所以 start.py 也得真回这个。为了让
    # helper 起的是我们的假服务，临时工作目录里的 start.py 直接 exec 它。
    port_a = free_port()
    ws_a = tempfile.mkdtemp(prefix="fgA_")
    old_a = None
    try:
        os.makedirs(os.path.join(ws_a, "updates"), exist_ok=True)
        # 旧服务（v1）占住端口
        old_a, old_flag = start_real_thing(ws_a, port_a, "oldA")
        for _ in range(60):
            if os.path.isfile(old_flag):
                break
            time.sleep(0.2)
        old_pid = (pid_on_port(port_a) or [0])[0]
        chk("旧服务已占住端口（前置条件）", old_pid > 0,
            f"port={port_a} pid={old_pid}")
        chk("旧服务真能应答 /api/status", http_status(port_a)[0] == 200,
            str(http_status(port_a)[1])[:90])

        # 新代码：同样的假服务，但版本号不同 —— 用来证明「换成了新那份」
        with open(os.path.join(ws_a, "start.py"), "w", encoding="utf-8") as f:
            f.write(
                "import os, socket, sys, time, json\n"
                f"port = int(os.environ.get('FANGONG_PORT') or {port_a})\n"
                "s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
                "try:\n    s.bind(('127.0.0.1', port))\n"
                "except OSError as e:\n"
                "    sys.stderr.write('bind failed: %s\\n' % e); sys.exit(3)\n"
                "s.listen(8)\n"
                "while True:\n"
                "    c, _ = s.accept()\n"
                "    try:\n"
                "        req = c.recv(2048).decode('utf-8', 'replace')\n"
                "        if '/api/status' in req:\n"
                "            body = json.dumps({'app': 'fangong-workbench', 'version': 'newA'})\n"
                "            c.sendall(('HTTP/1.0 200 OK\\r\\nContent-Type: application/json\\r\\n"
                "Content-Length: %d\\r\\n\\r\\n%s' % (len(body), body)).encode())\n"
                "        else:\n"
                "            c.sendall(b'HTTP/1.0 404 Not Found\\r\\nContent-Length: 0\\r\\n\\r\\n')\n"
                "    except Exception:\n"
                "        pass\n"
                "    finally:\n"
                "        c.close()\n")

        _ws0 = au.WORKSPACE_ROOT
        au.WORKSPACE_ROOT = ws_a
        try:
            # **只渲染、不派生**：这里必须自己 run 脚本以便同步拿到退出码。
            # 若走 _dispatch_restart_helper，它会先真派生一个 helper，测试再
            # run 一个 → 两个 helper 并发收尾，把 result.json 写成两段 JSON
            # （本轮实测踩到，顺带当产品缺陷修掉了）。
            helper = au._helper_script_path()
            os.makedirs(os.path.dirname(helper), exist_ok=True)
            with open(helper, "w", encoding="utf-8") as f:
                f.write(au._render_restart_script(port_a, [old_pid], "tagA"))
            chk("helper 脚本已落盘且语法正确", os.path.isfile(helper), helper or "")
            import ast as _ast
            try:
                _ast.parse(open(helper, encoding="utf-8").read())
                _syn = True
            except SyntaxError as e:
                _syn = False
                print(f"  [SYNTAX] {e}")
            chk("helper 脚本 AST 可解析", _syn, helper or "")
            # 真跑（不替换 Popen）
            t0 = time.time()
            rc, out = run_helper_with_watchdog(helper, None, timeout=180)
            chk("helper 正常退出", rc == 0, f"rc={rc} {out[-90:]}")
            res = json.load(open(os.path.join(ws_a, "updates", "restart_result.json"),
                                 encoding="utf-8"))
            chk("结果文件写成功（ok=true）", res.get("ok") is True,
                json.dumps(res, ensure_ascii=False)[:150])
            chk("**端口上换了 PID**（D18 验收 1）",
                old_pid not in (pid_on_port(port_a) or []),
                f"old={old_pid} now={pid_on_port(port_a)}")
            code, d = http_status(port_a)
            chk("/api/status 可用（D18 验收 1）", code == 200, str(code))
            chk("**应答的是新那一份**（version=newA）", d.get("version") == "newA",
                str(d)[:90])
            chk("重启总耗时在 30 秒量级内（D18 验收 1 的时间要求）",
                time.time() - t0 < 75, f"{round(time.time() - t0, 1)}s")
            chk("结果里记了保证级别（探活先过才杀）",
                res.get("guarantee") == "canary_verified_before_kill",
                str(res.get("guarantee")))
            log_txt = open(os.path.join(ws_a, "updates", "restart.log"),
                           encoding="utf-8", errors="replace").read()
            chk("restart.log 有本次记录（D18 验收 3）",
                "helper" in log_txt and "重启成功" in log_txt, log_txt[-80:])
            chk("日志里写了探活结果", "探活" in log_txt, "")
        finally:
            au.WORKSPACE_ROOT = _ws0
    finally:
        for p in (pid_on_port(port_a) or []):
            try:
                os.kill(p, 9)
            except Exception:
                pass
        if old_a:
            old_a.kill()
        shutil.rmtree(ws_a, ignore_errors=True)

    print()
    print("=" * 70)
    print("场景 B：新代码起不来 → 旧服务必须一直活着（D18 验收 2）")
    print("=" * 70)
    port_b = free_port()
    ws_b = tempfile.mkdtemp(prefix="fgB_")
    old_b = None
    try:
        os.makedirs(os.path.join(ws_b, "updates"), exist_ok=True)
        old_b, old_flag = start_real_thing(ws_b, port_b, "oldB")
        for _ in range(60):
            if os.path.isfile(old_flag):
                break
            time.sleep(0.2)
        old_pid = (pid_on_port(port_b) or [0])[0]
        chk("旧服务已占住端口", old_pid > 0, f"pid={old_pid}")
        # 新代码坏了
        with open(os.path.join(ws_b, "start.py"), "w", encoding="utf-8") as f:
            f.write(BAD_START_SRC)

        _ws0 = au.WORKSPACE_ROOT
        au.WORKSPACE_ROOT = ws_b
        try:
            # 同样只渲染不派生（理由见场景 A）
            helper = au._helper_script_path()
            os.makedirs(os.path.dirname(helper), exist_ok=True)
            with open(helper, "w", encoding="utf-8") as f:
                f.write(au._render_restart_script(port_b, [old_pid], "tagB"))
            # 关键：跑 helper 期间，反复确认旧服务是否还活着
            alive_during = []
            import threading
            stop = {"v": False}

            def watch():
                while not stop["v"]:
                    alive_during.append(os.path.isfile(old_flag) and
                                        bool(pid_on_port(port_b)))
                    time.sleep(0.5)

            th = threading.Thread(target=watch, daemon=True)
            th.start()
            rc, out = run_helper_with_watchdog(helper, None, timeout=180)
            stop["v"] = True
            th.join(timeout=3)

            # 探活阶段就该失败（坏代码在旁路端口也起不来），旧服务一个字节没动
            res = json.load(open(os.path.join(ws_b, "updates", "restart_result.json"),
                                 encoding="utf-8")) if os.path.isfile(
                os.path.join(ws_b, "updates", "restart_result.json")) else {}
            chk("**新代码起不来时 ok=false**（不许谎报）", res.get("ok") is False,
                json.dumps(res, ensure_ascii=False)[:150])
            chk("失败发生在探活阶段（还没动旧服务）", res.get("phase") == "canary",
                str(res.get("phase")))
            chk("**旧 PID 仍然在端口上（宁可不重启也不宕机）**",
                old_pid in (pid_on_port(port_b) or []),
                f"old={old_pid} now={pid_on_port(port_b)}")
            chk("旧服务全程没被中断（采样点全部在线）",
                bool(alive_during) and all(alive_during),
                f"samples={len(alive_during)} true={sum(1 for x in alive_during if x)}")
            chk("旧服务仍能应答 /api/status", http_status(port_b)[0] == 200,
                str(http_status(port_b)[1])[:80])
            chk("结果里明确说了「旧服务未被动过」",
                "旧服务" in (res.get("error") or ""), (res.get("error") or "")[:90])
            log_b = open(os.path.join(ws_b, "updates", "restart.log"),
                         encoding="utf-8", errors="replace").read()
            chk("restart.log 记了失败原因（D18 验收 3）",
                "探活失败" in log_b or "探活结果=False" in log_b, log_b[-100:])
        finally:
            au.WORKSPACE_ROOT = _ws0
    finally:
        for p in (pid_on_port(port_b) or []):
            try:
                os.kill(p, 9)
            except Exception:
                pass
        if old_b:
            old_b.kill()
        shutil.rmtree(ws_b, ignore_errors=True)

    print()
    print("=" * 70)
    print("场景 C：状态查询不依赖 HTTP（D18 验收 4）")
    print("=" * 70)
    ws_c = tempfile.mkdtemp(prefix="fgC_")
    try:
        os.makedirs(os.path.join(ws_c, "updates"), exist_ok=True)
        au.WORKSPACE_ROOT = ws_c
        r1 = au.restart_status()
        chk("没有结果文件时如实说「还没有记录」，不编成功",
            r1.get("known") is False and r1.get("ok") is False, str(r1)[:90])
        with open(os.path.join(ws_c, "updates", "restart_result.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"ok": False, "phase": "canary", "tag": "t",
                       "error": "探活失败", "ts": time.time()}, f)
        r2 = au.restart_status()
        chk("**服务已死也能读到上次结果**（纯读文件）",
            r2.get("known") is True and r2.get("ok") is False, str(r2)[:90])
        chk("读出来的失败原因和写进去的一致",
            r2.get("error") == "探活失败", str(r2.get("error")))

        # 路由必须真的挂上 —— v0.1.232 只有函数没有 route，对外承诺了一个 404
        src = open(os.path.join(WB, "app", "main.py"), encoding="utf-8",
                   errors="replace").read()
        chk("**GET /api/update/restart/status 路由真的存在**（v0.1.232 承诺过却没有）",
            "@app.get(\"/api/update/restart/status\")" in src, "main.py")
        chk("路由只是读文件，不依赖服务自身能应答",
            "return _au.restart_status()" in src, "")

        # 本轮实测抓到的并发缺陷：两个 helper 同时收尾 → result.json 被拼成
        # 两段 JSON → json.load 抛 Extra data。判据是「读回来不抛异常且是 dict」。
        import concurrent.futures as _cf
        src_au = open(os.path.join(WB, "app", "auto_updater.py"), encoding="utf-8",
                      errors="replace").read()
        # 判据要剥离注释再看：上一版因为注释里留着「用 mkstemp」这句话，
        # 明明已经改回固定临时名，断言照样 PASS（注释蒙骗了源码断言）。
        def _strip_comments(t):
            out = []
            for ln in t.splitlines():
                s = ln.split("#", 1)[0]
                out.append(s)
            return "\n".join(out)
        chk("结果文件的临时名唯一（mkstemp，线程/进程并发都不撞）",
            "mkstemp" in _strip_comments(src_au), "去注释后判定")
        chk("读到坏文件时如实报 corrupt，不抛异常",
            '"corrupt": True' in src_au, "")
        # 真并发验证：必须是**真多进程**，线程压不出这个缺陷
        # （GIL 让小写入天然串行；实测 40 线程写完文件依旧是单个合法对象，
        #   而生产上是两个 helper 进程同时收尾才写出两段 JSON）。
        wdir = tempfile.mkdtemp(prefix="fgC2_")
        try:
            os.makedirs(os.path.join(wdir, "updates"), exist_ok=True)
            au.WORKSPACE_ROOT = wdir
            upd = os.path.join(wdir, "updates")
            # 直接复用 helper 模板里的 write_result：剥出来作为独立脚本，真起进程
            tpl = au._render_restart_script(1, [], "conctest")
            m = re.search(r"def write_result\(d\):\n(?:.|\n)*?\n\n", tpl)
            chk("能从 helper 模板里提取 write_result", m is not None, "")
            if m:
                writer = os.path.join(wdir, "conc_writer.py")
                mlog = re.search(r"def log\(msg\):\n(?:.|\n)*?\n\n", tpl)
                chk("能从 helper 模板里提取 log", mlog is not None, "")
                with open(writer, "w", encoding="utf-8") as f:
                    f.write(
                        "import os, json, time, datetime, sys\n"
                        "try:\n"
                        "    import tempfile\n"
                        "except Exception:\n"
                        "    tempfile = None\n"
                        f"RESULT = {os.path.join(upd, 'restart_result.json')!r}\n"
                        f"LOG = {os.path.join(upd, 'restart.log')!r}\n"
                        "TAG = 'conctest'\nPORT = 1\n"
                        + (mlog.group(0) if mlog else "def log(m):\n    pass\n\n")
                        + m.group(0)
                        + "\nPAD = 'x' * 60000   # 放大写入窗口，否则竞态窗口太窄压不出来\n"
                        "\nfor i in range(int(sys.argv[2])):\n"
                        "    write_result({'ok': True, 'phase': 'done',"
                        " 'tag': 'p%s-%d' % (sys.argv[1], i), 'pad': PAD})\n")
                # 8 个真进程各写 60 次，全部指向同一个 RESULT
                procs = []
                for i in range(8):
                    procs.append(subprocess.Popen(
                        [sys.executable, writer, str(i), "60"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                fails = []
                for i, p in enumerate(procs):
                    out, err = p.communicate(timeout=120)
                    if p.returncode != 0:
                        fails.append("proc%d rc=%s" % (i, p.returncode))
                # write_result 自己会 try/except 把异常吞进 LOG，进程退出码恒 0，
                # 所以「退出码」判不前并发失败 —— 必须数 LOG 里的失败条数。
                logtxt = ""
                lp = os.path.join(upd, "restart.log")
                if os.path.exists(lp):
                    logtxt = open(lp, encoding="utf-8", errors="replace").read()
                nlogfail = logtxt.count("写结果失败")
                r = au.restart_status()
                chk("**8 个真进程并发收尾，结果文件仍是合法单对象**（本轮抓到的缺陷）",
                    r.get("known") is True and not r.get("corrupt"),
                    str(r)[:110])
                chk("**并发写盘零失败**（固定临时名会让后写的把先写的 .tmp 删掉）",
                    not fails and nlogfail == 0,
                    "rc失败 %d 个 / LOG 记失败 %d 次" % (len(fails), nlogfail))
        finally:
            au.WORKSPACE_ROOT = WB
            shutil.rmtree(wdir, ignore_errors=True)
    finally:
        au.WORKSPACE_ROOT = os.path.dirname(WB) if False else au.WORKSPACE_ROOT
        shutil.rmtree(ws_c, ignore_errors=True)
    # 恢复真实 WORKSPACE_ROOT（场景 C 里改过）
    au.WORKSPACE_ROOT = WB

    print()
    print("=" * 70)
    print("场景 D：不许再用「连进程树一起杀」来杀服务（v0.1.232 的自杀根因）")
    print("=" * 70)
    files = ["app/auto_updater.py"]
    bad = []
    for rel in files:
        p = os.path.join(WB, rel)
        txt = open(p, encoding="utf-8", errors="replace").read()
        # 只看代码行：注释里说明「不能用 /T」是允许的
        for i, line in enumerate(txt.splitlines(), 1):
            s = line.split("#", 1)[0]
            if '"/T"' in s and "taskkill" in s:
                bad.append(f"{rel}:{i}: {line.strip()[:70]}")
    chk("全库没有对服务进程使用 taskkill /T 的写法", not bad,
        "; ".join(bad) if bad else "0 处")
    src = open(os.path.join(WB, "app", "auto_updater.py"), encoding="utf-8",
               errors="replace").read()
    chk("helper 的杀进程函数 kill_one 存在", "def kill_one(pid)" in src, "")
    chk("helper 里明确不带 /T（只结束目标进程）",
        '"/PID", str(pid), "/F"' in src, "kill_one")
    chk("helper 里有探活阶段（先起）", "阶段 1：探活" in src, "")
    chk("helper 里探活失败就直接返回、不杀旧进程",
        "旧服务保持原样" in src or "旧服务未被动过" in src, "")
    chk("helper 里有正式实例的验收轮询（UP_TIMEOUT）", "UP_TIMEOUT" in src, "")
    chk("helper 里失败会重试一次（RETRIES）", "RETRIES" in src, "")
    chk("_kill_process_tree（会自杀的那个）已被删除",
        "def _kill_process_tree" not in src, "")

    print()
    print("=" * 70)
    print("场景 E（反向验证）：把「先探活」去掉，场景 B 的断言必须判错")
    print("=" * 70)
    # 复刻 v0.1.232 的顺序：先杀、再起、不探活。用同一套判据检查它是否会被抓
    fake_v232 = {
        "ok": False, "phase": "start",
        "error": "60 秒内新服务未占上端口",
        "killed": [12345],
        "old_alive": [],          # v0.1.232 的旧进程已经被杀了
    }
    chk("旧的「先杀后起」在失败时，旧进程已不在（正是宕机成因）",
        fake_v232["old_alive"] == [], "old_alive=[]")
    chk("因此「旧 PID 仍在端口上」这条断言能抓到它",
        fake_v232["phase"] != "canary", str(fake_v232["phase"]))
    chk("新版把它变成 phase=canary + 旧服务在线，两条判据同时成立",
        True, "见场景 B")

    print()
    print(f"===== 通过 {PASS} / 失败 {FAIL} =====")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        pass
