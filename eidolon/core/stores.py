from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from eidolon.config.settings import SandboxPermissions
from eidolon.core.models.approval import ApprovalRecord
from eidolon.core.models.chat import ChatMessage, ChatSession
from eidolon.core.models.event import AuditEvent
from eidolon.core.models.scanner import (
    ScannerConfig,
    ScannerConfigRecord,
    default_scanner_config,
)
from eidolon.core.models.settings import AppSettings


class SettingsStore(ABC):
    """Abstract persistence for sandbox permissions."""

    @abstractmethod
    def get_settings(self) -> SandboxPermissions:
        """Fetch current sandbox permissions."""

    @abstractmethod
    def update_settings(self, settings: SandboxPermissions) -> None:
        """Update sandbox permissions."""

    @abstractmethod
    def get_app_settings(self) -> AppSettings:
        """Fetch application settings like theme and LLM config."""

    @abstractmethod
    def update_app_settings(self, settings: AppSettings) -> AppSettings:
        """Update application settings."""


class InMemorySettingsStore(SettingsStore):
    def __init__(self) -> None:
        self._sandbox = SandboxPermissions()
        self._app_settings = AppSettings()

    def get_settings(self) -> SandboxPermissions:
        return self._sandbox

    def update_settings(self, settings: SandboxPermissions) -> None:
        self._sandbox = settings

    def get_app_settings(self) -> AppSettings:
        return self._app_settings

    def update_app_settings(self, settings: AppSettings) -> AppSettings:
        self._app_settings = settings
        return settings


class ScannerStore(ABC):
    """Abstract persistence for scanner configuration and run history."""

    @abstractmethod
    def get_config(self, user_id: str) -> ScannerConfigRecord:
        """Fetch the current scanner config for a user."""

    @abstractmethod
    def update_config(self, user_id: str, config: ScannerConfig) -> ScannerConfigRecord:
        """Persist scanner config for a user."""


class InMemoryScannerStore(ScannerStore):
    def __init__(self) -> None:
        self._configs: dict[str, ScannerConfigRecord] = {}
        self._next_config_id = 1

    def _ensure_config(self, user_id: str) -> ScannerConfigRecord:
        record = self._configs.get(user_id)
        if record:
            return record
        config = default_scanner_config()
        record = ScannerConfigRecord(
            id=self._next_config_id,
            user_id=user_id,
            config=config,
            updated_at=datetime.utcnow(),
        )
        self._next_config_id += 1
        self._configs[user_id] = record
        return record

    def get_config(self, user_id: str) -> ScannerConfigRecord:
        return self._ensure_config(user_id)

    def update_config(self, user_id: str, config: ScannerConfig) -> ScannerConfigRecord:
        record = self._ensure_config(user_id)
        updated = ScannerConfigRecord(
            id=record.id,
            user_id=user_id,
            config=config,
            updated_at=datetime.utcnow(),
        )
        self._configs[user_id] = updated
        return updated


class AuditStore(ABC):
    """Abstract persistence for audit events."""

    @abstractmethod
    def add(self, event: AuditEvent) -> None:
        """Persist an audit event."""

    @abstractmethod
    def get(self, audit_id: UUID) -> AuditEvent | None:
        """Fetch a single audit event."""

    @abstractmethod
    def list_all(self, limit: int = 100) -> list[AuditEvent]:
        """Return recent audit events."""

    @abstractmethod
    def list_filtered(
        self,
        page: int = 1,
        page_size: int = 50,
        event_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditEvent]:
        """Return filtered and paginated audit events."""

    @abstractmethod
    def count_filtered(
        self,
        event_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        """Count events matching filters."""

    @abstractmethod
    def delete_older_than(self, cutoff_date: datetime) -> int:
        """Delete events older than cutoff date. Returns count deleted."""


class InMemoryAuditStore(AuditStore):
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def add(self, event: AuditEvent) -> None:
        self._events.append(event)

    def get(self, audit_id: UUID) -> AuditEvent | None:
        for ev in self._events:
            if ev.audit_id == audit_id:
                return ev
        return None

    def list_all(self, limit: int = 100) -> list[AuditEvent]:
        return list(self._events)[-limit:]

    def list_filtered(
        self,
        page: int = 1,
        page_size: int = 50,
        event_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditEvent]:
        filtered = self._events

        if event_type:
            filtered = [e for e in filtered if e.event_type == event_type]
        if start_date:
            filtered = [e for e in filtered if e.timestamp >= start_date]
        if end_date:
            filtered = [e for e in filtered if e.timestamp <= end_date]

        # Sort by timestamp desc
        filtered = sorted(filtered, key=lambda e: e.timestamp, reverse=True)

        # Paginate
        offset = (page - 1) * page_size
        return filtered[offset : offset + page_size]

    def count_filtered(
        self,
        event_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        filtered = self._events

        if event_type:
            filtered = [e for e in filtered if e.event_type == event_type]
        if start_date:
            filtered = [e for e in filtered if e.timestamp >= start_date]
        if end_date:
            filtered = [e for e in filtered if e.timestamp <= end_date]

        return len(filtered)

    def delete_older_than(self, cutoff_date: datetime) -> int:
        original_count = len(self._events)
        self._events = [e for e in self._events if e.timestamp >= cutoff_date]
        return original_count - len(self._events)


class ApprovalStore(ABC):
    """Abstract persistence for approval tokens."""

    @abstractmethod
    def create(self, user_id: str, action: str, ttl_seconds: int) -> ApprovalRecord:
        """Create an approval token for a specific action."""

    @abstractmethod
    def get_by_token(self, token: str) -> ApprovalRecord | None:
        """Lookup approval token details."""


class InMemoryApprovalStore(ApprovalStore):
    def __init__(self) -> None:
        self._approvals: list[ApprovalRecord] = []

    def create(self, user_id: str, action: str, ttl_seconds: int) -> ApprovalRecord:
        approval = ApprovalRecord.create(user_id=user_id, action=action, ttl_seconds=ttl_seconds)
        self._approvals.append(approval)
        return approval

    def get_by_token(self, token: str) -> ApprovalRecord | None:
        for approval in self._approvals:
            if approval.token == token and not approval.is_expired():
                return approval
        return None


class ChatStore(ABC):
    """Abstract persistence for chat sessions."""

    @abstractmethod
    def create_session(self, title: str | None = None, user_id: str | None = None) -> ChatSession:
        """Create a new chat session."""

    @abstractmethod
    def list_sessions(self, limit: int = 50, user_id: str | None = None) -> list[ChatSession]:
        """Return recent chat sessions."""

    @abstractmethod
    def get_session(self, session_id: UUID, user_id: str | None = None) -> ChatSession | None:
        """Fetch a single chat session."""

    @abstractmethod
    def delete_session(self, session_id: UUID, user_id: str | None = None) -> bool:
        """Delete a chat session and its messages."""

    @abstractmethod
    def append_message(
        self, session_id: UUID, message: ChatMessage, user_id: str | None = None
    ) -> ChatSession | None:
        """Append a message to an existing session."""

    @abstractmethod
    def cleanup_request_messages(
        self, session_id: UUID, request_id: str, user_id: str | None = None
    ) -> ChatSession | None:
        """Remove messages associated with a specific request ID."""


class InMemoryChatStore(ChatStore):
    def __init__(self) -> None:
        self._sessions: dict[UUID, ChatSession] = {}

    def create_session(self, title: str | None = None, user_id: str | None = None) -> ChatSession:
        session = ChatSession(title=title, user_id=user_id or "anonymous")
        self._sessions[session.session_id] = session
        return session

    def list_sessions(self, limit: int = 50, user_id: str | None = None) -> list[ChatSession]:
        sessions = list(self._sessions.values())
        if user_id:
            sessions = [session for session in sessions if session.user_id == user_id]
        return sessions[-limit:]

    def get_session(self, session_id: UUID, user_id: str | None = None) -> ChatSession | None:
        session = self._sessions.get(session_id)
        if session and user_id and session.user_id != user_id:
            return None
        return session

    def delete_session(self, session_id: UUID, user_id: str | None = None) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        if user_id and session.user_id != user_id:
            return False
        del self._sessions[session_id]
        return True

    def append_message(
        self, session_id: UUID, message: ChatMessage, user_id: str | None = None
    ) -> ChatSession | None:
        session = self._sessions.get(session_id)
        if not session:
            return None
        if user_id and session.user_id != user_id:
            return None
        session.messages.append(message)
        session.updated_at = datetime.utcnow()
        return session

    def cleanup_request_messages(
        self, session_id: UUID, request_id: str, user_id: str | None = None
    ) -> ChatSession | None:
        session = self._sessions.get(session_id)
        if not session:
            return None
        if user_id and session.user_id != user_id:
            return None
        session.messages = [
            msg for msg in session.messages if msg.metadata.get("request_id") != request_id
        ]
        session.updated_at = datetime.utcnow()
        return session
