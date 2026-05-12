from pathlib import Path
import sqlite3

from typer.testing import CliRunner

from segretario.audit import AuditLog
from segretario.cli import app


def test_tasks_cli_lists_waiting_confirmation_tasks(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()

    runner.invoke(app, ["mail", "send", "draft_test"])
    result = runner.invoke(app, ["tasks"])

    assert result.exit_code == 0
    assert "mail.send" in result.output
    assert "waiting_confirmation" in result.output
    assert "high" in result.output


def test_approve_cli_moves_confirmation_task_to_queue_and_audits(
    tmp_path: Path,
    monkeypatch,
):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    runner.invoke(app, ["mail", "send", "draft_test"])
    task_id = _latest_task_id(tmp_path)

    result = runner.invoke(app, ["approve", str(task_id)])

    assert result.exit_code == 0
    assert f"approved: {task_id}" in result.output
    assert _task_status(tmp_path, task_id) == "queued"
    assert _audit(tmp_path).verify() is True


def test_deny_cli_moves_confirmation_task_to_denied_and_audits(
    tmp_path: Path,
    monkeypatch,
):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    runner.invoke(app, ["calendar", "delete", "event_test"])
    task_id = _latest_task_id(tmp_path)

    result = runner.invoke(app, ["deny", str(task_id), "--reason", "not now"])

    assert result.exit_code == 0
    assert f"denied: {task_id}" in result.output
    assert _task_status(tmp_path, task_id) == "denied"
    assert _audit(tmp_path).verify() is True


def test_deny_cli_rejects_non_confirmation_task(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    runner.invoke(app, ["stats"])
    task_id = _latest_task_id(tmp_path)

    result = runner.invoke(app, ["deny", str(task_id)])

    assert result.exit_code == 1
    assert "not waiting for confirmation" in result.output
    assert _task_status(tmp_path, task_id) == "completed"


def _write_config(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: il_segretario
vault:
  path: "{vault.as_posix()}"
taskboard:
  sqlite_path: "{(tmp_path / 'state' / 'taskboard.sqlite').as_posix()}"
audit:
  events_path: "{(tmp_path / 'state' / 'audit' / 'events.jsonl').as_posix()}"
  hash_chain_path: "{(tmp_path / 'state' / 'audit' / 'hash_chain.jsonl').as_posix()}"
google:
  credentials_path: "{(tmp_path / 'secrets' / 'google' / 'credentials.json').as_posix()}"
  token_path: "{(tmp_path / 'secrets' / 'google' / 'token.json').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config


def _latest_task_id(tmp_path: Path) -> int:
    db = sqlite3.connect(tmp_path / "state" / "taskboard.sqlite")
    return db.execute("select id from tasks order by id desc limit 1").fetchone()[0]


def _task_status(tmp_path: Path, task_id: int) -> str:
    db = sqlite3.connect(tmp_path / "state" / "taskboard.sqlite")
    return db.execute("select status from tasks where id = ?", (task_id,)).fetchone()[0]


def _audit(tmp_path: Path) -> AuditLog:
    return AuditLog(
        events_path=tmp_path / "state" / "audit" / "events.jsonl",
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    )
