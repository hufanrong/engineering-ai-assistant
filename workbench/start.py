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
    time.sleep(1.5)
    # v0.1.134：HOST=0.0.0.0/:: 时浏览器打不开，回退 127.0.0.1
    host = "127.0.0.1" if config.HOST in ("0.0.0.0", "::", "") else config.HOST
    webbrowser.open(f"http://{host}:{config.PORT}")


if __name__ == "__main__":
    threading.Thread(target=_open_browser, daemon=True).start()
    from app.main import run
    run()
