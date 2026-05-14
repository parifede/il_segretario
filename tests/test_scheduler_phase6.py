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
            max_tasks_per_cycle=5,
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
        "weekly.lint",
        "periodic.stats",
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
            max_tasks_per_cycle=5,
        ),
    )

    summary = run_scheduler_once(settings, taskboard=taskboard, audit=audit, execute=True)

    assert [item.command for item in summary.executed] == [
        "watch.raw",
        "daily.digest",
        "weekly.lint",
        "periodic.stats",
        "bookmark.review",
    ]
    assert taskboard.acquire_lease(owner="phase6-test", lease_seconds=60) is None
    rows = _task_rows(tmp_path / "state" / "taskboard.sqlite")
    assert rows == [
        ("watch.raw", "completed"),
        ("daily.digest", "completed"),
        ("weekly.lint", "completed"),
        ("periodic.stats", "completed"),
        ("bookmark.review", "completed"),
    ]
    raw_report = (vault / "output" / "watch-raw.md").read_text(encoding="utf-8")
    assert "raw/articles/note.md" in raw_report
    assert "DO_NOT_SCAN" not in raw_report
    assert (vault / "output" / "daily-digest.md").exists()
    assert (vault / "output" / "weekly-lint.md").exists()
    assert (vault / "output" / "periodic-stats.md").exists()
    assert audit.verify() is True


def test_scheduler_execute_ignores_non_scheduler_queued_tasks(tmp_path: Path):
    vault = tmp_path / "vault"
    _make_valid_vault(vault)
    taskboard = TaskboardStore(tmp_path / "state" / "taskboard.sqlite")
    taskboard.initialize()
    taskboard.create_task(
        source="cli",
        requested_by="owner",
        command="mail.send",
        risk="low",
        assigned_agent="cli",
    )
    audit = AuditLog(
        events_path=tmp_path / "state" / "audit" / "events.jsonl",
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    )
    settings = Settings(
        vault=VaultSettings(path=vault),
        scheduler=SchedulerSettings(
            enabled=True,
            raw_watcher_enabled=False,
            daily_digest_enabled=False,
            maintenance_budget_minutes=7,
            max_tasks_per_cycle=1,
        ),
    )

    summary = run_scheduler_once(settings, taskboard=taskboard, audit=audit, execute=True)

    assert [item.command for item in summary.executed] == ["weekly.lint"]
    rows = _task_rows(tmp_path / "state" / "taskboard.sqlite")
    assert ("mail.send", "queued") in rows
    assert ("weekly.lint", "completed") in rows
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
  max_tasks_per_cycle: 5
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["scheduler", "run-once", "--execute"])

    assert result.exit_code == 0
    assert "Scheduled: 5" in result.output
    assert "Executed: 5" in result.output
    assert "watch.raw: completed" in result.output
    assert (vault / "output" / "watch-raw.md").exists()


def test_scheduler_respects_max_tasks_per_cycle_and_schedules_no_high_risk(tmp_path: Path):
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
            maintenance_budget_minutes=10,
            max_tasks_per_cycle=3,
        ),
    )

    summary = run_scheduler_once(settings, taskboard=taskboard, audit=audit)

    assert len(summary.scheduled) == 3
    assert [job.command for job in summary.scheduled] == [
        "watch.raw",
        "watch.inbox",
        "daily.digest",
    ]
    rows = _task_rows(tmp_path / "state" / "taskboard.sqlite")
    assert all(status == "queued" for _command, status in rows)
    assert audit.verify() is True


def test_scheduler_watch_inbox_scans_local_vault_inbox_without_elaborati(tmp_path: Path):
    vault = tmp_path / "vault"
    _make_valid_vault(vault)
    (vault / "inbox").mkdir()
    (vault / "inbox" / "new-note.md").write_text("# New\n", encoding="utf-8")
    (vault / "raw" / "elaborati" / "secret.md").write_text("DO_NOT_SCAN_18", encoding="utf-8")
    taskboard = TaskboardStore(tmp_path / "state" / "taskboard.sqlite")
    audit = AuditLog(
        events_path=tmp_path / "state" / "audit" / "events.jsonl",
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    )
    settings = Settings(
        vault=VaultSettings(path=vault),
        scheduler=SchedulerSettings(
            enabled=True,
            inbox_watcher_enabled=True,
            maintenance_budget_minutes=0,
            max_tasks_per_cycle=1,
        ),
    )

    summary = run_scheduler_once(settings, taskboard=taskboard, audit=audit, execute=True)

    assert [item.command for item in summary.executed] == ["watch.inbox"]
    report = (vault / "output" / "inbox-watch.md").read_text(encoding="utf-8")
    assert "inbox/new-note.md" in report
    assert "DO_NOT_SCAN_18" not in report


def test_scheduler_execution_honors_configured_skip_paths(tmp_path: Path):
    vault = tmp_path / "vault"
    _make_valid_vault(vault)
    (vault / ".pytest_cache").mkdir()
    (vault / ".pytest_cache" / "cache.md").write_text("CACHE_SKIP_TOKEN\n", encoding="utf-8")
    (vault / "output").mkdir()
    (vault / "output" / "old-report.md").write_text("OUTPUT_SKIP_TOKEN\n", encoding="utf-8")
    (vault / "self" / "profile").mkdir(parents=True, exist_ok=True)
    (vault / "self" / "profile" / "profile.md").write_text("SELF_SKIP_TOKEN\n", encoding="utf-8")
    (vault / "raw" / "private").mkdir()
    (vault / "raw" / "private" / "secret.md").write_text("RAW_PRIVATE_SKIP_TOKEN\n", encoding="utf-8")
    (vault / "raw" / "articles" / "visible.md").write_text("# Visible\n", encoding="utf-8")
    taskboard = TaskboardStore(tmp_path / "state" / "taskboard.sqlite")
    audit = AuditLog(
        events_path=tmp_path / "state" / "audit" / "events.jsonl",
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    )
    settings = Settings(
        vault=VaultSettings(
            path=vault,
            skip_paths=["raw/elaborati", "raw/private", ".pytest_cache", "output", "self"],
        ),
        scheduler=SchedulerSettings(
            enabled=True,
            raw_watcher_enabled=True,
            daily_digest_enabled=True,
            maintenance_budget_minutes=7,
            max_tasks_per_cycle=4,
        ),
    )

    summary = run_scheduler_once(settings, taskboard=taskboard, audit=audit, execute=True)

    assert [item.command for item in summary.executed] == [
        "watch.raw",
        "daily.digest",
        "weekly.lint",
        "periodic.stats",
    ]
    raw_report = (vault / "output" / "watch-raw.md").read_text(encoding="utf-8")
    stats_report = (vault / "output" / "periodic-stats.md").read_text(encoding="utf-8")
    assert "raw/articles/visible.md" in raw_report
    assert "raw/private/secret.md" not in raw_report
    assert "RAW_PRIVATE_SKIP_TOKEN" not in raw_report
    assert ".pytest_cache:" not in stats_report
    assert "output:" not in stats_report
    assert "self:" not in stats_report
    assert audit.verify() is True


def test_scheduler_failure_uses_scheduler_cooldown_minutes(tmp_path: Path, monkeypatch):
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
            maintenance_budget_minutes=0,
            cooldown_minutes_after_failure=60,
        ),
    )

    def fail_command(command, settings):
        raise RuntimeError("forced scheduler failure")

    monkeypatch.setattr("segretario.scheduler.jobs._execute_command", fail_command)

    summary = run_scheduler_once(settings, taskboard=taskboard, audit=audit, execute=True)

    assert summary.executed[0].status == "queued"
    task = taskboard.get_task(1)
    assert task is not None
    assert task["status"] == "queued"
    assert task["lease_expires_at"] is not None


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
