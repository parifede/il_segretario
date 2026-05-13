# Task Show CLI Task Show CLI Hardening Implementation Plan

**Goal:** Add the spec-listed `uv run segretario task show <task_id>` command for inspecting a single taskboard row from the CLI.

## File Structure

- `src/segretario/cli.py`: `task show` subcommand.
- `tests/test_tasks_cli_taskboard_hardening.py`: single-task display and missing-id behavior.
- `README.md`: command listing.

## Tasks

- [x] Write failing CLI tests for showing an existing task and rejecting an unknown id.
- [x] Add read-only `task show` command.
- [x] Verify targeted tests, full suite, lint, and real CLI path.

## Safety Boundaries

- The command reads taskboard state only.
- The command does not append audit events.
- The command does not transition task state.
