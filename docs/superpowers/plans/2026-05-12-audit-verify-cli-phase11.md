# Audit Verify CLI Phase 11 Implementation Plan

**Goal:** Add a read-only `uv run segretario audit verify` command so audit integrity can be checked without Python snippets.

## File Structure

- `src/segretario/cli.py`: audit subcommand.
- `tests/test_audit_cli_phase11.py`: valid and tampered hash-chain CLI tests.
- `README.md`: command listing.

## Tasks

- [x] Write failing CLI tests for valid and tampered audit logs.
- [x] Add read-only audit verification command.
- [x] Verify targeted tests, full suite, lint, and real CLI path.

## Safety Boundaries

- The command does not append audit events.
- The command does not create taskboard rows.
- Missing or tampered audit state exits non-zero.
