import time
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.cache import vault_cache
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services.vector_store import get_vector_store

router = APIRouter(tags=["Health"])
START_TIME = time.monotonic()


@router.get("/health")
def health_check(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "ai_mode": settings.ai_mode,
        "chat_model": settings.active_chat_model,
        "embedding_model": settings.active_embedding_model,
        "database_backend": "postgresql" if "postgres" in settings.database_url else "sqlite",
        "vector_backend": get_vector_store(settings).backend_name,
        "cache_backend": vault_cache.backend,
        "queue_mode": "celery" if settings.use_celery and settings.redis_url else "background_tasks",
        "uptime_seconds": round(time.monotonic() - START_TIME, 2),
    }
