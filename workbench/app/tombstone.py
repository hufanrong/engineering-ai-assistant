# 繁工AI 本地解析工作台 - 项目删除墓碑（v0.1.247 / D35）
"""项目被删除之后，**任何落盘写都必须被拒绝**。

实测事故（真机 2026-11-13，WORKbuddy D35）：
    通过官方接口删了 4 个项目，接口全部返回 `data_deleted: true`，
    但 `data/projects/f95c1a30/`（15 MB）**又出现了**，里面
    `project_meta.json` 没了、`index.json` 是 0 条、`vector_db/` 在。

根因不是「删不干净」，是**删完之后有人把它写回来了**：

    删除发生的那一刻，有一个扫描线程正在这个项目目录里跑。
    delete_project() 把目录 rmtree 掉了 → 此刻目录确实不存在了，
    `_safe_rmtree` 返回 True → 接口如实返回 `data_deleted: true`。
    紧接着，那个还活着的扫描线程继续走下一步：
        `_save_index(idx, ddir)`   → 重新 mkdir + 写出 index.json（0 条，因为刚被清空）
        `VectorStore(db_path=.../vector_db)` → 重新建出 vector_db/
    目录就这样"复活"了。

    这正是本项目反复出现的母题「同一件事两个答案」的加强版：
    「项目还在不在」有两个答案 —— 接口说"删干净了"，磁盘说"还在"。

修法（两道闸）：
    ① **墓碑**（本模块）：删除前先在全局 `data/deleted_projects/` 登记
       该 data_dir；所有落盘写（索引 / 解析缓存 / 上传队列 / 车间归属 /
       版本台账 / 向量库）动手前先问一句 `is_deleted(data_dir)`，
       命中就直接跳过 —— 目录不再被写回来。
    ② **取消在跑的扫描**：`scanner.cancel_scans_for(data_dir)` 把该目录
       上正在跑的扫描置为取消，让它尽快收尾而不是继续空转。

    墓碑放在 `config.DATA_DIR/deleted_projects/`，**不在项目目录里** ——
    项目目录会被整个删掉，墓碑放里面就跟着一起没了，挡不住任何东西。

多项目平台通则：
    · 墓碑按**目录绝对路径**索引，不是按项目 id —— 同一个 id 在不同
      DATA_DIR 下是两个不同的落点。
    · 墓碑目录是全局的，跨项目共享；但它只影响自己那条路径。
    · `clear(data_dir)` **只由显式调用**触发（新建项目 / 项目恢复），
      不再因为「目录恰好不在磁盘上」自动清除 —— 自动清除会让墓碑
      在最需要它的那一瞬间失效（见 `is_deleted` 里的事故说明）。
"""

import os
import json
import hashlib
import threading
import time

_LOCK = threading.RLock()
# 进程内缓存：data_dir(绝对路径) -> 墓碑记录
_MEM: dict = {}

# 墓碑有效期（秒）。默认 7 天。
#
# 为什么要有 TTL：墓碑是"这个落点被删了，别再往里写"的**否定事实**，
# 它必须比任何还在跑的扫描都活得久（一次全量扫描可达 45 分钟），
# 否则删完项目后扫描线程继续写，目录照样复活。
# 但也不能永久留着 —— 同一路径将来真被复用时（目前只有 uuid 目录，
# 实际不会发生）旧的墓碑会永久挡写。7 天足够长，也不至于无限堆积。
TTL_SECONDS = 7 * 24 * 3600


def _tomb_root() -> str:
    """墓碑根目录：config.DATA_DIR/deleted_projects/（全局，不随项目删除而消失）。"""
    from . import config
    root = os.path.join(config.DATA_DIR, "deleted_projects")
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        pass
    return root


def _abs(data_dir: str) -> str:
    try:
        return os.path.abspath(data_dir)
    except Exception:  # noqa: BLE001
        return str(data_dir or "")


def _key(data_dir: str) -> str:
    return hashlib.sha1(_abs(data_dir).encode("utf-8")).hexdigest()


def _path(data_dir: str) -> str:
    return os.path.join(_tomb_root(), _key(data_dir) + ".json")


def mark_deleted(data_dir: str, project_id: str = "", reason: str = "") -> bool:
    """登记墓碑。返回是否登记成功。

    必须在 rmtree **之前**调用 —— 否则删除与写入之间存在窗口，
    扫描线程能在删完之后把目录写回来。
    """
    if not data_dir:
        return False
    rec = {
        "data_dir": _abs(data_dir),
        "project_id": project_id or "",
        "reason": (reason or "")[:500],
        "ts": time.time(),
        "ts_str": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = _path(data_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        # 墓碑写不下去也要让内存那份生效（进程内至少能挡住本轮）
        pass
    with _LOCK:
        _MEM[_abs(data_dir)] = rec
    return True


def is_deleted(data_dir: str) -> bool:
    """该目录是否已被删除（墓碑命中）。

    v0.1.247 修订：**墓碑是黏性的 —— 目录不在磁盘上也照样有效。**

    第一版写成「目录不在磁盘上就自动清掉墓碑」，理由是「留着会误伤
    将来复用同一路径的新项目」。实测证明这个理由站不住：
    目录刚被 rmtree 掉的那一刻它就不在磁盘上了，而那正是
    **最需要挡住写入**的时刻 —— 扫描线程下一步的 os.makedirs
    就把目录复活了（D35 缺陷原样复发，接口照旧返回 data_deleted:true）。

    证据：反向验证脚本 verify_reverse_247.py 的对照组输出
    「修复在位 → REVIVED=YES」，即守卫等于没装。

    误伤风险实际为零：项目目录名是 uuid，不会被复用；真需要放行的
    场景（同名项目重建）由 create_project 显式 clear() 处理。
    过期用 TTL 兜底（默认 7 天，远长于任何一次扫描的时长）。
    """
    if not data_dir:
        return False
    key = _abs(data_dir)
    with _LOCK:
        rec = _MEM.get(key)
    if rec is None:
        path = _path(data_dir)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    rec = json.load(f)
            except Exception:  # noqa: BLE001
                rec = None
            if rec:
                with _LOCK:
                    _MEM[key] = rec
    if not rec:
        return False
    ts = 0.0
    try:
        ts = float(rec.get("ts") or 0)
    except Exception:  # noqa: BLE001
        ts = 0.0
    if ts and (time.time() - ts) > TTL_SECONDS:
        # 墓碑过期（远超任何一次扫描的时长），放行并顺手清掉
        clear(data_dir)
        return False
    return True


def clear(data_dir: str) -> None:
    """清掉墓碑（目录已不存在，或项目被重新创建时）。"""
    if not data_dir:
        return
    key = _abs(data_dir)
    with _LOCK:
        _MEM.pop(key, None)
    path = _path(data_dir)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def prune_expired() -> int:
    """清掉过期墓碑，返回清理条数（启动时调用一次，避免目录无限堆积）。"""
    n = 0
    for rec in list_tombstones():
        ddir = rec.get("data_dir") or ""
        if not ddir:
            continue
        ts = 0.0
        try:
            ts = float(rec.get("ts") or 0)
        except Exception:  # noqa: BLE001
            ts = 0.0
        if ts and (time.time() - ts) > TTL_SECONDS:
            clear(ddir)
            n += 1
    return n


def list_tombstones() -> list:
    """列出全部墓碑（自测与运维排查用）。"""
    out = []
    root = _tomb_root()
    if not os.path.isdir(root):
        return out
    for fn in sorted(os.listdir(root)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(root, fn), encoding="utf-8") as f:
                rec = json.load(f)
            rec["still_on_disk"] = os.path.exists(rec.get("data_dir", ""))
            out.append(rec)
        except Exception:  # noqa: BLE001
            continue
    return out
