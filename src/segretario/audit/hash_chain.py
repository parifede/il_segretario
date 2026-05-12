from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SENSITIVE_KEYS = {
    "apikey",
    "auth",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
}


class AuditLog:
    def __init__(
        self,
        directory: str | Path | None = None,
        *,
        events_path: str | Path | None = None,
        chain_path: str | Path | None = None,
    ):
        if events_path is not None or chain_path is not None:
            if events_path is None or chain_path is None:
                raise ValueError("events_path and chain_path must be provided together")
            self.events_path = Path(events_path)
            self.chain_path = Path(chain_path)
        else:
            if directory is None:
                raise ValueError("directory or explicit audit paths are required")
            audit_dir = Path(directory)
            self.events_path = audit_dir / "events.jsonl"
            self.chain_path = audit_dir / "hash_chain.jsonl"

    def append_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.chain_path.parent.mkdir(parents=True, exist_ok=True)
        sequence = self._next_sequence()
        previous_hash = self._last_entry_hash()
        event = {
            "sequence": sequence,
            "event_type": event_type,
            "payload": _redact(payload),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        event_hash = _digest(event)
        chain_entry = {
            "sequence": sequence,
            "event_hash": event_hash,
            "previous_hash": previous_hash,
        }
        chain_entry["entry_hash"] = _digest(chain_entry)

        with self.events_path.open("a", encoding="utf-8") as events_file:
            events_file.write(_canonical_json(event) + "\n")
        with self.chain_path.open("a", encoding="utf-8") as chain_file:
            chain_file.write(_canonical_json(chain_entry) + "\n")

        return chain_entry

    def verify(self) -> bool:
        events = _read_jsonl(self.events_path)
        chain = _read_jsonl(self.chain_path)
        if len(events) != len(chain):
            return False

        previous_hash = None
        for expected_sequence, (event, entry) in enumerate(zip(events, chain), start=1):
            if event.get("sequence") != expected_sequence:
                return False
            if entry.get("sequence") != expected_sequence:
                return False
            if entry.get("event_hash") != _digest(event):
                return False
            if entry.get("previous_hash") != previous_hash:
                return False

            entry_without_hash = dict(entry)
            entry_hash = entry_without_hash.pop("entry_hash", None)
            if entry_hash != _digest(entry_without_hash):
                return False
            previous_hash = entry_hash

        return True

    def _next_sequence(self) -> int:
        return len(_read_jsonl(self.chain_path)) + 1

    def _last_entry_hash(self) -> str | None:
        entries = _read_jsonl(self.chain_path)
        if not entries:
            return None
        return entries[-1]["entry_hash"]


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(token in normalized for token in SENSITIVE_KEYS)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
