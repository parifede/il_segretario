from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class SessionLog:
    """JSONL append-only: ogni entry è immutabile dopo scrittura."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def append(
        self,
        *,
        session_id: str,
        role: str,
        content_ref: str,
        internal_request_id: str | None = None,
    ) -> dict:
        entry = {
            "message_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "role": role,
            "content_ref": content_ref,
            "internal_request_id": internal_request_id,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self) -> list[dict]:
        if not self._path.exists():
            return []
        return [
            json.loads(line)
            for line in self._path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def to_chat_md(self) -> str:
        """Proiezione human-readable del log JSONL."""
        lines = ["# Chat log\n"]
        for e in self.entries():
            ts = e.get("timestamp", "")[:19]
            role = e.get("role", "?")
            ref = e.get("content_ref", "")
            lines.append(f"**[{ts}] {role}:** {ref}\n")
        return "\n".join(lines)
