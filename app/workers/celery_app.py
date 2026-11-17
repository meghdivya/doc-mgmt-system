"""Optional Celery worker entrypoint for distributed Redis + Celery deployments.

Run worker with:
    celery -A app.workers.celery_app.celery_app worker --loglevel=info
"""

import os
from app.workers.pipeline import process_document_pipeline

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

try:
    from celery import Celery  # type: ignore[import-untyped]

    celery_app = Celery("vault_worker", broker=REDIS_URL, backend=REDIS_URL)

    @celery_app.task(name="vault.process_document")
    def process_document_task(document_id: int, database_url: str | None = None) -> None:
        process_document_pipeline(document_id, database_url)

except ImportError:  # pragma: no cover - local mode runs without Celery installed
    celery_app = None

    class _FallbackTask:
        @staticmethod
        def delay(document_id: int, database_url: str | None = None) -> None:
            process_document_pipeline(document_id, database_url)

    process_document_task = _FallbackTask()  # type: ignore[assignment]
