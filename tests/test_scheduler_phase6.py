from pathlib import Path

from typer.testing import CliRunner

from segretario.cli import app
from segretario.config.settings import Settings, VaultSettings, SchedulerSettings
from segretario.scheduler.jobs import run_scheduler_once
from segretario.taskboard import TaskboardStore
from segretario.audit import AuditLog
from segretario.vault.preflight import run_vault_preflight


def test_vault_preflight_reports_required_files_and_never_scans_elaborati(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "meta").mkdir(parents=True)
    (vault / "raw" / "elaborati").mkdir(parents=True)
    (vault / "self" / "profile").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
    (vault / "meta" / "index.md").write_text("# Index\n", encoding="utf-8")
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    (vault / "raw" / "elaborati" / "secret.md").write_text("DO_NOT_SCAN_PHASE6", encoding="utf-8")
    (vault / "self" / "profile" / "profile.md").write_text("PRIVATE_PHASE6", encoding="utf-8")

    report = run_vault_preflight(vault, skip_paths=["raw/elaborati"])

    assert report.ok is True
    assert report.required_files == {
        "AGENTS.md": "ok",
        "meta/index.md": "ok",
        "meta/log.md": "ok",
    }
    assert "raw/elaborati" in report.skip_paths
    assert "self/" in report.local_only_paths
    assert "DO_NOT_SCAN_PHASE6" not in "\n".join(report.notes)
    assert "PRIVATE_PHASE6" not in "\n".join(report.notes)


def test_scheduler_run_once_schedules_enabled_jobs_with_budget_and_audit(tmp_path: Path):
    vault = tmp_path / "vault"
    _make_valid_vault(vault)
    taskboard = TaskboardStore(tmp_path / "state" / "taskboard.sqlite")
    audit = AuditLog(
        events_path=tmp_path / "state" / "audit" / "events.jsonl",
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    )
    settings = Settings(
        vault=VaultSettings(path=vault),
        scheduler=SchedulerSettings(
            enabled=True,
            raw_watcher_enabled=True,
            inbox_watcher_enabled=True,
            daily_digest_enabled=True,
            maintenance_budget_minutes=7,
        ),
    )

    summary = run_scheduler_once(settings, taskboard=taskboard, audit=audit)

    assert summary.enabled is True
    assert summary.preflight_ok is True
    assert summary.budget_minutes == 7
    assert [job.command for job in summary.scheduled] == [
        "watch.raw",
        "watch.inbox",
        "daily.digest",
        "maintenance.cycle",
    ]
    assert summary.skipped == []
    assert taskboard.acquire_lease(owner="phase6-test", lease_seconds=60)["command"] == "watch.raw"
    assert audit.verify() is True


def test_scheduler_run_once_execute_finishes_safe_jobs_and_writes_outputs(tmp_path: Path):
    vault = tmp_path / "vault"
    _make_valid_vault(vault)
    (vault / "raw" / "articles" / "note.md").write_text("# Note\n", encoding="utf-8")
    (vault / "raw" / "elaborati" / "secret.md").write_text("DO_NOT_SCAN", encoding="utf-8")
    taskboard = TaskboardStore(tmp_path / "state" / "taskboard.sqlite")
    audit = AuditLog(
        events_path=tmp_path / "state" / "audit" / "events.jsonl",
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    )
    settings = Settings(
        vault=VaultSettings(path=vault),
        scheduler=SchedulerSettings(
            enabled=True,
            raw_watcher_enabled=True,
            daily_digest_enabled=True,
            maintenance_budget_minutes=7,
        ),
    )

    summary = run_scheduler_once(settings, taskboard=taskboard, audit=audit, execute=True)

    assert [item.command for item in summary.executed] == [
        "watch.raw",
        "daily.digest",
        "maintenance.cycle",
    ]
    assert taskboard.acquire_lease(owner="phase6-test", lease_seconds=60) is None
    rows = _task_rows(tmp_path / "state" / "taskboard.sqlite")
    assert rows == [
        ("watch.raw", "completed"),
        ("daily.digest", "completed"),
        ("maintenance.cycle", "completed"),
    ]
    raw_report = (vault / "output" / "watch-raw.md").read_text(encoding="utf-8")
    assert "raw/articles/note.md" in raw_report
    assert "DO_NOT_SCAN" not in raw_report
    assert (vault / "output" / "daily-digest.md").exists()
    assert (vault / "output" / "maintenance-cycle.md").exists()
    assert audit.verify() is True


def test_scheduler_cli_run_once_is_dry_when_disabled(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    _make_valid_vault(vault)
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
scheduler:
  enabled: false
  raw_watcher_enabled: true
  daily_digest_enabled: true
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["scheduler", "run-once"])

    assert result.exit_code == 0
    assert "Scheduler: disabled" in result.output
    assert "Preflight: ok" in result.output
    assert "Scheduled: 0" in result.output


def test_scheduler_cli_execute_runs_scheduled_jobs(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    _make_valid_vault(vault)
    (vault / "raw" / "articles" / "source.md").write_text("# Source\n", encoding="utf-8")
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
scheduler:
  enabled: true
  raw_watcher_enabled: true
  daily_digest_enabled: true
  maintenance_budget_minutes: 3
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["scheduler", "run-once", "--execute"])

    assert result.exit_code == 0
    assert "Scheduled: 3" in result.output
    assert "Executed: 3" in result.output
    assert "watch.raw: completed" in result.output
    assert (vault / "output" / "watch-raw.md").exists()


def _make_valid_vault(vault: Path) -> None:
    (vault / "meta").mkdir(parents=True)
    (vault / "raw" / "articles").mkdir(parents=True)
    (vault / "raw" / "elaborati").mkdir(parents=True)
    (vault / "self").mkdir()
    (vault / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (vault / "meta" / "index.md").write_text("# Index\n", encoding="utf-8")
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")


def _task_rows(db_path: Path) -> list[tuple[str, str]]:
    import sqlite3

    db = sqlite3.connect(db_path)
    return db.execute("select command, status from tasks order by id").fetchall()
