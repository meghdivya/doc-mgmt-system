# 2. Document Ingestion Pipeline (Single & Batch)

End-to-end asynchronous flow from file upload (`POST /api/v1/documents/upload` or `/upload/batch`) through parsing, chunking, embedding, vector indexing, AI insights, and live WebSocket status broadcasts.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant API as documents.py
    participant Quota as quota.py
    participant Disk as storage.py
    participant DB as SQLite / Postgres
    participant Worker as pipeline.py
    participant Parser as parser.py & chunker.py
    participant AI as insights.py & ai_provider.py
    participant VS as vector_store.py
    participant WS as ws_manager.py

    User->>API: POST /upload or /upload/batch (files)
    API->>Disk: save_upload_file() -> SHA-256 + data/uploads/
    API->>Quota: check_upload_quota(bytes, count)
    alt Quota Exceeded
        API->>Disk: delete_stored_file() (cleanup)
        API-->>User: 413 / 429 Quota Exceeded
    else Within Quota
        API->>DB: Insert Document(status="pending", version=N)
        API->>Worker: enqueue_document_processing / enqueue_batch_processing
        API-->>User: 201 Created (pending)
    end

    Worker->>DB: Update status="processing"
    Worker->>WS: publish_document_event(status="processing")
    Worker->>Parser: parse_document_file() -> chunk_pages()
    Worker->>DB: Save DocumentChunk rows + parse_and_chunk metric
    Worker->>WS: publish_document_event(stage="parse_and_chunk")

    Worker->>AI: embed_texts(chunks)
    AI-->>Worker: vectors + tokens + cost
    Worker->>DB: Save embeddings + embeddings metric
    Worker->>VS: upsert_document_chunks(doc_id, chunks)

    Worker->>AI: generate_document_insights(full_text)
    Worker->>DB: Save DocumentInsight + ai_insights metric
    Worker->>DB: Update status="completed" + full_pipeline metric
    Worker->>WS: publish_document_event(status="completed")
```

## Notes
- **Batch Processing:** `POST /api/v1/documents/upload/batch` validates the entire batch against `max_documents` and `max_total_storage_mb` before committing, cleans up all temporary files on failure, and records a `batch_pipeline` metric.
- **Live UI Updates:** The Web UI connects to `WS /api/v1/ws/documents` and auto-refreshes the document list when `completed` or `failed` events arrive.
