from __future__ import annotations

from collections.abc import Callable

from eidolon.collectors.manager import CollectorManager
from eidolon.collectors.network import NetworkCollector
from eidolon.core.models.event import CollectorEvent


def build_manager(
    config: dict,
    emit_fn,
    cancellation_checker: Callable[[], bool] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> CollectorManager:
    manager = CollectorManager(emit_fn=emit_fn)
    network_cfg: dict | None = config.get("network")
    if network_cfg is None:
        return manager

    manager.register(
        NetworkCollector(
            cidrs=network_cfg.get("cidrs", []),
            ping_concurrency=network_cfg.get("ping_concurrency", 64),
            port_scan_workers=network_cfg.get("port_scan_workers", 32),
            ports=network_cfg.get("ports"),
            port_preset=network_cfg.get("port_preset"),
            dns_resolution=network_cfg.get("dns_resolution", True),
            aggressive=network_cfg.get("aggressive", False),
            nmap_path=network_cfg.get("nmap_path", "nmap"),
            cancellation_checker=cancellation_checker,
            progress_callback=progress_callback,
        )
    )

    return manager


def collect_once(config: dict, emit_fn) -> int:
    events: list[CollectorEvent] = []

    def _emit(event: CollectorEvent) -> None:
        events.append(event)
        emit_fn(event)

    manager = build_manager(config, _emit)
    manager.run_all()
    return len(events)
