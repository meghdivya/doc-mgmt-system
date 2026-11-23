from collections.abc import Generator
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.core.cache import vault_cache
from app.core.middleware import http_tracker
from app.db.session import get_engine
from app.main import create_app
from app.services.vector_store import reset_vector_stores


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    vault_cache.clear()
    http_tracker.reset()
    reset_vector_stores()
    db_file = tmp_path / "test_vault.db"
    cache_file = tmp_path / "test_cache.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{db_file.as_posix()}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("CACHE_DB_PATH", cache_file.as_posix())
    monkeypatch.setenv("UPLOAD_DIR", upload_dir.as_posix())
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("USE_CELERY", "false")

    test_app = create_app()
    with TestClient(test_app) as test_client:
        yield test_client
    get_engine(db_url).dispose()
