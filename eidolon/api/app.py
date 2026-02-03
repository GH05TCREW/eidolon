from __future__ import annotations

import asyncio
from contextlib import suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from eidolon.api.dependencies import get_audit_store, get_graph_repository
from eidolon.api.handlers import tasks
from eidolon.api.middleware.auth import AuthMiddleware
from eidolon.api.middleware.rate_limit import RateLimitMiddleware
from eidolon.api.routes import (
    agent,
    approvals,
    audit,
    chat,
    collector,
    graph,
    ingest,
    permissions,
    plan,
    query,
)
from eidolon.api.routes import settings as settings_router
from eidolon.config.settings import get_settings
from eidolon.runtime.task_events import task_event_bus
from eidolon.worker.retention import RetentionWorker


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Eidolon API",
        version="0.1.0",
        description="Evidence-backed infrastructure graph and agent runtime.",
    )

    # Add routers first
    app.include_router(query.router)
    app.include_router(plan.router)
    app.include_router(graph.router)
    app.include_router(chat.router)
    app.include_router(collector.router)
    app.include_router(ingest.router)
    app.include_router(permissions.router)
    app.include_router(settings_router.router)
    app.include_router(audit.router)
    app.include_router(approvals.router)
    app.include_router(agent.router)
    app.include_router(tasks.router)

    # Add middleware in reverse order (they execute in reverse)
    # CORS must be added LAST so it executes FIRST
    app.add_middleware(RateLimitMiddleware, capacity=300, window_seconds=60)
    app.add_middleware(AuthMiddleware)

    # CORS middleware LAST = executes FIRST
    # For development: allow all origins without credentials
    # For production: specify exact origins in settings.api.cors_origins
    if "*" in settings.api.cors_origins:
        # Development mode: wildcard origins, no credentials
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
            allow_headers=["*"],
        )
    else:
        # Production mode: specific origins, allow credentials
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
            allow_headers=["*"],
        )

    @app.get("/healthz")
    def health() -> dict:
        return {"status": "ok"}

    @app.on_event("startup")
    async def startup() -> None:
        # Start retention worker to clean up old audit events
        audit_store = get_audit_store()
        retention_worker = RetentionWorker(audit_store, retention_days=90)
        app.state.retention_task = asyncio.create_task(
            retention_worker.run_forever(interval_hours=24)
        )

    @app.on_event("shutdown")
    def shutdown() -> None:
        # Signal task event bus to shutdown streaming connections
        task_event_bus.shutdown()

        # Close graph repository
        with suppress(Exception):
            repo = get_graph_repository()
            close = getattr(repo, "close", None)
            if close:
                close()

    return app


app = create_app()
