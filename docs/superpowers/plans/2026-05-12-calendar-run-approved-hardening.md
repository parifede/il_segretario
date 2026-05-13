# Calendar Run Approved Calendar Run Hardening Implementation Plan

**Goal:** Complete approved Calendar task execution for attendee creates and deletes through `task run`.

## File Structure

- `src/segretario/tools/calendar_tool.py`: local delete-event support.
- `src/segretario/connectors/calendar_client.py`: Google Calendar event delete call.
- `src/segretario/agents/calendar_agent.py`: route `calendar.delete`.
- `src/segretario/cli.py`: persist executable delete payloads and route command.
- `tests/test_task_execution_task_run_hardening.py`: approved attendee create and delete execution.

## Tasks

- [x] Write failing tests for approved calendar delete execution.
- [x] Confirm attendee create already runs from stored payload.
- [x] Add local calendar delete behavior.
- [x] Add Google Calendar delete method.
- [x] Route calendar delete through task runner.
- [x] Verify targeted tests, full suite, lint, and real local CLI path.

## Safety Boundaries

- Calendar delete still requires confirmation.
- `task run` rejects waiting-confirmation tasks.
- Automated real test uses local state, not a live Google Calendar deletion.
- Google delete is only reachable after explicit approve + task run.
