"""项目级数据路径解析（v0.1.176）

背景：早期约 25 个模块把业务数据直接写到进程工作目录下的 `data/`，
导致**跨项目串味**——在项目 A 里录的施工日志，切到项目 B 还能读到。
这些数据（施工日志、隐蔽验收、吊装方案、进度、各类合并记录等）
都属于具体工程项目，必须落在项目自己的目录里。

统一入口：
    project_paths.data_file("site_logs.json")
    project_paths.data_dir()

无当前项目时**拒绝写入**并抛 NoProjectError。这一点是有意的：
回落到全局 `data/` 正是串味的根源，宁可让调用方显式处理，
也不允许把数据写到没有归属的地方。
"""

import os
from typing import Optional


class NoProjectError(RuntimeError):
    """当前没有选中项目，业务数据无处可落。"""

    def __init__(self, what: str = ""):
        self.what = what
        msg = "当前没有选中项目，无法保存业务数据"
        if what:
            msg += f"（{what}）"
        msg += "。请先新建或切换项目。"
        super().__init__(msg)


def current_project_id() -> Optional[str]:
    """当前项目 id；没有则 None。"""
    from . import project_manager as pm
    try:
        cur = pm.get_current_project()
    except Exception:  # noqa: BLE001  project_manager 初始化失败时按「无项目」处理
        return None
    return cur.get("id") if cur else None


def data_dir(project_id: str = None, create: bool = True) -> str:
    """当前项目（或指定项目）的数据目录。"""
    from . import project_manager as pm
    pid = project_id or current_project_id()
    if not pid:
        raise NoProjectError()
    d = pm.get_project_data_dir(pid)
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def data_file(filename: str, project_id: str = None, create: bool = True) -> str:
    """当前项目数据目录下的文件绝对路径。"""
    return os.path.join(data_dir(project_id, create=create), filename)


def data_subdir(name: str, project_id: str = None, create: bool = True) -> str:
    """当前项目数据目录下的子目录（如 generated_docs）。"""
    return os.path.join(data_dir(project_id, create=create), name)


def _legacy_root() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def legacy_global_file(filename: str) -> str:
    """旧全局路径。只用于**一次性迁移**：老机器上历史数据还躺在全局 data/。"""
    return os.path.join(_legacy_root(), filename)


def _migrate_once(filename: str, target: str) -> None:
    """把全局历史文件**复制**进当前项目，且整个数据库只做一次。

    关键：不能给每个项目都复制一遍——那等于把「A 串到 B」的毛病做成默认行为。
    复制完在全局 data/ 下留一个标记，之后任何项目都不会再吃到这份历史数据。
    只复制不删除：老机器上的历史数据原样保留，出问题还能回退。
    """
    import shutil

    old = legacy_global_file(filename)
    if not os.path.exists(old):
        return
    marker = os.path.join(_legacy_root(), ".migrated_" + filename.replace("/", "_"))
    if os.path.exists(marker):
        return
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        shutil.copy2(old, target)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(target)
    except Exception:  # noqa: BLE001  迁移失败不该阻断业务，本次按空数据起步
        pass


def data_file_with_legacy(filename: str, project_id: str = None) -> str:
    """当前项目内的数据文件路径；首次访问时把全局历史文件迁移**一次**进来。

    迁移仅在项目内还没有该文件、全局 data/ 里有历史文件、且从未迁移过时发生。
    """
    path = data_file(filename, project_id)
    if not os.path.exists(path):
        _migrate_once(filename, path)
    return path
