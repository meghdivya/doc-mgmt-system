import time
from typing import Any
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import ChatMessage, ChatSession, Document, DocumentChunk, ProcessingMetric
from app.services.ai_provider import (
    cosine_similarity,
    embed_texts,
    generate_grounded_rag_answer,
    tokenize_words,
)


def contextualize_query(question: str, prior_messages: list[ChatMessage]) -> str:
    """Enrich follow-up questions with key terms from recent conversation turns."""
    user_turns = [m.content for m in prior_messages if m.role == "user"]
    if not user_turns:
        return question

    q_words = tokenize_words(question)
    pronouns = {"it", "its", "they", "their", "that", "this", "those", "these", "there", "more"}
    raw_tokens = {w.lower().strip("?.,!") for w in question.split()}
    needs_context = len(q_words) <= 2 or bool(raw_tokens & pronouns)

    if needs_context:
        recent_context = " ".join(user_turns[-2:])
        context_terms = tokenize_words(recent_context)[:8]
        return f"{question} (context: {' '.join(context_terms)})"
    return question


def retrieve_relevant_chunks(
    db: Session,
    query: str,
    document_ids: list[int],
    top_k: int,
    settings: Settings,
) -> list[dict[str, Any]]:
    """Hybrid dense + lexical retrieval across single or multiple vault documents."""
    chunk_query = (
        db.query(DocumentChunk, Document.filename)
        .join(Document, DocumentChunk.document_id == Document.id)
        .filter(Document.status == "completed")
    )
    if document_ids:
        chunk_query = chunk_query.filter(DocumentChunk.document_id.in_(document_ids))

    rows = chunk_query.all()
    if not rows:
        return []

    query_vecs, _tok, _cost = embed_texts([query], settings)
    query_vec = query_vecs[0] if query_vecs else []
    query_terms = set(tokenize_words(query))

    scored: list[tuple[float, DocumentChunk, str]] = []
    for chunk, filename in rows:
        dense = cosine_similarity(query_vec, chunk.embedding or [])
        chunk_terms = set(tokenize_words(chunk.content))
        if query_terms and chunk_terms:
            lexical = len(query_terms & chunk_terms) / max(1, min(len(query_terms), 8))
        else:
            lexical = 0.0
        hybrid_score = 0.65 * max(0.0, dense) + 0.35 * lexical
        if hybrid_score > 0.01:
            scored.append((hybrid_score, chunk, filename))

    # Fallback if query terms had zero direct overlap: take highest dense matches
    if not scored:
        for chunk, filename in rows:
            dense = max(0.0, cosine_similarity(query_vec, chunk.embedding or []))
            scored.append((dense, chunk, filename))

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = scored[:top_k]

    results: list[dict[str, Any]] = []
    for idx, (score, chunk, filename) in enumerate(selected, start=1):
        excerpt = chunk.content[:240].strip()
        if len(chunk.content) > 240:
            excerpt += "..."
        results.append(
            {
                "source_index": idx,
                "document_id": chunk.document_id,
                "filename": filename,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "score": round(float(score), 4),
                "content": chunk.content,
                "excerpt": excerpt,
            }
        )
    return results


def execute_chat_turn(
    db: Session,
    session: ChatSession,
    question: str,
    top_k: int | None,
    settings: Settings,
) -> tuple[ChatMessage, ChatMessage, bool]:
    """Run full multi-turn RAG cycle, persist user & assistant messages, and record metrics."""
    turn_start = time.perf_counter()

    prior_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id)
        .all()
    )

    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=question,
        citations=[],
        follow_up_questions=[],
        latency_ms=0.0,
        model_used="user",
        tokens_used=0,
        estimated_cost_usd=0.0,
    )
    db.add(user_msg)
    db.flush()

    search_query = contextualize_query(question, prior_messages)
    k = top_k or settings.top_k_chunks
    retrieved = retrieve_relevant_chunks(
        db=db,
        query=search_query,
        document_ids=list(session.document_ids or []),
        top_k=k,
        settings=settings,
    )

    history_dicts = [{"role": m.role, "content": m.content} for m in prior_messages[-6:]]
    rag_res = generate_grounded_rag_answer(
        question=question,
        history=history_dicts,
        contexts=retrieved,
        settings=settings,
    )

    citations_payload = [
        {
            "source_index": c["source_index"],
            "document_id": c["document_id"],
            "filename": c["filename"],
            "page_number": c["page_number"],
            "chunk_index": c["chunk_index"],
            "score": c["score"],
            "excerpt": c["excerpt"],
        }
        for c in retrieved
    ]

    latency_ms = round((time.perf_counter() - turn_start) * 1000, 2)
    assistant_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=rag_res.answer,
        citations=citations_payload,
        follow_up_questions=rag_res.follow_up_questions,
        latency_ms=latency_ms,
        model_used=rag_res.model_used,
        tokens_used=rag_res.tokens_used,
        estimated_cost_usd=rag_res.estimated_cost_usd,
    )
    db.add(assistant_msg)

    # Auto-title untitled session on first turn
    if session.title == "Document Chat" and not prior_messages:
        session.title = question[:60].strip()

    target_doc_id = session.document_ids[0] if len(session.document_ids) == 1 else None
    db.add(
        ProcessingMetric(
            document_id=target_doc_id,
            stage="rag_query",
            status="completed",
            duration_ms=latency_ms,
            chunks_created=len(retrieved),
            tokens_used=rag_res.tokens_used,
            estimated_cost_usd=rag_res.estimated_cost_usd,
        )
    )
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant_msg)
    return user_msg, assistant_msg, rag_res.cached
