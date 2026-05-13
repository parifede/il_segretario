# Phase 5 Runner Consolidation Checklist

**Goal:** Preserve the real-tested Gmail/Calendar confirmation-runner workflow before moving to the next spec area.

## Real Flow

```text
high-risk command
-> waiting_confirmation task
-> task run blocked while waiting_confirmation
-> approve
-> queued
-> task run
-> completed
-> task show has input_ref and output_ref
-> audit verify ok
```

## Commands

```powershell
uv run segretario google status
uv run segretario mail read --query "newer_than:7d"
uv run segretario mail archive <MESSAGE_ID>
uv run segretario approve <TASK_ID>
uv run segretario task run <TASK_ID>
uv run segretario task show <TASK_ID>
uv run segretario audit verify
```

```powershell
uv run segretario calendar create "Output ref test" --config state\output-ref-hardening-test\segretario.yaml
uv run segretario calendar modify <EVENT_ID> --summary "Updated output ref test" --config state\output-ref-hardening-test\segretario.yaml
uv run segretario approve <TASK_ID> --config state\output-ref-hardening-test\segretario.yaml
uv run segretario task run <TASK_ID> --config state\output-ref-hardening-test\segretario.yaml
uv run segretario calendar delete <EVENT_ID> --config state\output-ref-hardening-test\segretario.yaml
uv run segretario approve <TASK_ID> --config state\output-ref-hardening-test\segretario.yaml
uv run segretario task run <TASK_ID> --config state\output-ref-hardening-test\segretario.yaml
uv run segretario task show <TASK_ID> --config state\output-ref-hardening-test\segretario.yaml
uv run segretario audit verify --config state\output-ref-hardening-test\segretario.yaml
```

## Real Evidence Recorded In Chat

- Gmail OAuth scopes were missing, then fixed with `google login --force`.
- `google status` reported `Scopes: ok` after re-login.
- Gmail archive with a real message id completed as task `35`.
- Calendar delete local test completed as task `4` in output-ref hardening state.
- `task show` displayed `output_ref: event_4fb14ec48eb0`.
- Calendar modify is part of Phase 5 and must be confirmed, run from stored payload, and checked against persisted state.
- `audit verify` returned `ok`.

## Notes

- Failed task `33` is historical evidence of using a draft id where Gmail required a message id.
- Old task `30` predates payload storage and is not executable.
- Do not rewrite these historical task records; they are useful audit trail.
