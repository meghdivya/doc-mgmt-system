from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.models import Document, DocumentChunk
from app.db.session import get_session_factory
from app.services.vector_store import LocalVectorStore, get_vector_store, reset_vector_stores


def test_health_reports_vector_backend(client: TestClient) -> None:
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["vector_backend"] == "local-vector-index"


def test_local_vector_store_upsert_search_filter_and_delete(client: TestClient) -> None:
    settings = get_settings()
    session_factory = get_session_factory(settings.database_url)

    with session_factory() as db:
        doc1 = Document(
            filename="alpha.txt",
            content_type="text/plain",
            file_ext=".txt",
            file_size=100,
            sha256="a" * 64,
            storage_path="alpha.txt",
            status="completed",
        )
        doc2 = Document(
            filename="beta.txt",
            content_type="text/plain",
            file_ext=".txt",
            file_size=100,
            sha256="b" * 64,
            storage_path="beta.txt",
            status="completed",
        )
        db.add_all([doc1, doc2])
        db.flush()

        c1 = DocumentChunk(
            document_id=doc1.id,
            chunk_index=0,
            page_number=1,
            content="Quarterly revenue and financial forecast",
            token_count=6,
            embedding=[1.0, 0.0, 0.0],
        )
        c2 = DocumentChunk(
            document_id=doc2.id,
            chunk_index=0,
            page_number=1,
            content="Kubernetes deployment architecture",
            token_count=4,
            embedding=[0.0, 1.0, 0.0],
        )
        db.add_all([c1, c2])
        db.commit()

        store = LocalVectorStore()
        store.upsert_document_chunks(doc1.id, doc1.filename, [c1])
        store.upsert_document_chunks(doc2.id, doc2.filename, [c2])

        # Search all docs with query aligned to doc1
        hits = store.search(db, [0.9, 0.1, 0.0], document_ids=[], top_k=2)
        assert len(hits) == 2
        assert hits[0].document_id == doc1.id
        assert hits[0].score > hits[1].score

        # Filter to doc2 only
        filtered = store.search(db, [1.0, 0.0, 0.0], document_ids=[doc2.id], top_k=2)
        assert len(filtered) == 1
        assert filtered[0].document_id == doc2.id

        # Delete doc1 from index
        store.delete_document_chunks(doc1.id)
        after_del = store.search(db, [1.0, 0.0, 0.0], document_ids=[], top_k=5)
        assert [h.document_id for h in after_del] == [doc2.id]


def test_local_vector_store_lazy_hydration_after_reset(client: TestClient) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        files={"file": ("vector_test.txt", b"FastAPI and SQLite power this local vector vault.", "text/plain")},
    )
    assert upload.status_code == 201
    doc_id = upload.json()["id"]

    # Simulate fresh process by clearing in-memory vector store
    reset_vector_stores()
    settings = get_settings()
    store = get_vector_store(settings)
    with get_session_factory(settings.database_url)() as db:
        hits = store.search(db, [0.1] * 256, document_ids=[doc_id], top_k=3)
        assert len(hits) >= 1
        assert hits[0].document_id == doc_id
