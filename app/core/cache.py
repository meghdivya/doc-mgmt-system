from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any


class SmartCache:
    """Thread-safe LRU + TTL cache with local SQLite persistence and optional Redis backing."""

    def __init__(
        self,
        max_size: int = 1024,
        ttl_seconds: int = 3600,
        db_path: str | None = None,
        redis_url: str | None = None,
    ) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self._db_path: str | None = None
        self._redis: Any = None
        self.backend = "memory"
        self.configure(db_path=db_path, ttl_seconds=ttl_seconds, redis_url=redis_url)

    def configure(
        self,
        db_path: str | None = None,
        ttl_seconds: int | None = None,
        redis_url: str | None = None,
    ) -> None:
        with self._lock:
            if ttl_seconds is not None:
                self.ttl_seconds = ttl_seconds
            self._redis = None
            self._db_path = None
            self.backend = "memory"

            if redis_url:
                try:
                    import redis  # type: ignore[import-untyped]

                    client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1)
                    client.ping()
                    self._redis = client
                    self.backend = "redis"
                    return
                except Exception:
                    self._redis = None

            if db_path:
                if db_path != ":memory:":
                    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                self._db_path = db_path
                self._init_sqlite_table(db_path)
                self.backend = "memory+sqlite"

    @staticmethod
    def _init_sqlite_table(db_path: str) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def make_key(namespace: str, payload: Any) -> str:
        serialized = json.dumps(payload, sort_keys=True, default=str)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]
        return f"{namespace}:{digest}"

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            if self._redis is not None:
                try:
                    raw = self._redis.get(key)
                    if raw is not None:
                        self.hits += 1
                        return json.loads(raw)
                except Exception:
                    pass

            entry = self._store.get(key)
            if entry is not None:
                expires_at, value = entry
                if now <= expires_at:
                    self._store.move_to_end(key)
                    self.hits += 1
                    return value
                del self._store[key]

            if self._db_path is not None:
                try:
                    with sqlite3.connect(self._db_path) as conn:
                        row = conn.execute(
                            "SELECT value_json, expires_at FROM cache_entries WHERE key = ?",
                            (key,),
                        ).fetchone()
                        if row is not None:
                            value_json, expires_at = row
                            if now <= float(expires_at):
                                value = json.loads(value_json)
                                self._put_memory_locked(key, value, float(expires_at))
                                self.hits += 1
                                return value
                            conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                            conn.commit()
                except Exception:
                    pass

            self.misses += 1
            return None

    def _put_memory_locked(self, key: str, value: Any, expires_at: float) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (expires_at, value)
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        expires_at = time.time() + ttl
        with self._lock:
            self._put_memory_locked(key, value, expires_at)

            if self._redis is not None:
                try:
                    self._redis.setex(key, max(1, int(ttl)), json.dumps(value, default=str))
                    return
                except Exception:
                    pass

            if self._db_path is not None:
                try:
                    serialized = json.dumps(value, default=str)
                    with sqlite3.connect(self._db_path) as conn:
                        conn.execute(
                            """
                            INSERT INTO cache_entries (key, value_json, expires_at)
                            VALUES (?, ?, ?)
                            ON CONFLICT(key) DO UPDATE SET
                                value_json = excluded.value_json,
                                expires_at = excluded.expires_at
                            """,
                            (key, serialized, expires_at),
                        )
                        conn.commit()
                except Exception:
                    pass

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self.hits + self.misses
            hit_rate = round((self.hits / total) * 100, 2) if total > 0 else 0.0
            return {
                "backend": self.backend,
                "entries": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate_pct": hit_rate,
            }

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0
            if self._db_path is not None:
                try:
                    with sqlite3.connect(self._db_path) as conn:
                        conn.execute("DELETE FROM cache_entries")
                        conn.commit()
                except Exception:
                    pass


vault_cache = SmartCache()
