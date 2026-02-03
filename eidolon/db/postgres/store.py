from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
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
from eidolon.core.stores import ApprovalStore, AuditStore, ChatStore, ScannerStore, SettingsStore

try:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional dependency
    psycopg = None
    sql = None
    dict_row = None

if psycopg is None:
    POSTGRES_ERRORS: tuple[type[Exception], ...] = (RuntimeError, TypeError, ValueError)
else:
    POSTGRES_ERRORS = (psycopg.Error, RuntimeError, TypeError, ValueError)


def _ensure_uuid(value) -> UUID:
    """Convert database UUID value to UUID object if needed."""
    return value if isinstance(value, UUID) else UUID(value)


def postgres_available() -> bool:
    return psycopg is not None


class PostgresStoreBase:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection]:
        if psycopg is None:
            raise RuntimeError("psycopg is not installed")
        conn = psycopg.connect(self._dsn, row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()


class PostgresAuditStore(PostgresStoreBase, AuditStore):
    def __init__(self, dsn: str, fallback: AuditStore | None = None) -> None:
        super().__init__(dsn)
        self._fallback = fallback

    def add(self, event: AuditEvent) -> None:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO audit_events (id, event_type, details, status, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            str(event.audit_id),
                            event.event_type,
                            json.dumps(event.details),
                            event.status,
                            event.timestamp,
                        ),
                    )
                conn.commit()
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.add(event)
            raise

    def get(self, audit_id: UUID) -> AuditEvent | None:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, event_type, details, status, created_at
                        FROM audit_events
                        WHERE id = %s
                        """,
                        (str(audit_id),),
                    )
                    row = cur.fetchone()
            if not row:
                return None
            payload = {
                "audit_id": UUID(row["id"]),
                "event_type": row["event_type"],
                "details": row["details"],
                "status": row["status"],
                "timestamp": row["created_at"],
            }
            return AuditEvent.model_validate(payload)
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.get(audit_id)
            raise

    def list_all(self, limit: int = 100) -> list[AuditEvent]:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, event_type, details, status, created_at
                        FROM audit_events
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                    rows = cur.fetchall()
            events: list[AuditEvent] = []
            for row in rows:
                payload = {
                    "audit_id": _ensure_uuid(row["id"]),
                    "event_type": row["event_type"],
                    "details": row["details"],
                    "status": row["status"],
                    "timestamp": row["created_at"],
                }
                events.append(AuditEvent.model_validate(payload))
            return events
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.list_all(limit=limit)
            raise

    def list_filtered(
        self,
        page: int = 1,
        page_size: int = 50,
        event_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditEvent]:
        try:
            if sql is None:
                raise RuntimeError("psycopg is not installed")
            # Build dynamic WHERE clause
            conditions: list[sql.Composable] = []
            params: list = []

            if event_type:
                conditions.append(sql.SQL("event_type = %s"))
                params.append(event_type)
            if start_date:
                conditions.append(sql.SQL("created_at >= %s"))
                params.append(start_date)
            if end_date:
                conditions.append(sql.SQL("created_at <= %s"))
                params.append(end_date)

            where_clause = sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("TRUE")
            offset = (page - 1) * page_size
            params.extend([page_size, offset])

            with self._connect() as conn:
                with conn.cursor() as cur:
                    query = sql.SQL("""
                        SELECT id, event_type, details, status, created_at
                        FROM audit_events
                        WHERE {where_clause}
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                        """).format(where_clause=where_clause)
                    cur.execute(query, tuple(params))
                    rows = cur.fetchall()

            events: list[AuditEvent] = []
            for row in rows:
                payload = {
                    "audit_id": _ensure_uuid(row["id"]),
                    "event_type": row["event_type"],
                    "details": row["details"],
                    "status": row["status"],
                    "timestamp": row["created_at"],
                }
                events.append(AuditEvent.model_validate(payload))
            return events
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.list_filtered(
                    page, page_size, event_type, start_date, end_date
                )
            raise

    def count_filtered(
        self,
        event_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        try:
            if sql is None:
                raise RuntimeError("psycopg is not installed")
            conditions: list[sql.Composable] = []
            params: list = []

            if event_type:
                conditions.append(sql.SQL("event_type = %s"))
                params.append(event_type)
            if start_date:
                conditions.append(sql.SQL("created_at >= %s"))
                params.append(start_date)
            if end_date:
                conditions.append(sql.SQL("created_at <= %s"))
                params.append(end_date)

            where_clause = sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("TRUE")

            with self._connect() as conn:
                with conn.cursor() as cur:
                    query = sql.SQL(
                        "SELECT COUNT(*) as total FROM audit_events WHERE {where_clause}"
                    ).format(where_clause=where_clause)
                    cur.execute(query, tuple(params))
                    result = cur.fetchone()
            return int(result["total"]) if result else 0
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.count_filtered(event_type, start_date, end_date)
            raise

    def delete_older_than(self, cutoff_date: datetime) -> int:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM audit_events WHERE created_at < %s",
                        (cutoff_date,),
                    )
                    deleted = cur.rowcount
                conn.commit()
            return deleted
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.delete_older_than(cutoff_date)
            raise


class PostgresApprovalStore(PostgresStoreBase, ApprovalStore):
    def __init__(self, dsn: str, fallback: ApprovalStore | None = None) -> None:
        super().__init__(dsn)
        self._fallback = fallback

    def create(self, user_id: str, action: str, ttl_seconds: int) -> ApprovalRecord:
        approval = ApprovalRecord.create(user_id=user_id, action=action, ttl_seconds=ttl_seconds)
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO approvals (id, user_id, token, action, expires_at, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            str(approval.approval_id),
                            approval.user_id,
                            approval.token,
                            approval.action,
                            approval.expires_at,
                            approval.created_at,
                        ),
                    )
                conn.commit()
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.create(
                    user_id=user_id, action=action, ttl_seconds=ttl_seconds
                )
            raise
        return approval

    def get_by_token(self, token: str) -> ApprovalRecord | None:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, user_id, token, action, expires_at, created_at
                        FROM approvals
                        WHERE token = %s
                        """,
                        (token,),
                    )
                    row = cur.fetchone()
            if not row:
                return None
            record = ApprovalRecord.model_validate(
                {
                    "approval_id": _ensure_uuid(row["id"]),
                    "user_id": row["user_id"],
                    "token": row["token"],
                    "action": row["action"],
                    "expires_at": row["expires_at"],
                    "created_at": row["created_at"],
                }
            )
            return None if record.is_expired() else record
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.get_by_token(token)
            raise


class PostgresChatStore(PostgresStoreBase, ChatStore):
    def __init__(self, dsn: str, fallback: ChatStore | None = None) -> None:
        super().__init__(dsn)
        self._fallback = fallback
        self._supports_metadata: bool | None = None

    def _metadata_supported(self, conn) -> bool:
        if self._supports_metadata is not None:
            return self._supports_metadata
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'chat_messages'
                  AND column_name = 'metadata'
                """)
            self._supports_metadata = cur.fetchone() is not None
        return self._supports_metadata

    def create_session(self, title: str | None = None, user_id: str | None = None) -> ChatSession:
        session = ChatSession(title=title, user_id=user_id or "anonymous")
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            str(session.session_id),
                            session.user_id,
                            session.title,
                            session.created_at,
                            session.updated_at,
                        ),
                    )
                conn.commit()
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.create_session(title=title, user_id=session.user_id)
            raise
        return session

    def list_sessions(self, limit: int = 50, user_id: str | None = None) -> list[ChatSession]:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    if user_id:
                        cur.execute(
                            """
                            SELECT id, user_id, title, created_at, updated_at
                            FROM chat_sessions
                            WHERE user_id = %s
                            ORDER BY updated_at DESC
                            LIMIT %s
                            """,
                            (user_id, limit),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT id, user_id, title, created_at, updated_at
                            FROM chat_sessions
                            ORDER BY updated_at DESC
                            LIMIT %s
                            """,
                            (limit,),
                        )
                    rows = cur.fetchall()
            sessions: list[ChatSession] = []
            for row in rows:
                session_id = _ensure_uuid(row["id"])
                messages = self._get_messages(session_id)
                sessions.append(
                    ChatSession(
                        session_id=session_id,
                        user_id=row["user_id"],
                        title=row["title"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                        messages=messages,
                    )
                )
            if not sessions and self._fallback:
                fallback_sessions = self._fallback.list_sessions(limit=limit, user_id=user_id)
                if fallback_sessions:
                    return fallback_sessions
            return sessions
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.list_sessions(limit=limit, user_id=user_id)
            raise

    def get_session(self, session_id: UUID, user_id: str | None = None) -> ChatSession | None:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    if user_id:
                        cur.execute(
                            """
                            SELECT id, user_id, title, created_at, updated_at
                            FROM chat_sessions
                            WHERE id = %s AND user_id = %s
                            """,
                            (str(session_id), user_id),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT id, user_id, title, created_at, updated_at
                            FROM chat_sessions
                            WHERE id = %s
                            """,
                            (str(session_id),),
                        )
                    row = cur.fetchone()
            if not row:
                if self._fallback:
                    return self._fallback.get_session(session_id, user_id=user_id)
                return None
            messages = self._get_messages(session_id)
            return ChatSession(
                session_id=_ensure_uuid(row["id"]),
                user_id=row["user_id"],
                title=row["title"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                messages=messages,
            )
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.get_session(session_id, user_id=user_id)
            raise

    def delete_session(self, session_id: UUID, user_id: str | None = None) -> bool:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    if user_id:
                        cur.execute(
                            "SELECT id FROM chat_sessions WHERE id = %s AND user_id = %s",
                            (str(session_id), user_id),
                        )
                    else:
                        cur.execute(
                            "SELECT id FROM chat_sessions WHERE id = %s",
                            (str(session_id),),
                        )
                    if not cur.fetchone():
                        if self._fallback:
                            return self._fallback.delete_session(session_id, user_id=user_id)
                        return False
                    cur.execute(
                        "DELETE FROM chat_messages WHERE session_id = %s",
                        (str(session_id),),
                    )
                    cur.execute(
                        "DELETE FROM chat_sessions WHERE id = %s",
                        (str(session_id),),
                    )
                conn.commit()
            return True
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.delete_session(session_id, user_id=user_id)
            raise

    def append_message(
        self, session_id: UUID, message: ChatMessage, user_id: str | None = None
    ) -> ChatSession | None:
        try:
            with self._connect() as conn:
                supports_metadata = self._metadata_supported(conn)
                with conn.cursor() as cur:
                    # Check if session exists (with or without user_id constraint)
                    if user_id:
                        cur.execute(
                            "SELECT id FROM chat_sessions WHERE id = %s AND user_id = %s",
                            (str(session_id), user_id),
                        )
                    else:
                        cur.execute(
                            "SELECT id FROM chat_sessions WHERE id = %s",
                            (str(session_id),),
                        )

                    if not cur.fetchone():
                        if self._fallback:
                            fallback_session = self._fallback.append_message(
                                session_id, message, user_id=user_id
                            )
                            if fallback_session:
                                return fallback_session
                        return None

                    # Session exists, insert message with or without metadata
                    if supports_metadata:
                        cur.execute(
                            """
                            INSERT INTO chat_messages (
                                id, session_id, role, content, metadata, created_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (
                                str(message.message_id),
                                str(session_id),
                                message.role,
                                message.content,
                                json.dumps(message.metadata, default=str),
                                message.timestamp,
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO chat_messages (
                                id, session_id, role, content, created_at
                            )
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (
                                str(message.message_id),
                                str(session_id),
                                message.role,
                                message.content,
                                message.timestamp,
                            ),
                        )
                    cur.execute(
                        "UPDATE chat_sessions SET updated_at = %s WHERE id = %s",
                        (message.timestamp, str(session_id)),
                    )
                conn.commit()
            return self.get_session(session_id, user_id=user_id)
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.append_message(session_id, message, user_id=user_id)
            raise

    def cleanup_request_messages(
        self, session_id: UUID, request_id: str, user_id: str | None = None
    ) -> ChatSession | None:
        try:
            with self._connect() as conn:
                supports_metadata = self._metadata_supported(conn)
                if not supports_metadata:
                    if self._fallback:
                        return self._fallback.cleanup_request_messages(
                            session_id, request_id, user_id=user_id
                        )
                    return self.get_session(session_id, user_id=user_id)
                with conn.cursor() as cur:
                    if user_id:
                        cur.execute(
                            "SELECT id FROM chat_sessions WHERE id = %s AND user_id = %s",
                            (str(session_id), user_id),
                        )
                    else:
                        cur.execute(
                            "SELECT id FROM chat_sessions WHERE id = %s",
                            (str(session_id),),
                        )
                    if not cur.fetchone():
                        if self._fallback:
                            return self._fallback.cleanup_request_messages(
                                session_id, request_id, user_id=user_id
                            )
                        return None
                    cur.execute(
                        """
                        DELETE FROM chat_messages
                        WHERE session_id = %s
                          AND metadata ->> 'request_id' = %s
                        """,
                        (str(session_id), request_id),
                    )
                    cur.execute(
                        "UPDATE chat_sessions SET updated_at = %s WHERE id = %s",
                        (datetime.utcnow(), str(session_id)),
                    )
                conn.commit()
            return self.get_session(session_id, user_id=user_id)
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.cleanup_request_messages(
                    session_id, request_id, user_id=user_id
                )
            raise

    def _get_messages(self, session_id: UUID) -> list[ChatMessage]:
        with self._connect() as conn:
            supports_metadata = self._metadata_supported(conn)
            with conn.cursor() as cur:
                if supports_metadata:
                    cur.execute(
                        """
                        SELECT id, role, content, metadata, created_at
                        FROM chat_messages
                        WHERE session_id = %s
                        ORDER BY created_at ASC
                        """,
                        (str(session_id),),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, role, content, created_at
                        FROM chat_messages
                        WHERE session_id = %s
                        ORDER BY created_at ASC
                        """,
                        (str(session_id),),
                    )
                rows = cur.fetchall()
        messages: list[ChatMessage] = []
        for row in rows:
            metadata = row.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (json.JSONDecodeError, TypeError):
                    metadata = {}
            messages.append(
                ChatMessage(
                    message_id=_ensure_uuid(row["id"]),
                    role=row["role"],
                    content=row["content"],
                    metadata=metadata,
                    timestamp=row["created_at"],
                )
            )
        return messages


class PostgresSettingsStore(PostgresStoreBase, SettingsStore):
    """Postgres-backed sandbox permissions store."""

    def get_settings(self) -> SandboxPermissions:
        """Fetch sandbox permissions from database, or return defaults if not found."""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT permissions FROM sandbox_permissions WHERE id = %s",
                        ("default",),
                    )
                    row = cur.fetchone()
            if not row:
                return SandboxPermissions()
            return SandboxPermissions.model_validate(row["permissions"])
        except POSTGRES_ERRORS:
            return SandboxPermissions()

    def update_settings(self, settings: SandboxPermissions) -> None:
        """Update sandbox permissions in database."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sandbox_permissions (id, permissions, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (id) DO UPDATE
                    SET permissions = EXCLUDED.permissions, updated_at = now()
                    """,
                    ("default", json.dumps(settings.model_dump())),
                )
            conn.commit()

    def get_app_settings(self) -> AppSettings:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT settings FROM app_settings WHERE id = %s",
                        ("default",),
                    )
                    row = cur.fetchone()
            if not row:
                return AppSettings()
            payload = row.get("settings") if isinstance(row, dict) else row[0]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    payload = {}
            return AppSettings.model_validate(payload)
        except POSTGRES_ERRORS:
            return AppSettings()

    def update_app_settings(self, settings: AppSettings) -> AppSettings:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO app_settings (id, settings, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (id) DO UPDATE
                    SET settings = EXCLUDED.settings, updated_at = now()
                    """,
                    ("default", json.dumps(settings.model_dump())),
                )
            conn.commit()
        return settings


class PostgresScannerStore(PostgresStoreBase, ScannerStore):
    def __init__(self, dsn: str, fallback: ScannerStore | None = None) -> None:
        super().__init__(dsn)
        self._fallback = fallback

    @staticmethod
    def _coerce_json(value, default):
        if value is None:
            return default
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return default
        return value

    def _row_to_record(self, row, user_id: str) -> ScannerConfigRecord:
        options = self._coerce_json(row.get("options"), {})
        config = ScannerConfig(
            network_cidrs=row.get("network_cidrs") or [],
            ports=row.get("ports") or [],
            port_preset=row.get("port_preset") or "custom",
            options=options or {},
        )
        return ScannerConfigRecord(
            id=int(row["id"]),
            user_id=user_id,
            config=config,
            updated_at=row.get("updated_at"),
        )

    def get_config(self, user_id: str) -> ScannerConfigRecord:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, network_cidrs, ports, port_preset, collectors, options,
                               updated_at
                        FROM scan_configs
                        WHERE user_id = %s
                        """,
                        (user_id,),
                    )
                    row = cur.fetchone()
                if row:
                    return self._row_to_record(row, user_id)

                config = default_scanner_config()
                collectors_payload = json.dumps({"network": True})
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO scan_configs (
                            user_id, network_cidrs, ports, port_preset, collectors, options,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, now())
                        RETURNING id, updated_at
                        """,
                        (
                            user_id,
                            config.network_cidrs,
                            config.ports,
                            config.port_preset,
                            collectors_payload,
                            json.dumps(config.options.model_dump()),
                        ),
                    )
                    created = cur.fetchone()
                conn.commit()
            return ScannerConfigRecord(
                id=int(created["id"]),
                user_id=user_id,
                config=config,
                updated_at=created.get("updated_at"),
            )
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.get_config(user_id)
            raise

    def update_config(self, user_id: str, config: ScannerConfig) -> ScannerConfigRecord:
        try:
            collectors_payload = json.dumps({"network": True})
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO scan_configs (
                            user_id, network_cidrs, ports, port_preset, collectors, options,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, now())
                        ON CONFLICT (user_id) DO UPDATE
                        SET network_cidrs = EXCLUDED.network_cidrs,
                            ports = EXCLUDED.ports,
                            port_preset = EXCLUDED.port_preset,
                            collectors = EXCLUDED.collectors,
                            options = EXCLUDED.options,
                            updated_at = now()
                        RETURNING id, updated_at
                        """,
                        (
                            user_id,
                            config.network_cidrs,
                            config.ports,
                            config.port_preset,
                            collectors_payload,
                            json.dumps(config.options.model_dump()),
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
            return ScannerConfigRecord(
                id=int(row["id"]),
                user_id=user_id,
                config=config,
                updated_at=row.get("updated_at"),
            )
        except POSTGRES_ERRORS:
            if self._fallback:
                return self._fallback.update_config(user_id, config)
            raise
