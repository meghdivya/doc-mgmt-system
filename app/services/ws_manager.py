import asyncio
from collections import defaultdict
import threading
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    """Thread-safe WebSocket pub/sub manager bridging sync workers and async WS clients."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._topics: dict[str, set[tuple[WebSocket, asyncio.AbstractEventLoop]]] = defaultdict(set)

    async def connect(self, topic: str, websocket: WebSocket) -> None:
        await websocket.accept()
        loop = asyncio.get_running_loop()
        with self._lock:
            self._topics[topic].add((websocket, loop))

    def disconnect(self, topic: str, websocket: WebSocket) -> None:
        with self._lock:
            subscribers = self._topics.get(topic)
            if not subscribers:
                return
            to_remove = [item for item in subscribers if item[0] is websocket]
            for item in to_remove:
                subscribers.discard(item)
            if not subscribers:
                self._topics.pop(topic, None)

    def publish_from_thread(self, topic: str, payload: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._topics.get(topic, ()))

        for ws, loop in subscribers:
            if loop.is_closed():
                self.disconnect(topic, ws)
                continue
            try:
                asyncio.run_coroutine_threadsafe(ws.send_json(payload), loop)
            except Exception:
                self.disconnect(topic, ws)

    def publish_document_event(self, document_id: int, payload: dict[str, Any]) -> None:
        self.publish_from_thread("documents:all", payload)
        self.publish_from_thread(f"document:{document_id}", payload)


ws_manager = WebSocketManager()
