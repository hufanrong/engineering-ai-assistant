# 繁工AI 本地解析工作台 - 日志设施（v0.1.247 / D34）
"""**带时间戳、带 pid、带级别的日志**，以及"服务为什么死了"的退出留痕。

实测事故（真机 2026-11-13，WORKbuddy D34）：
    · 端口 8756 处于 LISTENING，但那个 PID 的进程**已经不在了**
      （连开三次 /api/status，HTTP 状态码全是 000 = 连不上）。
    · `reports/service.log` 有 2.4 MB 内容，`grep -c "2026-11-13" service.log`
      结果是 **0** —— 一行时间戳都没有。
    · 日志最后写入时间 04:29:01，**没有任何 traceback**。

也就是说：服务死了，但日志**没有能力回答"它什么时候死的、怎么死的"**。
原因有两个，都在这一版修掉：

  ① **没有时间戳**。原来全部是裸 `print()`，写进重定向文件后就是一堆无
     头的文本；而且 `uvicorn.run(..., log_level="warning")` 把带时间戳的
     访问日志也关掉了 —— 现场等于**没有日志**。
  ② **没有退出留痕**。进程被结束（任务管理器结束进程 / 开机脚本回收 /
     被别的进程带走）时，Python 不会执行任何清理代码，
     atexit / signal 钩子一个都没有，所以"死因"永远是空白。

现在：
  · 统一格式：`2026-11-13 04:29:01.123 INFO  [pid 24380] 模块: 内容`
  · 启动/退出都有结构化留痕（版本、pid、data_dir、当前项目、退出原因）
  · atexit + SIGTERM/SIGINT 钩子：能优雅退出时一定留下"为什么退出"
  · 兜底：被杀（kill -9 / 任务管理器强杀）时留不下任何东西 —— 所以
    **启动时**就把 pid + 启动时间写进 `logs/workbench.pid.json`，
    现场只要看这个文件就知道"它启动过、最后活到什么时候"（对比进程表）。
  · `sandbox_shim=on/off`：宿主 sitecustomize 的删除护栏会让同一份代码
    行为不同（实测 `SAFE_DELETE_FAIL_CLOSED`），必须写进日志，否则
    "同一份代码两个表现"永远查不清。
"""

import atexit
import json
import logging
import os
import signal
import sys
import time

LOGGER_NAME = "fangong"

_FMT = ("%(asctime)s.%(msecs)03d %(levelname)-5s [pid %(process)d] "
        "%(name)s: %(message)s")
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_configured = False
_exit_hooks_installed = False
_start_info = {}


def log_dir() -> str:
    """日志目录：<DATA_DIR>/logs/（跟随 config.DATA_DIR，不写死安装目录）。"""
    try:
        from . import config
        root = os.path.join(config.DATA_DIR, "logs")
    except Exception:  # noqa: BLE001
        root = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "logs")
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        pass
    return root


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    return logging.getLogger(name)


def sandbox_shim_state() -> str:
    """宿主 sitecustomize 护栏是否生效：on / off / unknown。

    实测：WorkBuddy 环境注入的 sitecustomize 会对删除操作加护栏
    （`[SAFE_DELETE_FAIL_CLOSED]` / `[SAFE_DELETE_BULK_CONFIRM_REQUIRED]`），
    同一份代码在护栏内外行为不同。不写进日志，现场根本无从判断。
    """
    try:
        import sitecustomize  # noqa: F401
    except Exception:  # noqa: BLE001
        return "off"
    path = getattr(sitecustomize, "__file__", "") or ""
    if not path or not os.path.exists(path):
        return "off"
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:  # noqa: BLE001
        return "unknown"
    if "SAFE_DELETE" in content or "FAIL_CLOSED" in content:
        return "on"
    return "off"


def setup_logging(level=logging.INFO, to_file: bool = True) -> logging.Logger:
    """配置根 logger：控制台 + 文件（同一套带时间戳的格式）。"""
    global _configured
    logger = get_logger()
    if _configured:
        return logger
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)

    ch = logging.StreamHandler(stream=sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    if to_file:
        try:
            path = os.path.join(log_dir(), "workbench.log")
            # 超过 8 MB 轮转一份，避免无限增长
            try:
                if os.path.exists(path) and os.path.getsize(path) > 8 * 1024 * 1024:
                    os.replace(path, path + ".1")
            except OSError:
                pass
            fh = logging.FileHandler(path, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except Exception:  # noqa: BLE001
            pass
    _configured = True
    return logger


def uvicorn_log_config(level: str = "INFO") -> dict:
    """给 uvicorn 用的日志配置：和时间戳 + pid 同一套格式。

    原来 `log_level="warning"` 把 uvicorn 自带的访问日志（本来带时间戳）
    整个关掉了 —— 现场只剩裸 print 的无时间戳文本。
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "fg": {"format": _FMT, "datefmt": _DATEFMT},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "fg",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["console"], "level": level, "propagate": False},
            "uvicorn.error": {"handlers": ["console"], "level": level, "propagate": False},
            "uvicorn.access": {"handlers": ["console"], "level": level, "propagate": False},
        },
    }


def write_pid_file(extra: dict = None) -> str:
    """写 pid 文件：进程被强杀时留不下退出日志，这个文件能回答"它活过"。"""
    path = os.path.join(log_dir(), "workbench.pid.json")
    rec = {
        "pid": os.getpid(),
        "start_ts": time.time(),
        "start_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python": sys.executable,
        "cwd": os.getcwd(),
        "sandbox_shim": sandbox_shim_state(),
    }
    if extra:
        rec.update(extra)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass
    return path


def install_exit_hooks(logger=None) -> None:
    """注册退出留痕钩子（atexit + SIGTERM/SIGINT）。

    注意：**kill -9 / 任务管理器"结束任务"是收不到的**，
    那类死法靠 write_pid_file() 留下的启动记录反推。
    """
    global _exit_hooks_installed
    if _exit_hooks_installed:
        return
    _exit_hooks_installed = True
    log = logger or get_logger()

    def _bye(reason, code=None):
        try:
            log.info("服务退出：%s%s", reason,
                     f"（exit={code}）" if code is not None else "")
        except Exception:  # noqa: BLE001
            pass

    def _on_atexit():
        _bye("正常退出（atexit）")

    def _on_signal(signum, _frame):
        try:
            log.warning("收到信号 %s，正在退出并留痕", signum)
        except Exception:  # noqa: BLE001
            pass
        _bye(f"收到信号 {signum}")
        # 恢复默认行为再退出，保证退出码正确
        try:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
        except Exception:  # noqa: BLE001
            raise SystemExit(0)

    try:
        atexit.register(_on_atexit)
    except Exception:  # noqa: BLE001
        pass
    for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
        if sig is None:
            continue
        try:
            signal.signal(sig, _on_signal)
        except Exception:  # noqa: BLE001
            pass


def log_startup(logger=None, extra: dict = None) -> dict:
    """启动结构化留痕：版本 / pid / data_dir / 当前项目 / sandbox_shim。"""
    log = logger or get_logger()
    info = {
        "version": _app_version(),
        "pid": os.getpid(),
        "data_dir": _data_dir(),
        "current_project": _current_project(),
        "sandbox_shim": sandbox_shim_state(),
        "start_ts": time.time(),
    }
    if extra:
        info.update(extra)
    try:
        log.info("服务启动：version=%s pid=%s data_dir=%s 当前项目=%s sandbox_shim=%s",
                 info["version"], info["pid"], info["data_dir"],
                 info["current_project"], info["sandbox_shim"])
    except Exception:  # noqa: BLE001
        pass
    write_pid_file(info)
    return info


def _app_version() -> str:
    try:
        from . import config
        return str(getattr(config, "APP_VERSION", "") or
                   getattr(config, "VERSION", "") or "unknown")
    except Exception:  # noqa: BLE001
        return "unknown"


def _data_dir() -> str:
    try:
        from . import config
        return str(config.DATA_DIR)
    except Exception:  # noqa: BLE001
        return "unknown"


def _current_project() -> str:
    try:
        from . import project_manager as pm
        cur = pm.get_current_project()
        if cur:
            return f"{cur.get('name', '')}({cur.get('id', '')})"
        return "（未选择项目）"
    except Exception:  # noqa: BLE001
        return "unknown"
