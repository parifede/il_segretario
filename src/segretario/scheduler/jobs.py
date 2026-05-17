from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from segretario.audit import AuditLog
from segretario.config.settings import Settings
from segretario.policies.permissions import PermissionDecision, PermissionKernel
from segretario.taskboard import TaskStatus, TaskboardStore
from segretario.vault.health import lint_vault, vault_stats
from segretario.vault.paths import classify_vault_path, matches_configured_skip_path
from segretario.vault.preflight import VaultPreflightReport, run_vault_preflight


@dataclass(frozen=True)
class SchedulerJob:
    command: str
    action: str
    risk: str
    reason: str


@dataclass(frozen=True)
class SchedulerExecutionResult:
    command: str
    status: str
    output_ref: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class SchedulerRunSummary:
    enabled: bool
    preflight_ok: bool
    budget_minutes: int
    scheduled: list[SchedulerJob]
    executed: list[SchedulerExecutionResult]
    skipped: list[str]
    preflight: VaultPreflightReport


def run_scheduler_once(
    settings: Settings,
    *,
    taskboard: TaskboardStore,
    audit: AuditLog,
    execute: bool = False,
    candidate_jobs: list[SchedulerJob] | None = None,
) -> SchedulerRunSummary:
    """Schedule one bounded maintenance pass; never runs an uncontrolled loop."""

    taskboard.initialize()
    preflight = run_vault_preflight(
        settings.vault.path,
        skip_paths=settings.vault.skip_paths,
    )
    audit.append_event(
        "scheduler.preflight",
        {
            "vault": str(settings.vault.path),
            "ok": preflight.ok,
            "skip_paths": preflight.skip_paths,
        },
    )

    scheduled: list[SchedulerJob] = []
    skipped: list[str] = []

    if not settings.scheduler.enabled:
        return SchedulerRunSummary(
            enabled=False,
            preflight_ok=preflight.ok,
            budget_minutes=settings.scheduler.maintenance_budget_minutes,
            scheduled=scheduled,
            executed=[],
            skipped=skipped,
            preflight=preflight,
        )

    if not preflight.ok:
        skipped.append("preflight failed")
        return SchedulerRunSummary(
            enabled=True,
            preflight_ok=False,
            budget_minutes=settings.scheduler.maintenance_budget_minutes,
            scheduled=scheduled,
            executed=[],
            skipped=skipped,
            preflight=preflight,
        )

    max_tasks = max(settings.scheduler.max_tasks_per_cycle, 0)
    jobs = candidate_jobs if candidate_jobs is not None else _candidate_jobs(settings)
    for job in jobs:
        if len(scheduled) >= max_tasks:
            break
        decision = PermissionKernel.decision_for(job.action)
        if decision != PermissionDecision.ALLOW:
            skipped.append(f"{job.command}: permission {decision.value}")
            continue
        if taskboard.has_active_command(job.command):
            skipped.append(f"{job.command}: already queued or running")
            continue
        task = taskboard.create_task(
            source="scheduler",
            requested_by="segretario",
            command=job.command,
            risk=job.risk,
            assigned_agent="scheduler",
            input_ref=job.reason,
        )
        audit.append_event(
            "scheduler.task_scheduled",
            {
                "task_id": task["id"],
                "command": job.command,
                "action": job.action,
                "reason": job.reason,
            },
        )
        scheduled.append(job)

    executed = (
        _execute_scheduled_tasks(settings, taskboard=taskboard, audit=audit)
        if execute
        else []
    )

    return SchedulerRunSummary(
        enabled=True,
        preflight_ok=True,
        budget_minutes=settings.scheduler.maintenance_budget_minutes,
        scheduled=scheduled,
        executed=executed,
        skipped=skipped,
        preflight=preflight,
    )


def _candidate_jobs(settings: Settings) -> list[SchedulerJob]:
    jobs: list[SchedulerJob] = []
    if settings.scheduler.raw_watcher_enabled:
        jobs.append(
            SchedulerJob(
                command="watch.raw",
                action=PermissionKernel.KNOWLEDGE_WRITE,
                risk="low",
                reason="scan raw inbox excluding configured skip paths",
            )
        )
    if settings.scheduler.inbox_watcher_enabled:
        jobs.append(
            SchedulerJob(
                command="watch.inbox",
                action=PermissionKernel.OUTPUT_WRITE,
                risk="low",
                reason="scan local inbox folder excluding configured skip paths",
            )
        )
    if settings.scheduler.daily_digest_enabled:
        jobs.append(
            SchedulerJob(
                command="daily.digest",
                action=PermissionKernel.OUTPUT_WRITE,
                risk="low",
                reason="prepare local daily digest output",
            )
        )
    if settings.backup.enabled:
        jobs.append(
            SchedulerJob(
                command="vault.backup_weekly",
                action=PermissionKernel.OUTPUT_WRITE,
                risk="low",
                reason="weekly vault backup with rolling retention",
            )
        )
        jobs.append(
            SchedulerJob(
                command="vault.backup_monthly",
                action=PermissionKernel.OUTPUT_WRITE,
                risk="low",
                reason="monthly vault backup with rolling retention",
            )
        )
    if settings.recall.enabled:
        jobs.append(
            SchedulerJob(
                command="recall.reindex",
                action=PermissionKernel.OUTPUT_WRITE,
                risk="low",
                reason="periodic recall reindex to keep semantic search up to date",
            )
        )
    if settings.scheduler.maintenance_budget_minutes > 0:
        budget = settings.scheduler.maintenance_budget_minutes
        jobs.extend(
            [
                SchedulerJob(
                    command="weekly.lint",
                    action=PermissionKernel.OUTPUT_WRITE,
                    risk="low",
                    reason=f"weekly lint within bounded maintenance budget {budget} minutes",
                ),
                SchedulerJob(
                    command="periodic.stats",
                    action=PermissionKernel.OUTPUT_WRITE,
                    risk="low",
                    reason=f"periodic stats within bounded maintenance budget {budget} minutes",
                ),
                SchedulerJob(
                    command="bookmark.review",
                    action=PermissionKernel.OUTPUT_WRITE,
                    risk="low",
                    reason=f"bookmark review within bounded maintenance budget {budget} minutes",
                ),
                SchedulerJob(
                    command="stale_stub.review",
                    action=PermissionKernel.OUTPUT_WRITE,
                    risk="low",
                    reason=f"stale stub review within bounded maintenance budget {budget} minutes",
                ),
                SchedulerJob(
                    command="orphan_page.review",
                    action=PermissionKernel.OUTPUT_WRITE,
                    risk="low",
                    reason=f"orphan page review within bounded maintenance budget {budget} minutes",
                ),
            ]
        )
    return jobs


def _execute_scheduled_tasks(
    settings: Settings,
    *,
    taskboard: TaskboardStore,
    audit: AuditLog,
) -> list[SchedulerExecutionResult]:
    lease_seconds = max(settings.taskboard.lease_minutes, 1) * 60
    max_jobs = max(settings.scheduler.max_tasks_per_cycle, 0)
    executed: list[SchedulerExecutionResult] = []

    for _ in range(max_jobs):
        task = taskboard.acquire_lease_for_commands(
            owner="scheduler",
            lease_seconds=lease_seconds,
            commands=_scheduler_commands(),
        )
        if task is None:
            break
        command = str(task["command"])
        try:
            output_ref = _execute_command(command, settings)
        except Exception as exc:
            failed_task = taskboard.record_failure(
                int(task["id"]),
                error=str(exc),
                max_retries=settings.taskboard.max_retries,
                cooldown_seconds=max(settings.scheduler.cooldown_minutes_after_failure, 0) * 60,
            )
            audit.append_event(
                "scheduler.task_failed",
                {"task_id": task["id"], "command": command, "error": str(exc)},
            )
            executed.append(
                SchedulerExecutionResult(
                    command=command,
                    status=str(failed_task["status"]),
                    error=str(exc),
                )
            )
            continue

        taskboard.complete_task(int(task["id"]), output_ref=output_ref)
        audit.append_event(
            "scheduler.task_completed",
            {"task_id": task["id"], "command": command, "output": output_ref},
        )
        executed.append(
            SchedulerExecutionResult(
                command=command,
                status=TaskStatus.COMPLETED.value,
                output_ref=output_ref,
            )
        )

    return executed


def _scheduler_commands() -> set[str]:
    return {
        "watch.raw",
        "watch.inbox",
        "daily.digest",
        "weekly.lint",
        "periodic.stats",
        "bookmark.review",
        "stale_stub.review",
        "orphan_page.review",
        "maintenance.cycle",
        "vault.backup_weekly",
        "vault.backup_monthly",
        "recall.reindex",
    }


def _execute_command(command: str, settings: Settings) -> str:
    if command == "watch.raw":
        return _write_raw_watch(settings)
    if command == "watch.inbox":
        return _write_inbox_watch(settings)
    if command == "daily.digest":
        return _write_daily_digest(settings)
    if command == "weekly.lint":
        return _write_weekly_lint(settings)
    if command == "periodic.stats":
        return _write_periodic_stats(settings)
    if command == "bookmark.review":
        return _write_bookmark_review(settings)
    if command == "stale_stub.review":
        return _write_filtered_lint_review(
            settings,
            relative_report="output/stale-stub-review.md",
            title="Stale Stub Review",
            needle="stale stub",
            empty_message="no stale stubs found",
        )
    if command == "orphan_page.review":
        return _write_filtered_lint_review(
            settings,
            relative_report="output/orphan-page-review.md",
            title="Orphan Page Review",
            needle="orphan",
            empty_message="no orphan pages found",
        )
    if command == "maintenance.cycle":
        return _write_maintenance_cycle(settings)
    if command == "vault.backup_weekly":
        return _run_vault_backup(settings, kind="weekly")
    if command == "vault.backup_monthly":
        return _run_vault_backup(settings, kind="monthly")
    if command == "recall.reindex":
        return _run_recall_reindex(settings)
    raise ValueError(f"unsupported scheduler task: {command}")


def _write_raw_watch(settings: Settings) -> str:
    vault = Path(settings.vault.path)
    raw_dir = vault / "raw"
    candidates: list[str] = []
    if raw_dir.exists():
        for path in sorted(raw_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(vault).as_posix()
            if _should_skip(relative, settings):
                continue
            candidates.append(relative)

    relative_report = "output/watch-raw.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Raw Watch", ""]
    if candidates:
        lines.extend(f"- {item}" for item in candidates)
    else:
        lines.append("- no raw inbox files")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return relative_report


def _write_inbox_watch(settings: Settings) -> str:
    vault = Path(settings.vault.path)
    inbox_dir = vault / "inbox"
    candidates: list[str] = []
    if inbox_dir.exists():
        for path in sorted(inbox_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(vault).as_posix()
            if _should_skip(relative, settings):
                continue
            candidates.append(relative)

    relative_report = "output/inbox-watch.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Inbox Watch", ""]
    if candidates:
        lines.extend(f"- {item}" for item in candidates)
    else:
        lines.append("- no local inbox files")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return relative_report


def _write_daily_digest(settings: Settings) -> str:
    vault = Path(settings.vault.path)
    stats = vault_stats(vault, skip_paths=settings.vault.skip_paths)
    recent_log = _tail_lines(vault / "meta" / "log.md", limit=10)
    relative_report = "output/daily-digest.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Daily Digest",
        "",
        f"- date: {date.today().isoformat()}",
        f"- total_markdown: {stats.total_markdown}",
        "",
        "## Recent Log",
    ]
    lines.extend(f"- {line}" for line in recent_log) if recent_log else lines.append("- none")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return relative_report


def _write_maintenance_cycle(settings: Settings) -> str:
    vault = Path(settings.vault.path)
    stats = vault_stats(vault, skip_paths=settings.vault.skip_paths)
    lint = lint_vault(vault, skip_paths=settings.vault.skip_paths)
    relative_report = "output/maintenance-cycle.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Maintenance Cycle",
        "",
        f"- total_markdown: {stats.total_markdown}",
        f"- lint_report: {lint.path}",
        f"- lint_issues: {len(lint.issues)}",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return relative_report


def _write_weekly_lint(settings: Settings) -> str:
    vault = Path(settings.vault.path)
    lint = lint_vault(vault, skip_paths=settings.vault.skip_paths)
    relative_report = "output/weekly-lint.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Weekly Lint", "", f"- lint_report: {lint.path}", f"- lint_issues: {len(lint.issues)}", ""]
    if lint.issues:
        lines.extend(f"- {issue}" for issue in lint.issues)
    else:
        lines.append("- no lint issues found")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return relative_report


def _write_periodic_stats(settings: Settings) -> str:
    vault = Path(settings.vault.path)
    stats = vault_stats(vault, skip_paths=settings.vault.skip_paths)
    relative_report = "output/periodic-stats.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Periodic Stats",
        "",
        f"- total_markdown: {stats.total_markdown}",
    ]
    lines.extend(f"- {name}: {count}" for name, count in sorted(stats.markdown_by_area.items()))
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return relative_report


def _write_bookmark_review(settings: Settings) -> str:
    vault = Path(settings.vault.path)
    bookmarks = _tail_lines(vault / "meta" / "bookmarks.md", limit=50)
    relative_report = "output/bookmark-review.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Bookmark Review", ""]
    if bookmarks:
        lines.extend(f"- {line}" for line in bookmarks)
    else:
        lines.append("- no bookmarks file or entries found")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return relative_report


def _write_filtered_lint_review(
    settings: Settings,
    *,
    relative_report: str,
    title: str,
    needle: str,
    empty_message: str,
) -> str:
    vault = Path(settings.vault.path)
    lint = lint_vault(vault, skip_paths=settings.vault.skip_paths)
    matches = [
        issue
        for issue in lint.issues
        if needle.casefold() in issue.casefold()
    ]
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]
    if matches:
        lines.extend(f"- {issue}" for issue in matches)
    else:
        lines.append(f"- {empty_message}")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return relative_report


def _tail_lines(path: Path, *, limit: int) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()[-limit:] if line.strip()]


def _run_vault_backup(settings: Settings, kind: str) -> str:
    from segretario.backup.manager import BackupManager

    manager = BackupManager(settings.backup, settings.vault.path)
    result = manager.create(kind=kind)
    if not result.ok:
        return f"backup.{kind} failed: {result.message}"
    if result.path is None:
        return f"backup.{kind}: {result.message}"
    return f"backup.{kind}: {result.path.name} ({result.size_bytes / (1024 * 1024):.1f} MB)"


def _run_recall_reindex(settings: Settings) -> str:
    if not settings.recall.enabled:
        return "recall.reindex: skipped: recall disabled in config"

    from segretario.recall.state import ReindexStateStore
    from segretario.recall.indexer import VaultIndexer
    from segretario.recall.embedder import OllamaEmbedder
    from segretario.recall.sqlite_vec_store import SqliteVecStore
    from segretario.recall.chunker import WholeNoteChunker
    from datetime import datetime, timezone

    state = ReindexStateStore(settings.recall.state_path)
    now = datetime.now(timezone.utc)

    if state.should_skip(now, settings.recall.reindex_threshold_minutes):
        last = state.get_last_run()
        return (
            f"recall.reindex: skipped: last run at {last.isoformat()}, "
            f"threshold {settings.recall.reindex_threshold_minutes} min"
        )

    try:
        embedder = OllamaEmbedder(
            model=settings.recall.embedding_model,
            base_url=settings.recall.ollama_base_url,
        )
        store = SqliteVecStore(
            db_path=settings.recall.db_path,
            embedding_model=settings.recall.embedding_model,
        )
        vault_path = Path(settings.vault.path)
        indexer = VaultIndexer(
            vault_path=vault_path,
            store=store,
            embedder=embedder,
            chunker=WholeNoteChunker(),
            skip_paths=settings.recall.skip_paths,
        )
        result = indexer.reindex()
        state.set_last_run(now, result.indexed_total, settings.recall.embedding_model)
        return (
            f"recall.reindex: indexed={result.indexed} deleted={result.deleted} "
            f"skipped_unchanged={result.skipped_unchanged} errors={len(result.errors)}"
        )
    except Exception as exc:
        return f"recall.reindex: error: {exc}"


def _should_skip(relative: str, settings: Settings) -> bool:
    return classify_vault_path(relative).skip or matches_configured_skip_path(
        relative,
        settings.vault.skip_paths,
    )
