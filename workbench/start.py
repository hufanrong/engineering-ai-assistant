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

from app import config  # noqa: E402


def _open_browser():
    import time
    time.sleep(1.5)
    webbrowser.open(f"http://{config.HOST}:{config.PORT}")


if __name__ == "__main__":
    threading.Thread(target=_open_browser, daemon=True).start()
    from app.main import run
    run()
