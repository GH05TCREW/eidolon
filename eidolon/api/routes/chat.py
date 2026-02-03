from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from eidolon.api.dependencies import (
    get_chat_store,
    get_graph_repository,
    get_llm_client,
    require_roles,
)
from eidolon.api.middleware.auth import IdentityContext
from eidolon.core.graph.repository import GraphRepository
from eidolon.core.models.chat import ChatMessage, ChatSession
from eidolon.core.reasoning.llm import LiteLLMClient
from eidolon.core.stores import ChatStore
from eidolon.runtime.assistant import AssistantAgent, build_system_prompt
from eidolon.runtime.sandbox import SandboxRuntime
from eidolon.runtime.tools.browser import BrowserTool
from eidolon.runtime.tools.file_edit import FileEditTool
from eidolon.runtime.tools.finish import FinishTool
from eidolon.runtime.tools.graph_query import GraphQueryTool
from eidolon.runtime.tools.terminal import TerminalTool
from eidolon.runtime.tools.thinking import ThinkingTool
from eidolon.runtime.tools.todo import TodoTool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])
_CHAT_STORE = Depends(get_chat_store)
_LLM_CLIENT = Depends(get_llm_client)
_GRAPH_REPOSITORY = Depends(get_graph_repository)
_VIEWER_IDENTITY = Depends(require_roles("viewer", "planner", "executor"))
_EXECUTOR_IDENTITY = Depends(require_roles("executor"))


def _build_sandbox(
    repository: GraphRepository, settings_store: ChatStore | None = None
) -> SandboxRuntime:
    """Build the sandbox runtime with all tools and permission checking."""
    from eidolon.api.dependencies import get_settings_store

    # Get runtime permissions from database if available, otherwise use config file defaults
    if settings_store is None:
        settings_store = get_settings_store()

    sandbox_settings = settings_store.get_settings()
    runtime = SandboxRuntime(settings=sandbox_settings)

    # Register all available tools
    runtime.register_tool(TerminalTool())
    runtime.register_tool(BrowserTool())
    runtime.register_tool(FileEditTool())
    runtime.register_tool(ThinkingTool())
    runtime.register_tool(TodoTool())
    runtime.register_tool(FinishTool())
    runtime.register_tool(GraphQueryTool(repository))

    return runtime


def _find_last_request_id(messages: list[ChatMessage]) -> str | None:
    for msg in reversed(messages):
        request_id = msg.metadata.get("request_id")
        if isinstance(request_id, str) and request_id:
            return request_id
    return None


def _is_cancelled_message(msg: ChatMessage) -> bool:
    return msg.role == "assistant" and msg.metadata.get("cancelled") is True


def _append_cancelled_tool_responses(
    store: ChatStore,
    session_id: UUID,
    user_id: str,
    request_id: str | None,
    tool_calls: list[Any],
) -> None:
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        tool_call_id = call.get("id")
        if not tool_call_id:
            continue
        metadata = {"tool_call_id": tool_call_id, "tool_name": call.get("name", "unknown")}
        if request_id:
            metadata["request_id"] = request_id
        tool_response = ChatMessage(
            role="tool",
            content="Cancelled by user",
            metadata=metadata,
        )
        store.append_message(session_id, tool_response, user_id=user_id)


def _append_cancellation_message(
    store: ChatStore,
    session_id: UUID,
    user_id: str,
    request_id: str | None,
    reason: str,
) -> None:
    metadata: dict[str, Any] = {"kind": "internal", "cancelled": True}
    if request_id:
        metadata["request_id"] = request_id
    assistant_message = ChatMessage(
        role="assistant",
        content=reason,
        metadata=metadata,
    )
    store.append_message(session_id, assistant_message, user_id=user_id)


def _finalize_cancelled_request(
    session: ChatSession | None,
    store: ChatStore,
    user_id: str,
    request_id: str | None,
    reason: str,
) -> None:
    if not session or not session.messages:
        return
    last_msg = session.messages[-1]
    if _is_cancelled_message(last_msg):
        return
    if last_msg.role == "assistant" and "tool_calls" in last_msg.metadata:
        tool_calls = last_msg.metadata.get("tool_calls", [])
        if isinstance(tool_calls, list):
            _append_cancelled_tool_responses(
                store, session.session_id, user_id, request_id, tool_calls
            )
    _append_cancellation_message(store, session.session_id, user_id, request_id, reason)


def _auto_cancel_pending_request(
    session: ChatSession,
    store: ChatStore,
    user_id: str,
) -> None:
    if not session.messages:
        return
    last_msg = session.messages[-1]
    if last_msg.role == "assistant" and "tool_calls" not in last_msg.metadata:
        return
    if _is_cancelled_message(last_msg):
        return
    request_id = _find_last_request_id(session.messages)
    _finalize_cancelled_request(
        session,
        store,
        user_id,
        request_id,
        "Previous request cancelled by a newer message.",
    )


class CancellationToken:
    def __init__(self, session_id: UUID, request_id: str, registry: CancellationRegistry) -> None:
        self._session_id = session_id
        self._request_id = request_id
        self._registry = registry

    def is_set(self) -> bool:
        return self._registry.is_cancelled(self._session_id, self._request_id)

    def set(self) -> None:
        self._registry.cancel(self._session_id, self._request_id)


class CancellationRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, threading.Event] = {}

    def register(self, session_id: UUID, request_id: str) -> CancellationToken:
        token_key = self._token_key(session_id, request_id)
        with self._lock:
            event = self._events.get(token_key)
            if event is None:
                event = threading.Event()
                self._events[token_key] = event
        return CancellationToken(session_id, request_id, self)

    def cancel(self, session_id: UUID, request_id: str) -> bool:
        found = False
        token_key = self._token_key(session_id, request_id)
        with self._lock:
            event = self._events.get(token_key)
            if event is not None:
                event.set()
                found = True
        return found

    def is_cancelled(self, session_id: UUID, request_id: str) -> bool:
        token_key = self._token_key(session_id, request_id)
        with self._lock:
            event = self._events.get(token_key)
            if event is not None and event.is_set():
                return True
        return False

    def clear(self, session_id: UUID, request_id: str) -> None:
        token_key = self._token_key(session_id, request_id)
        with self._lock:
            self._events.pop(token_key, None)

    def _token_key(self, session_id: UUID, request_id: str) -> str:
        return f"{session_id}:{request_id}"


_cancellation_registry = CancellationRegistry()


class CreateSessionRequest(BaseModel):
    title: str | None = Field(default=None)


class ChatSessionSummary(BaseModel):
    session_id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int


class ChatMessageRequest(BaseModel):
    role: Literal["user", "assistant", "system"] = Field(default="user")
    content: str
    metadata: dict[str, Any] | None = Field(default=None)
    request_id: str | None = Field(default=None)


class BulkDeleteResponse(BaseModel):
    status: str
    deleted: int


class CancelChatRequest(BaseModel):
    request_id: str = Field(..., min_length=1)


@router.get("/sessions", response_model=list[ChatSessionSummary])
def list_sessions(
    store: ChatStore = _CHAT_STORE,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> list[ChatSessionSummary]:
    sessions = store.list_sessions(limit=50, user_id=identity.user_id)
    return [
        ChatSessionSummary(
            session_id=session.session_id,
            title=session.title,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=len(session.messages),
        )
        for session in sessions
    ]


@router.post("/sessions", response_model=ChatSession)
def create_session(
    request: CreateSessionRequest,
    store: ChatStore = _CHAT_STORE,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> ChatSession:
    return store.create_session(title=request.title, user_id=identity.user_id)


@router.get("/sessions/{session_id}", response_model=ChatSession)
def get_session(
    session_id: UUID,
    store: ChatStore = _CHAT_STORE,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> ChatSession:
    session = store.get_session(session_id, user_id=identity.user_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: UUID,
    store: ChatStore = _CHAT_STORE,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> dict[str, str]:
    deleted = store.delete_session(session_id, user_id=identity.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    return {"status": "deleted"}


@router.delete("/sessions", response_model=BulkDeleteResponse)
def delete_sessions(
    store: ChatStore = _CHAT_STORE,
    identity: IdentityContext = _EXECUTOR_IDENTITY,
) -> BulkDeleteResponse:
    deleted = 0
    while True:
        sessions = store.list_sessions(limit=200, user_id=identity.user_id)
        if not sessions:
            break
        for session in sessions:
            if store.delete_session(session.session_id, user_id=identity.user_id):
                deleted += 1
    return BulkDeleteResponse(status="deleted", deleted=deleted)


@router.post("/sessions/{session_id}/messages", response_model=ChatSession)
def add_message(
    request: Request,
    session_id: UUID,
    payload: ChatMessageRequest,
    store: ChatStore = _CHAT_STORE,
    llm_client: LiteLLMClient = _LLM_CLIENT,
    repository: GraphRepository = _GRAPH_REPOSITORY,
    stream: bool = False,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> ChatSession | StreamingResponse:
    from eidolon.api.dependencies import get_settings_store

    request_id = payload.request_id
    if stream and not request_id:
        request_id = f"req_{uuid4()}"
    metadata = dict(payload.metadata or {})
    if request_id:
        metadata["request_id"] = request_id
    if payload.role == "user":
        existing_session = store.get_session(session_id, user_id=identity.user_id)
        if not existing_session:
            raise HTTPException(status_code=404, detail="session not found")
        _auto_cancel_pending_request(existing_session, store, identity.user_id)
    message = ChatMessage(
        role=payload.role,
        content=payload.content,
        metadata=metadata,
    )
    session = store.append_message(session_id, message, user_id=identity.user_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    # If user message, run the agent loop to generate response
    if payload.role == "user" and llm_client.is_available():
        settings_store = get_settings_store()
        sandbox = _build_sandbox(repository, settings_store)
        system_prompt = build_system_prompt(
            sandbox.active_tools.values(), sandbox.settings, repository
        )
        agent = AssistantAgent(
            llm_client=llm_client,
            sandbox=sandbox,
            system_prompt=system_prompt,
            max_iterations=10,
        )
        if stream:
            cancellation_token = (
                _cancellation_registry.register(session_id, request_id) if request_id else None
            )

            def event_stream():
                cancelled = False
                try:
                    for msg in agent.run_iter(
                        session.messages, cancellation_token=cancellation_token
                    ):
                        if cancellation_token and cancellation_token.is_set():
                            cancelled = True
                            break
                        if anyio.from_thread.run(request.is_disconnected):
                            cancelled = True
                            if cancellation_token:
                                cancellation_token.set()
                            break
                        if request_id:
                            msg.metadata["request_id"] = request_id
                        stored = store.append_message(session_id, msg, user_id=identity.user_id)
                        if stored:
                            payload = {
                                "type": "message",
                                "message": msg.model_dump(mode="json"),
                            }
                            yield json.dumps(payload) + "\n"
                except Exception as e:
                    logger.exception("Agent loop failed")
                    error_metadata = {"kind": "error"}
                    if request_id:
                        error_metadata["request_id"] = request_id
                    assistant_message = ChatMessage(
                        role="assistant",
                        content=f"I encountered an error: {e}",
                        metadata=error_metadata,
                    )
                    store.append_message(session_id, assistant_message, user_id=identity.user_id)
                    payload = {
                        "type": "message",
                        "message": assistant_message.model_dump(mode="json"),
                    }
                    yield json.dumps(payload) + "\n"
                finally:
                    if request_id:
                        was_cancelled = cancelled or (
                            cancellation_token and cancellation_token.is_set()
                        )
                        _cancellation_registry.clear(session_id, request_id)
                        if was_cancelled:
                            current_session = store.get_session(
                                session_id, user_id=identity.user_id
                            )
                            _finalize_cancelled_request(
                                current_session,
                                store,
                                identity.user_id,
                                request_id,
                                "Request cancelled by user.",
                            )
                yield json.dumps({"type": "done"}) + "\n"

            return StreamingResponse(
                event_stream(),
                media_type="application/x-ndjson",
                headers={"Cache-Control": "no-cache"},
            )

        try:
            for msg in agent.run_iter(session.messages):
                if request_id:
                    msg.metadata["request_id"] = request_id
                session = store.append_message(session_id, msg, user_id=identity.user_id)
        except Exception as e:
            logger.exception("Agent loop failed")
            error_metadata = {"kind": "error"}
            if request_id:
                error_metadata["request_id"] = request_id
            assistant_message = ChatMessage(
                role="assistant",
                content=f"I encountered an error: {e}",
                metadata=error_metadata,
            )
            session = store.append_message(session_id, assistant_message, user_id=identity.user_id)

    return session


@router.post("/sessions/{session_id}/cancel")
def cancel_request(
    session_id: UUID,
    payload: CancelChatRequest,
    store: ChatStore = _CHAT_STORE,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> dict[str, str]:
    cancelled = _cancellation_registry.cancel(session_id, payload.request_id)
    if cancelled:
        return {"status": "cancelled"}
    return {"status": "not_found"}
