import time
from fastapi import BackgroundTasks

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.models import Document, DocumentChunk, ProcessingMetric
from app.db.session import get_session_factory
from app.services.chunker import chunk_pages
from app.services.parser import parse_document_file
from app.services.ws_manager import ws_manager

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
        ws_manager.publish_document_event(
            doc.id,
            {
                "event": "status",
                "document_id": doc.id,
                "filename": doc.filename,
                "status": "processing",
                "stage": "started",
            },
        )

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
            ws_manager.publish_document_event(
                doc.id,
                {
                    "event": "status",
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "status": "processing",
                    "stage": "parse_and_chunk",
                    "page_count": doc.page_count,
                    "word_count": doc.word_count,
                    "chunks_created": len(chunk_models),
                    "duration_ms": parse_ms,
                },
            )

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
            ws_manager.publish_document_event(
                doc.id,
                {
                    "event": "status",
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "status": "completed",
                    "stage": "full_pipeline",
                    "page_count": doc.page_count,
                    "word_count": doc.word_count,
                    "chunks_created": len(chunk_models),
                    "duration_ms": total_ms,
                },
            )
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
            ws_manager.publish_document_event(
                document_id,
                {
                    "event": "status",
                    "document_id": document_id,
                    "status": "failed",
                    "stage": "full_pipeline",
                    "error_message": str(exc),
                },
            )
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


def process_batch_pipeline(document_ids: list[int], database_url: str | None = None) -> None:
    """Process a batch of documents sequentially and record batch-level telemetry."""
    settings = get_settings()
    batch_start = time.perf_counter()
    for doc_id in document_ids:
        process_document_pipeline(doc_id, database_url)

    batch_ms = round((time.perf_counter() - batch_start) * 1000, 2)
    session_factory = get_session_factory(database_url or settings.database_url)
    with session_factory() as db:
        db.add(
            ProcessingMetric(
                document_id=None,
                stage="batch_pipeline",
                status="completed",
                duration_ms=batch_ms,
                chunks_created=len(document_ids),
            )
        )
        db.commit()


def enqueue_batch_processing(
    background_tasks: BackgroundTasks,
    document_ids: list[int],
    settings: Settings,
) -> str:
    if settings.use_celery and settings.redis_url:
        from app.workers.celery_app import process_document_task

        for doc_id in document_ids:
            process_document_task.delay(doc_id, settings.database_url)
        return "celery"

    background_tasks.add_task(process_batch_pipeline, document_ids, settings.database_url)
    return "background_tasks"
