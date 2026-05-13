# Taskboard CLI Taskboard CLI Hardening Implementation Plan

**Goal:** Add the spec MVP commands `tasks`, `approve <task_id>`, and `deny <task_id>` so operators do not need to inspect SQLite manually.

**Architecture:** Task lifecycle remains inside `TaskboardStore`. CLI commands initialize the configured taskboard, list recent tasks, and transition only waiting-confirmation tasks. Approval returns tasks to `queued`; denial moves waiting tasks to `denied`. Each operator transition appends an audit event.

## File Structure

- `src/segretario/taskboard/store.py`: recent task listing.
- `src/segretario/cli.py`: `tasks`, `approve`, and `deny` commands.
- `tests/test_tasks_cli_taskboard_hardening.py`: CLI lifecycle tests using real confirmation-producing commands.

## Tasks

- [x] Write failing CLI tests for task listing, approval, denial, and invalid denial.
- [x] Implement task listing through `TaskboardStore`.
- [x] Implement approval with audit.
- [x] Implement denial with audit and waiting-confirmation guard.
- [x] Verify with full suite, lint, and real CLI tests.

## Safety Boundaries

- `approve` does not execute the high-risk side effect; it only moves the task back to `queued`.
- `deny` is allowed only for tasks waiting confirmation.
- Operator transitions are audited.
