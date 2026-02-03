from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException, Request

from eidolon.config.settings import get_settings
from eidolon.core.graph.neo4j import Neo4jGraphRepository
from eidolon.core.graph.repository import GraphRepository
from eidolon.core.reasoning.entity import EntityResolver
from eidolon.core.reasoning.llm import LiteLLMClient
from eidolon.core.stores import (
    ApprovalStore,
    AuditStore,
    ChatStore,
    InMemoryApprovalStore,
    InMemoryAuditStore,
    InMemoryChatStore,
    InMemoryScannerStore,
    InMemorySettingsStore,
    ScannerStore,
    SettingsStore,
)
from eidolon.db.postgres.store import (
    PostgresApprovalStore,
    PostgresAuditStore,
    PostgresChatStore,
    PostgresScannerStore,
    PostgresSettingsStore,
    postgres_available,
)


@lru_cache(maxsize=1)
def get_graph_repository() -> GraphRepository:
    return Neo4jGraphRepository()


@lru_cache(maxsize=1)
def get_entity_resolver() -> EntityResolver:
    return EntityResolver()


@lru_cache(maxsize=1)
def get_llm_client() -> LiteLLMClient:
    store = get_settings_store()
    app_settings = store.get_app_settings()
    return LiteLLMClient(settings=app_settings.llm)


@lru_cache(maxsize=1)
def get_audit_store() -> AuditStore:
    settings = get_settings()
    fallback = InMemoryAuditStore()
    if postgres_available():
        return PostgresAuditStore(settings.postgres.url, fallback=fallback)
    return fallback


@lru_cache(maxsize=1)
def get_approval_store() -> ApprovalStore:
    settings = get_settings()
    fallback = InMemoryApprovalStore()
    if postgres_available():
        return PostgresApprovalStore(settings.postgres.url, fallback=fallback)
    return fallback


@lru_cache(maxsize=1)
def get_chat_store() -> ChatStore:
    settings = get_settings()
    fallback = InMemoryChatStore()
    if postgres_available():
        return PostgresChatStore(settings.postgres.url, fallback=fallback)
    return fallback


@lru_cache(maxsize=1)
def get_settings_store() -> SettingsStore:
    settings = get_settings()
    if postgres_available():
        return PostgresSettingsStore(settings.postgres.url)
    # Fallback: return in-memory that always returns defaults
    store = InMemorySettingsStore()
    store.update_settings(settings.sandbox)
    return store


@lru_cache(maxsize=1)
def get_scanner_store() -> ScannerStore:
    settings = get_settings()
    fallback = InMemoryScannerStore()
    if postgres_available():
        return PostgresScannerStore(settings.postgres.url, fallback=fallback)
    return fallback


def require_roles(*roles: str):
    def _dependency(request: Request):
        auth_error = getattr(request.state, "auth_error", None)
        if auth_error:
            raise HTTPException(status_code=401, detail=str(auth_error))
        identity = getattr(request.state, "identity", None)
        if not identity:
            raise HTTPException(status_code=403, detail="missing identity")
        if not any(identity.has_role(role) for role in roles):
            raise HTTPException(status_code=403, detail="insufficient role")
        return identity

    return _dependency
