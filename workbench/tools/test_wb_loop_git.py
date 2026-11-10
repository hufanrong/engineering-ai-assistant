#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动回传通道不许「一声不吭」地失败。（v0.1.232）

实测背景（老板机器 2026-11-10）：
  老板问「有没有完成反馈」，核对发现 origin/main 上当日三单缺陷都在，
  但全是手工 git push 推的 —— **自动回传一条都没成功过**。
  计划任务 FangongAI-AutoFeedback：16:04:10 准时触发，LastResult=2，
  reports/_loop.log 一行没写，16:04 后没新增任何报告目录。

  根因两层：
    ① 任务用 pythonw 起在裸环境，系统 PATH 里没有 git（只有 gh）。
       本机唯一 git 是 WorkBuddy PortableGit，只由 WorkBuddy 终端注入 PATH。
       → wb_loop 第一句 git rev-parse 就失败 → is_repo=False → return 2。
    ② 那条分支用**裸 print**，pythonw 下 sys.stdout=None 直接抛
       AttributeError，_loop.log 零痕迹。外面看就是「按时跑了、没报错」。

这个测试要能抓住：
  1) PATH 里没有 git 时，find_git() 仍能找到常见安装位置/PortableGit；
  2) 真找不到时，给出的是**能照着做的说明**，不是一个空字符串；
  3) main() 的每条失败分支都写进 _loop.log（不许只 print）；
  4) --preflight 能独立给出环境结论，且 redisplays 出红在哪一条。
"""
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.dirname(HERE)
sys.path.insert(0, HERE)

PASS = FAIL = 0
def chk(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f": {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f": {detail}" if detail else ""))


def main():
    import wb_loop as w

    print("=" * 70)
    print("场景1：git 发现 —— PATH 里没有 git 时仍能找到")
    print("=" * 70)
    # 沙箱里 /usr/bin/git 在，这一条验的是「有绝对路径库存」这件事本身
    exe, why = w.find_git()
    chk("find_git 返回了绝对路径（不是靠 PATH 的裸 'git'）",
        bool(exe) and os.path.isabs(exe), f"{exe} | {why}")
    chk("说明文字是人话（含路径或修法）", bool(why) and len(why) > 5, why[:100])
    chk("结果被缓存（第二次不再重新扫）", w._GIT_CACHE.get("path") == exe, str(w._GIT_CACHE))

    print()
    print("=" * 70)
    print("场景2：找不到 git 时，说明必须能照着做")
    print("=" * 70)
    _saved = dict(w._GIT_CACHE)
    try:
        w._GIT_CACHE.clear()
        # 把「所有可能的路径」都屏蔽：清空环境 + 让 which 恒空 + 平台路径不存在
        _env = dict(os.environ)
        os.environ.pop("GIT_EXECUTABLE", None)
        _which = shutil.which
        shutil.which = lambda *a, **k: None
        # 让 isfile 对候选路径恒假 —— 模拟「这台机器上真没装 git」
        _isfile = os.path.isfile
        os.path.isfile = lambda p: False if ("git" in str(p)) else _isfile(p)
        try:
            exe2, why2 = w.find_git()
            # 必须在「git 不可用」这个窗口内调用 git() —— 缓存在上面已被清空，
            # 一旦出了这个窗口 find_git() 会重新找到真 git，测出来的就不是这条逻辑
            # （第一版就是这么写的，结果 rc=128 假失败）
            w._GIT_CACHE.clear()
            rc_git, out_git, err_git = w.git("status")
        finally:
            shutil.which = _which
            os.path.isfile = _isfile
            os.environ.clear(); os.environ.update(_env)
        chk("找不到时返回空路径", exe2 == "", f"exe={exe2}")
        chk("说明里列出「试过哪些位置」", "已试过" in why2, why2[:120])
        chk("说明里给出具体修法（系统 PATH / GIT_EXECUTABLE）",
            ("PATH" in why2) and ("GIT_EXECUTABLE" in why2), why2[-110:])
        # git() 在找不到 git 时必须是 127，且 stderr 带原因，不能是空
        rc, out, err = rc_git, out_git, err_git
        chk("git() 找不到 git 时返回 127", rc == 127, f"rc={rc}")
        chk("并且把原因放在 stderr 里（调用方不用猜）",
            bool(err) and "git" in err, err[:80])
    finally:
        w._GIT_CACHE.clear(); w._GIT_CACHE.update(_saved)

    print()
    print("=" * 70)
    print("场景3：失败必须留日志（pythonw 下 stdout=None 也不能吞）")
    print("=" * 70)
    tmp = tempfile.mkdtemp(prefix="fgwb_")
    try:
        logf = os.path.join(tmp, "_loop.log")
        _logfile0, _stdout0 = w._LOG_FILE, sys.stdout
        w._LOG_FILE = logf
        try:
            # 模拟 pythonw：stdout 是 None
            sys.stdout = None
            w.log("这是一条 pythonw 下的日志")
            # 直接跑 main() 的「不是仓库」分支（用一个临时非仓库目录）
            _repo0 = w.REPO_DIR
            w.REPO_DIR = tmp
            try:
                _argv0 = sys.argv
                sys.argv = ["wb_loop.py", "--once"]
                try:
                    rc_bad = w.main()
                finally:
                    sys.argv = _argv0
            finally:
                w.REPO_DIR = _repo0
        finally:
            sys.stdout = _stdout0
            w._LOG_FILE = _logfile0

        chk("stdout=None 时 log() 也没抛异常", True)
        chk("日志文件真的写下来了", os.path.isfile(logf), logf)
        txt = io.open(logf, encoding="utf-8").read() if os.path.isfile(logf) else ""
        chk("pythonw 那句日志在里面", "pythonw 下的日志" in txt, txt.splitlines()[:2])
        chk("「不是仓库」分支也留了痕（含错误说明）",
            "[错误]" in txt, [l for l in txt.splitlines() if "[错误]" in l][:2])
        chk("返回码是 2（与原来一致，调用约定不变）", rc_bad == 2, f"rc={rc_bad}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 70)
    print("场景4：--preflight 独立给出环境结论")
    print("=" * 70)
    tmp2 = tempfile.mkdtemp(prefix="fgwb2_")
    try:
        logf2 = os.path.join(tmp2, "_loop.log")
        _logfile0 = w._LOG_FILE
        w._LOG_FILE = logf2
        try:
            rc = w.preflight()
        finally:
            w._LOG_FILE = _logfile0
        txt2 = io.open(logf2, encoding="utf-8").read() if os.path.isfile(logf2) else ""
        chk("preflight 有结论行", "预检结束" in txt2, txt2.splitlines()[-2:])
        chk("逐项列出了 OK/RED", ("[OK  ]" in txt2) or ("[RED ]" in txt2),
            [l for l in txt2.splitlines() if l.startswith("[OK")][:2])
        chk("必查项里有 git 与远端", ("git 可执行" in txt2) and ("是 git 仓库" in txt2),
            [l for l in txt2.splitlines() if "git" in l][:2])
        chk("返回码能表意（0=全绿 / 1=有红项）", rc in (0, 1), f"rc={rc}")
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)

    print()
    print("=" * 70)
    print("场景5（反向验证）：旧写法必须被本测试抓住")
    print("=" * 70)
    src = io.open(os.path.join(HERE, "wb_loop.py"), encoding="utf-8").read()
    # 去掉注释再判定，避免「历史说明里提到旧写法」被误判
    code_lines = [l for l in src.splitlines()
                  if not l.lstrip().startswith("#")]
    code = "\n".join(code_lines)
    chk("git() 不再硬写裸 'git'（必须走 find_git 的绝对路径）",
        "run([exe] + list(args)" in code, "")
    chk("main() 的失败分支不再用裸 print",
        "print(f\"[错误]" not in code, "")
    chk("存在 find_git 实现", "def find_git(" in code, "")
    chk("存在 --preflight 参数", "--preflight" in code, "")

    print()
    print(f"===== 通过 {PASS} / 失败 {FAIL} =====")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
