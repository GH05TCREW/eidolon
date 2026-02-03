from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ApprovalRecord(BaseModel):
    """Approval token record stored in Postgres."""

    approval_id: UUID = Field(default_factory=uuid4, alias="id")
    user_id: str
    token: str
    action: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def create(cls, user_id: str, action: str, ttl_seconds: int) -> ApprovalRecord:
        token = str(uuid4())
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        return cls(user_id=user_id, token=token, action=action, expires_at=expires_at)

    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at
