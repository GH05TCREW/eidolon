from __future__ import annotations

import ipaddress
import threading
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from eidolon.api.dependencies import (
    get_audit_store,
    get_entity_resolver,
    get_graph_repository,
    get_scanner_store,
    require_roles,
)
from eidolon.api.middleware.auth import IdentityContext
from eidolon.collectors.factory import build_manager
from eidolon.collectors.network import ScanCancelledError
from eidolon.core.graph.repository import GraphRepository
from eidolon.core.models.event import AuditEvent
from eidolon.core.models.scanner import ScannerConfig
from eidolon.core.reasoning.entity import EntityResolver
from eidolon.core.stores import AuditStore, ScannerStore
from eidolon.runtime.task_events import TaskEvent, task_event_bus
from eidolon.worker.ingest import IngestWorker


class CollectorRunResponse(BaseModel):
    task_id: str
    status: str = "started"


class ScanHistoryItem(BaseModel):
    id: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: str
    events_collected: int
    error_message: str | None = None
    config_summary: str | None = None


class ScanHistoryResponse(BaseModel):
    scans: list[ScanHistoryItem]


class CancelScanRequest(BaseModel):
    task_id: str


router = APIRouter(prefix="/collector", tags=["collector"])
_AUDIT_STORE = Depends(get_audit_store)
_SCANNER_STORE = Depends(get_scanner_store)
_GRAPH_REPOSITORY = Depends(get_graph_repository)
_ENTITY_RESOLVER = Depends(get_entity_resolver)
_VIEWER_IDENTITY = Depends(require_roles("viewer", "planner", "executor"))
_PLANNER_EXECUTOR_IDENTITY = Depends(require_roles("planner", "executor"))


PORT_PRESET_PORTS: dict[str, list[int]] = {
    "fast": [80, 443],
    "normal": [
        21,
        22,
        23,
        25,
        53,
        80,
        110,
        143,
        443,
        465,
        587,
        993,
        995,
        3306,
        3389,
        5432,
        8080,
        8443,
    ],
}
VALID_PORT_PRESETS = {"fast", "normal", "full", "custom"}


class _ScanRegistry:
    def __init__(self) -> None:
        self._active: set[str] = set()
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    def register(self, task_id: str) -> None:
        with self._lock:
            self._active.add(task_id)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._active:
                self._cancelled.add(task_id)
                return True
            return False

    def is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._cancelled

    def clear(self, task_id: str) -> None:
        with self._lock:
            self._active.discard(task_id)
            self._cancelled.discard(task_id)


_scan_registry = _ScanRegistry()


def _parse_target_range(value: str) -> tuple[int, int]:
    if "/" in value:
        network = ipaddress.ip_network(value, strict=False)
        if network.version != 4:
            raise ValueError("Only IPv4 targets are supported")
        return int(network.network_address), int(network.broadcast_address)

    if "-" in value:
        start_str, end_str = value.split("-", 1)
        start_ip = ipaddress.ip_address(start_str)
        if start_ip.version != 4:
            raise ValueError("Only IPv4 targets are supported")
        if "." in end_str:
            end_ip = ipaddress.ip_address(end_str)
        else:
            parts = start_str.split(".")
            if len(parts) != 4:
                raise ValueError("Invalid IP range")
            end_ip = ipaddress.ip_address(".".join([*parts[:3], end_str]))
        if end_ip.version != 4:
            raise ValueError("Only IPv4 targets are supported")
        start_val = int(start_ip)
        end_val = int(end_ip)
        if end_val < start_val:
            raise ValueError("Range end must be greater than start")
        return start_val, end_val

    ip_val = ipaddress.ip_address(value)
    if ip_val.version != 4:
        raise ValueError("Only IPv4 targets are supported")
    ip_int = int(ip_val)
    return ip_int, ip_int


def _validate_targets(targets: list[str]) -> None:
    if not targets:
        raise HTTPException(status_code=422, detail="At least one target is required")
    if len(targets) > 50:
        raise HTTPException(status_code=422, detail="Maximum of 50 targets allowed")
    normalized = [target.strip() for target in targets if target.strip()]
    if len(set(normalized)) != len(normalized):
        raise HTTPException(status_code=422, detail="Duplicate targets are not allowed")

    ranges = []
    for target in normalized:
        try:
            start, end = _parse_target_range(target)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        ranges.append((start, end, target))

    ranges.sort(key=lambda item: item[0])
    for idx in range(1, len(ranges)):
        _prev_start, prev_end, prev_target = ranges[idx - 1]
        curr_start, _curr_end, curr_target = ranges[idx]
        if curr_start <= prev_end:
            raise HTTPException(
                status_code=422,
                detail=f"Target {curr_target} overlaps {prev_target}",
            )


def _validate_ports(port_preset: str, ports: list[int]) -> list[int]:
    if port_preset not in VALID_PORT_PRESETS:
        raise HTTPException(status_code=422, detail="Invalid port preset")

    if port_preset in PORT_PRESET_PORTS:
        return PORT_PRESET_PORTS[port_preset]

    if port_preset == "full":
        return []

    if not ports:
        raise HTTPException(status_code=422, detail="Custom ports are required")

    seen: set[int] = set()
    normalized: list[int] = []
    for port in ports:
        if not isinstance(port, int):
            raise HTTPException(status_code=422, detail="Ports must be integers")
        if port < 1 or port > 65535:
            raise HTTPException(status_code=422, detail="Ports must be between 1 and 65535")
        if port in seen:
            raise HTTPException(status_code=422, detail="Duplicate ports are not allowed")
        seen.add(port)
        normalized.append(port)

    if len(normalized) > 1000:
        raise HTTPException(status_code=422, detail="Maximum of 1000 ports allowed")

    return normalized


def _normalize_config(config: ScannerConfig) -> ScannerConfig:
    config.network_cidrs = [target.strip() for target in config.network_cidrs if target.strip()]
    _validate_targets(config.network_cidrs)

    config.ports = _validate_ports(config.port_preset, config.ports)

    return config


def _format_config_summary(config: ScannerConfig) -> str:
    targets = ", ".join(config.network_cidrs)
    if config.port_preset == "full":
        port_label = "ports 1-65535"
    elif config.ports:
        head = ",".join(str(port) for port in config.ports[:5])
        port_label = f"ports {head}{'...' if len(config.ports) > 5 else ''}"
    else:
        port_label = "ports none"
    return " ".join([part for part in [targets, port_label] if part]).strip()


def _build_scan_config(config: ScannerConfig) -> dict:
    return {
        "network": {
            "cidrs": config.network_cidrs,
            "ping_concurrency": config.options.ping_concurrency,
            "port_scan_workers": config.options.port_scan_workers,
            "ports": config.ports,
            "port_preset": config.port_preset,
            "dns_resolution": config.options.dns_resolution,
            "aggressive": config.options.aggressive,
        }
    }


def _run_scan_sync(
    task_id: str,
    config: dict,
    config_summary: str,
    repository: GraphRepository,
    resolver: EntityResolver,
    audit_store: AuditStore,
) -> None:
    """Synchronous scan logic that runs in background."""
    worker = IngestWorker(repository, resolver)

    # Track stats per collector
    collector_stats: dict[str, dict] = {}
    current_collector: str | None = None

    def emit_fn(event) -> None:
        nonlocal current_collector
        if current_collector:
            stats = collector_stats[current_collector]
            stats["events_processed"] += 1
            # Track entity types
            entity_type = event.entity_type
            stats["by_type"][entity_type] = stats["by_type"].get(entity_type, 0) + 1
        worker.process_event(event)

    def progress_fn(line: str) -> None:
        """Publish scan progress output to event bus."""
        task_event_bus.publish(
            TaskEvent(
                event_type="collector.scan",
                status="progress",
                payload={"task_id": task_id, "output": line},
            )
        )

    try:
        manager = build_manager(
            config,
            emit_fn,
            cancellation_checker=lambda: _scan_registry.is_cancelled(task_id),
            progress_callback=progress_fn,
        )
        collectors = manager.list_collectors()

        # Initialize stats for each collector
        for name in collectors:
            collector_stats[name] = {
                "events_processed": 0,
                "by_type": {},
                "status": "pending",
            }

        # Emit scan start events
        audit_store.add(
            AuditEvent(
                event_type="collector.scan.started",
                details={
                    "collectors": collectors,
                    "task_id": task_id,
                    "config_summary": config_summary,
                },
                status="running",
            )
        )
        task_event_bus.publish(
            TaskEvent(
                event_type="collector.scan",
                status="started",
                payload={"collectors": collectors, "task_id": task_id},
            )
        )

        # Run each collector and track results
        errors: list[Exception] = []
        for collector_name in collectors:
            if _scan_registry.is_cancelled(task_id):
                audit_store.add(
                    AuditEvent(
                        event_type="collector.scan.cancelled",
                        details={"task_id": task_id, "config_summary": config_summary},
                        status="cancelled",
                    )
                )
                task_event_bus.publish(
                    TaskEvent(
                        event_type="collector.scan",
                        status="cancelled",
                        payload={"task_id": task_id},
                    )
                )
                return

            current_collector = collector_name
            collector = manager._collectors[collector_name]

            # Publish task event for this collector starting
            task_event_bus.publish(
                TaskEvent(
                    event_type="collector.scan",
                    status="running",
                    payload={"current_collector": collector_name, "task_id": task_id},
                )
            )

            try:
                collector.run()
                collector_stats[collector_name]["status"] = "ok"

                # Emit per-collector audit event
                stats = collector_stats[collector_name]
                audit_store.add(
                    AuditEvent(
                        event_type=f"collector.{collector_name}",
                        details={
                            "events_processed": stats["events_processed"],
                            "by_type": stats["by_type"],
                            "task_id": task_id,
                        },
                        status="ok",
                    )
                )

                # Publish task event for collector completion
                task_event_bus.publish(
                    TaskEvent(
                        event_type="collector.scan",
                        status="progress",
                        payload={
                            "collector": collector_name,
                            "events_processed": stats["events_processed"],
                            "task_id": task_id,
                        },
                    )
                )
            except ScanCancelledError:
                # Scan was cancelled during this collector
                collector_stats[collector_name]["status"] = "cancelled"
                audit_store.add(
                    AuditEvent(
                        event_type="collector.scan.cancelled",
                        details={
                            "task_id": task_id,
                            "config_summary": config_summary,
                            "collector": collector_name,
                        },
                        status="cancelled",
                    )
                )
                task_event_bus.publish(
                    TaskEvent(
                        event_type="collector.scan",
                        status="cancelled",
                        payload={"task_id": task_id, "collector": collector_name},
                    )
                )
                return
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
                collector_stats[collector_name]["status"] = "failed"
                collector_stats[collector_name]["error"] = str(exc)
                events_processed = collector_stats[collector_name]["events_processed"]

                audit_store.add(
                    AuditEvent(
                        event_type=f"collector.{collector_name}",
                        details={
                            "events_processed": events_processed,
                            "error": str(exc),
                            "task_id": task_id,
                        },
                        status="failed",
                    )
                )

        current_collector = None
        total_events = sum(stats["events_processed"] for stats in collector_stats.values())
        if errors and total_events == 0:
            status = "failed"
        elif errors:
            status = "partial"
        else:
            status = "complete"

        audit_store.add(
            AuditEvent(
                event_type="collector.scan.complete",
                details={
                    "collectors": collectors,
                    "total_events": total_events,
                    "collector_stats": collector_stats,
                    "errors": [str(err) for err in errors],
                    "task_id": task_id,
                    "config_summary": config_summary,
                    "status": status,
                },
                status=(
                    "ok"
                    if status == "complete"
                    else "failed" if status == "failed" else "partial_failure"
                ),
            )
        )
        task_event_bus.publish(
            TaskEvent(
                event_type="collector.scan",
                status="complete" if status == "complete" else status,
                payload={
                    "collectors": collectors,
                    "total_events": total_events,
                    "errors": [str(err) for err in errors],
                    "task_id": task_id,
                },
            )
        )
    except Exception as exc:  # noqa: BLE001
        audit_store.add(
            AuditEvent(
                event_type="collector.scan.failed",
                details={"error": str(exc), "task_id": task_id, "config_summary": config_summary},
                status="failed",
            )
        )
        task_event_bus.publish(
            TaskEvent(
                event_type="collector.scan",
                status="failed",
                payload={"error": str(exc), "task_id": task_id},
            )
        )
    finally:
        _scan_registry.clear(task_id)


@router.get("/config", response_model=ScannerConfig)
async def get_config(
    scanner_store: ScannerStore = _SCANNER_STORE,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> ScannerConfig:
    record = scanner_store.get_config(identity.user_id)
    return record.config


@router.put("/config", response_model=ScannerConfig)
async def update_config(
    payload: dict,
    scanner_store: ScannerStore = _SCANNER_STORE,
    identity: IdentityContext = _PLANNER_EXECUTOR_IDENTITY,
) -> ScannerConfig:
    try:
        config = ScannerConfig.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    config = _normalize_config(config)
    record = scanner_store.update_config(identity.user_id, config)
    return record.config


@router.get("/scan/history", response_model=ScanHistoryResponse)
async def scan_history(
    limit: int = 10,
    audit_store: AuditStore = _AUDIT_STORE,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> ScanHistoryResponse:
    """Get scan history from audit log instead of separate scan_runs table."""
    # Query audit events for scan completions
    events = audit_store.list_filtered(
        page=1,
        page_size=limit,
        event_type="collector.scan.complete",
    )

    scans = []
    for event in events:
        details = event.details or {}
        scans.append(
            ScanHistoryItem(
                id=str(event.audit_id),
                started_at=event.timestamp,
                completed_at=event.timestamp,
                status=details.get("status", "complete"),
                events_collected=details.get("total_events", 0),
                error_message=(
                    "; ".join(details.get("errors", [])) if details.get("errors") else None
                ),
                config_summary=details.get("config_summary"),
            )
        )

    return ScanHistoryResponse(scans=scans)


@router.post("/scan", response_model=CollectorRunResponse)
async def trigger_scan(
    background_tasks: BackgroundTasks,
    repository: GraphRepository = _GRAPH_REPOSITORY,
    resolver: EntityResolver = _ENTITY_RESOLVER,
    audit_store: AuditStore = _AUDIT_STORE,
    scanner_store: ScannerStore = _SCANNER_STORE,
    identity: IdentityContext = _PLANNER_EXECUTOR_IDENTITY,
) -> CollectorRunResponse:
    """Start a network scan in the background and return immediately."""
    task_id = str(uuid4())
    record = scanner_store.get_config(identity.user_id)
    config = _normalize_config(record.config)
    config_summary = _format_config_summary(config)

    _scan_registry.register(task_id)

    # Schedule background task
    background_tasks.add_task(
        _run_scan_sync,
        task_id=task_id,
        config=_build_scan_config(config),
        config_summary=config_summary,
        repository=repository,
        resolver=resolver,
        audit_store=audit_store,
    )

    return CollectorRunResponse(
        task_id=task_id,
        status="started",
    )


@router.post("/scan/cancel")
async def cancel_scan(
    payload: CancelScanRequest,
    identity: IdentityContext = _PLANNER_EXECUTOR_IDENTITY,
) -> dict:
    if not _scan_registry.cancel(payload.task_id):
        raise HTTPException(status_code=404, detail="Scan not found")
    task_event_bus.publish(
        TaskEvent(
            event_type="collector.scan",
            status="cancelling",
            payload={"task_id": payload.task_id, "user_id": identity.user_id},
        )
    )
    return {"status": "cancelling"}
