# Mail Archive Delete Run Phase 15 Implementation Plan

**Goal:** Let approved `mail.archive` and `mail.delete` confirmation tasks execute through `task run`.

## File Structure

- `src/segretario/tools/gmail_tool.py`: local archive/delete records.
- `src/segretario/connectors/gmail_client.py`: Gmail archive and trash calls.
- `src/segretario/agents/mail_agent.py`: route `mail.archive` and `mail.delete`.
- `src/segretario/cli.py`: persist executable Google payloads and route commands.
- `tests/test_task_execution_phase14.py`: approved archive/delete task execution.

## Tasks

- [x] Write failing tests for approved archive/delete execution.
- [x] Add local archive/delete execution records.
- [x] Add Google archive/delete client methods.
- [x] Route archive/delete through MailAgent and task runner.
- [x] Verify targeted tests, full suite, lint, and real CLI path.

## Safety Boundaries

- Archive/delete still require confirmation.
- `mail.delete` uses Gmail trash, not permanent deletion.
- `task run` rejects waiting-confirmation tasks.
- Task state transitions still go through `TaskboardStore`.
