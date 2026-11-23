from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, ProcessingMetric


def _start_of_utc_day() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def get_quota_status(db: Session, settings: Settings) -> dict:
    doc_count = db.query(func.count(Document.id)).scalar() or 0
    storage_bytes = int(db.query(func.coalesce(func.sum(Document.file_size), 0)).scalar() or 0)

    day_start = _start_of_utc_day()
    daily_tokens, daily_cost = (
        db.query(
            func.coalesce(func.sum(ProcessingMetric.tokens_used), 0),
            func.coalesce(func.sum(ProcessingMetric.estimated_cost_usd), 0.0),
        )
        .filter(ProcessingMetric.created_at >= day_start)
        .one()
    )

    max_storage_bytes = settings.max_total_storage_mb * 1024 * 1024
    tokens_used = int(daily_tokens)
    cost_used = round(float(daily_cost), 6)

    return {
        "documents": {
            "used": int(doc_count),
            "limit": settings.max_documents,
            "remaining": max(0, settings.max_documents - int(doc_count)),
        },
        "storage_bytes": {
            "used": storage_bytes,
            "limit": max_storage_bytes,
            "remaining": max(0, max_storage_bytes - storage_bytes),
        },
        "daily_tokens": {
            "used": tokens_used,
            "limit": settings.max_daily_tokens,
            "remaining": max(0, settings.max_daily_tokens - tokens_used),
        },
        "daily_cost_usd": {
            "used": cost_used,
            "limit": settings.max_daily_cost_usd,
            "remaining": round(max(0.0, settings.max_daily_cost_usd - cost_used), 6),
        },
    }


def check_upload_quota(
    db: Session,
    incoming_bytes: int,
    incoming_count: int,
    settings: Settings,
) -> None:
    doc_count = int(db.query(func.count(Document.id)).scalar() or 0)
    if doc_count + incoming_count > settings.max_documents:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Document quota exceeded: {doc_count} existing + {incoming_count} incoming "
                f"exceeds limit of {settings.max_documents}."
            ),
        )

    storage_bytes = int(db.query(func.coalesce(func.sum(Document.file_size), 0)).scalar() or 0)
    max_storage_bytes = settings.max_total_storage_mb * 1024 * 1024
    if storage_bytes + incoming_bytes > max_storage_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Storage quota exceeded: {storage_bytes + incoming_bytes} bytes "
                f"exceeds limit of {settings.max_total_storage_mb} MB."
            ),
        )


def check_ai_quota(db: Session, settings: Settings) -> None:
    day_start = _start_of_utc_day()
    daily_tokens, daily_cost = (
        db.query(
            func.coalesce(func.sum(ProcessingMetric.tokens_used), 0),
            func.coalesce(func.sum(ProcessingMetric.estimated_cost_usd), 0.0),
        )
        .filter(ProcessingMetric.created_at >= day_start)
        .one()
    )
    if int(daily_tokens) >= settings.max_daily_tokens:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily token quota exceeded ({int(daily_tokens)} / {settings.max_daily_tokens}).",
        )
    if float(daily_cost) >= settings.max_daily_cost_usd:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily AI cost quota exceeded "
                f"(${float(daily_cost):.4f} / ${settings.max_daily_cost_usd:.4f})."
            ),
        )
