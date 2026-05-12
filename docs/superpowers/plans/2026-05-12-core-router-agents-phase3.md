# Core Router Agents Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route existing local operations through `SegretarioCore`, `TaskRouter`, fixed agents, TaskboardStore, PermissionKernel, and AuditLog.

**Architecture:** Keep policy decisions in `PermissionKernel`, task lifecycle in `TaskboardStore`, and side-effect execution in existing tool/agent functions. `SegretarioCore` is the integration boundary: it creates tasks, checks permission decisions, routes to fixed agents, records audit, and returns small result objects for CLI output.

**Tech Stack:** Python 3.11+, existing SQLite taskboard, JSONL audit, Typer CLI, pytest.

---

## File Structure

- `src/segretario/app/models.py`: add normalized `TaskRequest` and `CoreResult` dataclasses.
- `src/segretario/app/router.py`: map command names to fixed agent instances.
- `src/segretario/app/core.py`: create task, enforce permission decision, dispatch, audit outcome.
- `src/segretario/agents/base.py`: base fixed-agent protocol.
- `src/segretario/agents/search_agent.py`: wraps `search_vault`.
- `src/segretario/agents/wiki_maintainer_agent.py`: wraps meta index/log maintenance helpers.
- `src/segretario/agents/maintenance_agent.py`: wraps `vault_stats` and `lint_vault`.
- `src/segretario/agents/security_agent.py`: wraps privacy/path checks where needed.
- `src/segretario/agents/ingest_agent.py`: keep existing ingest function and add class wrapper.
- `src/segretario/cli.py`: use `SegretarioCore` for `search`, `stats`, `lint wiki`, and `ingest`.
- `tests/test_task_router.py`: route mapping tests.
- `tests/test_core_routing.py`: task/audit lifecycle tests.
- `tests/test_cli_core_integration.py`: CLI still behaves the same through core.

## Tasks

### Task 1: Fixed Agent Wrappers

- [x] Write failing tests for agent wrappers returning stable `CoreResult`-like payloads.
- [x] Implement `BaseAgent`, `SearchAgent`, `WikiMaintainerAgent`, `MaintenanceAgent`, `SecurityAgent`, and `IngestAgent.run`.
- [x] Run scoped tests.

### Task 2: TaskRouter

- [x] Write failing tests for commands `search`, `stats`, `lint.wiki`, and `ingest`.
- [x] Implement router lookup with explicit KeyError on unknown commands.
- [x] Run scoped tests.

### Task 3: SegretarioCore

- [x] Write failing tests proving core creates task records, dispatches through fixed agents, updates completion/failure, and appends audit entries.
- [x] Write failing tests proving denied or confirmation-required decisions do not execute the agent.
- [x] Implement minimal `SegretarioCore.handle`.
- [x] Run scoped tests.

### Task 4: CLI Integration

- [x] Write or adjust CLI tests so current commands still print same output while going through core.
- [x] Implement core construction helper in CLI.
- [x] Run CLI tests.

### Task 5: Verification

- [x] Run full pytest with workspace temp.
- [x] Run ruff.
- [x] Run integrity auditor and prune scan.
- [x] Commit Phase 3.

## Spec Coverage

- Covers Phase 3 core/router/fixed-agent skeleton.
- Integrates taskboard/audit for existing local commands.
- Defers real Gmail, Calendar, WebConnector, scheduler, and unrestricted autonomous loops.
