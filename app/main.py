from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.chat import router as chat_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.ws import router as ws_router
from app.core.cache import vault_cache
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import ObservabilityMiddleware
from app.db.session import init_db
from app.services.ai_provider import AIProviderError


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    settings = get_settings()
    init_db(settings.database_url)
    vault_cache.configure(
        db_path=settings.cache_db_path,
        ttl_seconds=settings.cache_ttl_seconds,
        redis_url=settings.redis_url,
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AI-first document management vault with async ingestion, automated AI insights, "
            "multi-turn RAG chat with citations, and system telemetry."
        ),
        lifespan=lifespan,
    )
    application.add_middleware(ObservabilityMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(documents_router, prefix="/api/v1")
    application.include_router(chat_router, prefix="/api/v1")
    application.include_router(metrics_router, prefix="/api/v1")
    application.include_router(ws_router, prefix="/api/v1")
    application.include_router(health_router)

    @application.exception_handler(AIProviderError)
    async def ai_provider_error_handler(_request: Request, exc: AIProviderError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @application.get("/", include_in_schema=False)
        def serve_vault_ui() -> FileResponse:
            return FileResponse(static_dir / "index.html")

    return application


app = create_app()
