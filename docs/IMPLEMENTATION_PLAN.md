# 4-Phase Local-First Implementation Plan

This plan covers the missing features identified from the **AI-Powered Vault Document System Case Study**, scoped strictly to features that run **100% locally** (SQLite + FastAPI + local filesystem) without requiring external cloud services (no Pinecone, Weaviate, or S3), while remaining compatible with optional local Docker services (`pgvector`, `redis`).

Each phase is implemented, unit-tested, and verified against the full `pytest` suite before moving to the next phase.

---

## Phase 1: Local Vector Store & `pgvector`-Ready Retrieval Layer
**Objective:** Replace raw full-table JSON scanning in `app/services/rag.py` with a dedicated vector store abstraction that works fast locally in SQLite/in-process memory and supports `pgvector` when running against local PostgreSQL.

### Changes
1. **`app/services/vector_store.py` (New)**
   - Define `VectorStore` interface (`upsert_document_chunks`, `delete_document_chunks`, `search`, `backend_name`).
   - Implement `LocalVectorStore`: maintains a fast in-process normalized vector index per document/chunk (hydrated lazily from SQLite `document_chunks` on first query and updated incrementally on ingestion/deletion).
   - Implement `PgVectorStore`: uses PostgreSQL `pgvector` cosine distance (`<=>`) when `DATABASE_URL` is PostgreSQL with `pgvector` available, falling back cleanly if the extension is unavailable.
   - Add `get_vector_store(settings)` factory.
2. **`app/services/rag.py` & `app/workers/pipeline.py` & `app/api/v1/documents.py`**
   - Update `retrieve_relevant_chunks()` to query the vector store for dense similarity and combine with lexical scoring.
   - Update `process_document_pipeline()` to upsert chunk embeddings into the vector store after embedding generation.
   - Update `delete_document()` to remove chunks from the vector store.
3. **`app/api/v1/health.py`**
   - Expose `vector_backend` in `/api/v1/health`.

### Verification Gate
- New tests in `tests/test_vector_store.py`: upsert, search ordering, document-scoped filtering, deletion, and lazy hydration from DB.
- Full `pytest -q` pass.

---

## Phase 2: Real-Time WebSocket Updates (Processing Status & Chat Streaming)
**Objective:** Add native FastAPI WebSocket endpoints for live document ingestion progress and real-time conversational RAG streaming.

### Changes
1. **`app/services/ws_manager.py` (New)**
   - Thread-safe `WebSocketManager` supporting topic subscriptions (`documents:all`, `document:{id}`, `chat:{session_id}`).
   - `publish_from_thread(...)` helper using `anyio`/event-loop scheduling so synchronous background workers (`pipeline.py`) can broadcast events safely to async WebSocket clients.
2. **`app/workers/pipeline.py`**
   - Emit status events (`pending`, `processing`, `parse_and_chunk`, `completed`, `failed`) with `document_id`, `stage`, `chunks_created`, `duration_ms`, and `error_message`.
3. **`app/api/v1/ws.py` (New) & `app/main.py`**
   - `WS /api/v1/ws/documents`: stream all document pipeline events.
   - `WS /api/v1/ws/documents/{document_id}`: stream events for a single document (sends current status immediately on connect).
   - `WS /api/v1/ws/chat/{session_id}`: accept `{"question": "...", "top_k": 5}` and stream `token`, `citations`, `follow_up_questions`, and `done` JSON frames.
   - Register router in `app/main.py`.
4. **`app/static/app.js`**
   - Connect to `/api/v1/ws/documents` to auto-refresh the document list when ingestion completes/fails (with graceful fallback if WebSocket is unavailable).

### Verification Gate
- New tests in `tests/test_websockets.py` using `TestClient.websocket_connect` for document status and chat streaming.
- Full `pytest -q` pass.

---

## Phase 3: Persistent Local Cache & Optional Redis Backend
**Objective:** Upgrade `SmartCache` so cached embeddings, summaries, and RAG answers persist locally across restarts (via SQLite) and optionally use local Redis when `REDIS_URL` is configured and reachable.

### Changes
1. **`app/core/cache.py`**
   - Keep `SmartCache` thread-safe LRU + TTL in-memory fast path.
   - Add optional **local SQLite persistence** (`cache_entries` table in a local SQLite file or `data/cache.db`) so cache survives process restarts in local mode.
   - Add optional **Redis backend** when `REDIS_URL` is set and `redis` client connects successfully, with automatic graceful fallback to local mode if Redis is unreachable.
   - Include `backend` (`memory+sqlite` or `redis`) in `vault_cache.stats()`.
2. **`app/core/config.py`**
   - Add `cache_db_path: str = "data/cache.db"` and `cache_ttl_seconds: int = 3600`.
3. **`app/api/v1/health.py` & `app/api/v1/metrics.py`**
   - Surface `cache_backend` in health and `cache_stats` in `/api/v1/metrics/processing`.

### Verification Gate
- New tests in `tests/test_cache.py`: LRU eviction, TTL expiration, persistence across `SmartCache` re-instantiation, and unreachable-Redis fallback.
- Full `pytest -q` pass.

---

## Phase 4: Batch Upload & Processing + Local Quota Management
**Objective:** Add multi-file batch upload/ingestion and configurable local usage quotas (storage, document count, daily AI tokens/cost).

### Changes
1. **`app/core/config.py`**
   - Add quota settings: `max_documents` (default `500`), `max_total_storage_mb` (default `500`), `max_daily_tokens` (default `1000000`), `max_daily_cost_usd` (default `10.0`).
2. **`app/services/quota.py` (New)**
   - `check_upload_quota(db, incoming_bytes, incoming_count, settings)` → raises HTTP `429` / `413` with clear message if document count or storage quota would be exceeded.
   - `check_ai_quota(db, settings)` → checks today's `ProcessingMetric` token & USD totals against `max_daily_tokens` / `max_daily_cost_usd`.
   - `get_quota_status(db, settings)` → returns current usage, limits, and remaining capacity.
3. **`app/api/v1/documents.py` & `app/workers/pipeline.py` & `app/schemas/document.py`**
   - Enforce upload quota on `POST /api/v1/documents/upload`.
   - Add `POST /api/v1/documents/upload/batch` accepting `files: list[UploadFile]`, validating quotas for the whole batch, saving files, creating `Document` rows, and running `process_batch_pipeline` (recording a `batch_pipeline` metric).
4. **`app/api/v1/chat.py` & `app/api/v1/metrics.py` & `app/schemas/metrics.py`**
   - Enforce AI daily quota on chat/summarize endpoints.
   - Add `GET /api/v1/metrics/quotas` returning quota usage and limits.
5. **End-to-End Integration**
   - Update `tests/test_e2e_flow.py` (or add `tests/test_batch_and_quotas.py`) to test batch upload → WebSocket/status → vector search → cached RAG chat → quota enforcement & metrics end-to-end.

### Verification Gate
- New tests for batch upload, batch pipeline metrics, quota enforcement (doc count, storage, daily tokens/cost), and `/api/v1/metrics/quotas`.
- Full `pytest -q` pass across all phases.
