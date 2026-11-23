import time
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, DocumentChunk, DocumentInsight, ProcessingMetric
from app.services.ai_provider import embed_texts, generate_document_insights
from app.services.vector_store import get_vector_store


def enrich_document_embeddings_and_insights(
    db: Session,
    doc: Document,
    settings: Settings,
) -> None:
    """Compute vector embeddings for all chunks and generate structured AI insights."""
    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc.id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    if not chunks:
        return

    # Stage 2: Vector Embeddings
    emb_start = time.perf_counter()
    vectors, emb_tokens, emb_cost = embed_texts([c.content for c in chunks], settings)
    for chunk, vec in zip(chunks, vectors):
        chunk.embedding = vec
    emb_ms = round((time.perf_counter() - emb_start) * 1000, 2)

    db.add(
        ProcessingMetric(
            document_id=doc.id,
            stage="embeddings",
            status="completed",
            duration_ms=emb_ms,
            chunks_created=len(chunks),
            tokens_used=emb_tokens,
            estimated_cost_usd=emb_cost,
        )
    )
    db.commit()
    get_vector_store(settings).upsert_document_chunks(doc.id, doc.filename, chunks)

    # Stage 3: Smart Document Analysis & Insights
    ins_start = time.perf_counter()
    full_text = "\n\n".join(c.content for c in chunks)
    result = generate_document_insights(full_text, settings)
    ins_ms = round((time.perf_counter() - ins_start) * 1000, 2)

    db.query(DocumentInsight).filter(DocumentInsight.document_id == doc.id).delete()
    db.add(
        DocumentInsight(
            document_id=doc.id,
            summary=result.summary,
            key_insights=result.key_insights,
            categories=result.categories,
            topics=result.topics,
            sentiment=result.sentiment,
            model_used=result.model_used,
            tokens_used=result.tokens_used,
            estimated_cost_usd=result.estimated_cost_usd,
        )
    )
    db.add(
        ProcessingMetric(
            document_id=doc.id,
            stage="ai_insights",
            status="completed",
            duration_ms=ins_ms,
            tokens_used=result.tokens_used,
            estimated_cost_usd=result.estimated_cost_usd,
        )
    )
    db.commit()
