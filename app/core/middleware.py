from collections import defaultdict, deque
import threading
import time
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings


class TelemetryAndRateLimitTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total_requests = 0
        self.total_latency_ms = 0.0
        self._client_windows: dict[str, deque[float]] = defaultdict(deque)

    def check_rate_limit(self, client_key: str, limit_per_minute: int) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        with self._lock:
            dq = self._client_windows[client_key]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= limit_per_minute:
                return False
            dq.append(now)
            return True

    def record_request(self, latency_ms: float) -> None:
        with self._lock:
            self.total_requests += 1
            self.total_latency_ms += latency_ms

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            avg = (
                round(self.total_latency_ms / self.total_requests, 2)
                if self.total_requests > 0
                else 0.0
            )
            return {
                "total_requests": self.total_requests,
                "avg_response_ms": avg,
            }

    def reset(self) -> None:
        with self._lock:
            self.total_requests = 0
            self.total_latency_ms = 0.0
            self._client_windows.clear()


http_tracker = TelemetryAndRateLimitTracker()


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        client_ip = request.client.host if request.client else "local"
        if not http_tracker.check_rate_limit(client_ip, settings.rate_limit_per_minute):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please retry shortly."},
            )

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        http_tracker.record_request(elapsed_ms)
        response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
        return response
