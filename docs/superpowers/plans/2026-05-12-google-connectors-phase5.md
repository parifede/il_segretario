# Google Connectors Phase 5 Implementation Plan

**Goal:** Add safe Google connector interfaces for Gmail and Calendar, with confirmation gates for irreversible actions.

**Architecture:** Keep real side effects behind tool interfaces. Phase 5 uses an OAuth connector plus Gmail/Calendar clients when credentials and token exist, and falls back to local state-backed tools in tests or unconfigured environments. No real Gmail send, archive, delete, or Calendar mutation is performed without explicit confirmation.

## File Structure

- `src/segretario/connectors/google_oauth.py`: credentials/token status and authorized credentials loading, no secret contents printed.
- `src/segretario/connectors/gmail_client.py`: Gmail API read and draft client.
- `src/segretario/connectors/calendar_client.py`: Calendar API read client.
- `src/segretario/tools/gmail_tool.py`: Gmail message read and draft creation with real-client or local fallback.
- `src/segretario/tools/calendar_tool.py`: Calendar event list with real-client or local fallback, and local private create.
- `src/segretario/agents/mail_agent.py`: fixed agent wrapper for `mail.read` and `mail.draft`.
- `src/segretario/agents/calendar_agent.py`: fixed agent wrapper for `calendar.list` and `calendar.create`.
- `src/segretario/cli.py`: `mail` and `calendar` command groups routed through `SegretarioCore`.
- `tests/test_google_phase5.py`: connector/tool/CLI confirmation tests.

## Tasks

- [x] Write failing tests for OAuth status, Gmail read/draft, Calendar list/create, and confirmation gates.
- [x] Implement local Google OAuth status connector.
- [x] Implement GmailTool and CalendarTool local state interfaces.
- [x] Implement Gmail and Calendar API clients for authorized read/list and draft interfaces.
- [x] Implement MailAgent and CalendarAgent wrappers.
- [x] Add CLI commands through Core/Taskboard/Audit.
- [x] Run full verification, integrity audit, local CLI tests, and real read-only Google API CLI tests.

## Safety Boundaries

- Gmail send/archive/delete creates confirmation tasks only.
- Calendar create with attendees, modify, and delete create confirmation tasks only.
- OAuth credentials and tokens are never printed or read into logs.
- Real Gmail send and destructive Calendar/Gmail actions are deferred until the user explicitly approves them.
