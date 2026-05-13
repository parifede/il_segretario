# Post-v1.0 Next Steps

`v1.0.0` covers `IL_SEGRETARIO_CODEX_SPEC.md` through Phase 6. Do not rename post-spec work as new spec phases.

## Current Local State

The code release is tagged at `v1.0.0`.

Expected local working tree changes after the real acceptance tests:

- `segretario.yaml`: local Ollama model set to `gemma4:e4b`;
- `vault_dev/meta/index.md`: dev vault index entries created by real ingest tests;
- `vault_dev/meta/log.md`: dev vault log entries created by real ingest tests.

These are local runtime/dev-vault state, not release code.

## Safe Continuation Order

1. Keep using `docs/v1.0-acceptance.md` as the baseline for regressions.
2. For every new capability, run the real CLI path and inspect taskboard plus audit state.
3. Treat external-agent Q&A, scoped relink apply, task cancellation, and Google mutation runners as post-spec hardening.
4. Avoid writing to `E:\vault` unless explicitly testing the real vault with the owner present.
5. Do not send email, archive/delete email, or modify/delete calendar events without an explicit confirmation test step.

## Candidate v1.1 Work

- Export/import-safe external-agent interface around `external answer`.
- More precise Google command UX for invalid draft/message/event ids.
- Optional local release command that runs status, audit verify, pytest, ruff, and acceptance smoke tests.
- Better separation between tracked dev fixtures and local runtime vault changes.
