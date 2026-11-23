from dataclasses import dataclass
import json
import math
import threading
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, DocumentChunk


@dataclass
class VectorSearchHit:
    chunk_id: int
    document_id: int
    filename: str
    page_number: int
    chunk_index: int
    content: str
    score: float


def _normalize_vector(vec: list[float]) -> list[float]:
    if not vec:
        return []
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return [0.0 for _ in vec]
    return [v / norm for v in vec]


def _dot(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


class VectorStore(Protocol):
    backend_name: str

    def upsert_document_chunks(
        self,
        document_id: int,
        filename: str,
        chunks: list[DocumentChunk],
    ) -> None: ...

    def delete_document_chunks(self, document_id: int) -> None: ...

    def search(
        self,
        db: Session,
        query_vec: list[float],
        document_ids: list[int],
        top_k: int,
    ) -> list[VectorSearchHit]: ...


class LocalVectorStore:
    """Thread-safe local in-process normalized vector index hydrated from SQLite/SQL."""

    backend_name = "local-vector-index"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # document_id -> list of (chunk_id, filename, page_number, chunk_index, content, unit_vec)
        self._by_doc: dict[int, list[tuple[int, str, int, int, str, list[float]]]] = {}
        self._hydrated = False

    def reset(self) -> None:
        with self._lock:
            self._by_doc.clear()
            self._hydrated = False

    def upsert_document_chunks(
        self,
        document_id: int,
        filename: str,
        chunks: list[DocumentChunk],
    ) -> None:
        entries = [
            (
                c.id,
                filename,
                c.page_number,
                c.chunk_index,
                c.content,
                _normalize_vector(list(c.embedding or [])),
            )
            for c in chunks
        ]
        with self._lock:
            self._by_doc[document_id] = entries
            self._hydrated = True

    def delete_document_chunks(self, document_id: int) -> None:
        with self._lock:
            self._by_doc.pop(document_id, None)

    def _ensure_hydrated(self, db: Session, document_ids: list[int]) -> None:
        with self._lock:
            if self._hydrated:
                missing_docs = [doc_id for doc_id in document_ids if doc_id not in self._by_doc]
                if not document_ids or not missing_docs:
                    return
            else:
                missing_docs = []

        query = (
            db.query(DocumentChunk, Document.filename)
            .join(Document, DocumentChunk.document_id == Document.id)
            .filter(Document.status == "completed")
        )
        if self._hydrated and missing_docs:
            query = query.filter(DocumentChunk.document_id.in_(missing_docs))

        rows = query.all()
        grouped: dict[int, list[tuple[int, str, int, int, str, list[float]]]] = {}
        for chunk, filename in rows:
            grouped.setdefault(chunk.document_id, []).append(
                (
                    chunk.id,
                    filename,
                    chunk.page_number,
                    chunk.chunk_index,
                    chunk.content,
                    _normalize_vector(list(chunk.embedding or [])),
                )
            )

        with self._lock:
            if not self._hydrated:
                self._by_doc = grouped
                self._hydrated = True
            else:
                for doc_id, entries in grouped.items():
                    self._by_doc[doc_id] = entries

    def search(
        self,
        db: Session,
        query_vec: list[float],
        document_ids: list[int],
        top_k: int,
    ) -> list[VectorSearchHit]:
        self._ensure_hydrated(db, document_ids)
        unit_query = _normalize_vector(query_vec)

        with self._lock:
            if document_ids:
                target_ids = [doc_id for doc_id in document_ids if doc_id in self._by_doc]
            else:
                target_ids = list(self._by_doc.keys())

            candidates: list[VectorSearchHit] = []
            for doc_id in target_ids:
                for chunk_id, filename, page_num, chunk_idx, content, unit_vec in self._by_doc[doc_id]:
                    score = max(0.0, _dot(unit_query, unit_vec))
                    candidates.append(
                        VectorSearchHit(
                            chunk_id=chunk_id,
                            document_id=doc_id,
                            filename=filename,
                            page_number=page_num,
                            chunk_index=chunk_idx,
                            content=content,
                            score=score,
                        )
                    )

        candidates.sort(key=lambda h: h.score, reverse=True)
        return candidates[:top_k]


class PgVectorStore:
    """PostgreSQL pgvector-backed similarity search with local fallback."""

    backend_name = "pgvector"

    def __init__(self, fallback: LocalVectorStore) -> None:
        self._fallback = fallback

    def upsert_document_chunks(
        self,
        document_id: int,
        filename: str,
        chunks: list[DocumentChunk],
    ) -> None:
        self._fallback.upsert_document_chunks(document_id, filename, chunks)

    def delete_document_chunks(self, document_id: int) -> None:
        self._fallback.delete_document_chunks(document_id)

    def search(
        self,
        db: Session,
        query_vec: list[float],
        document_ids: list[int],
        top_k: int,
    ) -> list[VectorSearchHit]:
        if not query_vec:
            return self._fallback.search(db, query_vec, document_ids, top_k)

        vec_literal = json.dumps(query_vec)
        try:
            sql = """
                SELECT dc.id, dc.document_id, d.filename, dc.page_number, dc.chunk_index, dc.content,
                       1 - (CAST(dc.embedding::text AS vector) <=> CAST(:qvec AS vector)) AS score
                FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE d.status = 'completed'
            """
            params: dict[str, object] = {"qvec": vec_literal, "limit": top_k}
            if document_ids:
                sql += " AND dc.document_id = ANY(:doc_ids)"
                params["doc_ids"] = document_ids
            sql += " ORDER BY CAST(dc.embedding::text AS vector) <=> CAST(:qvec AS vector) LIMIT :limit"

            rows = db.execute(text(sql), params).fetchall()
            return [
                VectorSearchHit(
                    chunk_id=int(r[0]),
                    document_id=int(r[1]),
                    filename=str(r[2]),
                    page_number=int(r[3]),
                    chunk_index=int(r[4]),
                    content=str(r[5]),
                    score=max(0.0, float(r[6] or 0.0)),
                )
                for r in rows
            ]
        except Exception:
            return self._fallback.search(db, query_vec, document_ids, top_k)


_local_stores: dict[str, LocalVectorStore] = {}
_stores_lock = threading.Lock()


def get_vector_store(settings: Settings) -> VectorStore:
    with _stores_lock:
        local = _local_stores.get(settings.database_url)
        if local is None:
            local = LocalVectorStore()
            _local_stores[settings.database_url] = local

    if settings.database_url.startswith("postgresql"):
        return PgVectorStore(fallback=local)
    return local


def reset_vector_stores() -> None:
    with _stores_lock:
        for store in _local_stores.values():
            store.reset()
        _local_stores.clear()
