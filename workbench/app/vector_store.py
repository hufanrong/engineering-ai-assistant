# 繁工AI 本地解析工作台 - 分块 + 向量化 + 向量库
# 使用 ChromaDB 持久化到本地 data/vectordb/；embedding 用 sentence-transformers 本地模型
# （首次运行自动下载模型约 470MB，需联网一次；之后离线可用）

import os
import json
import datetime

from . import config


class VectorStore:
    def __init__(self):
        self._model = None
        self._client = None
        self._collection = None
        self._db_path = os.path.join(config.DATA_DIR, "vectordb")

    # ---------- 懒加载 ----------
    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
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

    def stats(self) -> dict:
        try:
            col = self._get_collection()
            return {"count": col.count()}
        except Exception:  # noqa: BLE001
            return {"count": 0}
