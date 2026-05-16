import json
from pathlib import Path

from pydantic import ValidationError

from app.audit.models import AuditEvent


class JsonlAuditStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, event: AuditEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = event.model_dump(mode="json")
        line = json.dumps(payload, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(f"{line}\n")

    def list_events(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        if limit <= 0 or not self.path.exists():
            return []

        events: list[AuditEvent] = []
        with self.path.open(encoding="utf-8") as audit_file:
            for line in audit_file:
                event = self._event_from_line(line)
                if event is None:
                    continue
                if session_id is not None and event.session_id != session_id:
                    continue
                events.append(event)

        return events[-limit:]

    @staticmethod
    def _event_from_line(line: str) -> AuditEvent | None:
        stripped = line.strip()
        if stripped == "":
            return None

        try:
            data = json.loads(stripped)
            return AuditEvent.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            return None
