from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_VERSION = 1


class ReindexStateStore:
    """Persists the last recall reindex run info to a JSON file.

    Pattern: identical to BackupStateStore (see src/segretario/backup/state.py).
    File: state/recall_last_run.json
    """

    def __init__(self, state_path: Path) -> None:
        self._path = state_path

    def get_last_run(self) -> datetime | None:
        """Return the datetime of the last successful reindex, or None."""
        data = self._load()
        if data is None:
            return None
        try:
            return datetime.fromisoformat(data["last_run"])
        except (KeyError, ValueError):
            return None

    def set_last_run(self, when: datetime, indexed_count: int, model: str) -> None:
        """Persist the last run metadata."""
        data = {
            "version": _STATE_VERSION,
            "last_run": when.isoformat(),
            "indexed_count": indexed_count,
            "embedding_model": model,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def should_skip(self, now: datetime, threshold_minutes: int) -> bool:
        """Return True if the last run was less than threshold_minutes ago."""
        last = self.get_last_run()
        if last is None:
            return False
        # Normalize to UTC to handle aware/naive datetime mixing
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        elapsed = (now - last).total_seconds() / 60
        return elapsed < threshold_minutes

    def _load(self) -> dict | None:
        """Load state file. Returns None on missing or corrupt file."""
        if not self._path.exists():
            return None
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("ReindexStateStore: corrupt state file %s: %s", self._path, exc)
            return None
