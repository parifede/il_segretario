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
from segretario.tools.extractor_tool import plan_extraction
from segretario.tools.ollama_tool import build_local_llm
from segretario.vault.frontmatter import parse_frontmatter
from segretario.vault.paths import matches_configured_skip_path
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
ocr_app = typer.Typer(help="Local OCR queue commands.")
recall_app = typer.Typer(help="Semantic recall index commands.")
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
app.add_typer(ocr_app, name="ocr")
app.add_typer(recall_app, name="recall")

# sub-app zarsuit — Flow 02
zarsuit_app = typer.Typer(name="zarsuit", help="Flow 02: protocollo Zarsuit.")
app.add_typer(zarsuit_app)


@zarsuit_app.command("context-request")
def zarsuit_context_request(
    request_id: str = typer.Option(..., "--request-id", help="UUID richiesta utente"),
    goal: str = typer.Option(..., "--goal", help="Obiettivo visibile all'utente"),
    intent: str = typer.Option("conversational", "--intent",
                               help="conversational | task | memory_lookup"),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Invia una richiesta a Zarsuit (stub) e mostra il risultato."""
    from pathlib import Path as _Path
    from segretario.flow02.attestation import AttestationBuilder
    from segretario.flow02.character_store import CharacterStore
    from segretario.flow02.context_broker import ContextBroker
    from segretario.flow02.models import DetailLevel, IntentType, OutputPolicy
    from segretario.flow02.output_guard import OutputGuard
    from segretario.flow02.recall_engine import RecallEngine
    from segretario.flow02.retry_loop import RetryLoop
    from segretario.flow02.working_memory import WorkingMemory
    from segretario.flow02.zarsuit_client import ZarsuitClientStub

    settings = load_settings(config_path=config)
    try:
        intent_type = IntentType(intent)
    except ValueError:
        _echo("intent non valido: " + intent + ". Valori: conversational, task, memory_lookup")
        raise typer.Exit(1)

    broker = ContextBroker(
        character_store=CharacterStore.from_config(settings.character.identity),
        working_memory=WorkingMemory(4000),
        recall_engine=RecallEngine(_Path(settings.vault.path) / "meta" / "index.md"),
    )
    att = AttestationBuilder().build(
        request_id=request_id,
        internal_request_id=request_id + "-i1",
        approved_context_projection=["vault", "calendar", "contacts"],
        output_policy=OutputPolicy.FREE,
        max_detail_level=DetailLevel.OPERATIONAL,
        allowed_next_steps=[],
        user_visible_goal=goal,
    )
    stub = ZarsuitClientStub(
        responses_file=_Path(settings.zarsuit.stub_response_file)
        if settings.zarsuit.stub_response_file else None
    )
    messages: list[str] = []
    loop = RetryLoop(
        client=stub, guard=OutputGuard(), broker=broker,
        on_ux_message=lambda msg: (_echo("[ux] " + msg), messages.append(msg)),
    )
    result = loop.run(
        request_id=request_id, session_id="cli-session",
        user_message=goal, intent=intent_type,
        goal=goal, attestation=att,
    )
    if result.ok:
        _echo(result.message)
    else:
        _echo("[fail] " + result.message)
        raise typer.Exit(1)


# sub-app session — Flow 02
session_app = typer.Typer(name="session", help="Gestione sessione Zarsuit.")
app.add_typer(session_app)


def _get_session_manager(settings):
    from pathlib import Path as _Path
    from segretario.flow02.session.manager import SessionManager
    sessions_dir = _Path(settings.taskboard.sqlite_path).parent / "sessions"
    return SessionManager(sessions_dir)


@session_app.command("status")
def session_status(
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Mostra lo stato della sessione attiva."""
    settings = load_settings(config_path=config)
    manager = _get_session_manager(settings)
    session = manager.current_session()
    if session is None:
        _echo("Nessuna sessione attiva.")
        return
    _echo(f"Session ID:   {session.session_id}")
    _echo(f"Aperta:       {session.opened_at.isoformat()}")
    _echo(f"Ultima att.:  {session.last_activity().isoformat()}")
    _echo(f"Inattiva:     {session.minutes_inactive():.1f} min")
    _echo(f"Aperta da:    {session.hours_since_open():.1f} ore")
    _echo(f"Da chiudere:  {'si' if session.should_close() else 'no'}")


@session_app.command("chat")
def session_chat(
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Proiezione human-readable della sessione (chat.md)."""
    settings = load_settings(config_path=config)
    manager = _get_session_manager(settings)
    session = manager.current_session()
    if session is None:
        _echo("Nessuna sessione attiva.")
        return
    _echo(session.log.to_chat_md())


@session_app.command("close")
def session_close(
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Chiude manualmente la sessione attiva (debug)."""
    settings = load_settings(config_path=config)
    manager = _get_session_manager(settings)
    session = manager.current_session()
    if session is None:
        _echo("Nessuna sessione da chiudere.")
        return
    manager.close_session(session)
    _echo(f"Sessione {session.session_id} chiusa.")


@session_app.command("consolidate")
def session_consolidate(
    session_id: str = typer.Option(..., "--session-id", help="ID sessione da consolidare"),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Esegue il consolidamento di una sessione (richiede Ollama + async_model).

    Prima di caricare async_model, fa unload di sync_model per liberare VRAM."""
    from pathlib import Path as _Path
    from segretario.connectors.async_llm_client import build_async_client
    from segretario.flow02.session.consolidation import ConsolidationJob

    settings = load_settings(config_path=config)
    session_jsonl = _Path(settings.taskboard.sqlite_path).parent / "sessions" / f"session_{session_id}.jsonl"
    if not session_jsonl.exists():
        _echo(f"Sessione non trovata: {session_jsonl}")
        raise typer.Exit(1)

    client = build_async_client(settings.llm)
    job = ConsolidationJob(
        client=client,
        sync_model_to_unload=settings.llm.sync_model,
        ollama_base_url=settings.llm.base_url,
    )
    result = job.run(session_jsonl, _Path(settings.vault.path))

    if result.ok:
        _echo(f"Consolidamento ok: {result.message}")
        for item in result.extracted_facts:
            _echo(f"  - {item}")
    else:
        _echo(f"Consolidamento fallito: {result.message}")
        raise typer.Exit(1)


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
        f"LLM:          {settings.llm.provider} / {settings.llm.sync_model}",
        f"Ollama:       {ollama_status}",
        f"Taskboard:    {taskboard_status}",
        f"Audit:        {audit_status}",
        f"Google:       {google_status}",
        f"Web:          {'enabled' if settings.web.enabled else 'disabled'}",
        f"Scheduler:    {'enabled' if settings.scheduler.enabled else 'disabled'}",
        "---------------------------",
    ]
    _echo("\n".join(lines))


@app.command()
def start(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Open the local operator console with the current actionable state."""
    settings = load_settings(config_path=config)
    for line in _start_lines(settings):
        _echo(line)


@app.command()
def work(
    limit: int = typer.Option(
        3,
        "--limit",
        min=0,
        help="Maximum extract/OCR tasks to queue and run per stage.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Run a bounded local work cycle without manual taskboard juggling."""
    settings = load_settings(config_path=config)
    _run_work_cycle(settings, limit=limit)


@app.command()
def chat(
    once: str | None = typer.Option(
        None,
        "--once",
        help="Handle one instruction and exit; omit for an interactive loop.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Interact with the local Segretario command layer."""
    settings = load_settings(config_path=config)
    if once is not None:
        _handle_chat_instruction(settings, once)
        return

    _echo("Segretario chat. Type 'exit' to stop.")
    while True:
        try:
            instruction = typer.prompt("segretario")
        except (EOFError, KeyboardInterrupt):
            _echo("")
            return
        if instruction.strip().casefold() in {"exit", "quit", "q"}:
            return
        _handle_chat_instruction(settings, instruction)


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


@vault_app.command("backup")
def vault_backup(
    target: Path | None = typer.Option(None, "--target", help="Override target directory"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Crea un backup manuale del vault."""
    from segretario.backup.manager import BackupKind, BackupManager

    settings = load_settings(config_path=config)
    backup_settings = settings.backup
    if target:
        backup_settings = backup_settings.model_copy(update={"target_dir": target})
    manager = BackupManager(backup_settings, settings.vault.path)
    result = manager.create(kind=BackupKind.MANUAL)
    if result.ok:
        _echo(f"Backup ok: {result.path}")
        _echo(f"Size: {result.size_bytes / (1024 * 1024):.1f} MB")
        _echo(f"SHA256: {result.sha256}")
    else:
        _echo(f"Backup failed: {result.message}")
        raise typer.Exit(1)


@vault_app.command("backup-list")
def vault_backup_list(
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Lista i backup esistenti."""
    from segretario.backup.manager import BackupManager

    settings = load_settings(config_path=config)
    manager = BackupManager(settings.backup, settings.vault.path)
    backups = manager.list_backups()
    if not backups:
        _echo("Nessun backup trovato.")
        return
    for b in backups:
        size_mb = b["size_bytes"] / (1024 * 1024)
        _echo(f"{b['mtime']}  [{b['kind']:8}]  {b['name']}  ({size_mb:.1f} MB)")


@vault_app.command("restore")
def vault_restore(
    backup_name: str = typer.Argument(..., help="Nome del file di backup"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Solo verifica integrita"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Ripristina un backup nel vault corrente (DISTRUTTIVO senza --dry-run)."""
    from segretario.backup.manager import BackupManager

    settings = load_settings(config_path=config)
    manager = BackupManager(settings.backup, settings.vault.path)
    if not dry_run:
        _echo(f"ATTENZIONE: questa operazione SOVRASCRIVE il vault corrente: {settings.vault.path}")
        confirm = typer.confirm("Procedere?")
        if not confirm:
            _echo("Restore annullato.")
            raise typer.Exit(0)
    result = manager.restore(backup_name, dry_run=dry_run)
    if result.ok:
        _echo(result.message)
    else:
        _echo(f"Restore failed: {result.message}")
        raise typer.Exit(1)


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
    executed = _run_agent_batch(settings, limit=limit)

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
            or str(task.get("command", "")).startswith("extract.")
            or str(task.get("command", "")).startswith("ocr.")
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


def _start_lines(settings) -> list[str]:
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    pending = taskboard.list_tasks(limit=100, status=TaskStatus.QUEUED.value)
    waiting = taskboard.list_tasks(limit=100, status=TaskStatus.WAITING_CONFIRMATION.value)
    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    vault_ok = settings.vault.path.is_dir()
    audit_ok = audit.verify()
    next_step = "run `segretario work --limit 3`"
    if waiting:
        next_step = "review waiting confirmations with `segretario tasks --status waiting_confirmation`"
    elif pending:
        next_step = "run queued work with `segretario agents run --limit 3`"
    return [
        "Segretario ready",
        f"Project: {settings.project_name}",
        f"Vault: {'ok' if vault_ok else 'missing'}",
        f"Audit: {'ok' if audit_ok else 'failed'}",
        f"Pending tasks: {len(pending)}",
        f"Waiting confirmations: {len(waiting)}",
        f"Next: {next_step}",
    ]


def _handle_chat_instruction(settings, instruction: str) -> None:
    text = instruction.strip()
    lowered = text.casefold()
    if not text:
        _echo("No instruction.")
        return
    if lowered in {"start", "status"}:
        for line in _start_lines(settings):
            _echo(line)
        return
    if lowered == "tasks":
        for line in _task_list_lines(settings, limit=10):
            _echo(line)
        return
    if lowered == "work":
        _run_work_cycle(settings, limit=3)
        return
    if lowered.startswith("search "):
        _print_search_results(settings, text[7:].strip())
        return
    if lowered.startswith("query "):
        llm = build_local_llm(settings.llm)
        try:
            result = query_vault(settings.vault.path, text[6:].strip(), llm=llm)
        except Exception as exc:
            _echo(str(exc))
            return
        _echo(result.answer)
        return
    _echo("Supported: start, status, tasks, work, search <text>, query <question>, exit")


def _print_search_results(settings, query_text: str) -> None:
    result = _build_core(settings).handle(
        TaskRequest(
            command="search",
            payload={
                "vault_path": settings.vault.path,
                "query": query_text,
                "skip_paths": settings.vault.skip_paths,
            },
            risk="low",
            action="vault.search",
        )
    )
    if not result.ok:
        _echo(result.message)
        return
    results = result.output
    if not results:
        _echo("No matches found.")
        return
    for item in results:
        _echo(f"{item['path']}:{item['line']}: {item['snippet']}")


def _task_list_lines(settings, *, limit: int) -> list[str]:
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    rows = taskboard.list_tasks(limit=limit)
    if not rows:
        return ["No tasks found."]
    lines: list[str] = []
    for task in rows:
        reason = ""
        if task["status"] in {"denied", "failed", "cancelled"}:
            reason = task.get("last_error") or task.get("confirmation_reason") or ""
        elif task["status"] != "completed":
            reason = task.get("confirmation_reason") or task.get("last_error") or ""
        suffix = f" - {reason}" if reason else ""
        lines.append(f"{task['id']}: {task['command']} [{task['status']}] risk={task['risk']}{suffix}")
    return lines


def _run_work_cycle(settings, *, limit: int) -> None:
    _echo("Work cycle")
    extract_queued = _queue_extract_pdf_tasks(settings, limit=limit)
    _echo(f"Queued extract tasks: {len(extract_queued)}")
    for task_id, source_path in extract_queued:
        _echo(f"- {task_id}: {source_path}")
    extract_executed = _run_agent_batch(settings, limit=limit)
    _echo(f"Executed extract tasks: {len(extract_executed)}")
    for task_id, command, status, output_ref in extract_executed:
        suffix = f" -> {output_ref}" if output_ref else ""
        _echo(f"- {task_id}: {command} {status}{suffix}")

    ocr_queued = _queue_ocr_tasks(settings, limit=limit)
    _echo(f"Queued OCR tasks: {len(ocr_queued)}")
    for task_id, marker_path in ocr_queued:
        _echo(f"- {task_id}: {marker_path}")
    ocr_executed = _run_agent_batch(settings, limit=limit)
    _echo(f"Executed OCR tasks: {len(ocr_executed)}")
    for task_id, command, status, output_ref in ocr_executed:
        suffix = f" -> {output_ref}" if output_ref else ""
        _echo(f"- {task_id}: {command} {status}{suffix}")

    ingest_queued = _queue_ingest_tasks(settings, limit=limit)
    _echo(f"Queued ingest tasks: {len(ingest_queued)}")
    for task_id, marker_path in ingest_queued:
        _echo(f"- {task_id}: {marker_path}")
    ingest_executed = _run_agent_batch(settings, limit=limit)
    _echo(f"Executed ingest tasks: {len(ingest_executed)}")
    for task_id, command, status, output_ref in ingest_executed:
        suffix = f" -> {output_ref}" if output_ref else ""
        _echo(f"- {task_id}: {command} {status}{suffix}")


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
            or command.startswith("extract.")
            or command.startswith("ocr.")
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


def _run_agent_batch(settings, *, limit: int) -> list[tuple[int, str, str, str | None]]:
    executed: list[tuple[int, str, str, str | None]] = []
    for _ in range(limit):
        result = _run_one_agent_task(settings)
        if result is None:
            break
        executed.append(result)
    return executed


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


@extract_app.command("queue")
def extract_queue_command(
    kind: str = typer.Option("pdf", "--kind", help="Extraction kind to queue."),
    limit: int = typer.Option(
        5,
        "--limit",
        min=0,
        help="Maximum number of extract_candidate files to queue.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Queue safe extraction tasks from the extract plan without executing them."""
    if kind != "pdf":
        _echo(f"unsupported extract kind: {kind}")
        raise typer.Exit(1)
    settings = load_settings(config_path=config)
    queued = _queue_extract_pdf_tasks(settings, limit=limit)
    _echo(f"Queued extract tasks: {len(queued)}")
    for task_id, source_path in queued:
        _echo(f"- {task_id}: {source_path}")


def _queue_extract_pdf_tasks(settings, *, limit: int) -> list[tuple[int, str]]:
    plan = plan_extraction(settings.vault.path, skip_paths=settings.vault.skip_paths)
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    payload_store = TaskPayloadStore(settings.taskboard.sqlite_path.parent)
    active_sources = _active_sources_for_command(taskboard, payload_store, "extract.pdf")
    candidates = [
        source_path
        for source_path in _extract_plan_candidates(plan.items, kind="pdf")
        if source_path not in active_sources
    ][:limit]
    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    queued: list[tuple[int, str]] = []
    for source_path in candidates:
        request = TaskRequest(
            command="extract.pdf",
            payload={
                "vault_path": settings.vault.path,
                "source_path": source_path,
                "action": "extract.pdf",
                "skip_paths": settings.vault.skip_paths,
            },
            risk="low",
            action=PermissionKernel.OUTPUT_WRITE,
            source="extract",
            requested_by="segretario",
        )
        task = taskboard.create_task(
            source="extract",
            requested_by="segretario",
            command="extract.pdf",
            risk="low",
            assigned_agent="agent-runner",
            input_ref="pending",
        )
        payload_ref = payload_store.save(int(task["id"]), request)
        taskboard.update_input_ref(int(task["id"]), payload_ref)
        audit.append_event("extract.task_queued", {"task_id": task["id"], "source_path": source_path})
        queued.append((int(task["id"]), source_path))
    return queued


@extract_app.command("pdf")
def extract_pdf_command(
    source: str,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Extract one PDF source to raw/extracted staging."""
    settings = load_settings(config_path=config)
    result = _build_core(settings).handle(
        TaskRequest(
            command="extract.pdf",
            payload={
                "vault_path": settings.vault.path,
                "source_path": source,
                "action": "extract.pdf",
                "skip_paths": settings.vault.skip_paths,
            },
            risk="low",
            action=PermissionKernel.OUTPUT_WRITE,
        )
    )
    if not result.ok:
        _echo(result.message)
        raise typer.Exit(1)
    output = result.output or {}
    _echo(f"extracted: {output['path']}")


@ocr_app.command("queue")
def ocr_queue_command(
    limit: int = typer.Option(
        5,
        "--limit",
        min=0,
        help="Maximum number of needs_ocr markers to queue.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to segretario.yaml.",
    ),
) -> None:
    """Queue local OCR tasks for extracted PDF markers that need OCR."""
    settings = load_settings(config_path=config)
    queued = _queue_ocr_tasks(settings, limit=limit)
    _echo(f"Queued OCR tasks: {len(queued)}")
    for task_id, marker_path in queued:
        _echo(f"- {task_id}: {marker_path}")


def _queue_ocr_tasks(settings, *, limit: int) -> list[tuple[int, str]]:
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    payload_store = TaskPayloadStore(settings.taskboard.sqlite_path.parent)
    active_markers = _active_markers_for_command(taskboard, payload_store, "ocr.pdf")
    candidates = [
        marker_path
        for marker_path in _ocr_needs_ocr_markers(settings.vault.path, skip_paths=settings.vault.skip_paths)
        if marker_path not in active_markers
    ][:limit]
    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    queued: list[tuple[int, str]] = []
    for marker_path in candidates:
        request = TaskRequest(
            command="ocr.pdf",
            payload={
                "vault_path": settings.vault.path,
                "marker_path": marker_path,
                "action": "ocr.pdf",
                "skip_paths": settings.vault.skip_paths,
                "tesseract_cmd": settings.ocr.tesseract_cmd,
            },
            risk="low",
            action=PermissionKernel.OUTPUT_WRITE,
            source="ocr",
            requested_by="segretario",
        )
        task = taskboard.create_task(
            source="ocr",
            requested_by="segretario",
            command="ocr.pdf",
            risk="low",
            assigned_agent="agent-runner",
            input_ref="pending",
        )
        payload_ref = payload_store.save(int(task["id"]), request)
        taskboard.update_input_ref(int(task["id"]), payload_ref)
        audit.append_event("ocr.task_queued", {"task_id": task["id"], "marker_path": marker_path})
        queued.append((int(task["id"]), marker_path))
    return queued


def _raw_plan_ingest_candidates(items: list[str]) -> list[str]:
    candidates: list[str] = []
    for item in items:
        if " -> ingest_candidate:" not in item:
            continue
        source = item.removeprefix("- ").split(" -> ", 1)[0].strip()
        if source:
            candidates.append(source)
    return candidates


def _ocr_needs_ocr_markers(
    vault_path: Path,
    *,
    skip_paths: list[str] | tuple[str, ...] | None,
) -> list[str]:
    vault = Path(vault_path)
    extracted_dir = vault / "raw" / "extracted"
    if not extracted_dir.exists():
        return []
    markers: list[str] = []
    for marker in sorted(extracted_dir.rglob("*.md")):
        if not marker.is_file():
            continue
        relative = marker.relative_to(vault).as_posix()
        if matches_configured_skip_path(relative, skip_paths):
            continue
        metadata, _body = parse_frontmatter(marker.read_text(encoding="utf-8", errors="replace"))
        if metadata.get("status") == "needs_ocr" and isinstance(metadata.get("source_path"), str):
            markers.append(relative)
    return markers


_INGEST_READY_STATUSES = {"extracted", "ocr_extracted"}


def _ingest_ready_markers(
    vault_path: Path,
    *,
    skip_paths: list[str] | tuple[str, ...] | None,
) -> list[str]:
    vault = Path(vault_path)
    extracted_dir = vault / "raw" / "extracted"
    if not extracted_dir.exists():
        return []
    ready: list[str] = []
    for marker in sorted(extracted_dir.rglob("*.md")):
        if not marker.is_file():
            continue
        relative = marker.relative_to(vault).as_posix()
        if matches_configured_skip_path(relative, skip_paths):
            continue
        metadata, _body = parse_frontmatter(marker.read_text(encoding="utf-8", errors="replace"))
        if metadata.get("status") in _INGEST_READY_STATUSES:
            ready.append(relative)
    return ready


def _queue_ingest_tasks(settings, *, limit: int) -> list[tuple[int, str]]:
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    payload_store = TaskPayloadStore(settings.taskboard.sqlite_path.parent)
    active_sources = _active_ingest_sources(taskboard, payload_store)
    candidates = [
        marker_path
        for marker_path in _ingest_ready_markers(settings.vault.path, skip_paths=settings.vault.skip_paths)
        if marker_path not in active_sources
    ][:limit]
    audit = AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    queued: list[tuple[int, str]] = []
    for marker_path in candidates:
        request = TaskRequest(
            command="ingest",
            payload={
                "vault_path": settings.vault.path,
                "source_path": marker_path,
                "action": "ingest",
                "auto": True,
                "skip_paths": settings.vault.skip_paths,
            },
            risk="low",
            action=PermissionKernel.KNOWLEDGE_WRITE,
            source="ingest",
            requested_by="segretario",
        )
        task = taskboard.create_task(
            source="ingest",
            requested_by="segretario",
            command="ingest",
            risk="low",
            assigned_agent="agent-runner",
            input_ref="pending",
        )
        payload_ref = payload_store.save(int(task["id"]), request)
        taskboard.update_input_ref(int(task["id"]), payload_ref)
        audit.append_event("ingest.task_queued", {"task_id": task["id"], "marker_path": marker_path})
        queued.append((int(task["id"]), marker_path))
    return queued


def _extract_plan_candidates(items: list[str], *, kind: str) -> list[str]:
    expected_reason = f"{kind} text extraction candidate"
    candidates: list[str] = []
    for item in items:
        if " -> extract_candidate:" not in item or expected_reason not in item:
            continue
        source = item.removeprefix("- ").split(" -> ", 1)[0].strip()
        if source:
            candidates.append(source)
    return candidates


def _active_ingest_sources(
    taskboard: TaskboardStore,
    payload_store: TaskPayloadStore,
) -> set[str]:
    return _active_sources_for_command(taskboard, payload_store, "ingest")


def _active_sources_for_command(
    taskboard: TaskboardStore,
    payload_store: TaskPayloadStore,
    command: str,
) -> set[str]:
    active_statuses = {
        TaskStatus.QUEUED.value,
        TaskStatus.RUNNING.value,
        TaskStatus.WAITING_CONFIRMATION.value,
    }
    sources: set[str] = set()
    for task in taskboard.list_tasks(limit=1000):
        if task.get("command") != command or task.get("status") not in active_statuses:
            continue
        try:
            request = payload_store.load(str(task.get("input_ref") or ""))
        except (FileNotFoundError, ValueError, KeyError):
            continue
        source_path = request.payload.get("source_path")
        if source_path:
            sources.add(str(source_path).replace("\\", "/"))
    return sources


def _active_markers_for_command(
    taskboard: TaskboardStore,
    payload_store: TaskPayloadStore,
    command: str,
) -> set[str]:
    active_statuses = {
        TaskStatus.QUEUED.value,
        TaskStatus.RUNNING.value,
        TaskStatus.WAITING_CONFIRMATION.value,
    }
    markers: set[str] = set()
    for task in taskboard.list_tasks(limit=1000):
        if task.get("command") != command or task.get("status") not in active_statuses:
            continue
        try:
            request = payload_store.load(str(task.get("input_ref") or ""))
        except (FileNotFoundError, ValueError, KeyError):
            continue
        marker_path = request.payload.get("marker_path")
        if marker_path:
            markers.add(str(marker_path).replace("\\", "/"))
    return markers


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
        "extract.pdf": ExtractionAgent(),
        "ocr.pdf": ExtractionAgent(),
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


# ---------------------------------------------------------------------------
# recall sub-app commands
# ---------------------------------------------------------------------------

@recall_app.command("reindex")
def recall_reindex(
    force: bool = typer.Option(False, "--force", help="Re-embed all notes regardless of hash."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report changes without writing (not yet implemented)."),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Reindex the vault for semantic recall."""
    if dry_run:
        _echo("Recall index: DRY RUN — would scan vault and report changes without writing")
        _echo("(dry-run not yet implemented in VaultIndexer)")
        return

    from segretario.recall.embedder import OllamaEmbedder
    from segretario.recall.indexer import VaultIndexer
    from segretario.recall.sqlite_vec_store import SqliteVecStore

    settings = load_settings(config_path=config)
    recall = settings.recall

    recall_cfg = settings.recall
    if not recall_cfg.enabled:
        typer.echo("Recall is disabled in config (recall.enabled=false). Nothing to reindex.")
        raise typer.Exit(0)

    if force:
        _echo("Recall index: force reindexing all notes...")
    else:
        _echo("Recall index: reindexing...")

    try:
        embedder = OllamaEmbedder(
            model=recall.embedding_model,
            base_url=recall.ollama_base_url,
        )
        store = SqliteVecStore(
            db_path=recall.db_path,
            embedding_model=recall.embedding_model,
        )
        indexer = VaultIndexer(
            vault_path=settings.vault.path,
            store=store,
            embedder=embedder,
            skip_paths=recall.skip_paths,
        )
        result = indexer.reindex(force=force)
    except Exception as exc:
        _echo(f"Reindex failed: {exc}")
        raise typer.Exit(1) from exc

    _echo(
        f"Reindex complete: indexed={result.indexed} deleted={result.deleted} "
        f"skipped_unchanged={result.skipped_unchanged} errors={len(result.errors)}"
    )
    if result.errors:
        for err in result.errors[:10]:
            _echo(f"  error: {err}")


@recall_app.command("status")
def recall_status(
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Show the recall subsystem status."""
    import json as _json

    from segretario.recall.health import check_embedder, check_store

    settings = load_settings(config_path=config)
    recall = settings.recall

    _echo("Recall status:")
    _echo(f"  Enabled:        {str(recall.enabled).lower()}")
    _echo(f"  Model:          {recall.embedding_model}")
    _echo(f"  DB:             {recall.db_path}")

    # Last reindex info from state file
    state_path = recall.state_path
    last_reindex_str = "never"
    if state_path.exists():
        try:
            data = _json.loads(state_path.read_text(encoding="utf-8"))
            last_run = data.get("last_run", "")
            indexed_count = data.get("indexed_count", "?")
            if last_run:
                last_reindex_str = f"{last_run} ({indexed_count} notes)"
        except Exception:
            last_reindex_str = "(corrupt state file)"
    _echo(f"  Last reindex:   {last_reindex_str}")

    if not recall.enabled:
        _echo("  Embedder:       (not checked — recall disabled)")
        _echo("  Store:          (not checked — recall disabled)")
        return

    # Check embedder health
    from segretario.recall.embedder import OllamaEmbedder
    from segretario.recall.sqlite_vec_store import SqliteVecStore

    try:
        embedder = OllamaEmbedder(
            model=recall.embedding_model,
            base_url=recall.ollama_base_url,
        )
        embedder_ok, embedder_reason = check_embedder(embedder)
        _echo(f"  Embedder:       {'OK' if embedder_ok else 'FAIL: ' + embedder_reason}")
    except Exception as exc:
        _echo(f"  Embedder:       FAIL: {exc}")

    try:
        store = SqliteVecStore(
            db_path=recall.db_path,
            embedding_model=recall.embedding_model,
        )
        store_ok, store_reason = check_store(store)
        _echo(f"  Store:          {'OK' if store_ok else 'FAIL: ' + store_reason}")
    except Exception as exc:
        _echo(f"  Store:          FAIL: {exc}")


@recall_app.command("search")
def recall_search(
    query: str = typer.Argument(..., help="Search query."),
    k: int = typer.Option(5, "--k", help="Number of results to return."),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Search the vault using semantic recall."""
    from segretario.flow02.recall_engine import RecallEngine
    from segretario.recall.models import RecallEngineState, RecallMode

    settings = load_settings(config_path=config)
    vault_path = settings.vault.path
    index_path = vault_path / "meta" / "index.md"

    engine = RecallEngine(index_path=index_path, recall_settings=settings.recall)
    result = engine.recall(query, k=k)

    _echo(f"State:  {result.state.value}")
    _echo(f"Mode:   {result.mode_used.value}")

    if result.hits:
        _echo("Hits:")
        for hit in result.hits:
            _echo(f"  {hit.note_path} (score {hit.score:.3f})")
            if hit.content_preview:
                preview_line = hit.content_preview.splitlines()[0][:120] if hit.content_preview else ""
                if preview_line:
                    _echo(f'    "{preview_line}"')

    if result.wizard_required is not None:
        _echo(f"Wizard: {result.wizard_required.value}")
        if result.wizard_context:
            for key, val in result.wizard_context.items():
                _echo(f"Context: {key}={val}")
    else:
        _echo("Wizard: None")


@recall_app.command("reset-wizard")
def recall_reset_wizard(
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Reset the recall activation wizard (set user_dismissed_wizard to False)."""
    import tempfile
    import os

    settings = load_settings(config_path=config)

    # Determine the config file to update
    config_path = settings.loaded_config_path
    if config_path is None:
        config_path = default_config_path()
        if not config_path.exists():
            _echo("No segretario.yaml found. Create one first.")
            raise typer.Exit(1)

    # Load raw YAML
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        _echo("Invalid config file format.")
        raise typer.Exit(1)

    # Update recall.user_dismissed_wizard
    if "recall" not in raw or not isinstance(raw.get("recall"), dict):
        raw["recall"] = {}
    raw["recall"]["user_dismissed_wizard"] = False

    # Write back atomically
    new_content = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=config_path.parent,
        suffix=".tmp",
        prefix=config_path.stem + "_",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(tmp_path, config_path)
    except Exception as exc:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        _echo(f"Failed to write config: {exc}")
        raise typer.Exit(1) from exc

    _echo("Wizard reset: user_dismissed_wizard set to False.")
    _echo("Run 'segretario recall search' to trigger the activation wizard again.")

