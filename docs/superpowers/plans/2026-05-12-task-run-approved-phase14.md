# Task Run Approved Phase 14 Implementation Plan

**Goal:** Make approved queued tasks executable instead of leaving them as inert `queued` rows.

## File Structure

- `src/segretario/taskboard/payloads.py`: local payload storage for confirmation tasks.
- `src/segretario/taskboard/store.py`: taskboard transition helpers for payload refs and explicit run leases.
- `src/segretario/app/core.py`: persist executable payloads when a task waits for confirmation.
- `src/segretario/cli.py`: `uv run segretario task run <task_id>`.
- `src/segretario/agents/mail_agent.py`: execute approved `mail.send`.
- `src/segretario/tools/gmail_tool.py`: local and Google draft-send interface.
- `src/segretario/connectors/gmail_client.py`: Gmail draft send call.
- `tests/test_task_execution_phase14.py`: approved send and waiting-confirmation guard.

## Tasks

- [x] Write failing tests for approved task execution and confirmation guard.
- [x] Persist local executable payloads for confirmation tasks.
- [x] Add read/transition-safe `task run <task_id>`.
- [x] Add local Gmail draft-send execution path.
- [x] Verify targeted tests, full suite, lint, and real CLI path.

## Safety Boundaries

- `task run` only runs `queued` tasks.
- Waiting-confirmation tasks are rejected.
- Task status changes go through `TaskboardStore`.
- Gmail send still requires explicit `approve` before execution.
