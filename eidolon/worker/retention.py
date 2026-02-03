"""Retention policy worker for cleaning up old audit events."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from eidolon.core.stores import AuditStore


class RetentionWorker:
    """Periodically clean up old audit events based on retention policy."""

    def __init__(self, audit_store: AuditStore, retention_days: int = 90) -> None:
        self.audit_store = audit_store
        self.retention_days = retention_days
        self._running = False

    async def run_forever(self, interval_hours: int = 24) -> None:
        """Run retention cleanup every interval_hours."""
        self._running = True
        while self._running:
            try:
                deleted = self.cleanup()
                if deleted > 0:
                    print(
                        "[RetentionWorker] Deleted "
                        f"{deleted} events older than {self.retention_days} days"
                    )
            except Exception as e:  # noqa: BLE001
                print(f"[RetentionWorker] Error during cleanup: {e}")

            # Sleep for interval
            await asyncio.sleep(interval_hours * 3600)

    def cleanup(self) -> int:
        """Delete events older than retention period. Returns count deleted."""
        cutoff_date = datetime.now() - timedelta(days=self.retention_days)
        return self.audit_store.delete_older_than(cutoff_date)

    def stop(self) -> None:
        """Stop the retention worker."""
        self._running = False
