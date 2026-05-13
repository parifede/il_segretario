from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from segretario.audit import AuditLog
from segretario.config.settings import Settings
from segretario.connectors.gmail_client import GmailClient
from segretario.policies.permissions import PermissionDecision, PermissionKernel
from segretario.taskboard import TaskStatus, TaskboardStore
from segretario.tools.gmail_tool import GmailTool
from segretario.vault.health import lint_vault, vault_stats
from segretario.vault.paths import classify_vault_path
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

    for job in _candidate_jobs(settings):
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
                action=PermissionKernel.GMAIL_READ,
                risk="low",
                reason="read inbox metadata for local triage",
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
    if settings.scheduler.maintenance_budget_minutes > 0:
        jobs.append(
            SchedulerJob(
                command="maintenance.cycle",
                action=PermissionKernel.OUTPUT_WRITE,
                risk="low",
                reason=f"bounded maintenance budget {settings.scheduler.maintenance_budget_minutes} minutes",
            )
        )
    return jobs


def _execute_scheduled_tasks(
    settings: Settings,
    *,
    taskboard: TaskboardStore,
    audit: AuditLog,
) -> list[SchedulerExecutionResult]:
    lease_seconds = max(settings.taskboard.lease_minutes, 1) * 60
    max_jobs = len(_candidate_jobs(settings))
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
            taskboard.record_failure(
                int(task["id"]),
                error=str(exc),
                max_retries=settings.taskboard.max_retries,
                cooldown_seconds=settings.taskboard.retry_cooldown_seconds,
            )
            audit.append_event(
                "scheduler.task_failed",
                {"task_id": task["id"], "command": command, "error": str(exc)},
            )
            executed.append(
                SchedulerExecutionResult(
                    command=command,
                    status=TaskStatus.FAILED.value,
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
    return {"watch.raw", "watch.inbox", "daily.digest", "maintenance.cycle"}


def _execute_command(command: str, settings: Settings) -> str:
    if command == "watch.raw":
        return _write_raw_watch(settings.vault.path)
    if command == "watch.inbox":
        return _write_inbox_watch(settings)
    if command == "daily.digest":
        return _write_daily_digest(settings.vault.path)
    if command == "maintenance.cycle":
        return _write_maintenance_cycle(settings.vault.path)
    raise ValueError(f"unsupported scheduler task: {command}")


def _write_raw_watch(vault_path: str | Path) -> str:
    vault = Path(vault_path)
    raw_dir = vault / "raw"
    candidates: list[str] = []
    if raw_dir.exists():
        for path in sorted(raw_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(vault).as_posix()
            if classify_vault_path(relative).skip:
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
    tool = GmailTool(
        state_dir=settings.taskboard.sqlite_path.parent / "google",
        google_client=_gmail_client(settings),
    )
    messages = tool.read(query="in:inbox newer_than:1d")
    relative_report = "output/inbox-watch.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Inbox Watch", ""]
    if messages:
        for message in messages[:20]:
            subject = str(message.get("subject", "")).replace("\n", " ")[:120]
            message_id = str(message.get("id", ""))
            lines.append(f"- {message_id}: {subject}")
    else:
        lines.append("- no inbox messages")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return relative_report


def _write_daily_digest(vault_path: str | Path) -> str:
    vault = Path(vault_path)
    stats = vault_stats(vault)
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


def _write_maintenance_cycle(vault_path: str | Path) -> str:
    vault = Path(vault_path)
    stats = vault_stats(vault)
    lint = lint_vault(vault)
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


def _tail_lines(path: Path, *, limit: int) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()[-limit:] if line.strip()]


def _gmail_client(settings: Settings):
    if not (
        settings.google.enabled
        and settings.google.credentials_path.exists()
        and settings.google.token_path.exists()
    ):
        return None
    return GmailClient.from_token(
        credentials_path=settings.google.credentials_path,
        token_path=settings.google.token_path,
    )
