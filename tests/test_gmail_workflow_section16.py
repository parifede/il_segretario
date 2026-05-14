from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from segretario.audit import AuditLog
from segretario.cli import app


def test_gmail_workflow_keeps_secrets_gitignored():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "secrets/" in gitignore
    assert "credentials.json" in gitignore
    assert "token.json" in gitignore


def test_mail_draft_body_is_not_written_to_audit_or_wiki(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    secret_body = "SECTION16_PRIVATE_EMAIL_BODY_MUST_NOT_REACH_AUDIT_OR_WIKI"

    result = CliRunner().invoke(
        app,
        [
            "mail",
            "draft",
            "--to",
            "person@example.com",
            "--subject",
            "Section 16",
            "--body",
            secret_body,
        ],
    )

    assert result.exit_code == 0
    assert "draft:" in result.output
    audit_raw = (tmp_path / "state" / "audit" / "events.jsonl").read_text(encoding="utf-8")
    assert secret_body not in audit_raw
    assert AuditLog(
        events_path=tmp_path / "state" / "audit" / "events.jsonl",
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    ).verify()
    assert not (tmp_path / "vault" / "knowledge").exists()
    assert not (tmp_path / "vault" / "self").exists()


def test_mail_mutations_require_confirmation_before_execution(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()

    send = runner.invoke(app, ["mail", "send", "draft_section16"])
    archive = runner.invoke(app, ["mail", "archive", "msg_section16"])
    delete = runner.invoke(app, ["mail", "delete", "msg_section16"])
    tasks = runner.invoke(app, ["tasks", "--limit", "5"])

    assert send.exit_code == 1
    assert archive.exit_code == 1
    assert delete.exit_code == 1
    assert "gmail.send requires confirmation" in send.output
    assert "gmail.archive requires confirmation" in archive.output
    assert "gmail.delete requires confirmation" in delete.output
    assert "mail.send [waiting_confirmation] risk=high" in tasks.output
    assert "mail.archive [waiting_confirmation] risk=high" in tasks.output
    assert "mail.delete [waiting_confirmation] risk=high" in tasks.output
    assert not (tmp_path / "state" / "google" / "gmail_sent.jsonl").exists()
    assert not (tmp_path / "state" / "google" / "gmail_archived.jsonl").exists()
    assert not (tmp_path / "state" / "google" / "gmail_deleted.jsonl").exists()


def _write_config(tmp_path: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: section16_test
vault:
  path: "{(tmp_path / 'vault').as_posix()}"
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
  enabled: false
  credentials_path: "{(tmp_path / 'secrets' / 'google' / 'credentials.json').as_posix()}"
  token_path: "{(tmp_path / 'secrets' / 'google' / 'token.json').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config
