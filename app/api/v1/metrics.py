from collections import Counter
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.cache import vault_cache
from app.core.config import Settings, get_settings
from app.core.middleware import http_tracker
from app.db.models import (
    ChatMessage,
    ChatSession,
    Document,
    DocumentChunk,
    DocumentInsight,
    ProcessingMetric,
)
from app.db.session import get_db
from app.schemas.metrics import (
    DocumentStatisticsResponse,
    ProcessingEventRead,
    ProcessingMetricsResponse,
    QuotaStatusResponse,
    StageLatencySummary,
)
from app.services.quota import get_quota_status

router = APIRouter(prefix="/metrics", tags=["Monitoring & Metrics"])


@router.get("/documents", response_model=DocumentStatisticsResponse)
def get_document_statistics(db: Session = Depends(get_db)) -> DocumentStatisticsResponse:
    total_docs = db.query(func.count(Document.id)).scalar() or 0

    status_rows = (
        db.query(Document.status, func.count(Document.id))
        .group_by(Document.status)
        .all()
    )
    status_breakdown = {row[0]: row[1] for row in status_rows}

    ext_rows = (
        db.query(Document.file_ext, func.count(Document.id))
        .group_by(Document.file_ext)
        .all()
    )
    file_type_breakdown = {row[0]: row[1] for row in ext_rows}

    cat_counter: Counter[str] = Counter()
    for (cats,) in db.query(DocumentInsight.categories).all():
        for cat in (cats or []):
            cat_counter[cat] += 1

    totals = db.query(
        func.coalesce(func.sum(Document.file_size), 0),
        func.coalesce(func.sum(Document.page_count), 0),
        func.coalesce(func.sum(Document.word_count), 0),
    ).one()

    total_chunks = db.query(func.count(DocumentChunk.id)).scalar() or 0
    total_sessions = db.query(func.count(ChatSession.id)).scalar() or 0
    total_messages = db.query(func.count(ChatMessage.id)).scalar() or 0

    return DocumentStatisticsResponse(
        total_documents=total_docs,
        status_breakdown=status_breakdown,
        file_type_breakdown=file_type_breakdown,
        category_distribution=dict(cat_counter),
        total_storage_bytes=int(totals[0]),
        total_pages=int(totals[1]),
        total_words=int(totals[2]),
        total_chunks=total_chunks,
        total_chat_sessions=total_sessions,
        total_chat_messages=total_messages,
    )


@router.get("/processing", response_model=ProcessingMetricsResponse)
def get_processing_metrics(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProcessingMetricsResponse:
    total_events = db.query(func.count(ProcessingMetric.id)).scalar() or 0
    completed_events = (
        db.query(func.count(ProcessingMetric.id))
        .filter(ProcessingMetric.status == "completed")
        .scalar()
        or 0
    )
    failed_events = (
        db.query(func.count(ProcessingMetric.id))
        .filter(ProcessingMetric.status == "failed")
        .scalar()
        or 0
    )
    success_rate = (
        round((completed_events / total_events) * 100, 2) if total_events > 0 else 100.0
    )

    stage_rows = (
        db.query(
            ProcessingMetric.stage,
            func.count(ProcessingMetric.id),
            func.coalesce(func.avg(ProcessingMetric.duration_ms), 0.0),
            func.coalesce(func.max(ProcessingMetric.duration_ms), 0.0),
        )
        .group_by(ProcessingMetric.stage)
        .all()
    )
    stage_latency = {
        stage: StageLatencySummary(
            count=int(cnt),
            avg_duration_ms=round(float(avg_ms), 2),
            max_duration_ms=round(float(max_ms), 2),
        )
        for stage, cnt, avg_ms, max_ms in stage_rows
    }

    ai_totals = db.query(
        func.coalesce(func.sum(ProcessingMetric.tokens_used), 0),
        func.coalesce(func.sum(ProcessingMetric.estimated_cost_usd), 0.0),
    ).one()

    recent = (
        db.query(ProcessingMetric)
        .order_by(ProcessingMetric.id.desc())
        .limit(15)
        .all()
    )

    return ProcessingMetricsResponse(
        total_events=total_events,
        completed_events=completed_events,
        failed_events=failed_events,
        success_rate_pct=success_rate,
        stage_latency_ms=stage_latency,
        ai_usage={
            "active_ai_mode": settings.ai_mode,
            "chat_model": settings.active_chat_model,
            "embedding_model": settings.active_embedding_model,
            "total_tokens_used": int(ai_totals[0]),
            "total_estimated_cost_usd": round(float(ai_totals[1]), 6),
        },
        cache_stats=vault_cache.stats(),
        http_performance=http_tracker.snapshot(),
        recent_events=[ProcessingEventRead.model_validate(ev) for ev in recent],
    )


@router.get("/quotas", response_model=QuotaStatusResponse)
def get_quotas(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> QuotaStatusResponse:
    return QuotaStatusResponse(**get_quota_status(db, settings))
