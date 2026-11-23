# 4. Data Model & Entity-Relationship (ER) Diagram

SQLAlchemy 2.0 schema defined in `app/db/models.py` (works identically on SQLite locally and PostgreSQL in production).

```mermaid
erDiagram
    DOCUMENTS ||--o{ DOCUMENT_CHUNKS : "has (cascade delete)"
    DOCUMENTS ||--o| DOCUMENT_INSIGHTS : "has (cascade delete)"
    DOCUMENTS ||--o{ PROCESSING_METRICS : "logs (set null)"
    CHAT_SESSIONS ||--o{ CHAT_MESSAGES : "contains (cascade delete)"

    DOCUMENTS {
        int id PK
        string filename
        string content_type
        string file_ext
        int file_size
        string sha256
        string storage_path
        int version
        string status "pending|processing|completed|failed"
        int page_count
        int word_count
        text error_message
        datetime created_at
        datetime updated_at
    }

    DOCUMENT_CHUNKS {
        int id PK
        int document_id FK
        int chunk_index
        int page_number
        text content
        int token_count
        json embedding "float[] vector"
        datetime created_at
    }

    DOCUMENT_INSIGHTS {
        int id PK
        int document_id FK "unique"
        text summary
        json key_insights
        json categories
        json topics
        string sentiment
        string model_used
        int tokens_used
        float estimated_cost_usd
        datetime created_at
    }

    CHAT_SESSIONS {
        int id PK
        string title
        json document_ids "[] = all completed docs"
        datetime created_at
        datetime updated_at
    }

    CHAT_MESSAGES {
        int id PK
        int session_id FK
        string role "user|assistant"
        text content
        json citations
        json follow_up_questions
        float latency_ms
        string model_used
        int tokens_used
        float estimated_cost_usd
        datetime created_at
    }

    PROCESSING_METRICS {
        int id PK
        int document_id FK "nullable"
        string stage "parse_and_chunk|embeddings|ai_insights|full_pipeline|batch_pipeline|rag_query"
        string status "completed|failed"
        float duration_ms
        int chunks_created
        int tokens_used
        float estimated_cost_usd
        text error_message
        datetime created_at
    }
```

## Notes
- **Document Versioning:** Re-uploading a file with the same `filename` increments `version` automatically while retaining history.
- **Multi-Doc Chat Scope:** `chat_sessions.document_ids` stores a JSON list of document IDs (`[]` means vault-wide across all `completed` documents).
- **Separate Cache Store:** `SmartCache` persists entries in `data/cache.db` (`cache_entries` table) or Redis rather than the primary application DB.
