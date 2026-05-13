# Task Output Ref Task Output Ref Hardening Implementation Plan

**Goal:** Record task output references in `TaskboardStore` when tasks complete, so `task show` reflects what the task produced.

## File Structure

- `src/segretario/taskboard/store.py`: `complete_task` transition helper.
- `src/segretario/app/core.py`: use `complete_task` for normal core dispatch.
- `src/segretario/cli.py`: use `complete_task` for `task run`.
- `src/segretario/scheduler/jobs.py`: use `complete_task` for scheduler execution.
- `tests/test_task_execution_task_run_hardening.py`: task-run output refs for mail/calendar operations.

## Tasks

- [x] Write failing tests showing completed task output refs are missing.
- [x] Add `complete_task` transition that clears leases and stores output refs.
- [x] Route core, scheduler, and CLI task execution through `complete_task`.
- [x] Verify targeted tests, full suite, lint, and real local CLI path.

## Safety Boundaries

- Task state transitions still go through `TaskboardStore`.
- Terminal completion clears leases.
- Output refs are short identifiers/paths, not sensitive payload dumps.
