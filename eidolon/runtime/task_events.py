from __future__ import annotations

import asyncio
import queue
import threading
from collections import deque
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class TaskEvent:
    event_type: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    message: str | None = None
    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_payload(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "status": self.status,
            "payload": self.payload,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


class TaskEventBus:
    def __init__(self, history_size: int = 200, queue_size: int = 200) -> None:
        self._history: deque[TaskEvent] = deque(maxlen=history_size)
        self._subscribers: set[queue.Queue[TaskEvent]] = set()
        self._async_subscribers: set[asyncio.Queue[TaskEvent]] = set()
        self._lock = threading.Lock()
        self._queue_size = queue_size
        self._shutdown = False

    def publish(self, event: TaskEvent) -> None:
        with self._lock:
            self._history.append(event)
            subscribers = list(self._subscribers)
            async_subscribers = list(self._async_subscribers)

        # Publish to sync subscribers
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                with suppress(queue.Empty):
                    subscriber.get_nowait()
                with suppress(queue.Full):
                    subscriber.put_nowait(event)

        # Publish to async subscribers
        for subscriber in async_subscribers:
            try:
                subscriber.put_nowait(event)
            except asyncio.QueueFull:
                with suppress(asyncio.QueueEmpty):
                    subscriber.get_nowait()
                with suppress(asyncio.QueueFull):
                    subscriber.put_nowait(event)

    def subscribe(self) -> queue.Queue[TaskEvent]:
        subscriber: queue.Queue[TaskEvent] = queue.Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[TaskEvent]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def subscribe_async(self) -> asyncio.Queue[TaskEvent]:
        """Subscribe with an async queue for proper cancellation support."""
        subscriber: asyncio.Queue[TaskEvent] = asyncio.Queue(maxsize=self._queue_size)
        with self._lock:
            self._async_subscribers.add(subscriber)
        return subscriber

    def unsubscribe_async(self, subscriber: asyncio.Queue[TaskEvent]) -> None:
        with self._lock:
            self._async_subscribers.discard(subscriber)

    def history(self) -> Iterable[TaskEvent]:
        with self._lock:
            return list(self._history)

    def shutdown(self) -> None:
        """Signal shutdown to all async subscribers."""
        with self._lock:
            self._shutdown = True
            # Wake up all async subscribers with None sentinel
            for subscriber in self._async_subscribers:
                with suppress(asyncio.QueueFull):
                    subscriber.put_nowait(None)  # type: ignore


task_event_bus = TaskEventBus()
