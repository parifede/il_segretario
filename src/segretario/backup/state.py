from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class BackupStateStore:
    """Persiste l'ultimo timestamp di esecuzione per backup periodici.

    Backup `manual` non vengono mai registrati qui: girano sempre senza vincoli.
    Se il file di state è corrotto o illeggibile, logga un warning e si comporta
    come se nessun backup fosse mai stato eseguito (il backup procede).
    """

    KINDS_WITH_GUARD = ("weekly", "monthly")

    def __init__(self, state_path: Path) -> None:
        self._path = state_path

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "backup state file unreadable at %s: %s. "
                "Proceeding as if no previous run was recorded.",
                self._path,
                exc,
            )
            return {}

    def get_last_run(self, kind: str) -> datetime | None:
        data = self._read()
        value = data.get(kind)
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning(
                "backup state has invalid timestamp for kind=%s: %r. Ignoring.",
                kind,
                value,
            )
            return None

    def set_last_run(self, kind: str, when: datetime) -> None:
        if kind not in self.KINDS_WITH_GUARD:
            return
        data = self._read()
        data[kind] = when.isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def should_skip(self, kind: str, now: datetime, threshold_days: int) -> bool:
        """True se l'ultimo run è più recente di threshold_days."""
        if kind not in self.KINDS_WITH_GUARD:
            return False
        last = self.get_last_run(kind)
        if last is None:
            return False
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return (now - last) < timedelta(days=threshold_days)
