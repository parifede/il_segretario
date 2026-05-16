from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from segretario.flow02.session.log import SessionLog


class Session:
    def __init__(
        self,
        session_id: str,
        opened_at: datetime,
        log: SessionLog,
    ) -> None:
        self.session_id = session_id
        self.opened_at = opened_at
        self.log = log
        self._last_activity: datetime = opened_at

    def record_activity(self) -> None:
        self._last_activity = datetime.now(timezone.utc)

    def last_activity(self) -> datetime:
        return self._last_activity

    def hours_since_open(self) -> float:
        return (datetime.now(timezone.utc) - self.opened_at).total_seconds() / 3600

    def minutes_inactive(self) -> float:
        return (datetime.now(timezone.utc) - self._last_activity).total_seconds() / 60

    def should_close(self) -> bool:
        """Chiude solo se ENTRAMBE le condizioni sono vere."""
        return self.hours_since_open() >= 24 and self.minutes_inactive() >= 60


class SessionManager:
    def __init__(self, sessions_dir: Path) -> None:
        self._sessions_dir = sessions_dir
        self._state_path = sessions_dir / "active_session.json"
        self._current: Session | None = None

    def open_session(self) -> Session:
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        session_id = str(uuid.uuid4())
        log_path = self._sessions_dir / f"session_{session_id}.jsonl"
        now = datetime.now(timezone.utc)
        session = Session(session_id=session_id, opened_at=now, log=SessionLog(log_path))
        self._current = session
        self._save(session)
        return session

    def current_session(self) -> Session | None:
        if self._current is None:
            self._load()
        return self._current

    def close_session(self, session: Session) -> None:
        if self._state_path.exists():
            self._state_path.unlink()
        self._current = None

    def _save(self, session: Session) -> None:
        data = {
            "session_id": session.session_id,
            "opened_at": session.opened_at.isoformat(),
            "last_activity": session.last_activity().isoformat(),
            "log_path": str(session.log._path),
        }
        self._state_path.write_text(json.dumps(data), encoding="utf-8")

    def _load(self) -> None:
        if not self._state_path.exists():
            return
        data = json.loads(self._state_path.read_text(encoding="utf-8"))
        log_path = Path(data["log_path"])
        session = Session(
            session_id=data["session_id"],
            opened_at=datetime.fromisoformat(data["opened_at"]),
            log=SessionLog(log_path),
        )
        session._last_activity = datetime.fromisoformat(data["last_activity"])
        self._current = session
