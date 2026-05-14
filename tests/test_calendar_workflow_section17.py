from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from segretario.audit import AuditLog
from segretario.cli import app
from segretario.policies.permissions import PermissionDecision, PermissionKernel


def test_calendar_invitation_responses_require_confirmation_policy():
    assert PermissionKernel.decision_for(PermissionKernel.CALENDAR_ACCEPT) == PermissionDecision.CONFIRM
    assert PermissionKernel.decision_for(PermissionKernel.CALENDAR_DECLINE) == PermissionDecision.CONFIRM


def test_approved_calendar_accept_task_updates_local_event_response(
    tmp_path: Path,
    monkeypatch,
):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    create = runner.invoke(app, ["calendar", "create", "Section17 invitation"])
    event_id = create.output.strip().split("event: ", 1)[1]

    accept = runner.invoke(app, ["calendar", "accept", event_id])
    task_id = _latest_task_id(tmp_path)
    blocked = runner.invoke(app, ["task", "run", str(task_id)])
    approve = runner.invoke(app, ["approve", str(task_id)])
    run = runner.invoke(app, ["task", "run", str(task_id)])

    assert accept.exit_code == 1
    assert "calendar.accept requires confirmation" in accept.output
    assert blocked.exit_code == 1
    assert f"task {task_id} is not queued" in blocked.output
    assert approve.exit_code == 0
    assert run.exit_code == 0
    assert f"task {task_id}: completed" in run.output
    event = _event(tmp_path, event_id)
    assert event["response"] == "accepted"
    assert AuditLog(
        events_path=tmp_path / "state" / "audit" / "events.jsonl",
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    ).verify()


def test_approved_calendar_decline_task_updates_local_event_response(
    tmp_path: Path,
    monkeypatch,
):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    create = runner.invoke(app, ["calendar", "create", "Section17 invitation"])
    event_id = create.output.strip().split("event: ", 1)[1]

    decline = runner.invoke(app, ["calendar", "decline", event_id])
    task_id = _latest_task_id(tmp_path)
    runner.invoke(app, ["approve", str(task_id)])
    run = runner.invoke(app, ["task", "run", str(task_id)])

    assert decline.exit_code == 1
    assert "calendar.decline requires confirmation" in decline.output
    assert run.exit_code == 0
    assert _event(tmp_path, event_id)["response"] == "declined"


def _write_config(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: section17_test
vault:
  path: "{vault.as_posix()}"
taskboard:
  sqlite_path: "{(tmp_path / 'state' / 'taskboard.sqlite').as_posix()}"
audit:
  events_path: "{(tmp_path / 'state' / 'audit' / 'events.jsonl').as_posix()}"
  hash_chain_path: "{(tmp_path / 'state' / 'audit' / 'hash_chain.jsonl').as_posix()}"
google:
  enabled: false
  credentials_path: "{(tmp_path / 'secrets' / 'google' / 'credentials.json').as_posix()}"
  token_path: "{(tmp_path / 'secrets' / 'google' / 'token.json').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config


def _latest_task_id(tmp_path: Path) -> int:
    import sqlite3

    with sqlite3.connect(tmp_path / "state" / "taskboard.sqlite") as connection:
        row = connection.execute("select max(id) from tasks").fetchone()
    return int(row[0])


def _event(tmp_path: Path, event_id: str) -> dict[str, object]:
    events = json.loads((tmp_path / "state" / "google" / "calendar_events.json").read_text())
    return next(event for event in events if event["id"] == event_id)
