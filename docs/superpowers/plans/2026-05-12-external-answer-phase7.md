# External Answer Phase 7 Implementation Plan

**Goal:** Let `il_segretario` answer external-agent requests from the local vault while enforcing the existing privacy/export policy.

**Architecture:** The vault remains local. Phase 7 adds an output guard for external responses: it reads local files only inside the Segretario process, decides whether real text may be disclosed, and returns one of three outcomes: allow, project, or block. The first interface is CLI-first, matching the project spec; no remote server or new protocol is introduced.

## File Structure

- `src/segretario/policies/output_guard.py`: external answer decisions and safe response rendering.
- `src/segretario/agents/security_agent.py`: output guard validation action.
- `src/segretario/cli.py`: `external answer` command.
- `tests/test_external_answer_phase7.py`: public allow, local-only projection, no-export block, audit/taskboard CLI tests.

## Tasks

- [x] Write failing tests for allow/project/block decisions.
- [x] Implement `OutputGuard`.
- [x] Route SecurityAgent validation through the new guard.
- [x] Add CLI `uv run segretario external answer`.
- [x] Verify with full test suite, lint, and real CLI tests on `vault_dev`.
- [x] Verify public allow path read-only against `E:\vault`.

## Safety Boundaries

- `self/` and `meta/privacy_map.local.json` are blocked for external answers.
- `knowledge/` pages are exportable only with `privacy: public` and `cloud_ok: true`.
- Local-only pages require an explicit `--projection`; the raw body is never printed.
- Audit payloads contain only path/action/decision metadata, not page bodies.
