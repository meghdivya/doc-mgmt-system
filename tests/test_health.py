from sqlalchemy import inspect
from app.db.session import get_engine
from app.core.config import get_settings


def test_health_endpoints(client):
    res_v1 = client.get("/api/v1/health")
    assert res_v1.status_code == 200
    payload = res_v1.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "AI-Powered Vault Document System"
    assert payload["ai_mode"] == "local"
    assert payload["database_backend"] == "sqlite"

    res_root = client.get("/health")
    assert res_root.status_code == 200
    assert res_root.json()["status"] == "ok"


def test_database_tables_created(client):
    engine = get_engine(get_settings().database_url)
    tables = set(inspect(engine).get_table_names())
    expected = {
        "documents",
        "document_chunks",
        "document_insights",
        "chat_sessions",
        "chat_messages",
        "processing_metrics",
    }
    assert expected.issubset(tables)
