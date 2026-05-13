# Relink Scope Relink Scope Hardening Implementation Plan

**Goal:** Support the spec-listed `uv run segretario relink knowledge/ --dry-run` flow by adding an optional vault-relative source scope to relink dry-run and apply.

## File Structure

- `src/segretario/vault/relink.py`: source-scope filtering.
- `src/segretario/agents/maintenance_agent.py`: pass scope to relink functions.
- `src/segretario/cli.py`: optional `scope` argument for `relink`.
- `tests/test_relink_post_spec_relink.py`: CLI dry-run scope and apply scope coverage.
- `README.md`: command listing.

## Tasks

- [x] Write failing tests for scoped dry-run and apply.
- [x] Add vault-relative source scope support.
- [x] Verify targeted tests, full suite, lint, and real CLI path.

## Safety Boundaries

- Scope is source-side only: it filters which pages are edited or reported.
- Scope must be vault-relative; absolute paths and parent traversal are rejected.
- Existing unscoped behavior remains available.
