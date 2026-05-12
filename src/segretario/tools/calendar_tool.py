from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Protocol
from uuid import uuid4


class CalendarClientProtocol(Protocol):
    def list_events(self, *, max_results: int = 10) -> list[dict[str, object]]:
        """List calendar events through a configured client."""


class CalendarTool:
    def __init__(
        self,
        *,
        state_dir: str | Path,
        calendar_client: CalendarClientProtocol | None = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.events_path = self.state_dir / "calendar_events.json"
        self.calendar_client = calendar_client

    def list_events(self) -> list[dict[str, object]]:
        if self.calendar_client is not None:
            return self.calendar_client.list_events()
        return _read_events(self.events_path)

    def create_event(
        self,
        *,
        summary: str,
        when: str,
        attendees: list[str] | None = None,
    ) -> dict[str, object]:
        event = {
            "id": f"event_{uuid4().hex[:12]}",
            "summary": summary,
            "when": when,
            "attendees": attendees or [],
            "created_at": datetime.now(UTC).isoformat(),
        }
        events = _read_events(self.events_path)
        events.append(event)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.events_path.write_text(json.dumps(events, indent=2, sort_keys=True), encoding="utf-8")
        return event


def _read_events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON list")
    return [item for item in raw if isinstance(item, dict)]
