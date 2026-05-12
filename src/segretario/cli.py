from __future__ import annotations

from pathlib import Path

import typer
import yaml

from segretario.agents.ingest_agent import ConfirmationNeededError
from segretario.agents.ingest_agent import IngestAgent
from segretario.agents.maintenance_agent import MaintenanceAgent
from segretario.agents.research_agent import ResearchAgent
from segretario.agents.search_agent import SearchAgent
from segretario.agents.wiki_maintainer_agent import WikiMaintainerAgent
from segretario.app.core import SegretarioCore
from segretario.app.query import query_vault
from segretario.app.models import TaskRequest
from segretario.app.router import TaskRouter
from segretario.audit import AuditLog
from segretario.config.loader import default_config_path, load_settings
from segretario.taskboard import TaskboardStore
from segretario.tools.ollama_tool import build_local_llm

app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(help="Configuration commands.")
vault_app = typer.Typer(help="Vault commands.")
lint_app = typer.Typer(help="Lint commands.")
app.add_typer(config_app, name="config")
app.add_typer(vault_app, name="vault")
app.add_typer(lint_app, name="lint")


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
    typer.echo("\n".join(lines))


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
    typer.echo(yaml.safe_dump(settings.to_safe_dict(), sort_keys=False))


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
    typer.echo("\n".join(lines))


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
            payload={"vault_path": settings.vault.path, "query": query},
            risk="low",
            action="vault.search",
        )
    )
    if not result.ok:
        typer.echo(result.message)
        raise typer.Exit(1)
    results = result.output
    if not results:
        typer.echo("No matches found.")
        return
    for result in results:
        typer.echo(f"{result['path']}:{result['line']}: {result['snippet']}")


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
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(result.answer)


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
            payload={"vault_path": settings.vault.path, "action": "stats"},
            risk="low",
            action="vault.search",
        )
    )
    if not result.ok:
        typer.echo(result.message)
        raise typer.Exit(1)
    summary = result.output
    typer.echo("Vault stats")
    for area, count in summary["markdown_by_area"].items():
        typer.echo(f"{area}: {count}")
    typer.echo(f"total_markdown: {summary['total_markdown']}")


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
            payload={"vault_path": settings.vault.path, "action": "lint.wiki"},
            risk="low",
            action="output.write",
        )
    )
    if not result.ok:
        typer.echo(result.message)
        raise typer.Exit(1)
    report = result.output
    typer.echo(f"Lint report: {report['report_path']}")
    if report["issues"]:
        for issue in report["issues"]:
            typer.echo(f"- {issue}")
    else:
        typer.echo("- ok")


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
        typer.echo(str(exc))
        raise typer.Exit(1) from exc

    if not result.ok:
        typer.echo(result.message)
        raise typer.Exit(1)
    output = result.output
    action = "updated" if output["updated"] else "created"
    typer.echo(f"{action}: {output['path']}")


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
        typer.echo("web is disabled")
        raise typer.Exit(1)

    core = _build_core(settings)
    result = core.handle(
        TaskRequest(
            command="link",
            payload={
                "vault_path": settings.vault.path,
                "url": url,
                "save_dir": settings.web.save_dir,
            },
            risk="low",
            action="web.public_query",
        )
    )
    if not result.ok:
        typer.echo(result.message)
        raise typer.Exit(1)
    saved_path = result.output["path"]
    typer.echo(f"saved: {saved_path}")

    if ingest:
        ingest_result = core.handle(
            TaskRequest(
                command="ingest",
                payload={
                    "vault_path": settings.vault.path,
                    "source_path": saved_path,
                    "auto": True,
                },
                risk="low",
                action="knowledge.write",
            )
        )
        if not ingest_result.ok:
            typer.echo(ingest_result.message)
            raise typer.Exit(1)
        output = ingest_result.output
        action = "updated" if output["updated"] else "created"
        typer.echo(f"{action}: {output['path']}")


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
        typer.echo("web is disabled")
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
            },
            risk="low" if action == "web.public_query" else "medium",
            action=action,
        )
    )
    if not result.ok:
        typer.echo(result.message)
        raise typer.Exit(1)
    typer.echo(f"web query: {result.output['query']}")


def _build_core(settings) -> SegretarioCore:
    taskboard = TaskboardStore(settings.taskboard.sqlite_path)
    taskboard.initialize()
    return SegretarioCore(
        taskboard=taskboard,
        audit=AuditLog(
            events_path=settings.audit.events_path,
            chain_path=settings.audit.hash_chain_path,
        ),
        router=TaskRouter(
            {
                "search": SearchAgent(),
                "stats": MaintenanceAgent(),
                "lint.wiki": MaintenanceAgent(),
                "ingest": IngestAgent(),
                "link": ResearchAgent(),
                "web": ResearchAgent(),
                "meta.index.ensure": WikiMaintainerAgent(),
                "meta.log.append": WikiMaintainerAgent(),
            }
        ),
    )


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
