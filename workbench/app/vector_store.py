# 繁工AI 本地解析工作台 - 分块 + 向量化 + 向量库
# 使用 ChromaDB 持久化到本地 data/vectordb/；embedding 用 sentence-transformers 本地模型
# （首次运行自动下载模型约 470MB，需联网一次；之后离线可用）

import os
import json
import datetime

from . import config


class VectorStore:
    def __init__(self, db_path: str = None):
        self._model = None
        self._client = None
        self._collection = None
        # 默认项目向量库；平台级规范库传入独立目录（v0.1.10）
        self._db_path = db_path or os.path.join(config.DATA_DIR, "vectordb")

    # ---------- 懒加载 ----------
    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            # v0.1.144：优先本地加载（local_files_only=True），避免网络受限环境下
            # 向 huggingface.co 发 HEAD 请求检查版本导致扫描卡死/进程退出。
            # 若本地无缓存则回退联网下载（首次部署场景）。
            try:
                self._model = SentenceTransformer(config.EMBED_MODEL, local_files_only=True)
            except Exception:  # noqa: BLE001
                # v0.1.177：本地无缓存时**必须先提示**，不能静默去下 ~470MB。
                # 实测事故：首次解析时程序卡住几分钟、界面无任何变化，
                # 用户以为程序死了（端口在 LISTEN 但没有响应），实际在后台拉模型；
                # 断网/内网环境更会直接卡到超时，用户完全不知道发生了什么。
                import sys
                import threading as _th
                msg = (f"\n[繁工AI] 本地未找到语义模型「{config.EMBED_MODEL}」，"
                       f"首次使用需要联网下载约 470MB，可能需要数分钟。\n"
                       f"          如下载失败，可在「设置」里关闭语义检索，"
                       f"关键词检索不受影响。\n")
                sys.stderr.write(msg)
                sys.stderr.flush()
                try:
                    from . import config as _cfg
                    _log = os.path.join(_cfg.DATA_DIR, "logs", "model_download.log")
                    os.makedirs(os.path.dirname(_log), exist_ok=True)
                    with open(_log, "a", encoding="utf-8") as _lf:
                        _lf.write(datetime.datetime.now().isoformat() + msg)
                except Exception:  # noqa: BLE001
                    pass
                self._model = SentenceTransformer(config.EMBED_MODEL)
        return self._model

    def _get_collection(self):
        if self._collection is None:
            import chromadb
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
