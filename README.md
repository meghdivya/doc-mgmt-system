# Vault AI — AI-Powered Vault Document System

An AI-first document management and conversational RAG ("ChatGPT for your documents") backend with a minimal local web dashboard. Upload PDFs, DOCX, TXT, or Markdown files to automatically extract insights, tags, and summaries, then chat across single or multiple documents with grounded `[Source N]` page citations.

## Key Features
- **Intelligent Ingestion & Async Pipeline**: Validates uploads, tracks document versions via SHA-256, parses page-aware PDF/DOCX/TXT/MD text, chunks with overlap, and processes asynchronously (`pending → processing → completed/failed`).
- **Multi-Mode AI Engine (OpenRouter + OpenAI + Local Fallback)**:
  - **OpenRouter Mode**: Set `OPENROUTER_API_KEY` in `.env` to run real `openai/gpt-4o` + `openai/text-embedding-3-small` via `https://openrouter.ai/api/v1` with `HTTP-Referer` and `X-Title` headers and token/USD cost tracking.
  - **OpenAI Mode**: Set `OPENAI_API_KEY` to use `gpt-4o-mini` + `text-embedding-3-small`.
  - **Local Mode (Fallback)**: Works offline out-of-the-box when no API key is configured.
- **Smart Document Insights**: Auto-generated executive summaries, key takeaways, category/topic tags, sentiment, customizable summaries (`length`, `focus`, `tone`), and multi-document comparison.
- **Conversational RAG Chat**: Single-doc and multi-doc chat sessions, pronoun-aware multi-turn context expansion, hybrid dense + lexical retrieval, source citations (`filename`, `page_number`, `chunk_index`, `score`), follow-up question suggestions, and SSE streaming.
- **Observability & Production Controls**: Document statistics API, stage-level pipeline latency/cost metrics API, LRU+TTL `SmartCache`, `X-Process-Time-Ms` headers, and sliding-window rate limiting.

## Quickstart (Local Mode — Zero External Services)

```powershell
# 1. Install dependencies
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Run automated end-to-end demo (uploads Case Study PDF, extracts insights, runs RAG chat)
.\.venv\Scripts\python.exe -m scripts.demo

# 3. Run test suite
.\.venv\Scripts\python.exe -m pytest -q

# 4. Launch local server + web dashboard
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
- **Local Vault Web UI**: http://127.0.0.1:8000
- **Interactive Swagger / OpenAPI Docs**: http://127.0.0.1:8000/docs

## Enabling OpenAI, PostgreSQL & Redis (Production Stack)
1. Copy `.env.example` to `.env` and set `OPENAI_API_KEY=sk-...`.
2. Optional infrastructure via Docker:
   ```powershell
   docker compose up -d
   ```
   Set `DATABASE_URL=postgresql+psycopg://vault:vault@localhost:5432/vault` and `REDIS_URL=redis://localhost:6379/0` in `.env`.

## API Reference (`/api/v1`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Health, active AI mode, DB backend, and uptime |
| `POST` | `/api/v1/documents/upload` | Upload PDF/DOCX/TXT/MD/CSV & trigger async pipeline |
| `GET` | `/api/v1/documents` | List documents (`status`, `search`, `limit`, `offset`) |
| `GET` | `/api/v1/documents/{id}` | Metadata, version, processing status, chunk count & brief insight |
| `POST` | `/api/v1/documents/{id}/reprocess` | Re-run async ingestion pipeline |
| `DELETE` | `/api/v1/documents/{id}` | Delete document, chunks, insights, and stored file |
| `GET` | `/api/v1/documents/{id}/insights` | Full AI summary, key insights, categories, topics, sentiment |
| `POST` | `/api/v1/documents/{id}/summarize` | Custom summary (`length`, `focus`, `tone`) with caching |
| `POST` | `/api/v1/documents/compare` | Comparative topic/category/summary analysis across docs |
| `POST` | `/api/v1/chat/sessions` | Start single-doc, multi-doc, or vault-wide chat session |
| `GET` | `/api/v1/chat/sessions` | List chat sessions |
| `GET` | `/api/v1/chat/sessions/{id}` | Full chat history with citations & follow-ups |
| `POST` | `/api/v1/chat/sessions/{id}/messages` | Ask question → grounded answer + citations + follow-ups |
| `POST` | `/api/v1/chat/sessions/{id}/messages/stream` | Server-Sent Events (`text/event-stream`) streaming chat |
| `GET` | `/api/v1/metrics/documents` | Document counts, status/type/category breakdown, storage & chunks |
| `GET` | `/api/v1/metrics/processing` | Stage latencies, success rate, AI tokens/cost, cache & HTTP stats |

## Project Layout & Docs
- [docs/PLAN.md](docs/PLAN.md) — Feature milestones & requirements mapping
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Data flow & module boundaries
- [docs/PROGRESS.md](docs/PROGRESS.md) — Milestone tracker & test verification
- [AI_USAGE.md](AI_USAGE.md) — AI tool workflow & prompt engineering design

## Design Assumptions & Scaling to 1,000s of Documents
1. **Local-First Portability**: Defaults to SQLite + FastAPI `BackgroundTasks` + local embeddings so reviewers can clone and run tests/demos immediately without external daemons or API keys.
2. **Horizontal Scale Path**: Switching `DATABASE_URL` to PostgreSQL (`pgvector` index on `document_chunks.embedding`), enabling `USE_CELERY=true` with `REDIS_URL`, and pointing `storage.py` to S3 scales ingestion and retrieval horizontally across worker replicas.
3. **Cost & Latency Control**: Embeddings and RAG answers are content-hashed in `SmartCache`, avoiding redundant LLM/embedding calls on repeated documents or queries.
