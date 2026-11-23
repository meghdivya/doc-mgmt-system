# 3. Conversational RAG & Strict Grounding Flow

How `POST /api/v1/chat/sessions/{id}/messages`, SSE `/messages/stream`, and `WS /api/v1/ws/chat/{id}` retrieve context, prevent hallucinations/off-topic answers, and return `[Source N]` citations.

```mermaid
flowchart TD
    Q["User Question\n(REST / SSE / WebSocket)"] --> Quota["check_ai_quota()\n(Daily Tokens & USD Cap)"]
    Quota --> PersistUser["Save user ChatMessage"]
    PersistUser --> Ctx["contextualize_query()\n(Expand pronouns using last 2 turns)"]
    Ctx --> Embed["embed_texts([search_query])\n(Cached in SmartCache)"]

    Embed --> VSearch["vector_store.search()\n(LocalVectorStore / PgVectorStore)"]
    VSearch --> Rerank["Hybrid Scoring\n0.65 * dense + 0.35 * lexical"]
    Rerank --> Expand["Adjacent-Chunk Expansion\n(Include chunk_index + 1 on same page for top 2 hits)"]

    Expand --> CacheCheck{"SmartCache Hit?\n(rag:v3:...)"}
    CacheCheck -- Yes --> ReturnCached["Return Cached Answer\n(cached=true)"]
    CacheCheck -- No --> ModeCheck{"AI Mode?"}

    ModeCheck -- "OpenRouter / OpenAI" --> LLM["LLM Call with Strict System Prompt\n(No outside knowledge; cite [Source N];\nthorough list synthesis)"]
    ModeCheck -- "Local Fallback" --> LocalCheck{"Zero term overlap\nAND score < 0.25?"}
    LocalCheck -- Yes --> Refuse["Polite Off-Topic Refusal\n('I can help you with something else...')"]
    LocalCheck -- No --> Synth["Extractive Grounded Synthesis\nwith [Source N] + Follow-ups"]

    LLM & Refuse & Synth --> CacheSave["Store in SmartCache\n(memory+sqlite / Redis)"]
    CacheSave & ReturnCached --> PersistBot["Save assistant ChatMessage\n+ Citations + ProcessingMetric"]
    PersistBot --> Out["Return JSON / Stream Tokens"]
```

## Guardrails Built Into This Flow
1. **Strict Document-Only Grounding:** `RAG_CHAT_SYSTEM_PROMPT` forbids pretraining knowledge (e.g., general trivia or writing unrelated code) and returns a polite refusal offering help with uploaded documents instead.
2. **Adjacent-Chunk Expansion:** Multi-chunk sections (such as `Bonus Points` spanning two chunks on the same page) automatically pull in `chunk_index + 1` so lists aren't truncated.
3. **Pronoun Context Expansion:** Short follow-up questions like *"How long are they retained?"* are enriched with keywords from the last 2 user turns before retrieval.
