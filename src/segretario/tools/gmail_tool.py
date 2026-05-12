from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Protocol
from uuid import uuid4


class GmailClientProtocol(Protocol):
    def search_messages(self, *, query: str) -> list[dict[str, str]]:
        """Search Gmail messages through a configured client."""

    def create_draft(self, *, to: str, subject: str, body: str) -> dict[str, str]:
        """Create a Gmail draft through a configured client."""

    def send_draft(self, *, draft_id: str) -> dict[str, str]:
        """Send a Gmail draft through a configured client."""


class GmailTool:
    def __init__(
        self,
        *,
        state_dir: str | Path,
        google_client: GmailClientProtocol | None = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.google_client = google_client

    def read(self, *, query: str) -> list[dict[str, str]]:
        if self.google_client is not None:
            return self.google_client.search_messages(query=query)

        messages = _read_json_list(self.state_dir / "gmail_messages.json")
        if not query:
            return messages
        if ":" in query:
            key, value = query.split(":", 1)
            key = key.strip()
            needle = value.strip().casefold()
            if key:
                return [
                    message
                    for message in messages
                    if needle in str(message.get(key, "")).casefold()
                ]
        needle = query.casefold()
        return [
            message
            for message in messages
            if needle in json.dumps(message, sort_keys=True).casefold()
        ]

    def create_draft(self, *, to: str, subject: str, body: str) -> dict[str, str]:
        if self.google_client is not None:
            return self.google_client.create_draft(to=to, subject=subject, body=body)

        draft = {
            "id": f"draft_{uuid4().hex[:12]}",
            "to": to,
            "subject": subject,
            "body": body,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with (self.state_dir / "gmail_drafts.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(draft, sort_keys=True) + "\n")
        return draft

    def send_draft(self, *, draft_id: str) -> dict[str, str]:
        if self.google_client is not None:
            return self.google_client.send_draft(draft_id=draft_id)

        sent = {
            "id": f"sent_{uuid4().hex[:12]}",
            "draft_id": draft_id,
            "sent_at": datetime.now(UTC).isoformat(),
        }
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with (self.state_dir / "gmail_sent.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(sent, sort_keys=True) + "\n")
        return sent


def _read_json_list(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON list")
    return [item for item in raw if isinstance(item, dict)]
