# AI Usage & Prompt Engineering Documentation

## 1. How AI Coding Tools Were Leveraged
GitHub Copilot was used iteratively across architecture planning, implementation, and end-to-end verification:
- **Requirements Extraction & Gap Analysis**: Parsed the 4-page Case Study PDF (`requirements/AI-Powered Vault Document System_  Case Study.pdf`) to map every required endpoint, data model, deliverable, and bonus capability into 7 incremental milestones.
- **Modular Scaffolding**: Structured SQLAlchemy 2.0 ORM models (`app/db/models.py`), Pydantic v2 schemas (`app/schemas/`), and service boundaries (`parser`, `chunker`, `ai_provider`, `rag`, `insights`).
- **Real-Data Debugging**:
  - Detected that Google Docs / Skia-rendered PDFs emit one word per line in `pypdf`, and added automatic single-word-line reconstruction in `app/services/parser.py`.
  - Tuned multi-turn query expansion in `app/services/rag.py` so pronoun follow-ups (`"How long are they retained?"`) inherit context from prior turns without polluting standalone multi-keyword questions.
  - Added explicit SQLAlchemy engine disposal in Windows test fixtures (`tests/conftest.py`, `scripts/demo.py`) to prevent `WinError 32` SQLite file locks.

## 2. Prompt Engineering Rationale (`app/services/prompts.py`)

### A. Structured Document Insights (`DOCUMENT_INSIGHTS_SYSTEM_PROMPT`)
- **Goal**: Produce deterministic, machine-parseable metadata upon upload without hallucination.
- **Design Choices**:
  - Enforces `response_format={"type": "json_object"}` with `temperature=0.2` and an explicit JSON schema (`summary`, `key_insights`, `categories`, `topics`, `sentiment`).
  - Instructs the model to prioritize concrete metrics, requirements, and decisions rather than generic filler sentences.

### B. Parameterized Summarization (`CUSTOM_SUMMARY_SYSTEM_PROMPT`)
- **Goal**: Give users control over `length` (`short`, `medium`, `detailed`), `focus` (`general`, `technical`, `action_items`, `risks`), and `tone` (`professional`, `executive`, `simple`).
- **Design Choices**: Maps each length option to explicit structural constraints (2 sentences vs. paragraph vs. structured bullets) while keeping strict document-only grounding.

### C. Grounded Conversational RAG (`RAG_CHAT_SYSTEM_PROMPT`)
- **Goal**: Eliminate hallucination, attribute every claim to exact pages/chunks, and guide multi-turn exploration.
- **Design Choices**:
  1. **Numbered Context Blocks**: Retrieved chunks are formatted as `[Source N] (Document: <name>, Page <p>)` so inline `[Source N]` citations map 1-to-1 to structured `SourceCitation` objects returned by the API.
  2. **Explicit Abstention Rule**: Instructs the assistant to state what information is missing when context excerpts do not answer the question.
  3. **Follow-up Generation**: Co-generates 3 context-grounded `follow_up_questions` in the same structured JSON call, avoiding an extra LLM round-trip.
  4. **Hybrid Retrieval Upstream**: Combines dense cosine similarity (`0.65`) with lexical keyword overlap (`0.35`) so exact domain identifiers and broader semantic queries both rank relevant chunks at the top.
