from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import typer
import yaml

from segretario.agents.calendar_agent import CalendarAgent
from segretario.agents.extraction_agent import ExtractionAgent
from segretario.agents.ingest_agent import ConfirmationNeededError
from segretario.agents.ingest_agent import IngestAgent
from segretario.agents.mail_agent import MailAgent
from segretario.agents.maintenance_agent import MaintenanceAgent
from segretario.agents.research_agent import ResearchAgent
from segretario.agents.search_agent import SearchAgent
from segretario.agents.security_agent import SecurityAgent
from segretario.agents.wiki_maintainer_agent import WikiMaintainerAgent
from segretario.app.core import SegretarioCore
from segretario.app.query import query_vault
from segretario.app.models import TaskRequest
from segretario.app.router import TaskRouter
from segretario.audit import AuditLog
from segretario.config.loader import default_config_path, load_settings
from segretario.connectors.google_oauth import GoogleOAuthConnector
from segretario.policies.output_guard import sanitize_user_output
from segretario.policies.permissions import PermissionKernel
from segretario.policies.privacy import project_private_context
from segretario.scheduler.jobs import SchedulerJob, run_scheduler_once
from segretario.taskboard import TaskboardStore
from segretario.taskboard import TaskStatus
from segretario.taskboard.payloads import TaskPayloadStore
from segretario.tools.ollama_tool import build_local_llm
from segretario.vault.repair import repair_raw_plan as build_repair_raw_plan

app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(help="Configuration commands.")
vault_app = typer.Typer(help="Vault commands.")
lint_app = typer.Typer(help="Lint commands.")
mail_app = typer.Typer(help="Gmail commands.")
calendar_app = typer.Typer(help="Calendar commands.")
google_app = typer.Typer(help="Google OAuth commands.")
scheduler_app = typer.Typer(help="Scheduler commands.")
external_app = typer.Typer(help="External-agent answer commands.")
privacy_app = typer.Typer(help="Privacy projection commands.")
audit_app = typer.Typer(help="Audit commands.")
task_app = typer.Typer(help="Single task commands.")
agents_app = typer.Typer(help="Agent worker commands.")
repair_app = typer.Typer(help="Vault repair commands.")
extract_app = typer.Typer(help="Rich source extraction planning commands.")
app.add_typer(config_app, name="config")
app.add_typer(vault_app, name="vault")
app.add_typer(lint_app, name="lint")
app.add_typer(mail_app, name="mail")
app.add_typer(calendar_app, name="calendar")
app.add_typer(google_app, name="google")
app.add_typer(scheduler_app, name="scheduler")
app.add_typer(external_app, name="external")
app.add_typer(privacy_app, name="privacy")
app.add_typer(audit_app, name="audit")
app.add_typer(task_app, name="task")
app.add_typer(agents_app, name="agents")
app.add_typer(repair_app, name="repair")
app.add_typer(extract_app, name="extract")


def _echo(message: object = "", *, debug: bool = False) -> None:
    text = sanitize_user_output(message, debug=debug)
    try:
        typer.echo(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        typer.echo(text.encode(encoding, errors="replace").decode(encoding))


@app.command()
def status(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Print a partial local system report without failing on missing services."""
    settings = load_settings(config_path=config)
    vault_status = _path_status(settings.vault.path, require_dir=True)
    taskboard_status = _path_status(settings.taskboard.sqlite_path)
    audit_status = _path_status(settings.audit.events_path)
    google_status = (
        "configured"
        if settings.google.credentials_path.exists() and settings.google.token_path.exists()
        else "not configured"
    )
    ollama_status = _ollama_status(settings.llm.base_url)
    config_display = settings.loaded_config_path or default_config_path()

    lines = [
        "il_segretario status",
        "---------------------------",
        f"Project:      {settings.project_name}",
        f"Config:       {config_display}",
        f"Vault:        {settings.vault.path}",
        f"Vault check:  {vault_status}",
        f"LLM:          {settings.llm.provider} / {settings.llm.model}",
        f"Ollama:       {ollama_status}",
        f"Taskboard:    {taskboard_status}",
        f"Audit:        {audit_status}",
        f"Google:       {google_status}",
        f"Web:          {'enabled' if settings.web.enabled else 'disabled'}",
        f"Scheduler:    {'enabled' if settings.scheduler.enabled else 'disabled'}",
        "---------------------------",
    ]
    _echo("\n".join(lines))


@config_app.command("show")
def config_show(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Print the resolved configuration with secrets paths only, never contents."""
    settings = load_settings(config_path=config)
    _echo(yaml.safe_dump(settings.to_safe_dict(), sort_keys=False))


@google_app.command("status")
def google_status(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Show Google OAuth readiness without printing token contents."""
    settings = load_settings(config_path=config)
    status = GoogleOAuthConnector(
        credentials_path=settings.google.credentials_path,
        token_path=settings.google.token_path,
    ).status()
    _echo(f"Google: {'configured' if status.configured else 'not configured'}")
    _echo(f"Credentials: {status.credentials_path}")
    _echo(f"Token: {status.token_path}")
    if status.scopes_ok:
        _echo("Scopes: ok")
    else:
        _echo("Scopes: missing")
        for scope in status.missing_scopes:
            _echo(f"- {scope}")


@google_app.command("login")
def google_login(
    force: bool = typer.Option(
        False,
        "--force",
        help="Recreate the local OAuth token with the currently required scopes.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Create or refresh the local Google OAuth token."""
    settings = load_settings(config_path=config)
    status = GoogleOAuthConnector(
        credentials_path=settings.google.credentials_path,
        token_path=settings.google.token_path,
    ).login(force=force)
    _echo(f"Google login: {'ok' if status.scopes_ok else 'missing scopes'}")
    _echo(f"Token: {status.token_path}")


@vault_app.command("check")
def vault_check(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Check the configured vault structure."""
    settings = load_settings(config_path=config)
    vault = settings.vault.path
    lines = ["Vault check:"]
    lines.append(f"vault: {'ok' if vault.is_dir() else 'missing'}")
    for relative in ("AGENTS.md", "meta/index.md", "meta/log.md"):
        path = vault / relative
        lines.append(f"{relative}: {'ok' if path.exists() else 'missing'}")
    _echo("\n".join(lines))


@app.command()
def search(
    query: str,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Search allowed local vault markdown/text files."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="search",
            payload={
                "vault_path": settings.vault.path,
                "query": query,
                "skip_paths": settings.vault.skip_paths,
            },
            risk="low",
            action="vault.search",
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    results = result.output
    if not results:
        _echo("No matches found.")
        return
    for result in results:
        _echo(f"{result['path']}:{result['line']}: {result['snippet']}")


@app.command()
def query(
    question: str,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Answer a vault query using only local vault context and local LLMs."""
    settings = load_settings(config_path=config)
    llm = build_local_llm(settings.llm)
    try:
        result = query_vault(settings.vault.path, question, llm=llm)
    except Exception as exc:
        _echo(str(exc))
        raise typer.Exit(1) from exc
    _echo(result.answer)


@app.command()
def stats(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Print basic vault statistics."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="stats",
            payload={
                "vault_path": settings.vault.path,
                "action": "stats",
                "skip_paths": settings.vault.skip_paths,
            },
            risk="low",
            action="vault.search",
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    summary = result.output
    _echo("Vault stats")
    for area, count in summary["markdown_by_area"].items():
        _echo(f"{area}: {count}")
    _echo(f"total_markdown: {summary['total_markdown']}")


@app.command()
def tasks(
    status_filter: str | None = typer.Option(
        None,
        "--status",
        help="Only show tasks with this status.",
    ),
    limit: int = typer.Option(20, "--limit", help="Maximum number of tasks to show."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """List recent taskboard tasks."""
    settings = load_settings(config_path=config)
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    rows = taskboard.list_tasks(limit=limit, status=status_filter)
    if not rows:
        _echo("No tasks found.")
        return
    for task in rows:
        if task["status"] in {"denied", "failed", "cancelled"}:
            reason = task.get("last_error") or task.get("confirmation_reason") or ""
        elif task["status"] == "completed":
            reason = ""
        else:
            reason = task.get("confirmation_reason") or task.get("last_error") or ""
        suffix = f" - {reason}" if reason else ""
        _echo(
            f"{task['id']}: {task['command']} [{task['status']}] risk={task['risk']}{suffix}"
        )


@task_app.command("show")
def task_show(
    task_id: int,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Show one taskboard task."""
    settings = load_settings(config_path=config)
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    task = taskboard.get_task(task_id)
    if task is None:
        _echo(f"unknown task id: {task_id}")
        raise typer.Exit(1)
    for key in (
        "id",
        "source",
        "requested_by",
        "command",
        "status",
        "risk",
        "assigned_agent",
        "requires_confirmation",
        "confirmation_reason",
        "input_ref",
        "output_ref",
        "audit_ref",
        "created_at",
        "updated_at",
        "lease_owner",
        "lease_expires_at",
        "retries",
        "last_error",
    ):
        value = task.get(key)
        if isinstance(value, bool):
            value = str(value).lower()
        elif value is None:
            value = ""
        _echo(f"{key}: {value}")


@task_app.command("run")
def task_run(
    task_id: int,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Run one queued task after confirmation has been approved."""
    settings = load_settings(config_path=config)
    try:
        _run_queued_task(settings, task_id)
    except (FileNotFoundError, ValueError) as exc:
        _echo(str(exc))
        raise typer.Exit(1) from exc
    _echo(f"task {task_id}: completed")


@task_app.command("cancel")
def task_cancel(
    task_id: int,
    reason: str = typer.Option("operator cancelled", "--reason", help="Cancellation reason."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Cancel a queued, running, or waiting task with an audit record."""
    settings = load_settings(config_path=config)
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    try:
        task = taskboard.cancel_task(task_id, reason=reason)
    except (KeyError, ValueError) as exc:
        _echo(str(exc))
        raise typer.Exit(1) from exc
    audit.append_event(
        "task.cancelled_by_operator",
        {"task_id": task_id, "command": task["command"], "reason": reason},
    )
    _echo(f"cancelled: {task_id}")


@task_app.command("cancel-latest")
def task_cancel_latest(
    command: str,
    reason: str = typer.Option("operator cancelled latest task", "--reason", help="Cancellation reason."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Cancel the newest waiting confirmation task for a command."""
    settings = load_settings(config_path=config)
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    try:
        task_id = _latest_waiting_task_id(taskboard, command)
    except ValueError as exc:
        _echo(str(exc))
        raise typer.Exit(1) from exc

    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    task = taskboard.cancel_task(task_id, reason=reason)
    audit.append_event(
        "task.cancelled_by_operator",
        {"task_id": task_id, "command": task["command"], "reason": reason},
    )
    _echo(f"cancelled: {task_id}")


@task_app.command("approve-run-latest")
def task_approve_run_latest(
    command: str,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Approve and immediately run the newest waiting confirmation task for a command."""
    settings = load_settings(config_path=config)
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    try:
        task_id = _latest_waiting_task_id(taskboard, command)
        task = taskboard.approve_task(task_id)
    except (KeyError, ValueError) as exc:
        _echo(str(exc))
        raise typer.Exit(1) from exc

    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    audit.append_event(
        "task.approved",
        {"task_id": task_id, "command": task["command"]},
    )
    _echo(f"approved: {task_id}")
    _run_queued_task(settings, task_id)
    _echo(f"task {task_id}: completed")


@agents_app.command("run-once")
def agents_run_once(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Let an agent claim and execute one queued task."""
    settings = load_settings(config_path=config)
    result = _run_one_agent_task(settings)
    if result is None:
        _echo("No runnable agent tasks.")
        return
    task_id, command, status, output_ref = result
    if output_ref:
        _echo(f"{task_id}: {command} {status} -> {output_ref}")
    else:
        _echo(f"{task_id}: {command} {status}")


@agents_app.command("run")
def agents_run(
    limit: int = typer.Option(
        5,
        "--limit",
        min=0,
        help="Maximum number of queued agent tasks to execute sequentially.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Let fixed agents claim and execute a bounded batch of queued tasks."""
    settings = load_settings(config_path=config)
    executed: list[tuple[int, str, str, str | None]] = []
    for _ in range(limit):
        result = _run_one_agent_task(settings)
        if result is None:
            break
        executed.append(result)

    _echo(f"Executed: {len(executed)}")
    if not executed:
        _echo("No runnable agent tasks.")
        return
    for task_id, command, status, output_ref in executed:
        if output_ref:
            _echo(f"{task_id}: {command} {status} -> {output_ref}")
        else:
            _echo(f"{task_id}: {command} {status}")


def _run_queued_task(settings, task_id: int) -> None:
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    task = taskboard.get_task(task_id)
    if task is None:
        raise ValueError(f"unknown task id: {task_id}")
    if task["status"] != TaskStatus.QUEUED.value:
        raise ValueError(f"task {task_id} is not queued")

    payload_store = TaskPayloadStore(settings.taskboard.sqlite_path.parent)
    request = payload_store.load(str(task.get("input_ref") or ""))

    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    try:
        taskboard.start_queued_task(
            task_id,
            owner="cli",
            lease_seconds=max(settings.taskboard.lease_minutes, 1) * 60,
        )
        audit.append_event(
            "task.started",
            {"task_id": task_id, "command": request.command, "source": "cli"},
        )
        agent = _build_core(settings).router.agent_for(request.command)
        audit.append_event(
            "tool.requested",
            {
                "task_id": task_id,
                "command": request.command,
                "tools": sorted(getattr(agent, "allowed_tools", [])),
            },
        )
        output = agent.run(request)
    except Exception as exc:
        max_retries = (
            1
            if str(task.get("risk", "")).lower() in {"high", "critical"}
            else settings.taskboard.max_retries
        )
        taskboard.record_failure(
            task_id,
            error=str(exc),
            max_retries=max_retries,
            cooldown_seconds=settings.taskboard.retry_cooldown_seconds,
        )
        audit.append_event(
            "tool.failed",
            {"task_id": task_id, "command": task["command"], "error": str(exc)},
        )
        audit.append_event(
            "task.failed",
            {"task_id": task_id, "command": task["command"], "error": str(exc)},
        )
        _echo(str(exc))
        raise typer.Exit(1) from exc

    output_ref = _cli_output_ref(output)
    audit.append_event(
        "tool.completed",
        {"task_id": task_id, "command": request.command, "output": output_ref},
    )
    taskboard.complete_task(task_id, output_ref=output_ref)
    audit.append_event(
        "task.completed",
        {"task_id": task_id, "command": request.command, "output": output_ref},
    )


def _latest_waiting_task_id(taskboard: TaskboardStore, command: str) -> int:
    for task in taskboard.list_tasks(limit=100):
        if (
            task["command"] == command
            and task["status"] == TaskStatus.WAITING_CONFIRMATION.value
            and task["requires_confirmation"]
        ):
            return int(task["id"])
    raise ValueError(f"no waiting confirmation task found for {command}")


def _run_one_agent_task(settings) -> tuple[int, str, str, str | None] | None:
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    command_map = _agent_command_map()
    task = taskboard.acquire_lease_for_commands(
        owner="agent-runner",
        lease_seconds=max(settings.taskboard.lease_minutes, 1) * 60,
        commands=set(command_map),
    )
    if task is None:
        return None

    task_id = int(task["id"])
    command = str(task["command"])
    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    payload_store = TaskPayloadStore(settings.taskboard.sqlite_path.parent)
    try:
        request = payload_store.load(str(task.get("input_ref") or ""))
        audit.append_event(
            "agent.task_started",
            {"task_id": task_id, "command": request.command, "agent": "agent-runner"},
        )
        agent = command_map[request.command]
        audit.append_event(
            "tool.requested",
            {
                "task_id": task_id,
                "command": request.command,
                "tools": sorted(getattr(agent, "allowed_tools", [])),
            },
        )
        output = agent.run(request)
    except Exception as exc:
        max_retries = (
            1
            if str(task.get("risk", "")).lower() in {"high", "critical"}
            else settings.taskboard.max_retries
        )
        taskboard.record_failure(
            task_id,
            error=str(exc),
            max_retries=max_retries,
            cooldown_seconds=settings.taskboard.retry_cooldown_seconds,
        )
        audit.append_event(
            "tool.failed",
            {"task_id": task_id, "command": command, "error": str(exc)},
        )
        audit.append_event(
            "agent.task_failed",
            {"task_id": task_id, "command": command, "error": str(exc)},
        )
        return task_id, command, "failed", None

    output_ref = _cli_output_ref(output)
    audit.append_event(
        "tool.completed",
        {"task_id": task_id, "command": request.command, "output": output_ref},
    )
    taskboard.complete_task(task_id, output_ref=output_ref)
    audit.append_event(
        "agent.task_completed",
        {"task_id": task_id, "command": request.command, "output": output_ref},
    )
    return task_id, request.command, "completed", output_ref


@app.command()
def approve(
    task_id: int,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Approve a task waiting for confirmation."""
    settings = load_settings(config_path=config)
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    try:
        task = taskboard.approve_task(task_id)
    except (KeyError, ValueError) as exc:
        _echo(str(exc))
        raise typer.Exit(1) from exc
    audit.append_event(
        "task.approved",
        {"task_id": task_id, "command": task["command"]},
    )
    _echo(f"approved: {task_id}")


@app.command()
def deny(
    task_id: int,
    reason: str = typer.Option("operator denied", "--reason", help="Denial reason."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Deny a task waiting for confirmation."""
    settings = load_settings(config_path=config)
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    try:
        existing = taskboard.get_task(task_id)
        if existing is None:
            raise KeyError(f"unknown task id: {task_id}")
        if existing["status"] != "waiting_confirmation" or not existing["requires_confirmation"]:
            raise ValueError(f"task {task_id} is not waiting for confirmation")
        task = taskboard.deny_task(task_id, reason=reason)
    except (KeyError, ValueError) as exc:
        _echo(str(exc))
        raise typer.Exit(1) from exc
    audit.append_event(
        "task.denied_by_operator",
        {"task_id": task_id, "command": task["command"], "reason": reason},
    )
    _echo(f"denied: {task_id}")


@audit_app.command("verify")
def audit_verify(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Verify the audit hash chain without modifying it."""
    settings = load_settings(config_path=config)
    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    if audit.verify():
        _echo("Audit verify: ok")
        return
    _echo("Audit verify: failed")
    raise typer.Exit(1)


@privacy_app.command("project")
def privacy_project(text: str) -> None:
    """Project private context into privacy-safe tokens and bands."""
    projection = project_private_context(text)
    _echo(projection.text)


@lint_app.command("wiki")
def lint_wiki(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Run basic wiki lint checks and save a report."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="lint.wiki",
            payload={
                "vault_path": settings.vault.path,
                "action": "lint.wiki",
                "skip_paths": settings.vault.skip_paths,
            },
            risk="low",
            action="output.write",
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    report = result.output
    _echo(f"Lint report: {report['report_path']}")
    if report["issues"]:
        for issue in report["issues"]:
            _echo(f"- {issue}")
    else:
        _echo("- ok")


@app.command()
def relink(
    scope: str | None = typer.Argument(
        None,
        help="Optional vault-relative source scope, for example knowledge/.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview missing wikilinks and write a report without editing pages.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply unambiguous wikilinks to knowledge pages.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Preview or apply missing Obsidian wikilinks."""
    if dry_run == apply:
        _echo("choose exactly one: --dry-run or --apply")
        raise typer.Exit(1)
    settings = load_settings(config_path=config)
    command = "relink.dry_run" if dry_run else "relink.apply"
    action = "output.write" if dry_run else "knowledge.write"
    result = _build_core(settings).handle(
        TaskRequest(
            command=command,
            payload={
                "vault_path": settings.vault.path,
                "action": command,
                "source_scope": scope,
                "skip_paths": settings.vault.skip_paths,
            },
            risk="low",
            action=action,
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    report = result.output
    label = "Relink report" if dry_run else "Relink apply report"
    _echo(f"{label}: {report['report_path']}")
    if report["suggestions"]:
        for suggestion in report["suggestions"]:
            _echo(f"- {suggestion}")
    else:
        _echo("- no missing links found")


@repair_app.command("index")
def repair_index(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview missing knowledge entries for meta/index.md.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply missing knowledge entries to meta/index.md.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Repair meta/index.md by adding missing knowledge wikilinks."""
    if dry_run == apply:
        _echo("choose exactly one: --dry-run or --apply")
        raise typer.Exit(1)
    settings = load_settings(config_path=config)
    command = "repair.index.dry_run" if dry_run else "repair.index.apply"
    result = _build_core(settings).handle(
        TaskRequest(
            command=command,
            payload={
                "vault_path": settings.vault.path,
                "action": command,
                "skip_paths": settings.vault.skip_paths,
            },
            risk="low",
            action="output.write" if dry_run else "knowledge.write",
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    report = result.output or {}
    label = "Repair index report" if dry_run else "Repair index apply report"
    _echo(f"{label}: {report['report_path']}")
    if report["entries"]:
        for entry in report["entries"]:
            _echo(entry)
    else:
        _echo("- no index repairs needed")


@repair_app.command("raw-plan")
def repair_raw_plan_command(
    limit: int = typer.Option(
        80,
        "--limit",
        min=0,
        help="Maximum number of plan entries to print; full report is always written.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Plan conservative handling for unprocessed raw files."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="repair.raw_plan",
            payload={
                "vault_path": settings.vault.path,
                "action": "repair.raw_plan",
                "skip_paths": settings.vault.skip_paths,
            },
            risk="low",
            action="output.write",
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    report = result.output or {}
    _echo(f"Repair raw plan: {report['report_path']}")
    items = report["items"]
    if items:
        for item in items[:limit]:
            _echo(item)
        remaining = len(items) - limit
        if remaining > 0:
            _echo(f"- ... {remaining} more entries in report")
    else:
        _echo("- no raw planning needed")


@repair_app.command("raw-queue")
def repair_raw_queue_command(
    limit: int = typer.Option(
        5,
        "--limit",
        min=0,
        help="Maximum number of ingest_candidate raw files to queue.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Queue safe ingest tasks from the raw repair plan without executing them."""
    settings = load_settings(config_path=config)
    plan = build_repair_raw_plan(settings.vault.path, skip_paths=settings.vault.skip_paths)
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    payload_store = TaskPayloadStore(settings.taskboard.sqlite_path.parent)
    active_sources = _active_ingest_sources(taskboard, payload_store)
    candidates = [
        source_path
        for source_path in _raw_plan_ingest_candidates(plan.items)
        if source_path not in active_sources
    ][:limit]
    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    queued: list[tuple[int, str]] = []
    for source_path in candidates:
        request = TaskRequest(
            command="ingest",
            payload={
                "vault_path": settings.vault.path,
                "source_path": source_path,
                "auto": True,
            },
            risk="low",
            action=PermissionKernel.KNOWLEDGE_WRITE,
            source="repair",
            requested_by="segretario",
        )
        task = taskboard.create_task(
            source="repair",
            requested_by="segretario",
            command="ingest",
            risk="low",
            assigned_agent="agent-runner",
            input_ref="pending",
        )
        payload_ref = payload_store.save(int(task["id"]), request)
        taskboard.update_input_ref(int(task["id"]), payload_ref)
        audit.append_event(
            "repair.raw_ingest_queued",
            {"task_id": task["id"], "source_path": source_path},
        )
        queued.append((int(task["id"]), source_path))

    _echo(f"Queued ingest tasks: {len(queued)}")
    for task_id, source_path in queued:
        _echo(f"- {task_id}: {source_path}")


@extract_app.command("plan")
def extract_plan_command(
    limit: int = typer.Option(
        80,
        "--limit",
        min=0,
        help="Maximum number of plan entries to print; full report is always written.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Plan safe local extraction for unsupported raw files."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="extract.plan",
            payload={
                "vault_path": settings.vault.path,
                "action": "extract.plan",
                "skip_paths": settings.vault.skip_paths,
            },
            risk="low",
            action="output.write",
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    report = result.output or {}
    _echo(f"Extract plan: {report['report_path']}")
    items = report["items"]
    if items:
        for item in items[:limit]:
            _echo(item)
        remaining = len(items) - limit
        if remaining > 0:
            _echo(f"- ... {remaining} more entries in report")
    else:
        _echo("- no extraction planning needed")


def _raw_plan_ingest_candidates(items: list[str]) -> list[str]:
    candidates: list[str] = []
    for item in items:
        if " -> ingest_candidate:" not in item:
            continue
        source = item.removeprefix("- ").split(" -> ", 1)[0].strip()
        if source:
            candidates.append(source)
    return candidates


def _active_ingest_sources(
    taskboard: TaskboardStore,
    payload_store: TaskPayloadStore,
) -> set[str]:
    active_statuses = {
        TaskStatus.QUEUED.value,
        TaskStatus.RUNNING.value,
        TaskStatus.WAITING_CONFIRMATION.value,
    }
    sources: set[str] = set()
    for task in taskboard.list_tasks(limit=1000):
        if task.get("command") != "ingest" or task.get("status") not in active_statuses:
            continue
        try:
            request = payload_store.load(str(task.get("input_ref") or ""))
        except (FileNotFoundError, ValueError, KeyError):
            continue
        source_path = request.payload.get("source_path")
        if source_path:
            sources.add(str(source_path).replace("\\", "/"))
    return sources


@app.command()
def ingest(
    source: str,
    auto: bool = typer.Option(False, "--auto", help="Run safe automatic ingest."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Ingest a markdown/text source from raw/articles into knowledge."""
    settings = load_settings(config_path=config)
    try:
        result = _build_core(settings).handle(
            TaskRequest(
                command="ingest",
                payload={
                    "vault_path": settings.vault.path,
                    "source_path": source,
                    "auto": auto,
                },
                risk="low",
                action="knowledge.write",
            )
        )
    except (ConfirmationNeededError, FileNotFoundError, ValueError) as exc:
        _echo(str(exc))
        raise typer.Exit(1) from exc

    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    output = result.output
    action = "updated" if output["updated"] else "created"
    _echo(f"{action}: {output['path']}")


@app.command()
def link(
    url: str,
    ingest: bool = typer.Option(False, "--ingest", help="Ingest the fetched source after saving."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Fetch a public web link into raw/articles."""
    settings = load_settings(config_path=config)
    if not settings.web.enabled:
        _echo("web is disabled")
        raise typer.Exit(1)

    core = _build_core(settings)
    result = core.handle(
        TaskRequest(
            command="link",
            payload={
                "vault_path": settings.vault.path,
                "url": url,
                "save_dir": settings.web.save_dir,
                "ingest": ingest,
            },
            risk="low",
            action="web.public_query",
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    saved_path = result.output["path"]
    _echo(f"saved: {saved_path}")
    if ingest and result.output.get("ingested_path"):
        action = "updated" if result.output.get("ingested_updated") else "created"
        _echo(f"{action}: {result.output['ingested_path']}")


@app.command()
def web(
    query: str,
    private_context: bool = typer.Option(
        False,
        "--private-context",
        help="Mark the query as derived from private vault context.",
    ),
    projection: str | None = typer.Option(
        None,
        "--projection",
        help="Privacy-safe projection to use instead of the raw private query.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Prepare a privacy-safe web query payload."""
    settings = load_settings(config_path=config)
    if not settings.web.enabled:
        _echo("web is disabled")
        raise typer.Exit(1)

    context_privacy = "private" if private_context else "public"
    action = "web.public_query" if not private_context or projection else "web.private_context_query"
    result = _build_core(settings).handle(
        TaskRequest(
            command="web",
            payload={
                "action": "web.query",
                "query": query,
                "context_privacy": context_privacy,
                "projection": projection,
                "vault_path": settings.vault.path,
                "save_dir": settings.web.save_dir,
            },
            risk="low" if action == "web.public_query" else "medium",
            action=action,
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    _echo(f"web query: {result.output['query']}")
    if result.output.get("path"):
        _echo(f"saved: {result.output['path']}")
    if result.output.get("ingested_path"):
        action_label = "updated" if result.output.get("ingested_updated") else "created"
        _echo(f"{action_label}: {result.output['ingested_path']}")


@mail_app.command("read")
def mail_read(
    query: str = typer.Option("", "--query", help="Gmail search query."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Read local Gmail message metadata through the safe interface."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="mail.read",
            payload={
                **_google_payload(settings),
                "query": query,
            },
            risk="low",
            action=PermissionKernel.GMAIL_READ,
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    if not result.output:
        _echo("No messages found.")
        return
    for message in result.output:
        _echo(f"{message.get('id')}: {message.get('subject')} - {message.get('snippet')}")


@mail_app.command("draft")
def mail_draft(
    prompt: str | None = typer.Argument(None, help="Draft body/prompt."),
    to: str | None = typer.Option(None, "--to", help="Recipient email address."),
    subject: str | None = typer.Option(None, "--subject", help="Draft subject."),
    body: str | None = typer.Option(None, "--body", help="Draft body."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Create a local Gmail draft record."""
    settings = load_settings(config_path=config)
    draft_body = body if body is not None else prompt
    if not draft_body:
        _echo("mail draft requires --body or a prompt argument")
        raise typer.Exit(1)
    draft_to = to or ""
    draft_subject = subject or "Draft request"
    google_payload = _google_payload(settings)
    if not to or not subject:
        google_payload["use_google"] = False
    result = _build_core(settings).handle(
        TaskRequest(
            command="mail.draft",
            payload={
                **google_payload,
                "to": draft_to,
                "subject": draft_subject,
                "body": draft_body,
            },
            risk="low",
            action=PermissionKernel.GMAIL_DRAFT,
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    _echo(f"draft: {result.output['id']}")


@mail_app.command("send")
def mail_send(
    draft_or_task_id: str,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Create a Gmail send confirmation task, or run an approved mail.send task id."""
    settings = load_settings(config_path=config)
    if draft_or_task_id.isdigit():
        taskboard = TaskboardStore(settings.taskboard.sqlite_path)
        taskboard.initialize()
        task = taskboard.get_task(int(draft_or_task_id))
        if task is not None and task["command"] == "mail.send":
            try:
                _run_queued_task(settings, int(draft_or_task_id))
            except (FileNotFoundError, ValueError) as exc:
                _echo(str(exc))
                raise typer.Exit(1) from exc
            _echo(f"task {draft_or_task_id}: completed")
            return

    result = _build_core(settings).handle(
        TaskRequest(
            command="mail.send",
            payload={**_google_payload(settings), "draft_id": draft_or_task_id},
            risk="high",
            action=PermissionKernel.GMAIL_SEND,
        )
    )
    _echo(result.message)
    raise typer.Exit(0 if result.ok else 1)


@mail_app.command("archive")
def mail_archive(
    message_ref: str,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Create a confirmation task for Gmail archive."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="mail.archive",
            payload={**_google_payload(settings), "message_ref": message_ref},
            risk="high",
            action=PermissionKernel.GMAIL_ARCHIVE,
        )
    )
    _echo(result.message)
    raise typer.Exit(0 if result.ok else 1)


@mail_app.command("delete")
def mail_delete(
    message_ref: str,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Create a confirmation task for Gmail delete."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="mail.delete",
            payload={**_google_payload(settings), "message_ref": message_ref},
            risk="high",
            action=PermissionKernel.GMAIL_DELETE,
        )
    )
    _echo(result.message)
    raise typer.Exit(0 if result.ok else 1)


@calendar_app.command("list")
def calendar_list(
    today: bool = typer.Option(False, "--today", help="Show events dated today."),
    from_date: str | None = typer.Option(None, "--from", help="Inclusive start date."),
    to_date: str | None = typer.Option(None, "--to", help="Inclusive end date."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """List local calendar event metadata."""
    settings = load_settings(config_path=config)
    if today:
        current = date.today().isoformat()
        from_date = current
        to_date = current
    result = _build_core(settings).handle(
        TaskRequest(
            command="calendar.list",
            payload={
                **_google_payload(settings),
                "from": from_date,
                "to": to_date,
            },
            risk="low",
            action=PermissionKernel.CALENDAR_READ,
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    if not result.output:
        _echo("No events found.")
        return
    events = [
        event
        for event in result.output
        if _event_in_calendar_range(event, from_date=from_date, to_date=to_date)
    ]
    if not events:
        _echo("No events found.")
        return
    for event in events:
        _echo(f"{event.get('id')}: {event.get('summary')} @ {event.get('when')}")


@calendar_app.command("read")
def calendar_read(
    event_ref: str,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Read local calendar event details."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="calendar.read",
            payload={**_google_payload(settings), "event_ref": event_ref},
            risk="low",
            action=PermissionKernel.CALENDAR_READ,
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    event = result.output
    _echo(f"{event.get('id')}: {event.get('summary')} @ {event.get('when')}")


@calendar_app.command("create")
def calendar_create(
    summary: str,
    attendee: list[str] | None = typer.Option(None, "--attendee", help="Event attendee."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Create a local private calendar event, or confirmation task with attendees."""
    settings = load_settings(config_path=config)
    attendees = attendee or []
    action = (
        PermissionKernel.CALENDAR_CREATE_WITH_ATTENDEES
        if attendees
        else PermissionKernel.CALENDAR_CREATE
    )
    result = _build_core(settings).handle(
        TaskRequest(
            command="calendar.create",
            payload={
                **_google_payload(settings),
                "summary": summary,
                "when": summary,
                "attendees": attendees,
            },
            risk="high" if attendees else "low",
            action=action,
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    _echo(f"event: {result.output['id']}")


@calendar_app.command("schedule")
def calendar_schedule(
    summary: str,
    from_time: str = typer.Option(..., "--from", help="Earliest allowed event time."),
    to_time: str = typer.Option(..., "--to", help="Latest allowed event time."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Schedule a local private calendar event inside a constrained window."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="calendar.schedule",
            payload={
                **_google_payload(settings),
                "summary": summary,
                "window_start": from_time,
                "window_end": to_time,
            },
            risk="low",
            action=PermissionKernel.CALENDAR_SCHEDULE,
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    _echo(f"event: {result.output['id']}")


@calendar_app.command("modify")
def calendar_modify(
    event_ref: str,
    summary_arg: str | None = typer.Argument(None, help="Updated event summary."),
    summary: str | None = typer.Option(None, "--summary", help="Updated event summary."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Create a confirmation task for calendar modification."""
    settings = load_settings(config_path=config)
    summary_change = summary if summary is not None else summary_arg
    if not summary_change:
        _echo("calendar.modify requires a summary change")
        raise typer.Exit(1)
    result = _build_core(settings).handle(
        TaskRequest(
            command="calendar.modify",
            payload={
                **_google_payload(settings),
                "event_ref": event_ref,
                "summary": summary_change,
            },
            risk="high",
            action=PermissionKernel.CALENDAR_MODIFY,
        )
    )
    _echo(result.message)
    raise typer.Exit(0 if result.ok else 1)


@calendar_app.command("delete")
def calendar_delete(
    event_ref: str,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Create a confirmation task for calendar deletion."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="calendar.delete",
            payload={**_google_payload(settings), "event_ref": event_ref},
            risk="high",
            action=PermissionKernel.CALENDAR_DELETE,
        )
    )
    _echo(result.message)
    raise typer.Exit(0 if result.ok else 1)


@calendar_app.command("accept")
def calendar_accept(
    event_ref: str,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Create a confirmation task for accepting a calendar invitation."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="calendar.accept",
            payload={**_google_payload(settings), "event_ref": event_ref},
            risk="high",
            action=PermissionKernel.CALENDAR_ACCEPT,
        )
    )
    _echo(result.message)
    raise typer.Exit(0 if result.ok else 1)


@calendar_app.command("decline")
def calendar_decline(
    event_ref: str,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Create a confirmation task for declining a calendar invitation."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="calendar.decline",
            payload={**_google_payload(settings), "event_ref": event_ref},
            risk="high",
            action=PermissionKernel.CALENDAR_DECLINE,
        )
    )
    _echo(result.message)
    raise typer.Exit(0 if result.ok else 1)


@app.command("run-maintenance")
def run_maintenance(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Run one bounded local maintenance cycle."""
    settings = load_settings(config_path=config)
    scheduler = settings.scheduler.model_copy(
        update={
            "enabled": True,
            "raw_watcher_enabled": False,
            "inbox_watcher_enabled": False,
            "daily_digest_enabled": False,
            "maintenance_budget_minutes": max(settings.scheduler.maintenance_budget_minutes, 1),
        }
    )
    maintenance_job = SchedulerJob(
        command="maintenance.cycle",
        action=PermissionKernel.OUTPUT_WRITE,
        risk="low",
        reason=f"bounded maintenance budget {scheduler.maintenance_budget_minutes} minutes",
    )
    _run_scheduler_cli(
        settings.model_copy(update={"scheduler": scheduler}),
        execute=True,
        candidate_jobs=[maintenance_job],
    )


@app.command("watch")
def watch(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Run one bounded local watcher pass."""
    settings = load_settings(config_path=config)
    scheduler = settings.scheduler.model_copy(
        update={
            "enabled": True,
            "raw_watcher_enabled": True,
            "inbox_watcher_enabled": True,
            "daily_digest_enabled": False,
            "maintenance_budget_minutes": 0,
        }
    )
    _run_scheduler_cli(settings.model_copy(update={"scheduler": scheduler}), execute=True)


@scheduler_app.command("run-once")
def scheduler_run_once(
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Execute safe scheduled jobs after creating them.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Schedule one bounded scheduler cycle without starting a daemon."""
    settings = load_settings(config_path=config)
    _run_scheduler_cli(settings, execute=execute)


def _run_scheduler_cli(settings, *, execute: bool, candidate_jobs: list[SchedulerJob] | None = None) -> None:
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    summary = run_scheduler_once(
        settings,
        taskboard=taskboard,
        audit=audit,
        execute=execute,
        candidate_jobs=candidate_jobs,
    )
    _echo(f"Scheduler: {'enabled' if summary.enabled else 'disabled'}")
    _echo(f"Preflight: {'ok' if summary.preflight_ok else 'failed'}")
    _echo(f"Budget: {summary.budget_minutes} minutes")
    _echo(f"Scheduled: {len(summary.scheduled)}")
    for job in summary.scheduled:
        _echo(f"- {job.command}: {job.reason}")
    if summary.skipped:
        _echo("Skipped:")
        for item in summary.skipped:
            _echo(f"- {item}")
    if execute:
        _echo(f"Executed: {len(summary.executed)}")
        for item in summary.executed:
            if item.output_ref:
                _echo(f"- {item.command}: {item.status} -> {item.output_ref}")
            else:
                _echo(f"- {item.command}: {item.status}")


@external_app.command("answer")
def external_answer(
    question: str,
    source: str = typer.Option(..., "--source", help="Vault-relative source path."),
    projection: str | None = typer.Option(
        None,
        "--projection",
        help="Privacy-safe projection for local-only source content.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Answer an external-agent request through the output guard."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="external.answer",
            payload={
                "vault_path": settings.vault.path,
                "question": question,
                "source_path": source,
                "projection": projection,
            },
            risk="low",
            action=PermissionKernel.EXTERNAL_ANSWER,
            source="external",
            requested_by="external-agent",
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    _echo(result.output["answer"])


def _build_core(settings) -> SegretarioCore:
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    return SegretarioCore(
        taskboard=taskboard,
        audit=AuditLog(
            events_path=settings.audit.events_path,
            chain_path=settings.audit.hash_chain_path,
        ),
        router=TaskRouter(_agent_command_map()),
    )


def _agent_command_map():
    return {
        "search": SearchAgent(),
        "stats": MaintenanceAgent(),
        "lint.wiki": MaintenanceAgent(),
        "relink.dry_run": MaintenanceAgent(),
        "relink.apply": MaintenanceAgent(),
        "repair.index.dry_run": MaintenanceAgent(),
        "repair.index.apply": MaintenanceAgent(),
        "repair.raw_plan": MaintenanceAgent(),
        "extract.plan": ExtractionAgent(),
        "ingest": IngestAgent(),
        "link": ResearchAgent(),
        "web": ResearchAgent(),
        "meta.index.ensure": WikiMaintainerAgent(),
        "meta.log.append": WikiMaintainerAgent(),
        "mail.read": MailAgent(),
        "mail.draft": MailAgent(),
        "mail.send": MailAgent(),
        "mail.archive": MailAgent(),
        "mail.delete": MailAgent(),
        "calendar.list": CalendarAgent(),
        "calendar.read": CalendarAgent(),
        "calendar.create": CalendarAgent(),
        "calendar.schedule": CalendarAgent(),
        "calendar.modify": CalendarAgent(),
        "calendar.delete": CalendarAgent(),
        "calendar.accept": CalendarAgent(),
        "calendar.decline": CalendarAgent(),
        "external.answer": SecurityAgent(),
    }


def _google_state_dir(settings) -> Path:
    return settings.taskboard.sqlite_path.parent / "google"


def _google_payload(settings) -> dict[str, object]:
    return {
        "state_dir": _google_state_dir(settings),
        "credentials_path": settings.google.credentials_path,
        "token_path": settings.google.token_path,
        "use_google": (
            settings.google.enabled
            and settings.google.credentials_path.exists()
            and settings.google.token_path.exists()
        ),
    }


def _event_in_calendar_range(
    event: dict[str, object],
    *,
    from_date: str | None,
    to_date: str | None,
) -> bool:
    if from_date is None and to_date is None:
        return True
    event_date = _event_date(event)
    if event_date is None:
        return True
    if from_date is not None and event_date < from_date:
        return False
    if to_date is not None and event_date > to_date:
        return False
    return True


def _event_date(event: dict[str, object]) -> str | None:
    value = str(event.get("when") or "")
    if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
        return value[:10]
    return None


def _cli_output_ref(output: object) -> str:
    if isinstance(output, dict):
        for key in ("path", "report_path", "id"):
            value = output.get(key)
            if isinstance(value, str):
                return value
    return type(output).__name__


def _path_status(path: Path, *, require_dir: bool = False) -> str:
    if require_dir:
        return "ok" if path.is_dir() else "missing"
    if path.exists():
        return "ok"
    if path.parent.exists():
        return "missing"
    return "missing"


def _ollama_status(base_url: str) -> str:
    try:
        import httpx

        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=0.4)
        return "reachable" if response.status_code < 500 else "unreachable"
    except Exception:
        return "unreachable"

