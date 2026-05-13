from __future__ import annotations

from pathlib import Path
import sqlite3

from typer.testing import CliRunner

from segretario.audit import AuditLog
from segretario.cli import app


def test_calendar_list_accepts_spec_date_options(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path, scheduler_enabled=False)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    create = runner.invoke(app, ["calendar", "create", "2026-05-13 dentist"])
    assert create.exit_code == 0

    today = runner.invoke(app, ["calendar", "list", "--today"])
    ranged = runner.invoke(
        app,
        ["calendar", "list", "--from", "2026-05-13", "--to", "2026-05-14"],
    )

    assert today.exit_code == 0
    assert "2026-05-13 dentist" in today.output
    assert ranged.exit_code == 0
    assert "2026-05-13 dentist" in ranged.output


def test_calendar_modify_accepts_summary_argument_and_requires_change(
    tmp_path: Path,
    monkeypatch,
):
    config = _write_config(tmp_path, scheduler_enabled=False)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    create = runner.invoke(app, ["calendar", "create", "Original event"])
    event_id = create.output.strip().split("event: ", 1)[1]

    missing_change = runner.invoke(app, ["calendar", "modify", event_id])
    modify = runner.invoke(app, ["calendar", "modify", event_id, "Updated from arg"])

    assert missing_change.exit_code == 1
    assert "calendar.modify requires a summary change" in missing_change.output
    assert modify.exit_code == 1
    assert "calendar.modify requires confirmation" in modify.output
    assert _latest_task_id(tmp_path) == 2


def test_mail_draft_accepts_spec_prompt_argument_with_explicit_fields(
    tmp_path: Path,
    monkeypatch,
):
    config = _write_config(tmp_path, scheduler_enabled=False)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(
        app,
        [
            "mail",
            "draft",
            "Corpo scritto dalla forma prompt della spec",
            "--to",
            "person@example.com",
            "--subject",
            "Spec draft",
        ],
    )

    assert result.exit_code == 0
    assert "draft:" in result.output
    drafts = (tmp_path / "state" / "google" / "gmail_drafts.jsonl").read_text(
        encoding="utf-8"
    )
    assert "Corpo scritto dalla forma prompt della spec" in drafts


def test_mail_draft_prompt_only_creates_local_draft_request(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path, scheduler_enabled=False)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["mail", "draft", "write a reply to the last email"])

    assert result.exit_code == 0
    assert "draft:" in result.output
    drafts = (tmp_path / "state" / "google" / "gmail_drafts.jsonl").read_text(
        encoding="utf-8"
    )
    assert "Draft request" in drafts
    assert "write a reply to the last email" in drafts


def test_mail_send_accepts_approved_task_id_from_spec(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path, scheduler_enabled=False)
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
            "Body",
        ],
    )
    draft_id = draft.output.strip().split("draft: ", 1)[1]
    runner.invoke(app, ["mail", "send", draft_id])
    task_id = _latest_task_id(tmp_path)
    runner.invoke(app, ["approve", str(task_id)])

    result = runner.invoke(app, ["mail", "send", str(task_id)])

    assert result.exit_code == 0
    assert f"task {task_id}: completed" in result.output
    assert _task_status(tmp_path, task_id) == "completed"
    assert _audit(tmp_path).verify() is True


def test_run_maintenance_cli_executes_bounded_maintenance(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path, scheduler_enabled=False)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["run-maintenance"])

    assert result.exit_code == 0
    assert "maintenance.cycle: completed" in result.output
    assert (tmp_path / "vault" / "output" / "maintenance-cycle.md").exists()
    assert _audit(tmp_path).verify() is True


def test_watch_cli_executes_bounded_raw_watch(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path, scheduler_enabled=False)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    raw = tmp_path / "vault" / "raw" / "watch-me.md"
    raw.parent.mkdir(parents=True)
    raw.write_text("# Watch Me", encoding="utf-8")

    result = CliRunner().invoke(app, ["watch"])

    assert result.exit_code == 0
    assert "watch.raw: completed" in result.output
    report = (tmp_path / "vault" / "output" / "watch-raw.md").read_text(encoding="utf-8")
    assert "raw/watch-me.md" in report
    assert _audit(tmp_path).verify() is True


def test_privacy_project_cli_outputs_projection_without_raw_sensitive_values():
    result = CliRunner().invoke(
        app,
        [
            "privacy",
            "project",
            "Mario Rossi email mario.rossi@example.com telefono +39 333 123 4567",
        ],
    )

    assert result.exit_code == 0
    assert "PERSON_TOKEN_A" in result.output
    assert "EMAIL_TOKEN_A" in result.output
    assert "PHONE_TOKEN_A" in result.output
    assert "Mario Rossi" not in result.output
    assert "mario.rossi@example.com" not in result.output


def _write_config(tmp_path: Path, *, scheduler_enabled: bool) -> Path:
    vault = tmp_path / "vault"
    (vault / "meta").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (vault / "meta" / "index.md").write_text("# Index\n", encoding="utf-8")
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: il_segretario
vault:
  path: "{vault.as_posix()}"
llm:
  provider: ollama
  model: "local-test-model"
  base_url: "http://127.0.0.1:9"
taskboard:
  sqlite_path: "{(tmp_path / 'state' / 'taskboard.sqlite').as_posix()}"
audit:
  events_path: "{(tmp_path / 'state' / 'audit' / 'events.jsonl').as_posix()}"
  hash_chain_path: "{(tmp_path / 'state' / 'audit' / 'hash_chain.jsonl').as_posix()}"
google:
  credentials_path: "{(tmp_path / 'secrets' / 'google' / 'credentials.json').as_posix()}"
  token_path: "{(tmp_path / 'secrets' / 'google' / 'token.json').as_posix()}"
scheduler:
  enabled: {str(scheduler_enabled).lower()}
  raw_watcher_enabled: false
  inbox_watcher_enabled: false
  daily_digest_enabled: false
  maintenance_budget_minutes: 5
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
