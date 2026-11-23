from pathlib import Path
import time
from fastapi.testclient import TestClient

from app.core.cache import SmartCache


def test_smart_cache_lru_and_ttl(tmp_path: Path) -> None:
    cache = SmartCache(max_size=2, ttl_seconds=60, db_path=str(tmp_path / "c1.db"))
    cache.set("k1", {"v": 1})
    cache.set("k2", {"v": 2})
    assert cache.get("k1") == {"v": 1}  # touches k1 -> k2 is LRU
    cache.set("k3", {"v": 3})  # evicts k2 from memory

    # Clear SQLite persistence check? Actually k2 is still in SQLite, so check in-memory size
    assert len(cache._store) == 2

    short_cache = SmartCache(max_size=10, ttl_seconds=1, db_path=str(tmp_path / "c2.db"))
    short_cache.set("exp", "soon", ttl_seconds=0.05)
    time.sleep(0.08)
    assert short_cache.get("exp") is None


def test_smart_cache_sqlite_persistence_across_restart(tmp_path: Path) -> None:
    db_path = str(tmp_path / "persist.db")
    c1 = SmartCache(db_path=db_path)
    c1.set("summary:doc1", {"summary": "Persisted across restarts", "tokens": 42})

    # New instance pointing to same SQLite file (empty in-memory store)
    c2 = SmartCache(db_path=db_path)
    assert c2.backend == "memory+sqlite"
    assert c2.get("summary:doc1") == {"summary": "Persisted across restarts", "tokens": 42}
    assert c2.stats()["hits"] == 1


def test_smart_cache_unreachable_redis_falls_back_to_local(tmp_path: Path) -> None:
    db_path = str(tmp_path / "fallback.db")
    c = SmartCache(db_path=db_path, redis_url="redis://127.0.0.1:6399/0")
    assert c.backend == "memory+sqlite"
    c.set("hello", "world")
    assert c.get("hello") == "world"


def test_health_and_metrics_report_cache_backend(client: TestClient) -> None:
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["cache_backend"] == "memory+sqlite"

    proc = client.get("/api/v1/metrics/processing")
    assert proc.status_code == 200
    assert proc.json()["cache_stats"]["backend"] == "memory+sqlite"
