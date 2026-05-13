from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from segretario.cli import app
from segretario.connectors.google_oauth import (
    REQUIRED_GOOGLE_SCOPES,
    GoogleOAuthConnector,
)
from segretario.policies.permissions import PermissionDecision, PermissionKernel
from segretario.tools.calendar_tool import CalendarTool
from segretario.tools.gmail_tool import GmailTool


class FakeGmailClient:
    def __init__(self) -> None:
        self.created_drafts = []

    def search_messages(self, *, query: str) -> list[dict[str, str]]:
        return [
            {
                "id": "real_msg_1",
                "from": "sender@example.com",
                "subject": f"query={query}",
                "snippet": "real snippet",
            }
        ]

    def create_draft(self, *, to: str, subject: str, body: str) -> dict[str, str]:
        draft = {"id": "real_draft_1", "to": to, "subject": subject, "body": body}
        self.created_drafts.append(draft)
        return draft


class FakeCalendarClient:
    def __init__(self) -> None:
        self.updated_events = []
        self.deleted_events = []

    def list_events(self, *, max_results: int = 10) -> list[dict[str, object]]:
        return [
            {
                "id": "real_event_1",
                "summary": "Real Calendar Event",
                "when": "2026-05-19T07:00:00Z",
            }
        ]

    def get_event(self, *, event_ref: str) -> dict[str, object]:
        return {
            "id": event_ref,
            "summary": "Real Calendar Event",
            "when": "2026-05-19T07:00:00Z",
        }

    def update_event(self, *, event_ref: str, summary: str) -> dict[str, object]:
        event = {"id": event_ref, "summary": summary, "when": "2026-05-19T07:00:00Z"}
        self.updated_events.append(event)
        return event

    def delete_event(self, *, event_ref: str) -> dict[str, object]:
        self.deleted_events.append(event_ref)
        return {"id": event_ref, "deleted": True}


def test_google_oauth_status_reports_config_without_reading_secret_contents(tmp_path: Path):
    credentials = tmp_path / "credentials.json"
    token = tmp_path / "token.json"
    credentials.write_text('{"secret":"do-not-print"}', encoding="utf-8")
    token.write_text('{"token":"do-not-print"}', encoding="utf-8")

    status = GoogleOAuthConnector(credentials_path=credentials, token_path=token).status()

    assert status.configured is True
    assert status.credentials_path == str(credentials)
    assert status.token_path == str(token)
    assert "do-not-print" not in repr(status)


def test_google_oauth_status_reports_missing_scopes_without_token_contents(tmp_path: Path):
    credentials = tmp_path / "credentials.json"
    token = tmp_path / "token.json"
    credentials.write_text('{"secret":"do-not-print"}', encoding="utf-8")
    token.write_text(
        json.dumps(
            {
                "token": "do-not-print",
                "refresh_token": "do-not-print",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            }
        ),
        encoding="utf-8",
    )

    status = GoogleOAuthConnector(credentials_path=credentials, token_path=token).status()

    assert status.configured is True
    assert "https://www.googleapis.com/auth/gmail.modify" in status.missing_scopes
    assert "do-not-print" not in repr(status)


def test_google_oauth_credentials_reject_missing_required_scopes(tmp_path: Path):
    credentials = tmp_path / "credentials.json"
    token = tmp_path / "token.json"
    credentials.write_text('{"installed":{}}', encoding="utf-8")
    token.write_text(
        json.dumps(
            {
                "token": "token",
                "refresh_token": "refresh",
                "client_id": "client",
                "client_secret": "secret",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            }
        ),
        encoding="utf-8",
    )

    try:
        GoogleOAuthConnector(credentials_path=credentials, token_path=token).credentials()
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected missing scope error")

    assert "Google token missing OAuth scopes" in message
    assert "gmail.modify" in message
    assert "google login --force" in message


def test_google_status_cli_reports_missing_scopes(tmp_path: Path, monkeypatch):
    credentials = tmp_path / "secrets" / "google" / "credentials.json"
    token = tmp_path / "secrets" / "google" / "token.json"
    credentials.parent.mkdir(parents=True)
    credentials.write_text('{"secret":"do-not-print"}', encoding="utf-8")
    token.write_text(
        json.dumps(
            {
                "token": "do-not-print",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            }
        ),
        encoding="utf-8",
    )
    config = _write_config(tmp_path, tmp_path / "vault")
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["google", "status"])

    assert result.exit_code == 0
    assert "Google: configured" in result.output
    assert "Scopes: missing" in result.output
    assert "gmail.modify" in result.output
    assert "do-not-print" not in result.output


def test_required_google_scopes_include_mutating_gmail_and_calendar_access():
    assert "https://www.googleapis.com/auth/gmail.modify" in REQUIRED_GOOGLE_SCOPES
    assert "https://www.googleapis.com/auth/gmail.send" in REQUIRED_GOOGLE_SCOPES
    assert "https://www.googleapis.com/auth/calendar.events" in REQUIRED_GOOGLE_SCOPES


def test_gmail_tool_reads_messages_and_creates_local_drafts(tmp_path: Path):
    state_dir = tmp_path / "state" / "google"
    messages_path = state_dir / "gmail_messages.json"
    messages_path.parent.mkdir(parents=True)
    messages_path.write_text(
        json.dumps(
            [
                {
                    "id": "msg_1",
                    "from": "sender@example.com",
                    "subject": "Alpha",
                    "snippet": "hello",
                }
            ]
        ),
        encoding="utf-8",
    )
    tool = GmailTool(state_dir=state_dir)

    messages = tool.read(query="subject:Alpha")
    draft = tool.create_draft(to="person@example.com", subject="Reply", body="Body")

    assert messages == [
        {
            "id": "msg_1",
            "from": "sender@example.com",
            "subject": "Alpha",
            "snippet": "hello",
        }
    ]
    assert draft["id"].startswith("draft_")
    assert (state_dir / "gmail_drafts.jsonl").exists()
    assert "person@example.com" in (state_dir / "gmail_drafts.jsonl").read_text(
        encoding="utf-8"
    )


def test_gmail_tool_uses_google_client_when_available(tmp_path: Path):
    client = FakeGmailClient()
    tool = GmailTool(state_dir=tmp_path / "state" / "google", google_client=client)

    messages = tool.read(query="from:sender@example.com")
    draft = tool.create_draft(to="person@example.com", subject="Reply", body="Body")

    assert messages[0]["id"] == "real_msg_1"
    assert messages[0]["subject"] == "query=from:sender@example.com"
    assert draft["id"] == "real_draft_1"
    assert client.created_drafts[0]["to"] == "person@example.com"


def test_calendar_tool_lists_and_creates_local_events(tmp_path: Path):
    tool = CalendarTool(state_dir=tmp_path / "state" / "google")

    created = tool.create_event(summary="Dentist", when="tomorrow 15:00")
    read = tool.get_event(event_ref=str(created["id"]))
    updated = tool.update_event(event_ref=str(created["id"]), summary="Updated dentist")
    events = tool.list_events()

    assert created["id"].startswith("event_")
    assert read["summary"] == "Dentist"
    assert updated["id"] == created["id"]
    assert events[0]["summary"] == "Updated dentist"
    assert events[0]["when"] == "tomorrow 15:00"


def test_calendar_tool_uses_google_client_for_list_when_available(tmp_path: Path):
    client = FakeCalendarClient()
    tool = CalendarTool(
        state_dir=tmp_path / "state" / "google",
        calendar_client=client,
    )

    events = tool.list_events()
    updated = tool.update_event(event_ref="real_event_1", summary="Updated Real Event")

    assert events == [
        {
            "id": "real_event_1",
            "summary": "Real Calendar Event",
            "when": "2026-05-19T07:00:00Z",
        }
    ]
    assert updated["summary"] == "Updated Real Event"
    assert client.updated_events[0]["id"] == "real_event_1"


def test_calendar_tool_includes_and_mutates_local_events_when_google_client_exists(
    tmp_path: Path,
):
    client = FakeCalendarClient()
    tool = CalendarTool(
        state_dir=tmp_path / "state" / "google",
        calendar_client=client,
    )
    created = tool.create_event(summary="Local private event", when="2026-05-13 local")

    events = tool.list_events()
    updated = tool.update_event(
        event_ref=str(created["id"]),
        summary="Updated local private event",
    )
    deleted = tool.delete_event(event_ref=str(created["id"]))

    assert any(event["id"] == created["id"] for event in events)
    assert updated["summary"] == "Updated local private event"
    assert deleted == {"id": created["id"], "deleted": True}
    assert client.updated_events == []
    assert client.deleted_events == []


def test_calendar_private_create_is_allowed_but_attendees_require_confirmation():
    assert (
        PermissionKernel.decision_for(PermissionKernel.CALENDAR_CREATE)
        == PermissionDecision.ALLOW
    )
    assert (
        PermissionKernel.decision_for(PermissionKernel.CALENDAR_CREATE_WITH_ATTENDEES)
        == PermissionDecision.CONFIRM
    )


def test_mail_and_calendar_cli_route_through_core_and_confirmation_gates(
    tmp_path: Path,
    monkeypatch,
):
    vault = tmp_path / "vault"
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    read = CliRunner().invoke(app, ["mail", "read", "--query", "subject:Alpha"])
    draft = CliRunner().invoke(
        app,
        [
            "mail",
            "draft",
            "--to",
            "person@example.com",
            "--subject",
            "Hello",
            "--body",
            "Draft body",
        ],
    )
    send = CliRunner().invoke(app, ["mail", "send", "draft_123"])
    listing = CliRunner().invoke(app, ["calendar", "list"])
    create = CliRunner().invoke(app, ["calendar", "create", "Dentist tomorrow 15:00"])
    create_with_attendee = CliRunner().invoke(
        app,
        ["calendar", "create", "Meeting tomorrow", "--attendee", "person@example.com"],
    )
    modify = CliRunner().invoke(
        app,
        ["calendar", "modify", "event_123", "--summary", "Updated dentist"],
    )
    delete = CliRunner().invoke(app, ["calendar", "delete", "event_123"])

    assert read.exit_code == 0
    assert "No messages found." in read.output
    assert draft.exit_code == 0
    assert "draft:" in draft.output
    assert send.exit_code == 1
    assert "gmail.send requires confirmation" in send.output
    assert listing.exit_code == 0
    assert "No events found." in listing.output
    assert create.exit_code == 0
    assert "event:" in create.output
    assert create_with_attendee.exit_code == 1
    assert "calendar.create_with_attendees requires confirmation" in create_with_attendee.output
    assert modify.exit_code == 1
    assert "calendar.modify requires confirmation" in modify.output
    assert delete.exit_code == 1
    assert "calendar.delete requires confirmation" in delete.output

    with sqlite3.connect(tmp_path / "state" / "taskboard.sqlite") as connection:
        rows = connection.execute(
            "select command, status, risk from tasks order by id"
        ).fetchall()

    assert ("mail.read", "completed", "low") in rows
    assert ("mail.draft", "completed", "low") in rows
    assert ("mail.send", "waiting_confirmation", "high") in rows
    assert ("calendar.list", "completed", "low") in rows
    assert ("calendar.create", "completed", "low") in rows
    assert ("calendar.create", "waiting_confirmation", "high") in rows
    assert ("calendar.modify", "waiting_confirmation", "high") in rows
    assert ("calendar.delete", "waiting_confirmation", "high") in rows
    assert (tmp_path / "state" / "audit" / "events.jsonl").exists()


def _write_config(tmp_path: Path, vault: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: il_segretario
vault:
  path: "{vault.as_posix()}"
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
  credentials_path: "{(tmp_path / 'secrets' / 'google' / 'credentials.json').as_posix()}"
  token_path: "{(tmp_path / 'secrets' / 'google' / 'token.json').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config
