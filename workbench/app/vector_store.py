# 繁工AI 本地解析工作台 - 分块 + 向量化 + 向量库
# 使用 ChromaDB 持久化到本地 data/vectordb/；embedding 用 sentence-transformers 本地模型
# （首次运行自动下载模型约 470MB，需联网一次；之后离线可用）

import os
import json
import datetime
import threading

from . import config
# v0.1.247（D35）：项目删除墓碑 —— 落点被删后向量库不得再被写回。
from . import tombstone as _tombstone

# v0.1.234（D19）：**所有被创建过的 VectorStore 实例都要能被找到并关掉**。
#
# 真机根因（WORKbuddy 对照实验定性）：删项目时报
#   PermissionError [WinError 32] …vector_db\<uuid>\data_level0.bin
# 而「重启服务释放句柄后，同一个请求原样再发一次」立刻成功 ——
# 说明删除逻辑没错，是 chroma 的 PersistentClient 打开后从不关闭，
# 服务进程自己攥着那个 .bin 文件。Windows 没有 unlink-on-open，删不掉。
#
# 这里用一个弱引用注册表：谁创建了 VectorStore，谁就在表里，
# 删除项目前按 db_path 前缀把它们逐个关掉，再删目录。
# 用 weakref 是为了不因为注册表本身把实例续命（否则永远关不掉）。
_STORE_REGISTRY = []

# v0.1.240：最近一次「关库」的实际结果，给 delete_project 写进返回体与审计 ——
# 否则真机上只能说「我调了 close_stores_under」而说不出它到底关了没有。
_LAST_CLOSE_REPORT = {"closed": 0, "cache_cleared": False}


def _register(store):
    import weakref
    try:
        _STORE_REGISTRY.append(weakref.ref(store))
    except Exception:  # noqa: BLE001
        pass


def close_stores_under(prefix: str) -> int:
    """关掉所有 db_path 落在 prefix 之下的向量库实例，返回关闭个数。

    调用点：删除项目目录**之前**。不关就直接 rmtree，Windows 上必撞
    WinError 32（data_level0.bin / chroma.sqlite3 被本进程占着）。
    """
    import gc
    prefix = os.path.abspath(prefix)
    closed = 0
    alive = []
    for ref in list(_STORE_REGISTRY):
        st = ref()
        if st is None:
            continue
        alive.append(ref)
        try:
            p = os.path.abspath(getattr(st, "_db_path", "") or "")
        except Exception:  # noqa: BLE001
            continue
        if not p:
            continue
        # 目录比较要按「路径是项目目录的子路径」判，不能用字符串 startswith
        # （D:\proj\p1 与 D:\proj\p10 会假命中）。
        try:
            if os.path.commonpath([p, prefix]) == prefix:
                st.close()
                closed += 1
        except Exception:  # noqa: BLE001
            continue
    # 清掉已死的引用，避免注册表无界增长
    _STORE_REGISTRY[:] = alive
    # v0.1.240：**弱引用表清空 ≠ 句柄释放**。
    #
    # 真机 2026-11-11 17:04 的报告里，v0.1.234 加了 close_stores_under 之后
    # 删项目仍然报：
    #   PermissionError [WinError 32] …\0a0bd124\vector_db\04c8304f-…\data_level0.bin
    # 且「重启服务后同一个请求原样再发一次」立刻成功 —— 说明进程里仍有东西攥着那个
    # .bin。漏的就是这一层：chromadb 的 SharedSystemClient 按 path 维护**全局**
    # client 缓存，Python 层的 VectorStore 实例被 GC 回收（弱引用变 None）并不等于
    # 底层 sqlite / hnswlib 句柄关了；注册表只看得见还活着的实例，早就回收掉的那个
    # 恰好在缓存里继续持有文件。
    # 所以关完实例还要清 chromadb 自己的系统缓存，两条路径都试（0.5.x / 1.x 搬家过）。
    # 拿不到 chromadb（离线/精简环境）不影响删除主流程 —— 这里只做尽力而为，
    # 结果通过 last_close_report() 暴露给调用方与真机报告，可判「这条到底生效没有」。
    cache_cleared = _clear_chroma_system_cache()
    if closed:
        gc.collect()
    _LAST_CLOSE_REPORT["closed"] = closed
    _LAST_CLOSE_REPORT["cache_cleared"] = cache_cleared
    return closed


def _clear_chroma_system_cache() -> bool:
    """清 chromadb 的全局 client 缓存，返回是否清成功。永不抛异常。"""
    for mod, attr in (
        ("chromadb.api.client", "SharedSystemClient"),              # chromadb 1.x
        ("chromadb.api.shared_system_client", "SharedSystemClient"),  # chromadb 0.5.x
    ):
        try:
            import importlib
            m = importlib.import_module(mod)
            fn = getattr(getattr(m, attr), "clear_system_cache", None)
            if callable(fn):
                fn()
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def last_close_report() -> dict:
    """最近一次 close_stores_under 的实际结果（给 delete_project 写进返回体与审计）。"""
    return dict(_LAST_CLOSE_REPORT)


# v0.1.247（D33）：**embedding 模型预热状态**。
#
# 实测：真机一轮扫描 63 个文件要 20 分钟，最大的一段空档是 75.8 秒，
# 日志里写的是 "Loading weights" —— 每个文件的向量化都在**重新加载模型**。
# 模型加载是同步的，75 秒里扫描线程**完全不能发心跳**，界面看到的就是
# "程序死了"。
#
# 修法：服务启动时在后台线程把模型预热好，状态接口对外暴露 vector_ready，
# 前端据此提示"正在准备语义模型"而不是假装卡死。
_MODEL_READY = False
_MODEL_READY_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# v0.1.249（D37）：语义模型是**可选增强**，它不可用绝不能拖住扫描。
#
# 真机事故（WORKbuddy 2026-11-13 报告，阶段①「扫描按时结束」失败）：
#     done 一直是 0/63，心跳停 301s → 判定卡死 → 后续 12 条断言全红
#     （资料库 0 条 / 检索超时 / 竣工 total_devices=0 / 缺件清单空 …）
#
# 根因（现场推演 + 代码定位）：
#     scanner.scan_folder → store.index_file(res) → VectorStore._get_model()
#     → 本地无缓存 → **回退联网下载 470MB 模型，且没有任何超时**
#     → 这段阻塞发生在 `_parse_with_ticks`（120s 文件超时）**之外**，
#       所以「单文件超时不拖死整轮」那道闸根本没覆盖到它。
#
# 两个缺陷，同一个母题：
#     ① **扫描被可选增强绑架**：模型下不下来 = 整个产品不能用。
#     ② **逃生通道是假的**：提示语让用户「在设置里关闭语义检索」，
#        而**项目里根本没有这个开关**（v0.1.249 补上：app/settings.py）。
#
# 修法：
#     · 模型**进程级共享**：此前每个 VectorStore 实例各 load 一次（75s），
#       扫描起来就是 63×75s。现在全局一份，后面的实例直接复用。
#     · 联网下载**有上限**：放进后台线程，最多等 EMBED_MODEL_LOAD_TIMEOUT_SEC；
#       等不到就降级为关键词检索，**扫描继续**，不等、不重试。
#     · **熔断闩**：一旦确认不可用（或已超时放弃等待），后续文件**立刻**降级，
#       不再每个文件重复发起 470MB 下载（那是把一次卡死变成 63 次卡死）。
#     · 用户显式关闭语义检索时，**完全不碰模型**。
# ---------------------------------------------------------------------------
_MODEL_LOCK = threading.RLock()
_SHARED_MODEL = None            # 进程级共享模型（此前是实例级）
_MODEL_BLOCKED = False          # 熔断闩：已确认不可用 → 后续立刻降级
_MODEL_BLOCKED_REASON = ""
_MODEL_DOWNLOADING = False       # 是否已有下载在进行（防止重复发起）
_MODEL_DOWNLOAD_EVENT = threading.Event()


class ModelUnavailable(RuntimeError):
    """语义模型不可用（未安装 / 本地无缓存且下载失败或超时）。

    这是**可预期**的降级，不是致命错误 —— 调用方应当跳过向量化继续干活。
    """


def model_ready() -> bool:
    """语义模型是否已预热就绪。"""
    return bool(_MODEL_READY)


def _local_model_cached() -> bool:
    """本地有没有语义模型缓存？**只查目录**，不加载模型、不联网。

    用来区分「装了但没缓存（要联网下载）」和「已经缓存（只是还没加载）」——
    这两种情况给用户的提示完全不同。
    """
    raw = str(getattr(config, "EMBED_MODEL", "") or "")
    if not raw:
        return False
    # EMBED_MODEL 直接指向本地目录 → 本身就是缓存
    if os.path.isdir(raw):
        return True
    name = raw.split("/")[-1].lower().replace("_", "-")
    if not name:
        return False
    bases = []
    for env in ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE"):
        v = os.environ.get(env)
        if v:
            bases.append(v)
    bases.append(os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub"))
    for base in bases:
        try:
            if not base or not os.path.isdir(base):
                continue
            for entry in os.listdir(base):
                if name in entry.lower().replace("_", "-"):
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


# 探针结果记忆：「语义库没装」这件事在一次进程生命周期里不会变，
# 没必要每次状态查询都重试一次 import（异常不会被 sys.modules 记住）。
_PROBE_MEMO = {"reason": ""}


def _probe_unavailable_reason() -> str:
    """模型没就绪、且没有已知原因时，廉价地探一下**为什么**。

    绝不下载、绝不加载模型 —— 只 import 一下 + 看一眼缓存目录。
    返回可直接展示的中文原因。
    """
    if _PROBE_MEMO["reason"]:
        return _PROBE_MEMO["reason"]
    try:
        import sentence_transformers  # noqa: F401
    except Exception as e:  # noqa: BLE001
        _PROBE_MEMO["reason"] = f"语义库未安装（{type(e).__name__}），已降级为关键词检索"
        return _PROBE_MEMO["reason"]
    try:
        if _local_model_cached():
            return "语义模型已缓存但尚未加载（首次加载约 1 分钟），当前降级为关键词检索"
    except Exception:  # noqa: BLE001
        pass
    return "语义模型本地无缓存（首次使用需联网下载约 470MB），当前降级为关键词检索"


def model_status() -> dict:
    """语义模型当前状态 —— 给状态接口/界面用，避免「静默降级」。

    三个字段各说一件事：
        ready    —— 模型此刻可用（可以向量化/语义检索）
        enabled  —— 用户有没有关掉语义检索
        reason   —— 不可用时**为什么**（中文，直接可展示）
    """
    from . import settings as _settings
    with _MODEL_LOCK:
        ready = _SHARED_MODEL is not None or bool(_MODEL_READY)
        reason = _MODEL_BLOCKED_REASON
    enabled = bool(_settings.semantic_enabled())
    if not ready and not reason:
        # 没就绪却说不出原因 —— 界面只能显示「没反应」，
        # 用户分不清是「文件没内容」还是「模型没加载出来」。
        # 这里补一次**廉价探测**（不下载、不加载模型）。
        reason = ("语义检索已关闭（用户设置）" if not enabled
                  else _probe_unavailable_reason())
    return {
        "ready": bool(ready),
        "enabled": enabled,
        "reason": reason or "",
    }


def _set_model_blocked(reason: str) -> None:
    global _MODEL_BLOCKED, _MODEL_BLOCKED_REASON
    with _MODEL_LOCK:
        _MODEL_BLOCKED = True
        _MODEL_BLOCKED_REASON = reason


def _download_worker(SentenceTransformer) -> None:
    """后台下载语义模型（一次）。

    下载成功 → 填进进程级共享模型并**解除熔断**（后续文件立刻能用上）；
    下载失败 → 记下原因并置熔断（后续文件立刻降级，不再重试）。
    """
    global _SHARED_MODEL, _MODEL_BLOCKED, _MODEL_BLOCKED_REASON
    try:
        m = SentenceTransformer(config.EMBED_MODEL)
    except BaseException as e:  # noqa: BLE001 —— 宿主 sitecustomize 的 SystemExit 也要收
        with _MODEL_LOCK:
            _MODEL_BLOCKED = True
            _MODEL_BLOCKED_REASON = f"语义模型下载失败（{type(e).__name__}），已降级为关键词检索"
        _MODEL_DOWNLOAD_EVENT.set()
        return
    with _MODEL_LOCK:
        _SHARED_MODEL = m
        _MODEL_BLOCKED = False
        _MODEL_BLOCKED_REASON = ""
    _MODEL_DOWNLOAD_EVENT.set()


def _load_model_bounded(timeout=None):
    """加载语义模型，**有上限**。返回模型或 None（None = 降级，不抛）。

    为什么不能直接把异常抛给调用方：调用方（扫描）需要的是
    「这次没有向量，但解析结果照常入库」，不是一个异常。
    """
    global _MODEL_DOWNLOADING, _SHARED_MODEL
    timeout = config.EMBED_MODEL_LOAD_TIMEOUT_SEC if timeout is None else timeout
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as e:  # noqa: BLE001
        _set_model_blocked(f"语义库未安装（{type(e).__name__}），已降级为关键词检索")
        return None

    # 熔断已生效 → 立刻降级，绝不再发起下载。
    with _MODEL_LOCK:
        if _MODEL_BLOCKED:
            return None

    # ① 本地缓存优先：不走网络，命中即秒回。
    try:
        m = SentenceTransformer(config.EMBED_MODEL, local_files_only=True)
        with _MODEL_LOCK:
            _SHARED_MODEL = m
        return m
    except Exception:  # noqa: BLE001 —— 本地没有缓存是正常情况
        pass

    # ② 本地没有 → 联网下载：**一次性、有上限、后台进行**。
    with _MODEL_LOCK:
        start = not _MODEL_DOWNLOADING
        if start:
            _MODEL_DOWNLOADING = True
            _MODEL_DOWNLOAD_EVENT.clear()
    if start:
        th = threading.Thread(target=_download_worker, args=(SentenceTransformer,),
                              daemon=True, name="fg-embed-download")
        th.start()
    # 等它，但只等 config.EMBED_MODEL_LOAD_TIMEOUT_SEC。
    if _MODEL_DOWNLOAD_EVENT.wait(timeout):
        with _MODEL_LOCK:
            return _SHARED_MODEL
    # 等不到 —— 熔断，扫描继续。下载线程留在后台，跑成了会自动解除熔断。
    _set_model_blocked(
        f"语义模型下载超过 {int(timeout)}s 未完成（网络不可达），已降级为关键词检索")
    return None


def warmup_model() -> bool:
    """预热语义模型（应在后台线程调用，避免拖慢启动）。返回是否就绪。"""
    global _MODEL_READY
    try:
        from . import settings as _settings
        if not _settings.semantic_enabled():
            with _MODEL_READY_LOCK:
                _MODEL_READY = False
            return False
        st = VectorStore(db_path=os.path.join(config.DATA_DIR, "vectordb"))
        st._get_model()  # noqa: SLF001 —— 就是要触发懒加载
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    with _MODEL_READY_LOCK:
        _MODEL_READY = ok
    return ok


class VectorStore:
    def __init__(self, db_path: str = None):
        self._model = None
        self._client = None
        self._collection = None
        # 默认项目向量库；平台级规范库传入独立目录（v0.1.10）
        self._db_path = db_path or os.path.join(config.DATA_DIR, "vectordb")
        _register(self)

    def close(self):
        """释放底层 chroma 句柄。删除项目目录前必须调用（Windows 无 unlink-on-open）。"""
        errors = []
        col = getattr(self, "_collection", None)
        cli = getattr(self, "_client", None)
        self._collection = None
        self._client = None
        # 先放 collection，再关 client；反过来 client 关了 collection 还握着
        for obj, name in ((col, "collection"), (cli, "client")):
            if obj is None:
                continue
            for meth in ("close", "reset"):
                fn = getattr(obj, meth, None)
                if not callable(fn):
                    continue
                try:
                    fn()
                    break
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{name}.{meth}: {type(e).__name__}: {e}")
            # 有些版本的客户端只有一个可调用的 clear/stop，兜底把引用丢掉
            try:
                del obj
            except Exception:  # noqa: BLE001
                pass
        # 句柄有没有真放开，只有 gc + 再删一次目录才知道；这里只做尽力而为，
        # 由调用方（delete_project）在 rmtree 失败时把原因写进审计。
        self._closed_errors = errors
        return not errors

    # ---------- 懒加载 ----------
    def _get_model(self):
        """取语义模型。

        v0.1.249（D37）：模型**进程级共享**，且加载**有上限**。
        拿不到 → 抛 ModelUnavailable（调用方据此跳过向量化继续干活），
        绝不把「下不下来」变成「整个扫描卡住」。
        """
        global _SHARED_MODEL
        with _MODEL_LOCK:
            if _SHARED_MODEL is not None:
                self._model = _SHARED_MODEL
                return self._model

        from . import settings as _settings
        if not _settings.semantic_enabled():
            raise ModelUnavailable("语义检索已关闭（用户设置），已降级为关键词检索")

        model = _load_model_bounded()
        if model is None:
            with _MODEL_LOCK:
                reason = _MODEL_BLOCKED_REASON or "语义模型不可用，已降级为关键词检索"
            raise ModelUnavailable(reason)
        with _MODEL_LOCK:
            _SHARED_MODEL = model
        self._model = model
        return model

    def _project_deleted(self) -> bool:
        """本向量库所属的项目目录是否已被删除（D35 墓碑）。"""
        try:
            parent = os.path.dirname(self._db_path.rstrip("/\\"))
            if not parent:
                return False
            return _tombstone.is_deleted(parent)
        except Exception:  # noqa: BLE001
            return False

    def _get_collection(self):
        if self._collection is None:
            import chromadb
            # v0.1.247（D35）：项目已删除 → 不再创建 vector_db/。
            # 实测事故里 vector_db/ 就是在项目被删之后又出现的。
            if self._project_deleted():
                raise RuntimeError("项目已删除，向量库不再创建")
            os.makedirs(self._db_path, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self._db_path)
            self._collection = self._client.get_or_create_collection(
                name="project_files", metadata={"hnsw:space": "cosine"}
            )
        return self._collection

    # ---------- 分块 ----------
    def chunk_text(self, text: str) -> list:
        """固定窗口分块（v3.6 口径：500 字符 + 50 重叠；后续可换语义分块）。"""
        text = (text or "").strip()
        if not text:
            return []
        size, overlap = config.CHUNK_SIZE, config.CHUNK_OVERLAP
        step = size - overlap
        chunks = []
        i = 0
        while i < len(text):
            chunks.append(text[i:i + size])
            i += step
            if i >= len(text):
                break
        return chunks

    # ---------- 入库 ----------
    def index_file(self, parse_result) -> int:
        """对一个解析结果做分块 + 向量化 + 入库，返回块数。"""
        # v0.1.247（D35）：落点项目已删除 → 不再向量化入库（返回 0 块）。
        if self._project_deleted():
            return 0
        chunks = self.chunk_text(parse_result.text)
        if not chunks:
            return 0
        model = self._get_model()
        col = self._get_collection()
        base_id = parse_result.sha256[:16]
        ids, docs, metas = [], [], []
        for i, c in enumerate(chunks):
            ids.append(f"{base_id}-{i}")
            docs.append(c)
            metas.append({
                "file_name": parse_result.file_name,
                "sha256": parse_result.sha256,
                "ext": parse_result.ext,
                "parser": parse_result.parser,
                "chunk_index": i,
                "file_path": parse_result.file_path,
                "indexed_at": datetime.datetime.now().isoformat(),
            })
        embeds = model.encode(docs, normalize_embeddings=True).tolist()
        col.upsert(ids=ids, documents=docs, embeddings=embeds, metadatas=metas)
        parse_result.chunks = chunks
        return len(chunks)

    # ---------- 检索（供后续 AI/Agent 使用；也验证入库成功） ----------
    def search(self, query: str, top_k: int = 5, where: dict = None) -> list:
        col = self._get_collection()
        model = self._get_model()
        qv = model.encode([query], normalize_embeddings=True).tolist()[0]
        r = col.query(query_embeddings=[qv], n_results=top_k, where=where)
        out = []
        for i, doc in enumerate(r["documents"][0]):
            out.append({
                "text": doc,
                "distance": round(float(r["distances"][0][i]), 4),
                "meta": r["metadatas"][0][i],
            })
        return out

    # ---------- 关键词降级检索 ----------
    def search_keyword(self, query: str, top_k: int = 5, data_dir: str = None) -> list:
        """embedding 模型不可用时的降级检索：直接对解析缓存做中文/英文关键词匹配。

        设计动机：资料库的可用性不能被 '首次需联网下载 470MB 模型' 绑架。工地内网、
        离线环境、模型下载失败时，检索仍须返回命中文件，否则资料库等于不可用。
        返回结构与 search() 对齐（text/distance/meta），distance 用 0~1 的归一化失配度。
        """
        import glob
        import re as _re

        ddir = data_dir or os.path.join(
            os.path.dirname(self._db_path.rstrip("/\\")), "parsed_cache")
        files = sorted(glob.glob(os.path.join(ddir, "*.json")))
        if not files:
            return []

        q = (query or "").strip()
        if not q:
            return []
        # 中文按二元切分（避免整句匹配过严），英文/数字按词
        terms = set()
        for run in _re.findall(r"[A-Za-z0-9]+", q):
            if len(run) >= 2:
                terms.add(run.lower())
        cjk = _re.findall(r"[一-鿿]+", q)
        for seg in cjk:
            if len(seg) == 1:
                terms.add(seg)
            else:
                for i in range(len(seg) - 1):
                    terms.add(seg[i:i + 2])
        if not terms:
            return []

        scored = []
        for fp in files:
            try:
                with open(fp, encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:  # noqa: BLE001
                continue
            text = (d.get("text") or "")
            name = (d.get("file_name") or "")
            hay = (name + " " + text).lower()
            if not hay.strip():
                continue
            hit = sum(1 for t in terms if t in hay)
            if hit == 0:
                continue
            score = hit / len(terms)
            # 命中词更多、文件更短者优先（贴近检索意图）
            snippet = text
            for t in sorted(terms, key=len, reverse=True):
                p = text.lower().find(t)
                if p >= 0:
                    snippet = text[max(0, p - 60):p + 120]
                    break
            scored.append({
                "text": snippet.strip(),
                "distance": round(1.0 - score, 4),
                "meta": {
                    "file_name": name,
                    "sha256": d.get("sha256", ""),
                    "ext": d.get("ext", ""),
                    "parser": d.get("parser", ""),
                    "matched_terms": hit,
                    "total_terms": len(terms),
                    "file_path": d.get("file_path", ""),
                    "retrieval": "keyword",
                },
            })
        scored.sort(key=lambda x: (x["distance"], len(x["text"])))
        return scored[:top_k]

    def stats(self) -> dict:
        try:
            col = self._get_collection()
            return {"count": col.count()}
        except Exception:  # noqa: BLE001
            return {"count": 0}
