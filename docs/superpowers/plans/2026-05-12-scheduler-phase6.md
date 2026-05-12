# Scheduler Phase 6 Implementation Plan

**Goal:** Add a bounded scheduler/watch foundation that respects the real vault rules before creating any autonomous work.

**Architecture:** Phase 6 starts with a deterministic `scheduler run-once` command, not a background daemon. Each run performs a read-only vault preflight, checks configured scheduler flags, applies permission decisions, and creates queued tasks through `TaskboardStore`. With `--execute`, it leases and completes safe local jobs in one bounded pass. Execution remains explicit and bounded by leases, duplicate guards, and the configured maintenance budget.

## File Structure

- `src/segretario/vault/preflight.py`: read-only vault rule preflight for `AGENTS.md`, meta files, local-only paths, and skip paths.
- `src/segretario/scheduler/jobs.py`: candidate scheduler jobs and one bounded run function.
- `src/segretario/taskboard/store.py`: active-command query used as a cooldown/duplicate guard.
- `src/segretario/cli.py`: `scheduler run-once` command.
- `tests/test_scheduler_phase6.py`: Phase 6 preflight, scheduler, audit, taskboard, and CLI tests.

## Tasks

- [x] Write failing tests for vault preflight and scheduler run-once.
- [x] Implement read-only vault preflight without scanning `self/` bodies or `raw/elaborati/`.
- [x] Implement bounded scheduler job planning.
- [x] Create scheduled jobs through `TaskboardStore` only.
- [x] Execute safe scheduler jobs through Taskboard leases.
- [x] Append scheduler audit events with hash-chain verification.
- [x] Add CLI `uv run segretario scheduler run-once` and `--execute`.
- [x] Run full verification and real read-only CLI test against `E:\vault`.

## Safety Boundaries

- No daemon loop is started in Phase 6.
- No scheduler job directly mutates task status outside `TaskboardStore`.
- `raw/elaborati/` remains a configured skip path.
- `self/` is recognized as local-only; the preflight does not read its contents.
- If preflight fails, jobs are not scheduled.
