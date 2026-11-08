# 繁工AI 本地解析工作台 - 操作日志（审计流水）统一落点（v0.1.216）
#
# 为什么单独抽出来：
#   实测发现「删除项目」在 operation_log.jsonl 里一条都没有，于是有人据
#   「日志里没有删」得出「没发生删除」—— 审计空白被当成了否定证据。
#   根因是日志写入只埋在 app/main.py 的 HTTP 路由里：
#     · project_manager.delete_project() 被直接调用（自测/脚本/内部流程）就不留痕
#     · 换个入口（新增接口、命令行工具）又会漏
#   这与本项目反复出现的「同一件事两个答案」是同一母题：
#   同一个事实（"发生过删除"）有两条路径，一条记得、一条不记得。
#
#   ／所以日志写入下沉到**业务动作本身**（project_manager），
#   HTTP 路由不再重复埋点 —— 只有一个落点，任何调用方都覆盖。
#
# 口径：
#   · 位置：data/operation_log.jsonl，**全局**（不随项目切换，
#     见 project_scope.GLOBAL_BY_DESIGN）—— 审计流水不该只看得见当前项目。
#   · 格式：每行一个 JSON 对象 {time, type, content, operator}
#   · 失败不抛异常：审计写不进去不能连带业务失败，但返回 False 让调用方知道。

import datetime
import json
import os

from . import config


def log_file_path() -> str:
    """日志文件路径 —— 每次现算，不缓存（config.DATA_DIR 可能在运行时被切）。"""
    return os.path.join(config.DATA_DIR, "operation_log.jsonl")


def _log_time() -> str:
    """审计时间戳 —— 必须与历史流水同格式（%Y%m%d_%H%M）。

    v0.1.217：这里踩过一次「同一件事两个答案」。
    v0.1.216 把这套写盘逻辑从 app/main.py 抽出来时，顺手把时间格式换成了
    "%Y-%m-%d %H:%M:%S"（更可读），而历史 325 条全是 datetime_now() 产出的
    "20261029_2141"。结果同一份 operation_log.jsonl 里出现两种时间格式：
    老记录 20261029_2141、新记录 2026-11-08 13:22:58。
    前端「操作日志」列表和 CSV 导出的「时间」列是原样透传的，两种格式混排
    既不能排序也不能按日期筛选；而两条写入路径各自都"成功"，界面看不出异常。
    教训：抽取公共实现时，**对外可见的字段格式属于契约，不能顺手"优化"**。
    要改格式必须连带迁移历史数据并同步改前端解析，不能只改新写入的一侧。
    """
    return datetime.datetime.now().strftime("%Y%m%d_%H%M")


def log_op(op_type: str, content: str, operator: str = "") -> bool:
    """追加一条审计记录。返回是否写入成功（调用方可据此暴露给前端）。"""
    try:
        path = log_file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "time": _log_time(),
                "type": op_type,
                "content": content,
                "operator": operator or "系统",
            }, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001
        return False
