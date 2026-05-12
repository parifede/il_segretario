# Google Connectors Phase 5 Implementation Plan

**Goal:** Add safe local Google connector interfaces for Gmail and Calendar, with confirmation gates for irreversible actions.

**Architecture:** Keep real side effects behind tool interfaces. Phase 5 uses local state-backed Gmail/Calendar tools and an OAuth status connector; no real Gmail send, archive, delete, or Calendar mutation is performed without explicit confirmation.

## File Structure

- `src/segretario/connectors/google_oauth.py`: local credentials/token status, no secret contents read or printed.
- `src/segretario/tools/gmail_tool.py`: local Gmail message read and draft creation.
- `src/segretario/tools/calendar_tool.py`: local calendar event list and private create.
- `src/segretario/agents/mail_agent.py`: fixed agent wrapper for `mail.read` and `mail.draft`.
- `src/segretario/agents/calendar_agent.py`: fixed agent wrapper for `calendar.list` and `calendar.create`.
- `src/segretario/cli.py`: `mail` and `calendar` command groups routed through `SegretarioCore`.
- `tests/test_google_phase5.py`: connector/tool/CLI confirmation tests.

## Tasks

- [x] Write failing tests for OAuth status, Gmail read/draft, Calendar list/create, and confirmation gates.
- [x] Implement local Google OAuth status connector.
- [x] Implement GmailTool and CalendarTool local state interfaces.
- [x] Implement MailAgent and CalendarAgent wrappers.
- [x] Add CLI commands through Core/Taskboard/Audit.
- [x] Run full verification, integrity audit, and real local CLI tests.

## Safety Boundaries

- Gmail send/archive/delete creates confirmation tasks only.
- Calendar create with attendees, modify, and delete create confirmation tasks only.
- OAuth credentials and tokens are never printed or read into logs.
- Real Google API calls are deferred until the user explicitly asks to use credentials.
