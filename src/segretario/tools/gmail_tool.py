from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4


class GmailTool:
    def __init__(self, *, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)

    def read(self, *, query: str) -> list[dict[str, str]]:
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


def _read_json_list(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON list")
    return [item for item in raw if isinstance(item, dict)]
