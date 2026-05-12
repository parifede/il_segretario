from pathlib import Path
import sqlite3

from typer.testing import CliRunner

from segretario.audit import AuditLog
from segretario.cli import app


def test_approved_mail_send_task_can_be_run_from_stored_payload(
    tmp_path: Path,
    monkeypatch,
):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    draft = runner.invoke(
        app,
        [
            "mail",
            "draft",
            "--to",
            "person@example.com",
            "--subject",
            "Hello",
            "--body",
            "Draft body",
        ],
    )
    draft_id = draft.output.strip().split("draft: ", 1)[1]
    send = runner.invoke(app, ["mail", "send", draft_id])
    task_id = _latest_task_id(tmp_path)

    approve = runner.invoke(app, ["approve", str(task_id)])
    run = runner.invoke(app, ["task", "run", str(task_id)])

    assert send.exit_code == 1
    assert "gmail.send requires confirmation" in send.output
    assert approve.exit_code == 0
    assert run.exit_code == 0
    assert f"task {task_id}: completed" in run.output
    assert _task_status(tmp_path, task_id) == "completed"
    assert _task_lease_owner(tmp_path, task_id) is None
    assert draft_id in (tmp_path / "state" / "google" / "gmail_sent.jsonl").read_text(
        encoding="utf-8"
    )
    assert _audit(tmp_path).verify() is True


def test_task_run_rejects_waiting_confirmation_task(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    runner.invoke(app, ["mail", "send", "draft_test"])
    task_id = _latest_task_id(tmp_path)

    result = runner.invoke(app, ["task", "run", str(task_id)])

    assert result.exit_code == 1
    assert f"task {task_id} is not queued" in result.output
    assert _task_status(tmp_path, task_id) == "waiting_confirmation"


def test_approved_mail_archive_task_can_be_run_from_stored_payload(
    tmp_path: Path,
    monkeypatch,
):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    archive = runner.invoke(app, ["mail", "archive", "msg_archive_1"])
    task_id = _latest_task_id(tmp_path)

    blocked = runner.invoke(app, ["task", "run", str(task_id)])
    approve = runner.invoke(app, ["approve", str(task_id)])
    run = runner.invoke(app, ["task", "run", str(task_id)])

    assert archive.exit_code == 1
    assert "gmail.archive requires confirmation" in archive.output
    assert blocked.exit_code == 1
    assert f"task {task_id} is not queued" in blocked.output
    assert approve.exit_code == 0
    assert run.exit_code == 0
    assert f"task {task_id}: completed" in run.output
    assert "msg_archive_1" in (
        tmp_path / "state" / "google" / "gmail_archived.jsonl"
    ).read_text(encoding="utf-8")
    assert _audit(tmp_path).verify() is True


def test_approved_mail_delete_task_can_be_run_from_stored_payload(
    tmp_path: Path,
    monkeypatch,
):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    delete = runner.invoke(app, ["mail", "delete", "msg_delete_1"])
    task_id = _latest_task_id(tmp_path)

    approve = runner.invoke(app, ["approve", str(task_id)])
    run = runner.invoke(app, ["task", "run", str(task_id)])

    assert delete.exit_code == 1
    assert "gmail.delete requires confirmation" in delete.output
    assert approve.exit_code == 0
    assert run.exit_code == 0
    assert f"task {task_id}: completed" in run.output
    assert "msg_delete_1" in (tmp_path / "state" / "google" / "gmail_deleted.jsonl").read_text(
        encoding="utf-8"
    )
    assert _audit(tmp_path).verify() is True


def test_approved_calendar_create_with_attendee_can_be_run_from_stored_payload(
    tmp_path: Path,
    monkeypatch,
):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    create = runner.invoke(
        app,
        ["calendar", "create", "Meeting tomorrow", "--attendee", "person@example.com"],
    )
    task_id = _latest_task_id(tmp_path)

    blocked = runner.invoke(app, ["task", "run", str(task_id)])
    approve = runner.invoke(app, ["approve", str(task_id)])
    run = runner.invoke(app, ["task", "run", str(task_id)])

    assert create.exit_code == 1
    assert "calendar.create_with_attendees requires confirmation" in create.output
    assert blocked.exit_code == 1
    assert f"task {task_id} is not queued" in blocked.output
    assert approve.exit_code == 0
    assert run.exit_code == 0
    assert f"task {task_id}: completed" in run.output
    events = (tmp_path / "state" / "google" / "calendar_events.json").read_text(
        encoding="utf-8"
    )
    assert "Meeting tomorrow" in events
    assert "person@example.com" in events
    assert _audit(tmp_path).verify() is True


def test_approved_calendar_delete_task_can_be_run_from_stored_payload(
    tmp_path: Path,
    monkeypatch,
):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    create = runner.invoke(app, ["calendar", "create", "Local event"])
    event_id = create.output.strip().split("event: ", 1)[1]
    delete = runner.invoke(app, ["calendar", "delete", event_id])
    task_id = _latest_task_id(tmp_path)

    blocked = runner.invoke(app, ["task", "run", str(task_id)])
    approve = runner.invoke(app, ["approve", str(task_id)])
    run = runner.invoke(app, ["task", "run", str(task_id)])

    assert delete.exit_code == 1
    assert "calendar.delete requires confirmation" in delete.output
    assert blocked.exit_code == 1
    assert f"task {task_id} is not queued" in blocked.output
    assert approve.exit_code == 0
    assert run.exit_code == 0
    assert f"task {task_id}: completed" in run.output
    events = (tmp_path / "state" / "google" / "calendar_events.json").read_text(
        encoding="utf-8"
    )
    assert event_id not in events
    assert _audit(tmp_path).verify() is True


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


def _task_lease_owner(tmp_path: Path, task_id: int) -> str | None:
    db = sqlite3.connect(tmp_path / "state" / "taskboard.sqlite")
    return db.execute(
        "select lease_owner from tasks where id = ?",
        (task_id,),
    ).fetchone()[0]


def _audit(tmp_path: Path) -> AuditLog:
    return AuditLog(
        events_path=tmp_path / "state" / "audit" / "events.jsonl",
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    )
