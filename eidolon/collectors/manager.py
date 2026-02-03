from __future__ import annotations

from collections.abc import Callable, Iterable

from eidolon.collectors.base import BaseCollector
from eidolon.core.models.event import CollectorEvent


class CollectorManager:
    """Simple in-process collector orchestrator with start/stop hooks."""

    def __init__(self, emit_fn: Callable[[CollectorEvent], None]) -> None:
        self.emit_fn = emit_fn
        self._collectors: dict[str, BaseCollector] = {}

    def register(self, collector: BaseCollector) -> None:
        collector.emit_fn = self.emit_fn
        self._collectors[collector.name] = collector

    def run_all(self) -> list[Exception]:
        errors: list[Exception] = []
        for collector in self._collectors.values():
            try:
                collector.run()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        return errors

    def run_selected(self, names: Iterable[str]) -> list[Exception]:
        errors: list[Exception] = []
        for name in names:
            collector = self._collectors.get(name)
            if collector:
                try:
                    collector.run()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
        return errors

    def list_collectors(self) -> list[str]:
        return list(self._collectors.keys())
