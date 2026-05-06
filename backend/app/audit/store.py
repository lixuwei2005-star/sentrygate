from typing import Protocol

from app.audit.models import AuditEvent


class AuditStore(Protocol):
    def append(self, event: AuditEvent) -> None:
        ...

    def list_events(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        ...


class InMemoryAuditStore:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self._events.append(event)

    def list_events(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        if limit <= 0:
            return []

        events = self._events
        if session_id is not None:
            events = [event for event in events if event.session_id == session_id]

        return list(events[-limit:])
