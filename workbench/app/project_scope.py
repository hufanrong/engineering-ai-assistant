# 繁工AI 本地解析工作台 - 业务数据项目隔离（v0.1.199）
#
# 为什么需要这个模块
# ------------------
# 有一批模块把业务数据文件写成了「全局 data/xxx.json」的**模块级常量**，
# 例如 construction_logs.json / doc_relations.json / docplan_tasks.json /
# equipment_merge.json / piping_network.json / rejected_candidates.json /
# tag_alias.json / version_map.json。这带来两个真实缺陷：
#
#   ① 跨项目串味：项目 A 的施工日志、资料关联、版本记录直接出现在项目 B 里。
#      实测证据：data/projects/ 下 91 个项目目录，没有一个存在这些文件；
#      而 data/ 根目录里 version_map.json 躺着 12 个文件名、198 条版本记录，
#      不属于任何一个项目。
#
#   ② 切换项目后仍写旧路径：这些常量都是「第一次用到就 global 赋值、之后再不复算」，
#      project_manager.set_current_project() 换了项目，常量还是老的。
#      这与 v0.1.195 记录的 PROJECTS_ROOT 写死事故是同一类错误
#      （模块级常量逃过了运行时配置变更）。
#
# 统一做法
# --------
# 不在模块里放路径常量，改成每次读写都调用本模块函数现算：
#     from . import project_scope
#     path = project_scope.path("construction_logs.json")
#
# 解析顺序：当前项目目录 → 全局 data/（没有当前项目或取不到项目时兜底）。
# 兜底是必要的：迁移期、单项目部署、以及项目目录不可写时都不能让功能直接失效。

from . import config
import os


# 应当保持全局（应用级配置，不属于任何项目）的文件白名单。
# 这些文件按设计就住在 data/ 根目录，不能按项目隔离：
#   storage_config.json  —— 存储位置配置，config.py 启动时就要读，那时还没有项目概念
#   current_project.json —— 当前项目指针本身
#   operation_log.jsonl  —— 全局操作审计流水
#   version_map.json     —— 见 _MIGRATED_LEGACY，由 _migrate_legacy 一次性迁入项目
GLOBAL_BY_DESIGN = {
    "storage_config.json",
    "current_project.json",
    "operation_log.jsonl",
}


def project_dir(project_id: str = None):
    """当前（或指定）项目的业务数据目录；取不到时返回 None。"""
    try:
        from . import project_manager as _pm
        cur = _pm.get_current_project() if project_id is None else None
        if project_id is None:
            if not cur:
                return None
            project_id = cur["id"]
        ddir = _pm.get_project_data_dir(project_id)
        if ddir:
            os.makedirs(ddir, exist_ok=True)
        return ddir
    except Exception:  # noqa: BLE001
        return None


def path(filename: str, project_id: str = None, legacy_fallback: bool = True) -> str:
    """业务数据文件的落盘路径：优先当前项目目录，取不到时回退全局 data/。

    Args:
        filename: 文件名，如 "construction_logs.json"
        project_id: 指定项目；None 表示当前项目
        legacy_fallback: 项目目录不可用时是否回退全局（默认 True，保功能不失效）
    """
    ddir = project_dir(project_id)
    if ddir:
        return os.path.join(ddir, filename)
    if not legacy_fallback:
        return ""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    return os.path.join(config.DATA_DIR, filename)


def legacy_path(filename: str) -> str:
    """旧全局路径（迁移读取用）。"""
    return os.path.join(config.DATA_DIR, filename)


def load_with_migration(filename: str, project_id: str = None):
    """读业务数据；项目目录里没有时，回退读旧全局文件（不删除、不改写）。

    只读回退的目的：真实部署里已经攒在 data/根目录的历史数据不能因为
    升级到项目隔离就突然「消失」。下一次 _save 会把它写进项目目录，
    旧全局文件原样保留作为备份，不主动删除（删数据必须由用户确认）。

    返回 (data, source) —— source 为 "project" / "legacy" / "none"。
    """
    import json
    pdir = project_dir(project_id)
    if pdir:
        p = os.path.join(pdir, filename)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f), "project"
            except Exception:  # noqa: BLE001
                pass
    lp = legacy_path(filename)
    if os.path.isfile(lp):
        try:
            with open(lp, encoding="utf-8") as f:
                return json.load(f), "legacy"
        except Exception:  # noqa: BLE001
            pass
    return None, "none"
