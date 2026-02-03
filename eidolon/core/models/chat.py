from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    message_id: UUID = Field(default_factory=uuid4)
    role: Literal["user", "assistant", "system", "tool"] = Field(default="user")
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatSession(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    user_id: str = Field(default="anonymous")
    title: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    messages: list[ChatMessage] = Field(default_factory=list)
