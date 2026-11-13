# 繁工AI 本地解析工作台 - 文件夹扫描 + 解析 + 入库 + 上传队列 一体化
# 幂等：按 sha256 记录已处理文件（data/index.json），重复扫描自动跳过，不重复入库。

from . import atomic_io as _atomic_io
import os
import json
import threading
import datetime
import time
import uuid

from . import config
from parsers.engines import parse_file, ParseResult
from .vector_store import VectorStore
from . import upload_queue
from . import tombstone as _tombstone

INDEX_FILE = None  # 兼容旧引用（main.py 仅判断存在性）；实际读写不再依赖此全局变量

# v0.1.227：解析能力版本号。**凡是改变「同一份文件能抽出多少内容」的改动，
# 都必须把这个号加一。**
#
# 为什么需要它：索引里的 status="parsed" 只说明「曾经解析过」，不说明
# 「用当前的解析器解析过」。存量文件因此永远停在旧的解析结果上 ——
# 实测 2026-11-10 马诺诺真实资料 0c9a4b2d：ODA 探测修好、DWG 已经能从
# 0 字抽到 1300/26251 字，但 25 个 DWG 的缓存里仍是
#   {"status":"partial","text":"","error":"未找到 ODA File Converter…"}
# 扫描按 status=="parsed" 判重、直接跳过，于是**修好的解析器对老资料完全无效**，
# 老板看到的还是「图纸查不到内容」。这类「改完跟没改一样」的坑，
# 光靠重新上传是补不回来的（用户根本不知道该重传哪些）。
#
# 有了版本号，判重条件变成「parsed 且是当前版本解析的」，升级后第一次扫描
# 自动把旧结果重解析一遍，不需要用户做任何事。
PARSER_VERSION = config.PARSER_VERSION


def _get_data_dir(data_dir=None):
    """获取数据目录：优先传入的data_dir，其次当前项目目录，最后全局目录。

    v0.1.247（D35）：**落点被墓碑挡住时不建目录**。
    原来这里无条件 os.makedirs(data_dir) —— 项目被删之后，扫描线程再走
    一步就把刚删掉的目录重新建出来。实测事故：接口如实返回
    data_deleted:true，磁盘上 data/projects/<pid>/ 又出现了。
    """
    if data_dir:
        if not _tomb_blocked(data_dir):
            os.makedirs(data_dir, exist_ok=True)
        return data_dir
    try:
        from . import project_manager as _pm
        current = _pm.get_current_project()
        if current:
            pdir = _pm.get_project_data_dir(current["id"])
            if not _tomb_blocked(pdir):
                os.makedirs(pdir, exist_ok=True)
            return pdir
    except Exception:
        pass
    os.makedirs(config.DATA_DIR, exist_ok=True)
    return config.DATA_DIR


# v0.1.247（D35）：**落点被墓碑挡住**时的一票否决。
#
# 事故现场（真机 2026-11-13，WORKbuddy D35）：删掉的项目目录被正在跑的
# 扫描线程**写了回来** —— 接口如实返回 data_deleted:true，磁盘上目录却还在。
# 根因是 `_get_data_dir()` 里那行 os.makedirs(data_dir)：它会把刚删掉的
# 目录重新建出来，于是后面每一次写盘都落在一个"复活"的目录里。
#
# 所以判定必须放在**任何 mkdir 之前**。
def _tomb_blocked(data_dir) -> bool:
    """该落点是否已被删除（项目墓碑命中）。永不抛异常。"""
    try:
        return bool(data_dir) and _tombstone.is_deleted(data_dir)
    except Exception:  # noqa: BLE001
        return False


# v0.1.247（D35）：**在跑的扫描登记表**。
#
# 删除项目时必须先让该目录上的扫描收手，否则它会一边被删一边继续写。
# 多项目平台下这里按 data_dir 索引：A 项目扫描不影响 B 项目。
_ACTIVE_SCANS = {}
_ACTIVE_SCANS_LOCK = threading.Lock()


def cancel_scans_for(data_dir: str) -> int:
    """取消正在指定目录上跑的扫描，返回被取消的扫描数。

    v0.1.247（D35）：删除项目前调用。扫描线程在下一个文件边界就会退出，
    不再往一个已经被删掉的目录里写。
    """
    if not data_dir:
        return 0
    key = os.path.abspath(data_dir)
    with _ACTIVE_SCANS_LOCK:
        items = [(k, v) for k, v in _ACTIVE_SCANS.items() if k == key]
    n = 0
    for _k, ev in items:
        try:
            ev.set()
            n += 1
        except Exception:  # noqa: BLE001
            pass
    return n


def active_scans() -> list:
    """当前在跑的扫描清单（自测/运维用）。"""
    with _ACTIVE_SCANS_LOCK:
        return [{"data_dir": k, "running": True} for k in _ACTIVE_SCANS]


def _ensure(data_dir=None) -> str:
    """返回当前数据目录下的 index.json 路径（v0.1.129：不再设置全局 INDEX_FILE，消除多项目/并发竞态）。"""
    ddir = _get_data_dir(data_dir)
    os.makedirs(ddir, exist_ok=True)
    return os.path.join(ddir, "index.json")


def _load_index(data_dir=None) -> dict:
    # v0.1.247（D35）：落点已被删除 → 直接返回空索引，**不碰磁盘**。
    # 原来这里会先 _ensure() 建出目录，再去读一个不存在的 index.json。
    if data_dir and _tomb_blocked(data_dir):
        return {}
    idx_file = _ensure(data_dir)
    if os.path.exists(idx_file):
        try:
            with open(idx_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


# v0.1.198：索引写盘必须**原子替换**，且并发写要串行化。
#
# 实测事故（同一份 2000 条文件的索引，121831 B）：
#   原来 `open(idx_file, "w")` 直接覆盖写 —— 写到一半断电/进程被杀（现场是
#   用户在扫描大目录时关机、或笔记本电池耗尽），磁盘上留下 **半截 JSON**
#   (实测 60915 B)，`_load_index()` 的 except 静默返回 `{}`：
#     JSONDecodeError: Unterminated string starting at line 4075
#     → _load_index 兜底返回 {}
#   结果是**用户整个资料库索引全部丢失，界面上一个字都不报** ——
#   已解析的 2000 个文件全被当成「没处理过」，重扫一遍要几小时；
#   设备台账、"已入库"去重记录、文件状态全部归零。
#
#   这不是理论风险：index.json 是每 50 个文件落一次盘的**全量重写**，
#   文件越写越大（现场上千条），写盘窗口越来越长，撞上断电的概率随之变高。
#
#   两处改动：
#     ① 写临时文件再 os.replace —— 替换是原子操作，要么旧文件完整、要么新文件完整，
#        绝不会出现半截；临时文件名带 uuid，两路并发不会互抢同一个 .tmp；
#     ② 模块级可重入锁包住「读—改—写」——扫描线程与网页上传线程会同时改索引，
#        不加锁时后写的用旧快照整份覆盖，先写的条目凭空消失。
_INDEX_LOCK = threading.RLock()


def _save_index(idx: dict, data_dir=None):
    """原子写索引：先写唯一临时文件、再 os.replace 替换。

    v0.1.198：直接覆盖写在写到一半崩溃时会留下半截 JSON，
    _load_index 静默返回 {} → 用户整个资料库索引全部丢失（实测复现见上方注释）。

    v0.1.247（D35）：**落点被删（墓碑命中）时直接不写**。
    原来这里先 `_ensure(data_dir)`，而 `_ensure` 内部会 os.makedirs(data_dir)
    —— 刚被删掉的项目目录就这样被"复活"，index.json 重新出现（0 条）。
    """
    if data_dir and _tomb_blocked(data_dir):
        return False
    idx_file = _ensure(data_dir)
    with _INDEX_LOCK:
        tmp = f"{idx_file}.{uuid.uuid4().hex[:8]}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(idx, f, ensure_ascii=False, indent=1)
                f.flush()
                try:
                    os.fsync(f.fileno())   # 落盘再替换，断电后新文件也是完整的
                except OSError:
                    pass
            # v0.1.227：走统一的重试版 replace —— Windows 上读者持有句柄时
            # os.replace 会抛 WinError 5，索引写入被静默丢掉（见 atomic_io 注释）
            _atomic_io._replace_with_retry(tmp, idx_file)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass


def merge_index_entries(entries: dict, data_dir=None) -> int:
    """把若干条目**合并**进 index.json（v0.1.224）。

    修的是「批次上传用旧快照整份覆盖，把并发写入的条目抹掉」。

    实测事故（2026-11-10，项目 0c9a4b2d 马诺诺）：
      /api/upload-files 在函数开头 `idx = scanner._load_index()` 拿一份快照，
      整批传完才 `_save_index(idx)`。一次几十个文件的上传要跑好几分钟，
      这几分钟里任何别的写入（网页另开一批上传、/api/scan、设备同步）
      都会被批次末尾那一次 `_save_index` 用**旧快照**整份覆盖 ——
      磁盘上 parsed_cache 有 36 个解析结果，index.json 里只有 5 条，
      剩下 31 个文件在资料库里根本不存在，界面上一个字都不报。

    `_save_index` 的 `_INDEX_LOCK` 只保证「这一次写」原子，管不住
    「调用方拿的快照已经过期」。所以合并必须由本函数在锁内完成
    「读最新 → 只覆盖自己的键 → 写回」，调用方不能再自己攒着写。
    """
    if not isinstance(entries, dict) or not entries:
        return 0
    with _INDEX_LOCK:
        idx = _load_index(data_dir)
        if not isinstance(idx, dict):
            idx = {}
        skip = set(INDEX_RESERVED_KEYS) | set(INDEX_AUX_KEYS)
        changed = 0
        for k, v in entries.items():
            if not isinstance(k, str) or not k or k in skip:
                continue
            if idx.get(k) != v:
                idx[k] = v
                changed += 1
        if changed:
            _save_index(idx, data_dir)
        return changed


def reparse_stale(data_dir=None, dry_run: bool = True) -> dict:
    """统计「索引里有、但解析器已换代」的文件，供界面/自测核对（v0.1.227）。

    背景见 PARSER_VERSION 那段注释：存量文件不会因为解析器修好而自动更新，
    因为判重只看 status=="parsed"。修好 ODA 探测之后，25 张 DWG 在库里
    依旧是「0 字」，看上去像没修 —— 这是「同一件事两个答案」的又一例：
    磁盘上的解析器说能读，资料库里的结果说读不出。

    本函数不做重解析，只回答三个数：
      total  —— 索引里参与统计的文件数
      stale  —— 需要重解析的（解析器换代，或从没用 present 版本解析过）
      legacy —— 其中连 parser_version 字段都没有的历史条目
    dry_run=False 时只把 stale 条目里的 parser_version 抹掉，使下一次
    扫描/上传把它们当新文件重新解析（不动正文，出错也能回退）。
    """
    ddir = _get_data_dir(data_dir)
    idx = _load_index(ddir)
    if not isinstance(idx, dict):
        idx = {}
    skip = set(INDEX_RESERVED_KEYS) | set(INDEX_AUX_KEYS)
    out = {"total": 0, "stale": 0, "legacy": 0, "by_ext": {},
           "parser_version": PARSER_VERSION, "dry_run": bool(dry_run),
           "sample": []}
    touched = 0
    for k, v in idx.items():
        if k in skip or not isinstance(v, dict):
            continue
        out["total"] += 1
        pv = v.get("parser_version")
        if pv == PARSER_VERSION:
            continue
        out["stale"] += 1
        if not pv:
            out["legacy"] += 1
        ext = str(v.get("ext") or os.path.splitext(str(v.get("file_name") or ""))[1] or "?").lower()
        out["by_ext"][ext] = out["by_ext"].get(ext, 0) + 1
        if len(out["sample"]) < 8:
            out["sample"].append({"file_name": v.get("file_name"),
                                  "status": v.get("status"),
                                  "was_version": pv or "(无)"})
        if not dry_run:
            # 抹掉版本号而不是删条目：条目里的 file_path 还有用，
            # 下次扫描会按 sha 命中并重解析，重解析失败也不会丢路径。
            try:
                idx[k] = {**v, "parser_version": ""}
                touched += 1
            except Exception:  # noqa: BLE001
                pass
    if not dry_run and touched:
        _save_index(idx, ddir)
        out["marked"] = touched
    return out


def reconcile_index(data_dir=None, dry_run: bool = False) -> dict:
    """用 parsed_cache 回填 index.json 里缺失的文件条目（v0.1.224）。

    parsed_cache/{sha}.json 是「这个文件确实解析过」的原始凭证 ——
    上传和扫描两条路都先写缓存。index.json 则是资料库/去重/统计的唯一来源，
    原本**只有写它的那条路**知道自己要写，一旦那条路覆盖丢了（见
    merge_index_entries 的实测事故），没有任何人去比对两者，
    文件就永久从资料库里消失：缓存还在、正文还能读，列表里没有。

    本函数把缓存里存在、索引里没有的 sha 补回去，条目字段与
    上传路径 `_upload_process_one()` 写入的完全一致（不新增字段，
    避免下游按固定字段读取的地方取不到值）。
    """
    ddir = _get_data_dir(data_dir)
    out = {"index_files": 0, "cache_files": 0, "added": 0,
           "orphan_index": 0, "dry_run": bool(dry_run), "sample": []}
    idx = _load_index(ddir)
    if not isinstance(idx, dict):
        idx = {}
    out["index_files"] = count_index_files(idx)
    cache_dir = os.path.join(ddir, "parsed_cache")
    if not os.path.isdir(cache_dir):
        return out
    skip = set(INDEX_RESERVED_KEYS) | set(INDEX_AUX_KEYS)
    idx_keys = set(idx.keys())
    have = {k for k, v in idx.items()
            if isinstance(v, dict) and k not in skip}
    uploads = os.path.join(config.DATA_DIR, "uploads")
    new_entries = {}
    n_cache = 0
    cache_shas = set()
    for fn in os.listdir(cache_dir):
        if not fn.endswith(".json"):
            continue
        sha = fn[:-5]
        if len(sha) != 64:
            continue
        n_cache += 1
        cache_shas.add(sha)
        if sha in have:
            continue
        try:
            with open(os.path.join(cache_dir, fn), encoding="utf-8") as f:
                c = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(c, dict) or not c.get("file_name"):
            continue
        ents = c.get("entities")
        new_entries[sha] = {
            "file_name": c.get("file_name"),
            "file_path": os.path.join(uploads, c.get("file_name")),
            "status": c.get("status"),
            "parser": c.get("parser"),
            "error": c.get("error"),
            "entities": len(ents) if isinstance(ents, (list, tuple)) else 0,
            "retry_count": 0,
            "uploader": "",
            "orig_path": "",
            "ts": c.get("created_at") or "",
        }
    out["cache_files"] = n_cache
    out["added"] = len(new_entries)
    out["sample"] = sorted(new_entries)[:5]
    # 反向：索引里有、缓存里没有（文件被删/从未解析成功），只报数不改动
    out["orphan_index"] = max(0, len(have) - (n_cache - len(new_entries)))
    # 第三类：**落在 uploads 里但索引/缓存都没有**的文件 —— 批次上传被中断、
    # 或解析前抛异常时留下的孤儿。它既不在资料库里、也不在缓存里，
    # 除了对账没人会发现。落盘名是 `{sha[:12]}_{原名}`，按前缀比对即可，
    # 不必重新哈希整个文件（现场 uploads 常有几百 MB）。
    try:
        up_dir = os.path.join(config.DATA_DIR, "uploads")
        if os.path.isdir(up_dir):
            known = {k[:12] for k in have} | {k[:12] for k in cache_shas}
            orphans = []
            for fn in os.listdir(up_dir):
                pre = fn.split("_", 1)[0]
                if len(pre) == 12 and pre in known:
                    continue
                orphans.append(fn)
            out["orphan_uploads"] = len(orphans)
            out["orphan_uploads_sample"] = sorted(orphans)[:8]
    except Exception:  # noqa: BLE001
        pass
    if new_entries and not dry_run:
        merge_index_entries(new_entries, ddir)
        out["index_files_after"] = count_index_files(_load_index(ddir))
    return out


# 支持处理的扩展名集合（含未启用解析的类型，便于状态展示）
SUPPORTED_EXTS = (
    config.EXT_PDF + config.EXT_WORD + config.EXT_EXCEL + config.EXT_TEXT
    + config.EXT_IMAGE + config.EXT_CAD + config.EXT_PROJECT
    + list(getattr(config, "EXT_EXCEL_LEGACY", []))    # v0.1.224：.xls
)

# v0.1.134：索引保留键（非文件数据），遍历扁平键时必须跳过（P1 系列修复）
INDEX_RESERVED_KEYS = ("files", "devices", "workshops", "version", "updated_at", "relations")

# v0.1.209：索引里还有一类非文件键 —— 项目初始化/合并阶段会往顶层写
# `ledger_skipped_rows` 等辅助数组。它不在 INDEX_RESERVED_KEYS 里（历史遗漏），
# 但它同样不是文件条目。这里单独列出已知的非文件辅助键。
INDEX_AUX_KEYS = ("ledger_skipped_rows",)


def count_index_files(idx: dict = None) -> int:
    """统计索引里**真正已入库的文件数**（v0.1.209）。

    修的是一个口径错误：/api/status 原来写 `len(scanner._load_index())`，
    数的是**索引顶层字典的键数**，不是文件数。

    实测（2026-11-07 01:5x，项目 322fef90）：
      索引顶层 6 个键 = files / devices / workshops / <一个 sha256> /
                       ledger_skipped_rows / updated_at
      /api/status 的 indexed_files → 6
      同一时刻前端文件列表（/api/files）→ 1 条
      真实已入库文件 → 1 个（..._设备台账_真实_选矿厂.xlsx，status=parsed）
    6 对 1，同一件事两个答案；WORKbuddy 本机报告里的 indexed_files: 6
    也是这个假数（它当时有 6 个保留/辅助键，实际文件数并非 6）。

    口径统一为：files 列表条目 + 顶层 sha 形键条目（去重），剔除保留键与辅助键。
    与 main.py `_frontend_index_items()`（前端文件列表用的那个）同口径。
    传 idx 可复用已读到的索引，避免重复读盘。
    """
    if idx is None:
        idx = _load_index()
    if not isinstance(idx, dict):
        return 0
    skip = set(INDEX_RESERVED_KEYS) | set(INDEX_AUX_KEYS)
    seen = set()
    if isinstance(idx.get("files"), list):
        for f in idx["files"]:
            if not isinstance(f, dict):
                continue
            key = f.get("id") or f.get("sha256") or f.get("file_name") or ""
            if key:
                seen.add(key)
    for sha, info in idx.items():
        if not isinstance(info, dict) or sha in skip:
            continue
        key = sha or info.get("file_name") or ""
        if key:
            seen.add(key)
    return len(seen)

# v0.1.144：CAD/Office 临时锁定文件黑名单（扫描与上传均排除，避免误判为解析失败）
_TEMP_EXTS = (".dwl", ".dwl2", ".bak", ".tmp", ".temp", ".swp", ".swo")


def _is_temp_file(fn: str) -> bool:
    """判断是否为 CAD/Office 临时锁定文件（.dwl/.dwl2/.bak/~$* 等）。"""
    low = (fn or "").lower()
    if low.startswith("~$"):
        return True
    return any(low.endswith(ext) for ext in _TEMP_EXTS)


# v0.1.234（D23）：单文件解析硬超时。
#
# 现场事实：真机 65 个样本（25 张 DWG + 十几份扫描件 PDF）整轮扫描跑了 19.5 分钟，
# 而前 301 秒 /api/scan/status 一直返回 done=0/0、heartbeat 一次没刷新 ——
# 自测按 300s 判「卡死」，用户界面只能显示"0/0"，看不出是在啃大文件还是已经死了。
#
# 一个文件卡住就拖死整轮，是这一类「慢」最坏的表现形态。给它一个上限：
# 超时记失败、继续下一个文件，整轮永远能收尾。
PARSE_FILE_TIMEOUT_SEC = 120


def _parse_with_ticks(path, timeout=None, on_tick=None, tick_sec=2.0):
    """在线程里执行 parse_file，边等边按 tick 回调，超时则放弃。

    返回 (ParseResult | None, timed_out: bool, err: str)。

    为什么不像 OCR 那样起子进程：parse_file 内部已经会起子进程（ODA 转换、
    tesseract），外面再套一层进程，等于每个文件多付一次解释器启动开销
    （65 个文件 × 百毫秒级）。这里用线程 + 轮询：

      · **心跳由扫描线程自己刷**（每 tick_sec 一次），不是另起一个「永远在跳」的
        定时器 —— 后者会让真正卡死的扫描看起来一直活着，那就是假守卫；
      · 一旦超过 timeout，立刻放弃这个文件并继续下一个，所以「假活」最多持续
        到 timeout 为止，不会无限期掩盖真死。
    """
    timeout = PARSE_FILE_TIMEOUT_SEC if timeout is None else timeout
    out = {}

    def _work():
        try:
            out["res"] = parse_file(path)
        except BaseException as e:  # noqa: BLE001 —— 宿主 sitecustomize 的 SystemExit 也要收
            out["err"] = f"{type(e).__name__}: {e}"

    th = threading.Thread(target=_work, daemon=True)
    th.start()
    t0 = time.time()
    last_tick = 0.0
    while th.is_alive():
        th.join(tick_sec)
        if not th.is_alive():
            break
        elapsed = time.time() - t0
        if elapsed >= timeout:
            return None, True, f"解析超时（>{int(timeout)}s 未返回）"
        if on_tick is not None and elapsed - last_tick >= tick_sec:
            last_tick = elapsed
            try:
                on_tick(elapsed)
            except Exception:  # noqa: BLE001
                pass
    if out.get("err"):
        raise RuntimeError(out["err"])
    return out.get("res"), False, ""


def scan_folder(folder, force: bool = False, progress_cb=None, cancel_event=None,
                data_dir=None, stage_cb=None) -> dict:
    """扫描一个或多个文件夹，对每个新文件执行：解析 → 结构化入库 → 分块向量化 → 上传队列。
    folder 可为字符串或字符串列表。data_dir 指定数据目录（为None时自动使用当前项目目录）。返回统计。"""
    folders = [folder] if isinstance(folder, str) else list(folder)
    for f in folders:
        if not os.path.isdir(f):
            return {"error": f"路径不存在：{f}"}

    ddir = _get_data_dir(data_dir)
    idx = _load_index(ddir)
    store = VectorStore(db_path=os.path.join(ddir, "vector_db"))
    stats = {"found": 0, "parsed": 0, "vectorized": 0, "skipped": 0, "failed": 0, "duplicate": 0}

    file_list = []
    for folder in folders:
        for root, _dirs, files in os.walk(folder):
            for fn in sorted(files):
                ext = os.path.splitext(fn)[1].lower()
                if ext in SUPPORTED_EXTS and not _is_temp_file(fn):
                    file_list.append(os.path.join(root, fn))
    stats["found"] = len(file_list)
    _n_since_save = 0  # v0.1.177：索引分批落盘计数
    # v0.1.247（D33）：索引**按时间**落盘，不只按条数。
    # 原实现每 50 个文件才落一次盘 —— 真机 63 个文件的一轮扫描，
    # 前 12 个文件解析完了 index.json 都不存在（用户看到的是「资料库 0 条」），
    # 中途一断就全丢。改为「满 50 条 **或** 距上次落盘满 10 秒」就写。
    _last_save_at = time.time()
    _INDEX_SAVE_EVERY_SEC = 10

    def _set_stage(stage, fname=""):
        """阶段级进度（v0.1.247 / D33）。

        用户看到的进度必须能区分「在解析」「在向量化」「在归类」「在入库」——
        只给一个 done/total，用户分不清是慢还是死了。
        """
        if stage_cb is not None:
            try:
                stage_cb(stage, fname)
            except Exception:  # noqa: BLE001
                pass

    # v0.1.234（D23）：**枚举完立刻报一次进度**。
    # 原来 total 只在「某个文件解析完之后」的 cb 里才有值，于是扫描刚启动的
    # 那段时间 /api/scan/status 返回 done=0/0，界面无法区分「在啃大文件」和「死了」。
    # 真机实测这 301 秒里 done 一直是 0/0、heartbeat 一次未刷新。
    if progress_cb:
        try:
            progress_cb(0, len(file_list), f"开始解析（共 {len(file_list)} 个文件）")
        except Exception:  # noqa: BLE001
            pass

    for i, path in enumerate(file_list):
        if cancel_event is not None and cancel_event.is_set():
            break
        # v0.1.234（D23）：**解析开始前**打心跳，不是解析完之后。
        # 首个文件可能是 100MB 的 DWG（ODA 转换）或几十页扫描件（OCR），
        # 单它就上百秒；只在「解析完」回调，这段时间正好是心跳盲区。
        # v0.1.247（D35）：扫描途中项目被删 → 立刻收手，不再往墓碑目录写。
        if _tomb_blocked(ddir):
            stats["aborted_deleted_project"] = True
            break
        if progress_cb:
            try:
                progress_cb(i, len(file_list), f"解析中 {os.path.basename(path)}")
            except Exception:  # noqa: BLE001
                pass
        _set_stage("解析", os.path.basename(path))
        try:
            if not force:
                import hashlib
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    for block in iter(lambda: f.read(65536), b""):
                        h.update(block)
                key = h.hexdigest()
                if (key in idx and idx[key].get("status") == "parsed"
                        and idx[key].get("parser_version") == PARSER_VERSION):
                    stats["duplicate"] += 1
                    if progress_cb:
                        progress_cb(i + 1, len(file_list), f"重复跳过 {os.path.basename(path)}")
                    continue
            else:
                key = None

            size_mb = os.path.getsize(path) / 1024 / 1024
            if size_mb > config.MAX_FILE_MB:
                stats["skipped"] += 1
                if progress_cb:
                    progress_cb(i + 1, len(file_list), f"超限跳过 {os.path.basename(path)}")
                continue

            res, _timed_out, _to_err = _parse_with_ticks(
                path,
                on_tick=(lambda el, _i=i, _p=path: progress_cb(
                    _i, len(file_list), f"解析中 {os.path.basename(_p)}（{int(el)}s）")
                if progress_cb else None),
            )
            if _timed_out or res is None:
                # v0.1.234（D23）：单文件超时不拖死整轮，记失败并继续下一个。
                # 用户能在「失败清单」里看到它，也不会因此永远等不到扫描结束。
                stats["failed"] += 1
                stats.setdefault("timeouts", 0)
                stats["timeouts"] += 1
                if progress_cb:
                    try:
                        progress_cb(i + 1, len(file_list),
                                    f"超时跳过 {os.path.basename(path)}")
                    except Exception:  # noqa: BLE001
                        pass
                continue
            if res.status == "parsed" or res.status == "partial":
                stats["parsed"] += 1
                # 向量化失败不得影响已解析文件的入库（原实现中 index_file 抛异常
                # 会被外层 except 捕获并把整个文件判为 failed，导致解析成功的文件
                # 全部无法进入资料库；embedding 模型缺失时这是必然触发路径）
                _set_stage("向量化", os.path.basename(path))
                try:
                    n = store.index_file(res)
                except Exception as _ve:  # noqa: BLE001
                    n = 0
                    res.structure = res.structure or {}
                    res.structure["vector_error"] = str(_ve)[:200]
                if n:
                    stats["vectorized"] += 1
                # 无论是否成功向量化都进上传队列（云端合并保留原文+解析）
                _set_stage("归类入库", os.path.basename(path))
                # v0.1.245：必须带 ddir —— 不带时包落「当前项目」队列。
                # 多项目平台下，用户扫的是项目 A 的资料、当前选中的却是 B，
                # A 的包就出现在 B 的待上传列表里（项目之间互相串包）。
                upload_queue.enqueue(res, data_dir=ddir)
                # v0.1.27：解析后自动归车间（人工登记不覆盖）
                # v0.1.177：**必须传 file_path** —— 用户是按车间/工艺单元分文件夹的，
                # 目录名是最强归属信号（detect_workshop 里 file_path 优先级 0.85，仅次于 CAD 图名）。
                # 实测事故：这里一直只传了文件名，file_path 恒为空 → 目录信号从未进入检测，
                # 237 个明确放在「重介质」目录的资料 96% 归不到车间。
                # v0.1.245：同时必须传 data_dir —— 车间归属同样只能落在本项目。
                try:
                    from . import workshop_assign
                    workshop_assign.assign_workshop(res.sha256, res.file_name, res.text or "",
                                                    res.structure or {}, file_path=path,
                                                    data_dir=ddir)
                except Exception:  # noqa: BLE001
                    pass
                # v0.1.32：登记文件版本（多版本对照+最新版判断）
                # v0.1.245：版本台账跟车间归属同理，只能落在本项目。
                try:
                    from . import version_manager
                    import os as _os
                    _fsize = _os.path.getsize(path) if _os.path.exists(path) else 0
                    _dv, _dd, _mt = version_manager.extract_doc_meta(res.structure, path)
                    version_manager.record_version(res.file_name, res.sha256,
                                                    ts=datetime.datetime.now().isoformat(),
                                                    size=_fsize, status=res.status,
                                                    doc_version=_dv, doc_date=_dd, mtime=_mt,
                                                    data_dir=ddir)
                except Exception:  # noqa: BLE001
                    pass
                # v0.1.34：群聊文件自动解析关联（检测到聊天记录则解析消息+提取位号/车间/事项）
                try:
                    from . import chat_parser
                    if chat_parser.is_chat_file(path, res.text or ""):
                        chat_result = chat_parser.analyze_chat(path)
                        if chat_result.get("ok"):
                            res.structure = res.structure or {}
                            res.structure["chat"] = {
                                "message_count": chat_result["message_count"],
                                "sender_count": chat_result["sender_count"],
                                "senders": chat_result["senders"],
                                "date_range": chat_result["date_range"],
                                "tags": list(chat_result["extracted"]["tags"].keys()),
                                "workshops": list(chat_result["extracted"]["workshops"].keys()),
                                "topics": list(chat_result["extracted"]["topics"].keys()),
                                "summary": chat_result["summary"],
                            }
                            res.parser = "chat"
                            stats["chat_parsed"] = stats.get("chat_parsed", 0) + 1
                except Exception:  # noqa: BLE001
                    pass
                # 所有后处理完成后保存解析缓存（含群聊/车间等 enrichment）
                # v0.1.245：必须带 ddir —— 不带时缓存落「当前项目」，
                # 扫项目 A 的资料却把缓存写进项目 B，B 的资料库会出现 A 的文件。
                _save_parsed_cache(res, ddir)
            else:
                stats["skipped" if res.status == "skipped" else "failed"] += 1
                # v0.1.143：解析失败/跳过的文件也按文件名+目录路径自动归车间
                # （与网页上传 elif 分支一致；DWG 无 ezdxf 等场景不依赖解析成功）
                try:
                    from . import workshop_assign
                    workshop_assign.assign_workshop(res.sha256, res.file_name,
                                                    res.text or "", res.structure or {},
                                                    file_path=path, data_dir=ddir)
                except Exception:  # noqa: BLE001
                    pass

            key = key or res.sha256
            idx[key] = {
                "file_name": res.file_name,
                "file_path": path,
                "status": res.status,
                "parser": res.parser,
                "error": res.error,
                "entities": len(res.entities),
                "retry_count": 0,
                "ts": datetime.datetime.now().isoformat(),
                "parser_version": PARSER_VERSION,
            }
            # v0.1.177：索引**分批落盘**，不再每个文件全量 dump。
            # 实测事故：索引写到上千条时，每解析一个文件就要把整个 index.json
            # 重新序列化写盘，扫描进度越来越慢，大目录扫到一半整站卡死。
            # 每 50 个落一次盘，既保证崩溃时可恢复，又把写盘次数降了 98%。
            _n_since_save += 1
            if (_n_since_save >= 50
                    or (time.time() - _last_save_at) >= _INDEX_SAVE_EVERY_SEC):
                _save_index(idx, ddir)
                _n_since_save = 0
                _last_save_at = time.time()
            if progress_cb:
                progress_cb(i + 1, len(file_list), f"{res.status}: {res.file_name}")
        except Exception as e:  # noqa: BLE001
            stats["failed"] += 1
            if progress_cb:
                progress_cb(i + 1, len(file_list), f"异常 {os.path.basename(path)}: {e}")

    # v0.1.177：收尾补一次落盘（不足 50 个的尾巴）
    # v0.1.247（D33b）：**异常路径也必须落盘**。
    # 原来只有"正常走完"才写；扫描中途被 Ctrl-C / 进程被杀 / 抛异常，
    # 已解析的几百个文件的索引全丢，用户重扫一遍（实测一轮 20 分钟）。
    try:
        if _n_since_save:
            _save_index(idx, ddir)
    except Exception:  # noqa: BLE001
        pass
    _set_stage("完成", "")

    # v0.1.172：扫描结束把设备台账行写进 index.json["devices"]
    # （原来该字段无人写入，导致监理确认表按车间出设备行时恒为空）
    try:
        sync_devices(ddir)
    except Exception:  # noqa: BLE001
        pass
    return stats


def reparse_file(path: str, data_dir=None) -> dict:
    """v0.1.212：单文件重新解析（前端「重解析」按钮的真实实现）。

    缺陷（实测 2026-11-07 19:2x）：/api/files/reparse 的后台线程里调用
    `_sc.index_result(res, src, force=True)` —— **这个函数在 scanner 里根本不存在**，
    一调用就抛 AttributeError，而外层是 `except Exception: pass` 把它彻底吞掉。
    于是接口对用户永远返回「已加入重解析队列」，实际一个字节都没处理：
    解析缓存没生成、索引没更新、车间没重算，界面上看不出任何异常。
    这类「静默失败 + 谎报成功」比直接报错更难查 —— 用户会以为是自己操作不对。

    这里复用 scan_folder 里那条真实链路（parse_file → 缓存 → 索引 → 车间 → 设备同步），
    并把结果如实返回，不再吞异常。
    """
    res: ParseResult = parse_file(path)
    ddir = _get_data_dir(data_dir)
    idx = _load_index(ddir)
    n_vec = 0
    if res.status in ("parsed", "partial"):
        try:
            n_vec = VectorStore(db_path=os.path.join(ddir, "vector_db")).index_file(res)
        except Exception as _ve:  # noqa: BLE001
            res.structure = res.structure or {}
            res.structure["vector_error"] = str(_ve)[:200]
        try:
            # v0.1.212：必须带上 ddir —— 不传时 enqueue 恒落「当前项目」队列，
            # 于是在临时目录里做重解析（单测 / 离线校验）会把包写进用户真实项目的
            # 待上传队列。实测：单测造的 4 个样本让真实项目 pending 变成 4。
            upload_queue.enqueue(res, data_dir=ddir)
        except Exception:  # noqa: BLE001
            pass
        try:
            from . import workshop_assign
            # v0.1.214：必须带上 ddir —— 不传时 assign_workshop 恒落「当前项目」，
            # 于是在临时目录里重解析会把车间归属写进用户真实项目。实测事故：
            # 真实项目 322fef90 的 workshop_assign.json 22 条里 21 条指向
            # /tmp/fgpath_*，界面上「待人工确认」从 0 涨到 10。
            workshop_assign.assign_workshop(res.sha256, res.file_name, res.text or "",
                                            res.structure or {}, file_path=path,
                                            data_dir=ddir)
        except Exception:  # noqa: BLE001
            pass
        _save_parsed_cache(res, ddir)
    idx[res.sha256] = {
        "file_name": res.file_name,
        "file_path": path,
        "status": res.status,
        "parser": res.parser,
        "error": res.error,
        "entities": len(res.entities),
        "retry_count": 0,
        "ts": datetime.datetime.now().isoformat(),
    }
    _save_index(idx, ddir)
    try:
        sync_devices(ddir)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": res.status in ("parsed", "partial"), "status": res.status,
            "parser": res.parser, "error": res.error,
            "entities": len(res.entities), "vectorized": n_vec,
            "sha256": res.sha256, "cache_saved": res.status in ("parsed", "partial")}


def sync_devices(data_dir=None) -> dict:
    """v0.1.172：把设备台账行写进 index.json 的 devices。
    失败不影响主流程（设备同步是下游增强项，不能让解析入库回滚）。"""
    ddir = _get_data_dir(data_dir)
    try:
        from . import equipment_merge as _em
        return _em.sync_devices_to_index(ddir)
    except Exception as e:  # noqa: BLE001
        return {"devices": 0, "error": f"设备同步失败：{e}"}


def _save_parsed_cache(res: ParseResult, data_dir=None):
    """把解析结果缓存到 data/parsed_cache/{sha256}.json，供详情页读取。
    v0.1.129：修复 BUG-0 —— data_dir 缺省时自行解析当前数据目录（原来引用 scan_folder 局部变量 ddir 导致 NameError）。"""
    if data_dir and _tomb_blocked(data_dir):
        return False
    ddir = _get_data_dir(data_dir)
    cache_dir = os.path.join(ddir, "parsed_cache")
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, f"{res.sha256}.json"), "w", encoding="utf-8") as f:
        json.dump({
            "file_name": res.file_name, "file_size": res.file_size,
            "sha256": res.sha256, "ext": res.ext, "parser": res.parser,
            "status": res.status, "error": res.error,
            "text": res.text[:20000], "structure": res.structure,
            "entities": res.entities, "created_at": res.created_at,
            # v0.1.227：谁解析的、用哪一代解析器解析的，落盘留证。
            # 缺这个字段的历史缓存会被下一次扫描判为「过期」并重解析。
            "parser_version": PARSER_VERSION,
        }, f, ensure_ascii=False, indent=1)


def _load_cache(sha: str, data_dir=None) -> dict:
    """读取解析缓存 data/parsed_cache/{sha256}.json。
    v0.1.143：此前不存在该函数，导致 workshop_assign.re_auto_unassigned()
    的 hasattr 判断恒为 False，车间重新识别按钮永远空转（返回 0）。"""
    ddir = _get_data_dir(data_dir)
    p = os.path.join(ddir, "parsed_cache", f"{sha}.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


MAX_RETRY = 3   # 单个文件失败重试上限（v0.1.21）


def retry_failed_files(status: dict = None, shas: list = None, data_dir=None) -> dict:
    """重试失败文件（v0.1.21）：可全部重试或指定 sha；每次失败 retry_count+1，
    达到 MAX_RETRY 后转 pending_manual（待处理，人工介入）。

    v0.1.245：补 data_dir，并把**四个落点对齐到同一目录**。
    实测事故：原来这里 `store = VectorStore()`（落全局 data/vectordb），
    而 scan_folder / reparse_file 都落「项目目录/vector_db」——
    同一个文件**扫描**进项目向量库、**重试**进全局向量库，两条路两个答案。
    平台化之后一个进程要同时服务多个施工项目，全局向量库会把所有项目的资料
    混在一起，检索时根本分不清命中的是哪个项目。现在 index / 向量库 / 队列包 /
    解析缓存四个落点都跟随 data_dir。
    """
    ddir = _get_data_dir(data_dir)
    idx = _load_index(ddir)
    store = VectorStore(db_path=os.path.join(ddir, "vector_db"))
    if shas:
        targets = [(sha, info) for sha, info in idx.items()
                   if sha in set(shas) and sha not in INDEX_RESERVED_KEYS
                   and isinstance(info, dict)
                   and info.get("status") in ("failed", "pending_manual")]
    else:
        targets = [(sha, info) for sha, info in idx.items()
                   if sha not in INDEX_RESERVED_KEYS and isinstance(info, dict)
                   and info.get("status") in ("failed", "pending_manual")]
    stats = {"retried": 0, "recovered": 0, "still_failed": 0, "missing": 0,
             "pending_manual": 0, "pending_list": []}

    for i, (sha, info) in enumerate(targets):
        path = info.get("file_path")
        if not path or not os.path.exists(path):
            stats["missing"] += 1
            rc = int(info.get("retry_count", 0)) + 1
            if rc >= MAX_RETRY:
                idx[sha] = {**info, "status": "pending_manual", "retry_count": rc,
                            "pending_note": "文件不在原位置且多次重试失败，请人工检查",
                            "ts": datetime.datetime.now().isoformat()}
                stats["pending_manual"] += 1
                stats["pending_list"].append({"sha256": sha, "file_name": info.get("file_name", ""),
                                              "error": info.get("error", "")})
            else:
                idx[sha] = {**info, "retry_count": rc, "ts": datetime.datetime.now().isoformat()}
            _save_index(idx, ddir)
            stats["retried"] += 1
            if status is not None:
                status.update({"msg": f"文件已不在原位置: {info.get('file_name')}"})
            continue
        res = parse_file(path)
        if res.status == "parsed" or res.status == "partial":
            store.index_file(res)
            upload_queue.enqueue(res, data_dir=ddir)
            _save_parsed_cache(res, ddir)
            stats["recovered"] += 1
            idx[sha] = {
                "file_name": res.file_name, "file_path": path,
                "status": res.status, "parser": res.parser,
                "error": res.error, "entities": len(res.entities),
                "retry_count": 0, "ts": datetime.datetime.now().isoformat(),
            }
        else:
            rc = int(info.get("retry_count", 0)) + 1
            if rc >= MAX_RETRY:
                idx[sha] = {**info, "status": "pending_manual", "retry_count": rc,
                            "pending_note": "多次重试仍失败，请人工检查文件",
                            "ts": datetime.datetime.now().isoformat()}
                stats["pending_manual"] += 1
                stats["pending_list"].append({"sha256": sha, "file_name": info.get("file_name", ""),
                                              "error": res.error or info.get("error", "")})
            else:
                idx[sha] = {**info, "status": "failed", "retry_count": rc,
                            "error": res.error or info.get("error", ""),
                            "ts": datetime.datetime.now().isoformat()}
            stats["still_failed"] += 1
        stats["retried"] += 1
        _save_index(idx, ddir)
        if status is not None:
            status.update({"done": i + 1, "total": len(targets), "msg": f"重试: {info.get('file_name')}"})
    if status is not None:
        status.update({"running": False, "stats": stats, "msg": "重试完成"})
    return stats


def list_failed(data_dir=None) -> list:
    """失败 + 待处理文件清单（供①页展示/重试/删除）。"""
    idx = _load_index(data_dir)
    out = []
    for sha, info in idx.items():
        if sha in INDEX_RESERVED_KEYS or not isinstance(info, dict):
            continue
        if info.get("status") in ("failed", "pending_manual"):
            out.append({
                "sha256": sha,
                "file_name": info.get("file_name", ""),
                "file_path": info.get("file_path", ""),
                "status": info.get("status", "failed"),
                "error": info.get("error", ""),
                "retry_count": int(info.get("retry_count", 0)),
                "pending_note": info.get("pending_note", ""),
                "ts": info.get("ts", ""),
            })
    out.sort(key=lambda x: x.get("ts", ""), reverse=True)
    return out


def delete_failed(shas: list, data_dir=None) -> dict:
    """删除失败/待处理登记（保留磁盘原文件）。"""
    idx = _load_index(data_dir)
    n = 0
    for sha in shas:
        info = idx.get(sha)
        if sha not in INDEX_RESERVED_KEYS and isinstance(info, dict) \
                and info.get("status") in ("failed", "pending_manual"):
            del idx[sha]
            n += 1
    _save_index(idx, data_dir)
    return {"deleted": n}


def background_scan(folder, force: bool = False, status: dict = None, progress_cb=None,
                    data_dir=None):
    """后台线程执行扫描（任务线程，不阻塞 API）。status: 共享 dict 用于轮询进度。
    v0.1.144：修复致命 Bug——main.py 调用时传 progress_cb=... 但本函数签名缺失该参数，
    导致每次扫描启动即抛 TypeError 被吞掉，上传文件永不入库。
    同时异常时也写入 stats（此前异常分支 stats 为 null，前端误判为"没数据"）。

    v0.1.245：新增 data_dir。落点必须在**请求时**定死并传进来，
    不能在子线程里现查「当前项目」——用户在扫描途中切了项目，
    文件就落进另一个项目（多项目平台上的串味）。"""
    ddir = _get_data_dir(data_dir)
    cancel = threading.Event()
    if status is not None:
        status["running"] = True
        status["cancel"] = cancel
        # v0.1.247（D33）：状态字段补全 —— 界面要能区分「在跑」「卡住」「在哪个文件」。
        status["stage"] = "准备中"
        status["in_flight_file"] = ""
        status["in_flight_seconds"] = 0
        status["last_progress"] = time.time()
        status["in_flight_started"] = 0
        # v0.1.234（D26）：**在后台线程接手的第一时间就把 running 钉成 True**。
        # 原来 /api/scan 先把 running 置 False、过一会儿才由本线程置 True，
        # 这个窗口里来的第二个 POST /api/scan 不会被 409 拦住，会起第二个
        # 扫描线程，两个线程共写同一份 SCAN_STATUS 与同一个 index.json。
        status["heartbeat"] = time.time()

    # v0.1.247（D35）：登记到「在跑扫描表」，删除项目时可以把它取消掉。
    _akey = os.path.abspath(ddir)
    with _ACTIVE_SCANS_LOCK:
        _ACTIVE_SCANS[_akey] = cancel

    # v0.1.247（D33）：**独立心跳守护线程**。
    #
    # 原来的心跳挂在扫描线程自己的 progress_cb 上，扫描线程被同步步骤
    # （加载 embedding 模型 ≈ 75 秒、OCR、DWG 转换）卡住时心跳跟着停 ——
    # 实测「75.8 秒没有任何心跳」，用户和监控都以为程序死了。
    #
    # 现在把两个概念拆开：
    #   · heartbeat      —— **服务还活着**（守护线程每 2 秒刷一次，与业务无关）
    #   · last_progress  —— **业务真有进展**的最后时刻（长时间不动才是真卡）
    #   · in_flight_file / in_flight_seconds —— 卡在哪个文件、卡了多久
    #
    # 三个字段一起给，界面才能区分「在啃大文件」和「真的死了」。
    _hb_stop = threading.Event()

    def _hb_loop():
        while not _hb_stop.wait(2.0):
            try:
                if status is not None:
                    status["heartbeat"] = time.time()
                    started = status.get("in_flight_started") or 0
                    if started:
                        status["in_flight_seconds"] = round(time.time() - started, 1)
            except Exception:  # noqa: BLE001
                pass

    _hb_thread = threading.Thread(target=_hb_loop, daemon=True,
                                  name="fg-scan-heartbeat")
    _hb_thread.start()

    def cb(done, total, msg):
        if status is not None:
            status.update({"done": done, "total": total, "msg": msg})
            status["last_progress"] = time.time()

    def stage_cb(stage, fname=""):
        """阶段进度（v0.1.247 / D33）。"""
        if status is not None:
            status["stage"] = stage
            status["in_flight_file"] = fname or ""
            status["in_flight_started"] = time.time() if fname else 0
            status["last_progress"] = time.time()

    # 组合回调：内部 cb 更新 status，外部 progress_cb（如心跳）同步调用
    def combined_cb(done, total, msg):
        cb(done, total, msg)
        if progress_cb is not None:
            try:
                progress_cb(done, total, msg)
            except Exception:  # noqa: BLE001
                pass

    try:
        stats = scan_folder(folder, force=force, progress_cb=combined_cb,
                            cancel_event=cancel, data_dir=ddir, stage_cb=stage_cb)
        if status is not None:
            status.update({"running": False, "done": stats.get("found", 0), "stats": stats, "msg": "完成"})
            status["stage"] = "已结束"
            status["in_flight_file"] = ""
    except Exception as e:  # noqa: BLE001
        if status is not None:
            status.update({"running": False, "stats": {"error": str(e)}, "msg": f"扫描异常: {e}"})
            status["stage"] = "异常结束"
    finally:
        _hb_stop.set()
        with _ACTIVE_SCANS_LOCK:
            if _ACTIVE_SCANS.get(_akey) is cancel:
                _ACTIVE_SCANS.pop(_akey, None)
        if status is not None:
            status["heartbeat"] = time.time()
