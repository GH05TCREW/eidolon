from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable

from eidolon.core.models.event import CollectorEvent


class BaseCollector(ABC):
    """Base collector interface. Collectors run deterministically and emit normalized events."""

    def __init__(
        self,
        name: str,
        emit_fn: Callable[[CollectorEvent], None] | None = None,
    ) -> None:
        self.name = name
        self.emit_fn = emit_fn

    def emit(self, event: CollectorEvent) -> None:
        if self.emit_fn:
            self.emit_fn(event)

    @abstractmethod
    def collect(self) -> Iterable[CollectorEvent]:
        """Run the collector and return a stream of normalized events."""

    def run(self) -> None:
        """Execute the collector and emit events."""
        for event in self.collect():
            self.emit(event)
