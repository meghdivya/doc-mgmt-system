# 1. System & Component Architecture

High-level view of how **Vault AI** connects the Web UI, FastAPI routers, middleware, services, workers, and local/optional storage backends.

```mermaid
flowchart TB
    subgraph Clients["Clients"]
        UI["Vault Web UI\n(app/static/index.html + app.js)"]
        API_Client["REST / Swagger Clients\n(/docs)"]
        WS_Client["WebSocket Clients\n(/api/v1/ws/*)"]
    end

    subgraph FastAPI["FastAPI Application (app/main.py)"]
        MW["ObservabilityMiddleware\n(Per-IP Rate Limit + X-Process-Time-Ms)"]
        R_Docs["documents.py\n(/upload, /upload/batch, /insights, /summarize, /compare)"]
        R_Chat["chat.py\n(/sessions, /messages, /messages/stream)"]
        R_WS["ws.py\n(/ws/documents, /ws/chat/{id})"]
        R_Metrics["metrics.py\n(/documents, /processing, /quotas)"]
        R_Health["health.py\n(/health)"]
    end

    subgraph Services["Core Services (app/services & app/core)"]
        Quota["quota.py\n(Doc/Storage/Token/Cost Caps)"]
        Storage["storage.py\n(SHA-256 + Local Disk)"]
        Worker["pipeline.py\n(BackgroundTasks / Celery)"]
        Parser["parser.py + chunker.py\n(PDF/DOCX/TXT/MD/CSV)"]
        Insights["insights.py\n(Embeddings + Summary/Tags)"]
        RAG["rag.py\n(Hybrid Search + Expansion)"]
        AI["ai_provider.py\n(OpenRouter / OpenAI / Local Fallback)"]
        VS["vector_store.py\n(LocalVectorStore / PgVectorStore)"]
        Cache["cache.py (SmartCache)\n(LRU + SQLite / Optional Redis)"]
        WSHub["ws_manager.py\n(Thread-safe Pub/Sub)"]
    end

    subgraph Persistence["Storage & External Providers"]
        DB[("SQLite (vault.db)\nor PostgreSQL")]
        CacheDB[("SQLite Cache (cache.db)\nor Redis")]
        Disk[("Local Uploads\n(data/uploads/)")]
        LLM["OpenRouter / OpenAI API\n(or Offline Local Mode)"]
    end

    UI & API_Client --> MW
    WS_Client --> R_WS
    MW --> R_Docs & R_Chat & R_Metrics & R_Health

    R_Docs --> Quota & Storage & Worker & AI
    R_Chat --> Quota & RAG
    R_WS --> WSHub & RAG
    R_Metrics --> Quota & Cache & DB
    R_Health --> VS & Cache & DB

    Worker --> Parser & Insights & WSHub
    Insights --> AI & VS & DB
    RAG --> VS & AI & Cache & DB
    Storage --> Disk
    VS --> DB
    Cache --> CacheDB
    AI --> Cache & LLM
```

## Key Design Points
- **Local-First Defaults:** Runs out-of-the-box on SQLite, local disk (`data/uploads/`), `LocalVectorStore`, `SmartCache (memory+sqlite)`, and FastAPI `BackgroundTasks`.
- **Optional Scale-Out:** Switching `DATABASE_URL` to PostgreSQL activates `PgVectorStore`, setting `REDIS_URL` activates Redis caching, and `USE_CELERY=true` delegates ingestion to Celery workers.
- **Cross-Cutting Guards:** `ObservabilityMiddleware` enforces per-IP rate limits (`120 req/min`) and records HTTP latency; `quota.py` enforces document count, storage, and daily AI token/cost caps.
