import time
from fastapi import BackgroundTasks

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.models import Document, DocumentChunk, ProcessingMetric
from app.db.session import get_session_factory
from app.services.chunker import chunk_pages
from app.services.parser import parse_document_file

logger = get_logger("pipeline")


def process_document_pipeline(document_id: int, database_url: str | None = None) -> None:
    """Asynchronous document ingestion pipeline: parse -> chunk -> embed -> insights."""
    settings = get_settings()
    session_factory = get_session_factory(database_url or settings.database_url)

    with session_factory() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            logger.warning("Document %s no longer exists; skipping pipeline.", document_id)
            return

        doc.status = "processing"
        doc.error_message = None
        db.commit()

        pipeline_start = time.perf_counter()
        try:
            # Stage 1: Parse & Chunk
            stage_start = time.perf_counter()
            pages = parse_document_file(doc.storage_path, doc.file_ext)
            if not pages:
                raise ValueError("No extractable text found in document.")

            total_words = sum(len(p.text.split()) for p in pages)
            chunks = chunk_pages(
                pages,
                chunk_size_chars=settings.chunk_size_chars,
                chunk_overlap_chars=settings.chunk_overlap_chars,
            )

            # Clear any prior chunks when reprocessing
            db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()
            chunk_models = [
                DocumentChunk(
                    document_id=doc.id,
                    chunk_index=c.chunk_index,
                    page_number=c.page_number,
                    content=c.content,
                    token_count=c.token_count,
                    embedding=[],
                )
                for c in chunks
            ]
            db.add_all(chunk_models)
            doc.page_count = len(pages)
            doc.word_count = total_words
            parse_ms = round((time.perf_counter() - stage_start) * 1000, 2)

            db.add(
                ProcessingMetric(
                    document_id=doc.id,
                    stage="parse_and_chunk",
                    status="completed",
                    duration_ms=parse_ms,
                    chunks_created=len(chunk_models),
                )
            )
            db.commit()

            # Stage 2 & 3: Embeddings + AI Insights (wired when insights/ai_provider module is present)
            try:
                from app.services.insights import enrich_document_embeddings_and_insights

                enrich_document_embeddings_and_insights(db, doc, settings)
            except ImportError:
                pass

            total_ms = round((time.perf_counter() - pipeline_start) * 1000, 2)
            doc.status = "completed"
            db.add(
                ProcessingMetric(
                    document_id=doc.id,
                    stage="full_pipeline",
                    status="completed",
                    duration_ms=total_ms,
                    chunks_created=len(chunk_models),
                )
            )
            db.commit()
            logger.info(
                "Processed document id=%s (%s): %s pages, %s chunks in %sms",
                doc.id,
                doc.filename,
                doc.page_count,
                len(chunk_models),
                total_ms,
            )
        except Exception as exc:
            db.rollback()
            doc = db.get(Document, document_id)
            fail_ms = round((time.perf_counter() - pipeline_start) * 1000, 2)
            if doc is not None:
                doc.status = "failed"
                doc.error_message = str(exc)
            db.add(
                ProcessingMetric(
                    document_id=document_id,
                    stage="full_pipeline",
                    status="failed",
                    duration_ms=fail_ms,
                    error_message=str(exc),
                )
            )
            db.commit()
            logger.error("Failed processing document id=%s: %s", document_id, exc)


def enqueue_document_processing(
    background_tasks: BackgroundTasks,
    document_id: int,
    settings: Settings,
) -> str:
    if settings.use_celery and settings.redis_url:
        from app.workers.celery_app import process_document_task

        process_document_task.delay(document_id, settings.database_url)
        return "celery"

    background_tasks.add_task(process_document_pipeline, document_id, settings.database_url)
    return "background_tasks"
