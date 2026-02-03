from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from eidolon.api.dependencies import require_roles
from eidolon.api.middleware.auth import IdentityContext
from eidolon.runtime.task_events import task_event_bus

router = APIRouter(prefix="/tasks", tags=["tasks"])
_TASK_STREAM_IDENTITY = Depends(require_roles("viewer", "planner", "executor"))


async def _stream() -> AsyncGenerator[bytes, None]:
    subscriber = task_event_bus.subscribe_async()
    try:
        # Send history first
        for event in task_event_bus.history():
            payload = json.dumps(event.to_payload())
            yield f"data: {payload}\n\n".encode()

        # Stream live events with proper cancellation support
        while True:
            try:
                # Wait for event with timeout for keepalive
                event = await asyncio.wait_for(subscriber.get(), timeout=15.0)

                # None is shutdown sentinel
                if event is None:
                    break

                payload = json.dumps(event.to_payload())
                yield f"data: {payload}\n\n".encode()
            except TimeoutError:
                # Send keepalive to prevent client timeout
                yield b": keepalive\n\n"
    except asyncio.CancelledError:
        # Client disconnected or server shutting down - clean exit
        pass
    finally:
        task_event_bus.unsubscribe_async(subscriber)


@router.get("/stream")
async def task_stream(identity: IdentityContext = _TASK_STREAM_IDENTITY) -> StreamingResponse:
    return StreamingResponse(_stream(), media_type="text/event-stream")
