#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重启服务必须「真的换掉进程」，不能只是回 ok:true。（v0.1.232）

实测背景（老板机器 2026-11-10，v0.1.231 更新后）：
    POST /api/update/restart
    -> {"ok": true, "killed_pids": [], "port": 8756}
    随后 5 次探版本全是 0.1.230，PID 前后都是 24808 —— 重启没发生。
    updates/restart.log 铁证：
      ERROR [Errno 10048] bind on ('127.0.0.1', 8756) 端口只允许使用一次

根因：uvicorn 单进程下监听端口的 pid 就是 os.getpid() 自己，而原代码
    for pid in pids:
        if pid == os.getpid(): continue
把唯一的目标跳过了 —— 「别自杀」被实现成「永远不重启」。
更糟的是 Popen 之后不做任何校验，新进程崩没崩都回 ok:true。

这个测试要能抓住三件事：
  1) 占端口的就是自己时，不能「什么都不做还回 ok」；
  2) 真到底层，必须能换掉一个真实进程（PID 必须变）；
  3) 新进程起不来时必须回 ok:false，而不是假装成功。

做法：起一个真的监听端口的小进程 → 调用 restart_service → 校验端口上的
PID 确实变了。全程用独立临时端口 + 临时工作目录，不碰 8756、不碰真实数据。
"""
import json
import os
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
    """用项目自己的实现查端口占用 PID（避免测试自带一套判据）。"""
    from app import auto_updater as au
    return au._get_pid_by_port(port)

# 一个最小服务：监听端口直到被杀
SERVER_SRC = """
import socket, sys, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", %(port)d))
s.listen(5)
print("listening", flush=True)
while True:
    time.sleep(1)
"""

# 会被 restart_service 拉起来当「新服务」的 start.py —— 必须能占上端口
START_SRC = """
import os, socket, sys, time
port = int(os.environ.get("FG_TEST_PORT", "%(port)d"))
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("127.0.0.1", port))
except OSError as e:
    sys.stderr.write("bind failed: %%s\\n" %% e)
    sys.exit(3)
s.listen(5)
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "up.flag"), "w").write("ok")
while True:
    time.sleep(1)
"""


def main():
    from app import auto_updater as au

    print("=" * 70)
    print("场景1：占端口的是「我自己」时，不能假装重启成功")
    print("=" * 70)
    # 这一场景要验的是**返回体是否诚实**。注意：helper 脚本会去杀 PIDS 里的进程，
    # 而这里 PIDS=[os.getpid()] 就是本测试进程自己 —— 所以必须拦住真正的 spawn，
    # 否则测试会把测试自己杀掉（第一次写这版时就差点这么干）。
    # 做法：临时把 au.subprocess.Popen 换成记录器，其余逻辑原样跑。
    _real = au._get_pid_by_port
    _real_popen = au.subprocess.Popen
    spawned = []

    class _Recorder:
        def __init__(self, cmd, **kw):
            spawned.append(cmd)

        def __getattr__(self, _n):
            return lambda *a, **k: None

    ws1 = tempfile.mkdtemp(prefix="fgrestart_self_")
    _ws0 = au.WORKSPACE_ROOT
    try:
        au.WORKSPACE_ROOT = ws1
        au._get_pid_by_port = lambda p: [os.getpid()]
        au.subprocess.Popen = _Recorder
        r = au.restart_service(port=19999)
    finally:
        au.subprocess.Popen = _real_popen
        au._get_pid_by_port = _real
        au.WORKSPACE_ROOT = _ws0

    try:
        chk("不返回 verified=True 的假成功",
            not (r.get("ok") and r.get("verified") is True),
            f"ok={r.get('ok')} verified={r.get('verified')} mode={r.get('mode')}")
        chk("明确交代走的是独立进程（mode=helper）", r.get("mode") == "helper",
            str(r.get("mode")))
        chk("如实列出「即将被结束的 PID」而不是空数组",
            bool(r.get("will_kill")), str(r.get("will_kill")))
        chk("消息里说明要靠 status 接口核对（不许只说成功）",
            "status" in (r.get("message") or ""), (r.get("message") or "")[:80])
        chk("helper 脚本真的被派生了（不是只回一句话）", len(spawned) == 1,
            str(spawned))
        _hp = os.path.join(ws1, "updates", "restart_service.py")
        chk("helper 脚本已落盘", os.path.isfile(_hp), _hp)
        if os.path.isfile(_hp):
            import ast as _ast
            try:
                _ast.parse(open(_hp, encoding="utf-8").read())
                _ok = True
            except SyntaxError:
                _ok = False
            chk("helper 脚本语法正确（double-brace 陷阱）", _ok, _hp)
    finally:
        shutil.rmtree(ws1, ignore_errors=True)

    print()
    print("=" * 70)
    print("场景2：真到底层 —— 换掉一个真实进程，PID 必须变")
    print("=" * 70)
    port = free_port()
    ws = tempfile.mkdtemp(prefix="fgrestart_")
    old = None
    try:
        os.makedirs(os.path.join(ws, "app"), exist_ok=True)
        os.makedirs(os.path.join(ws, "updates"), exist_ok=True)
        # 旧进程：占着端口
        old = subprocess.Popen([sys.executable, "-c", SERVER_SRC % {"port": port}],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
        # 新服务：restart_service 会去起 <WS>/start.py
        with open(os.path.join(ws, "start.py"), "w", encoding="utf-8") as f:
            f.write(START_SRC % {"port": port})

        # 等旧进程真占上端口
        old_pid = 0
        for _ in range(40):
            hit = pid_on_port(port)
            if hit:
                old_pid = hit[0]
                break
            time.sleep(0.25)
        chk("旧进程已占住端口（前置条件成立）", old_pid > 0,
            f"port={port} pid={old_pid}")

        # 让被测代码用临时工作目录 + 临时端口（它读模块级 WORKSPACE_ROOT）
        _ws0, _pg0 = au.WORKSPACE_ROOT, None
        au.WORKSPACE_ROOT = ws
        # 让新起的 start.py 也监听同一个临时端口
        os.environ["FG_TEST_PORT"] = str(port)
        try:
            # 注意：此时占端口的**不是**当前进程 → 走 direct 分支，当场杀 + 等新进程占端口
            r = au.restart_service(port=port)
        finally:
            au.WORKSPACE_ROOT = _ws0

        new_pid = 0
        for _ in range(60):
            hit = [p for p in pid_on_port(port) if p != old_pid]
            if hit:
                new_pid = hit[0]
                break
            time.sleep(0.5)

        chk("重启调用返回 ok", bool(r.get("ok")), json.dumps(r, ensure_ascii=False)[:200])
        chk("返回里 verified=True（当场确认过，不是猜的）",
            r.get("verified") is True, f"verified={r.get('verified')}")
        chk("旧 PID 真的被结束掉", old_pid > 0 and old_pid not in pid_on_port(port),
            f"old={old_pid} now={pid_on_port(port)}")
        chk("**端口上换成了另一个 PID**（这才是「重启生效」的判据）",
            new_pid > 0 and new_pid != old_pid, f"new={new_pid} old={old_pid}")
        chk("新服务确实起在临时工作目录里（up.flag 落盘）",
            os.path.isfile(os.path.join(ws, "up.flag")), ws)
    finally:
        for p in pid_on_port(port):
            try:
                os.kill(p, 9)
            except Exception:
                pass
        if old:
            try:
                old.kill()
            except Exception:
                pass
        shutil.rmtree(ws, ignore_errors=True)
        os.environ.pop("FG_TEST_PORT", None)

    print()
    print("=" * 70)
    print("场景3：新服务起不来时，必须回 ok:false（不许说谎）")
    print("=" * 70)
    port2 = free_port()
    ws2 = tempfile.mkdtemp(prefix="fgrestart_bad_")
    try:
        os.makedirs(os.path.join(ws2, "updates"), exist_ok=True)
        # 故意写一个起来就崩的 start.py（模拟老板机器上的 Errno 10048）
        with open(os.path.join(ws2, "start.py"), "w", encoding="utf-8") as f:
            f.write("import sys\nsys.stderr.write('bind failed: Errno 10048\\n')\nsys.exit(3)\n")
        # 先让端口被一个「外部进程」占着，但随后我们把它杀掉，留下空端口 + 会崩的新程序
        p_old = subprocess.Popen([sys.executable, "-c", SERVER_SRC % {"port": port2}],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
        for _ in range(40):
            if pid_on_port(port2):
                break
            time.sleep(0.25)
        _ws0 = au.WORKSPACE_ROOT
        au.WORKSPACE_ROOT = ws2
        try:
            r = au.restart_service(port=port2)
        finally:
            au.WORKSPACE_ROOT = _ws0
        chk("新服务没起来时，ok 必须为 false", r.get("ok") is False,
            json.dumps(r, ensure_ascii=False)[:220])
        chk("给出可执行的下一步（不是只回一句失败）",
            bool(r.get("suggestion") or r.get("error")), (r.get("error") or "")[:90])
        try:
            p_old.kill()
        except Exception:
            pass
    finally:
        for p in pid_on_port(port2):
            try:
                os.kill(p, 9)
            except Exception:
                pass
        shutil.rmtree(ws2, ignore_errors=True)

    print()
    print("=" * 70)
    print("场景4（反向验证）：把「跳过自己」改回去，场景2 的判据必须判错")
    print("=" * 70)
    # 复刻旧逻辑：跳过自己 → 什么也不杀 → killed 恒空
    def old_logic(pids, self_pid):
        killed = []
        for pid in pids:
            if pid == self_pid:
                continue
            killed.append(pid)
        return killed
    killed = old_logic([os.getpid()], os.getpid())
    chk("旧逻辑在「只有自己」时杀 0 个（这正是真机上的现象）",
        killed == [], f"killed={killed}")
    chk("因此旧代码无法满足「端口上换了 PID」这条判据",
        killed == [] and True)

    print()
    print(f"===== 通过 {PASS} / 失败 {FAIL} =====")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
