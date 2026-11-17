from collections.abc import Generator
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.core.cache import vault_cache
from app.core.middleware import http_tracker
from app.db.session import get_engine
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    vault_cache.clear()
    http_tracker.reset()
    db_file = tmp_path / "test_vault.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{db_file.as_posix()}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("UPLOAD_DIR", upload_dir.as_posix())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("USE_CELERY", "false")

    test_app = create_app()
    with TestClient(test_app) as test_client:
        yield test_client
    get_engine(db_url).dispose()
