from pathlib import Path

from typer.testing import CliRunner

from segretario.audit import AuditLog
from segretario.cli import app


def test_audit_verify_cli_reports_ok_for_valid_hash_chain(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    AuditLog(
        events_path=tmp_path / "state" / "audit" / "events.jsonl",
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    ).append_event("task.created", {"task_id": 1, "command": "safe"})

    result = CliRunner().invoke(app, ["audit", "verify"])

    assert result.exit_code == 0
    assert "Audit verify: ok" in result.output


def test_audit_verify_cli_reports_failure_for_tampered_hash_chain(
    tmp_path: Path,
    monkeypatch,
):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    events_path = tmp_path / "state" / "audit" / "events.jsonl"
    AuditLog(
        events_path=events_path,
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    ).append_event("task.created", {"task_id": 1, "command": "safe"})
    events_path.write_text(
        events_path.read_text(encoding="utf-8").replace("safe", "tampered"),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["audit", "verify"])

    assert result.exit_code == 1
    assert "Audit verify: failed" in result.output


def _write_config(tmp_path: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: audit_cli_test
vault:
  path: "{(tmp_path / 'vault').as_posix()}"
  require_agents_md: false
  require_meta_index: false
  require_meta_log: false
  skip_paths:
    - raw/elaborati
taskboard:
  sqlite_path: "{(tmp_path / 'state' / 'taskboard.sqlite').as_posix()}"
audit:
  events_path: "{(tmp_path / 'state' / 'audit' / 'events.jsonl').as_posix()}"
  hash_chain_path: "{(tmp_path / 'state' / 'audit' / 'hash_chain.jsonl').as_posix()}"
""",
        encoding="utf-8",
    )
    return config
