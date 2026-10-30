# 繁工AI 本地解析工作台 - 启动入口
# 用法：python start.py
# 会自动打开浏览器访问 http://127.0.0.1:8756

import os
import sys
import threading
import webbrowser

# 确保以项目根目录为工作目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# v0.1.144：HuggingFace 离线模式——模型已本地缓存，禁止向 huggingface.co 发 HEAD 请求
# 检查版本。网络受限（工地/内网/防火墙）环境下，联网检查会重试 5 次×10 秒超时，
# 卡死扫描线程甚至导致独立进程异常退出。必须在 import transformers/sentence_transformers 之前设置。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from app import config  # noqa: E402


def _open_browser():
    import time
    # v0.1.169：无人值守自测循环（tools/wb_loop.py）每次重启服务都会开一个
    # 浏览器窗口，跑一夜就是几十个。允许用环境变量关掉；手动启动时默认仍然开。
    if os.environ.get("FANGONG_NO_BROWSER", "").strip() in ("1", "true", "yes"):
        return
    time.sleep(1.5)
    # v0.1.134：HOST=0.0.0.0/:: 时浏览器打不开，回退 127.0.0.1
    host = "127.0.0.1" if config.HOST in ("0.0.0.0", "::", "") else config.HOST
    webbrowser.open(f"http://{host}:{config.PORT}")


def _startup_selfcheck():
    """v0.1.154：启动自检——自动更新后若代码不完整（ImportError），
    启动即崩且无提示。先子进程冒烟 import，失败则提示回滚并退出。"""
    import subprocess
    try:
        r = subprocess.run(
            [sys.executable, "-c", "from app.main import run; print('OK')"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, timeout=120)
    except Exception:
        return True  # 自检进程异常不阻塞启动（交给主流程报错）
    if r.returncode == 0:
        return True
    # 冒烟失败：提示用户回滚
    print("=" * 60)
    print("启动自检失败：程序代码可能不完整（自动更新后常见）。")
    err = (r.stderr or r.stdout or "").strip().splitlines()
    print("错误：", err[-1] if err else "未知")
    print("处理建议：")
    print("  1) 若刚执行过自动更新，请重启一次（回滚到上一版本目录）；")
    print("  2) 或从 GitHub 重新下载安装包覆盖安装（data 目录不受影响）。")
    print("=" * 60)
    return False


if __name__ == "__main__":
    if not _startup_selfcheck():
        sys.exit(1)
    threading.Thread(target=_open_browser, daemon=True).start()
    from app.main import run
    run()
