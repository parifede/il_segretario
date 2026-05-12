# Google OAuth Scopes Phase 16 Implementation Plan

**Goal:** Detect insufficient Google OAuth scopes before mutating Gmail/Calendar calls and provide a local CLI path to re-login with the required scopes.

## File Structure

- `src/segretario/connectors/google_oauth.py`: required scopes, scope status, missing-scope guard, login helper.
- `src/segretario/cli.py`: `google status` and `google login --force`.
- `tests/test_google_phase5.py`: missing-scope diagnostics and required-scope coverage.
- `README.md`: Google status/login commands.

## Tasks

- [x] Reproduce root cause from real Gmail 403: token lacks mutating scopes.
- [x] Add tests for missing scope status and actionable credential failure.
- [x] Add required Google scopes for Gmail read/compose/send/modify and Calendar events.
- [x] Add `google status` without leaking token contents.
- [x] Add `google login --force` to recreate the local OAuth token.
- [x] Verify targeted tests, full suite, lint, and real CLI status.

## Safety Boundaries

- Token contents are never printed.
- API calls fail before remote mutation when required scopes are missing.
- `google login --force` is explicit before replacing a token.
- Gmail delete remains trash, not permanent deletion.
