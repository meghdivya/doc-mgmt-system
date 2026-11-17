# Progress Tracker — AI-Powered Vault Document System

| Milestone | Feature | E2E Tests | Status |
|---|---|---|---|
| 1 | Core config, DB schema, health endpoint & plan | `tests/test_health.py` (2 passed) | Completed |
| 2 | Upload handler, PDF/DOCX/TXT parser, chunker, async worker | `tests/test_documents.py` (4 passed) | Completed |
| 3 | AI provider (OpenAI + Local fallback), caching, insights & custom summary | `tests/test_insights.py` (3 passed) | Completed |
| 4 | Multi-turn RAG chat, citations, multi-doc, follow-ups & SSE stream | `tests/test_chat_rag.py` (2 passed) | Completed |
| 5 | Document statistics & processing/cost metrics APIs | `tests/test_metrics.py` (2 passed) | Completed |
| 6 | Minimal local Vault UI (`/`) + CLI demo (`scripts/demo.py`) | `tests/test_e2e_flow.py` | In Progress |
| 7 | `README.md`, `AI_USAGE.md`, `docker-compose.yml` & final check | Full suite | Pending |
