from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from segretario.flow02.session.log import SessionLog
from segretario.flow02.session.manager import Session, SessionManager


def _session(*, hours_ago: float = 0, minutes_inactive: float = 0) -> Session:
    now = datetime.now(timezone.utc)
    opened_at = now - timedelta(hours=hours_ago)
    log = SessionLog(Path("/tmp/dummy.jsonl"))
    s = Session(session_id="s1", opened_at=opened_at, log=log)
    s._last_activity = now - timedelta(minutes=minutes_inactive)
    return s


# ── doppia condizione di chiusura ─────────────────────────────────────────────

def test_session_does_not_close_inactive_less_than_60_min():
    s = _session(hours_ago=25, minutes_inactive=30)
    assert s.should_close() is False


def test_session_does_not_close_open_less_than_24h():
    s = _session(hours_ago=12, minutes_inactive=120)
    assert s.should_close() is False


def test_session_closes_when_both_conditions_met():
    s = _session(hours_ago=25, minutes_inactive=61)
    assert s.should_close() is True


def test_session_closes_at_exact_thresholds():
    s = _session(hours_ago=24, minutes_inactive=60)
    assert s.should_close() is True  # >= significa che i valori esatti chiudono


def test_session_record_activity_resets_inactive_timer():
    s = _session(hours_ago=25, minutes_inactive=90)
    assert s.should_close() is True
    s.record_activity()
    assert s.should_close() is False


# ── SessionManager ────────────────────────────────────────────────────────────

def test_open_session_creates_log_file_path(tmp_path):
    manager = SessionManager(tmp_path / "sessions")
    session = manager.open_session()
    assert session.session_id
    assert session.opened_at is not None


def test_open_session_persists_state(tmp_path):
    sessions_dir = tmp_path / "sessions"
    manager1 = SessionManager(sessions_dir)
    session1 = manager1.open_session()

    manager2 = SessionManager(sessions_dir)
    loaded = manager2.current_session()
    assert loaded is not None
    assert loaded.session_id == session1.session_id


def test_close_session_removes_state(tmp_path):
    sessions_dir = tmp_path / "sessions"
    manager = SessionManager(sessions_dir)
    session = manager.open_session()
    manager.close_session(session)
    manager2 = SessionManager(sessions_dir)
    assert manager2.current_session() is None


def test_current_session_none_when_no_state(tmp_path):
    manager = SessionManager(tmp_path / "sessions")
    assert manager.current_session() is None
