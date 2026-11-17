# Architecture Overview

## Folder Layout
```text
app/
├── api/v1/          # FastAPI routers: health, documents, chat, metrics
├── core/            # Settings, structured logging, LRU/TTL cache, middleware
├── db/              # SQLAlchemy 2.0 base, session factory, ORM models
├── schemas/         # Pydantic v2 request/response contracts
├── services/        # Storage, PDF/DOCX parser, chunker, AI provider, RAG engine
├── workers/         # Async ingestion pipeline + optional Celery/Redis adapter
├── static/          # Minimal local Vault UI (upload, insights, RAG chat, metrics)
└── main.py          # App factory & lifespan hooks
docs/                # PLAN.md, ARCHITECTURE.md, PROGRESS.md
scripts/             # demo.py (end-to-end runnable case study demonstration)
tests/               # Feature-level & full lifecycle pytest suite
```

## Data Flow
1. **Upload**: Client uploads PDF/DOCX/TXT/MD → saved to `data/uploads/` → SHA-256 computed (auto-increments `version` on update) → `Document(status="pending")` persisted.
2. **Async Pipeline**: Background worker transitions `pending → processing`, extracts page-aware text, splits into overlapping chunks, computes vector embeddings, generates AI summary/insights/tags, records stage latencies in `processing_metrics`, and marks `completed`.
3. **RAG Chat**: User asks question in a session → query is contextualized with prior turns → hybrid retrieval (cosine similarity + lexical overlap) ranks chunks across target document(s) → grounded response generated with `[Source N]` citations and follow-up suggestions.
4. **Local + Cloud Portability**:
   - **Database**: Defaults to local `sqlite:///./data/vault.db`; switches to PostgreSQL via `DATABASE_URL`.
   - **AI Engine**: Uses OpenAI (`gpt-4o-mini` + `text-embedding-3-small`) when `OPENAI_API_KEY` is set; seamlessly falls back to a deterministic local embedding & extractive synthesis provider when offline.
   - **Queue**: Runs in-process background tasks locally; supports Celery + Redis via `REDIS_URL`.
