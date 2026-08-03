"""Bus di eventi thread-safe per la comunicazione col browser (SSE).

Il loop di monitoraggio pubblica eventi (es. "movimento"); la dashboard web
vi si iscrive e li riceve in tempo reale tramite Server-Sent Events.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any


class EventBus:
    def __init__(self, max_queue: int = 50):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._max_queue = max_queue
        self.last_motion_ts: float | None = None

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._max_queue)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        payload = {"type": event_type, "ts": time.time(), "data": data or {}}
        if event_type == "motion":
            self.last_motion_ts = payload["ts"]
        message = json.dumps(payload)
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(message)
            except queue.Full:
                # Consumatore lento: scarto il messaggio piu' vecchio.
                try:
                    q.get_nowait()
                    q.put_nowait(message)
                except queue.Empty:
                    pass
