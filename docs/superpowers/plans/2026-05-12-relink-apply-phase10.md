# Relink Apply Phase 10 Implementation Plan

**Goal:** Add a controlled `relink --apply` command that applies unambiguous wikilink suggestions after the dry-run analyzer has found them.

**Architecture:** `relink --apply` reuses the relink analyzer, then writes only source pages under `knowledge/`. It may link to any unambiguous local target title, but it does not rewrite `meta/`, `output/`, `self/`, or `raw/`. The command routes through `SegretarioCore`, `TaskboardStore`, and audit as a `knowledge.write` action.

## File Structure

- `src/segretario/vault/relink.py`: apply mode and report renderer.
- `src/segretario/agents/maintenance_agent.py`: `relink.apply` action.
- `src/segretario/cli.py`: `uv run segretario relink --apply`.
- `tests/test_relink_phase8.py`: apply unit and CLI tests.

## Tasks

- [x] Write failing tests for apply mode.
- [x] Implement apply mode with unambiguous suggestions.
- [x] Restrict writes to `knowledge/` source pages.
- [x] Route CLI through Core/Taskboard/Audit.
- [x] Verify with full suite, lint, and real mini-vault CLI test.

## Safety Boundaries

- `--dry-run` remains the preview mode.
- `--apply` writes only knowledge source pages.
- `raw/elaborati/` is never scanned.
- `meta/` and `output/` are not rewritten by apply.
- Duplicate target titles are skipped.
