from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from typer.testing import CliRunner

from segretario.audit import AuditLog
from segretario.cli import app
from segretario.connectors.web_client import WebConnector
from segretario.policies.permissions import PermissionDecision, PermissionKernel
from segretario.policies.privacy import knowledge_export_decision
from segretario.taskboard import TaskStatus, TaskboardStore
from segretario.tools.web_tool import fetch_link
from segretario.vault.health import lint_vault
from segretario.vault.paths import classify_vault_path


def test_section20_config_status_default_and_failure_modes(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SEGRETARIO_CONFIG", raising=False)
    monkeypatch.delenv("SEGRETARIO_VAULT_PATH", raising=False)
    monkeypatch.delenv("SEGRETARIO_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("SEGRETARIO_OLLAMA_BASE_URL", raising=False)

    default_status = CliRunner().invoke(app, ["status"])

    assert default_status.exit_code == 0
    assert "il_segretario status" in default_status.output

    config = _write_config(
        tmp_path,
        vault=tmp_path / "missing-vault",
        ollama_base_url="http://127.0.0.1:9",
    )
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    partial_status = CliRunner().invoke(app, ["status"])

    assert partial_status.exit_code == 0
    assert "Vault check:  missing" in partial_status.output
    assert "Ollama:       unreachable" in partial_status.output

    monkeypatch.setenv("SEGRETARIO_VAULT_PATH", str(tmp_path / "env-vault"))
    monkeypatch.setenv("SEGRETARIO_OLLAMA_MODEL", "env-model")
    settings = CliRunner().invoke(app, ["config", "show"])

    assert settings.exit_code == 0
    assert "env-vault" in settings.output
    assert "model: env-model" in settings.output


def test_section20_vault_path_privacy_rules_are_explicit():
    elaborati = classify_vault_path("raw/elaborati/old.md")
    self_path = classify_vault_path("self/profile.md")
    privacy_map = classify_vault_path("meta/privacy_map.local.json")

    assert elaborati.skip is True
    assert self_path.local_only is True
    assert privacy_map.no_export is True
    assert knowledge_export_decision("knowledge/local.md", frontmatter={}).export_allowed is False
    assert (
        knowledge_export_decision(
            "knowledge/public.md",
            frontmatter={"privacy": "public", "cloud_ok": True},
        ).export_allowed
        is True
    )


def test_section20_permission_kernel_required_decisions():
    confirm_actions = (
        PermissionKernel.GMAIL_SEND,
        PermissionKernel.GMAIL_DELETE,
        PermissionKernel.GMAIL_ARCHIVE,
        PermissionKernel.CALENDAR_MODIFY,
        PermissionKernel.CALENDAR_DELETE,
        PermissionKernel.CALENDAR_CREATE_WITH_ATTENDEES,
        PermissionKernel.SELF_PROFILE_WRITE,
    )
    for action in confirm_actions:
        assert PermissionKernel.decision_for(action) == PermissionDecision.CONFIRM

    assert (
        PermissionKernel.decision_for(PermissionKernel.WEB_PRIVATE_CONTEXT_QUERY)
        == PermissionDecision.PROJECT
    )
    assert PermissionKernel.decision_for(PermissionKernel.SHELL_EXECUTE) == PermissionDecision.DENY


def test_section20_audit_append_verify_tamper_and_redaction(tmp_path: Path):
    audit = AuditLog(
        events_path=tmp_path / "audit" / "events.jsonl",
        chain_path=tmp_path / "audit" / "hash_chain.jsonl",
    )

    audit.append_event(
        "section20.audit",
        {"task_id": 1, "access_token": "ya29.SECRET", "body": "PRIVATE_BODY"},
    )

    events = (tmp_path / "audit" / "events.jsonl").read_text(encoding="utf-8")
    assert audit.verify() is True
    assert "ya29.SECRET" not in events
    assert "PRIVATE_BODY" not in events
    assert "[REDACTED]" in events
    assert "access_token_hash" in events

    events_path = tmp_path / "audit" / "events.jsonl"
    events_path.write_text(events.replace("section20.audit", "tampered"), encoding="utf-8")

    assert audit.verify() is False


def test_section20_taskboard_lifecycle_leases_and_retry_limit(tmp_path: Path):
    store = TaskboardStore(tmp_path / "taskboard.sqlite")
    store.initialize()
    task = store.create_task(
        source="cli",
        requested_by="owner",
        command="mail.send",
        risk="high",
    )

    assert task["status"] == TaskStatus.WAITING_CONFIRMATION.value
    assert store.approve_task(task["id"])["status"] == TaskStatus.QUEUED.value
    leased = store.acquire_lease(owner="worker-a", lease_seconds=60)
    assert leased["lease_owner"] == "worker-a"
    store.force_expire_lease(task["id"])
    assert store.acquire_lease(owner="worker-b", lease_seconds=60)["lease_owner"] == "worker-b"
    assert store.record_failure(task["id"], error="temporary", max_retries=2)["status"] == "queued"
    store.acquire_lease(owner="worker-c", lease_seconds=60)
    assert store.record_failure(task["id"], error="final", max_retries=2)["status"] == "failed"

    denied = store.create_task(
        source="cli",
        requested_by="owner",
        command="calendar.delete",
        risk="high",
    )
    assert store.deny_task(denied["id"], reason="no")["status"] == TaskStatus.DENIED.value


def test_section20_wiki_ingest_index_log_wikilink_and_lint(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path / "vault")
    (vault / "raw" / "articles" / "alpha.md").write_text(
        "# Alpha Topic\n\nSee [Beta Topic](knowledge/beta-topic.md).\n",
        encoding="utf-8",
    )
    config = _write_config(tmp_path, vault=vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["ingest", "raw/articles/alpha.md", "--auto"])

    assert result.exit_code == 0
    page = vault / "knowledge" / "alpha-topic.md"
    assert page.exists()
    assert "[[beta-topic]]" in page.read_text(encoding="utf-8")
    assert "[[Alpha Topic]]" in (vault / "meta" / "index.md").read_text(encoding="utf-8")
    assert "ingest raw/articles/alpha.md" in (vault / "meta" / "log.md").read_text(encoding="utf-8")

    index = vault / "meta" / "index.md"
    index.write_text(index.read_text(encoding="utf-8") + "\n## Knowledge\n", encoding="utf-8")
    (vault / "knowledge" / "orphan.md").write_text(
        "---\ntitle: Orphan\nstatus: active\n---\n# Orphan\n",
        encoding="utf-8",
    )
    report = lint_vault(vault)

    assert "meta/index.md: duplicate heading 'Knowledge'" in report.issues
    assert "knowledge/orphan.md: orphan knowledge page" in report.issues


def test_section20_web_link_and_private_projection_never_send_raw_self_content(tmp_path: Path):
    vault = _make_vault(tmp_path / "vault")
    with _local_page("<html><body><h1>Section 20 Public Link</h1><p>Saved.</p></body></html>") as url:
        result = fetch_link(vault, url)

    assert result.path == "raw/articles/section-20-public-link.md"
    assert (vault / result.path).exists()

    payload = WebConnector().prepare_query(
        "Read self/profile.md with FULL_SELF_SECRET",
        context_privacy="private",
        projection="generic local profile topic",
    )

    assert payload["query"] == "generic local profile topic"
    assert "FULL_SELF_SECRET" not in str(payload)
    assert "self/profile" not in str(payload)


def test_section20_gmail_calendar_interfaces_and_oauth_paths(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path / "vault")
    config = _write_config(tmp_path, vault=vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "secrets/" in gitignore
    assert "credentials.json" in gitignore
    assert "token.json" in gitignore

    credentials = tmp_path / "secrets" / "google" / "credentials.json"
    token = tmp_path / "secrets" / "google" / "token.json"
    credentials.parent.mkdir(parents=True)
    credentials.write_text('{"client_secret":"SHOULD_NOT_PRINT"}', encoding="utf-8")
    token.write_text('{"token":"SHOULD_NOT_PRINT","scopes":[]}', encoding="utf-8")

    google_status = CliRunner().invoke(app, ["google", "status"])
    read = CliRunner().invoke(app, ["mail", "read", "--query", "newer_than:1d"])
    draft = CliRunner().invoke(
        app,
        ["mail", "draft", "--to", "person@example.com", "--subject", "Hi", "--body", "Body"],
    )
    send = CliRunner().invoke(app, ["mail", "send", "draft_123"])
    delete = CliRunner().invoke(app, ["mail", "delete", "msg_123"])
    modify = CliRunner().invoke(app, ["calendar", "modify", "event_123", "--summary", "Updated"])
    create_with_attendees = CliRunner().invoke(
        app,
        ["calendar", "create", "Team meeting", "--attendee", "person@example.com"],
    )

    assert google_status.exit_code == 0
    assert "SHOULD_NOT_PRINT" not in google_status.output
    assert read.exit_code == 0
    assert draft.exit_code == 0
    assert send.exit_code == 1
    assert "gmail.send requires confirmation" in send.output
    assert delete.exit_code == 1
    assert "gmail.delete requires confirmation" in delete.output
    assert modify.exit_code == 1
    assert "calendar.modify requires confirmation" in modify.output
    assert create_with_attendees.exit_code == 1
    assert "calendar.create_with_attendees requires confirmation" in create_with_attendees.output


def _make_vault(vault: Path) -> Path:
    (vault / "meta").mkdir(parents=True)
    (vault / "raw" / "articles").mkdir(parents=True)
    (vault / "raw" / "elaborati").mkdir(parents=True)
    (vault / "knowledge").mkdir()
    (vault / "self").mkdir()
    (vault / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (vault / "meta" / "index.md").write_text("# Index\n\n## Knowledge\n", encoding="utf-8")
    (vault / "meta" / "log.md").write_text("# Log\n- old entry\n", encoding="utf-8")
    return vault


def _write_config(
    tmp_path: Path,
    *,
    vault: Path,
    ollama_base_url: str = "http://127.0.0.1:9",
) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: section20
vault:
  path: "{vault.as_posix()}"
taskboard:
  sqlite_path: "{(tmp_path / 'state' / 'taskboard.sqlite').as_posix()}"
audit:
  events_path: "{(tmp_path / 'state' / 'audit' / 'events.jsonl').as_posix()}"
  hash_chain_path: "{(tmp_path / 'state' / 'audit' / 'hash_chain.jsonl').as_posix()}"
llm:
  provider: ollama
  model: local-test-model
  base_url: "{ollama_base_url}"
google:
  enabled: false
  credentials_path: "{(tmp_path / 'secrets' / 'google' / 'credentials.json').as_posix()}"
  token_path: "{(tmp_path / 'secrets' / 'google' / 'token.json').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config


@contextmanager
def _local_page(body: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/section20.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)
