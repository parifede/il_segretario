# il_segretario

Local-first CLI custodian for an Obsidian-compatible LLM Wiki vault.

## Bootstrap

```powershell
cd E:\il_segretario
uv sync
uv run segretario status
uv run segretario start
```

Copy `segretario.yaml.example` to `segretario.yaml` when you want a local config, then point the vault to the real Obsidian folder:

```yaml
vault:
  path: "E:\\YOUR_REAL_VAULT"
```

You can place or copy your actual Obsidian vault wherever you prefer, then update `segretario.yaml` to point at that folder. The default development vault path is `E:\il_segretario\vault_dev`. The real vault is always configurable and is not created inside the Python package.

Keep `segretario.yaml` as a local machine config and keep real vault metadata private. Use `segretario.yaml.example` as the tracked template; do not publish a real config, `vault_dev/meta/index.md`, or `vault_dev/meta/log.md` if they contain personal vault state.

## First Commands

```powershell
uv run segretario status
uv run segretario start
uv run segretario chat --once "search topic"
uv run segretario work --limit 3
uv run segretario config show
uv run segretario google status
uv run segretario google login --force
uv run segretario vault check
uv run segretario ingest raw/articles/example.md --auto
uv run segretario search "topic"
uv run segretario query "question"
uv run segretario lint wiki
uv run segretario stats
uv run segretario link "https://example.com/article"
uv run segretario web "public research query"
uv run segretario extract queue --kind pdf --limit 1
uv run segretario ocr queue --limit 1
uv run segretario mail read --query "subject:example"
uv run segretario mail draft "write a reply to the last email"
uv run segretario mail draft "Draft body" --to person@example.com --subject "Subject"
uv run segretario calendar list
uv run segretario calendar list --today
uv run segretario calendar list --from 2026-05-13 --to 2026-05-14
uv run segretario scheduler run-once
uv run segretario scheduler run-once --execute
uv run segretario run-maintenance
uv run segretario watch
uv run segretario external answer "question from another agent" --source knowledge/example.md
uv run segretario relink --dry-run
uv run segretario relink knowledge/ --dry-run
uv run segretario relink --apply
uv run segretario audit verify
uv run segretario tasks
uv run segretario task show <task_id>
uv run segretario task run <task_id>
uv run segretario approve <task_id>
uv run segretario deny <task_id>
uv run segretario recall status
uv run segretario recall reindex [--force]
uv run segretario recall search "query" [--k 5]
uv run segretario recall reset-wizard
```

## Spec Phases

The project follows `IL_SEGRETARIO_CODEX_SPEC.md` through Phase 6:

- Phase 0: bootstrap CLI, config, status, tests.
- Phase 1: vault adapter, path classification, search, ingest, lint, stats.
- Phase 2: Ollama-backed local query flow with graceful offline failure.
- Phase 3: SegretarioCore, task routing, agents, taskboard, audit.
- Phase 4: web/link ingestion with privacy projection checks.
- Phase 5: Google OAuth, Gmail, Calendar, and confirmation gates.
- Phase 6: watcher/scheduler run-once flows with budgets, leases, and cooldowns.

Extra commands such as `external answer`, scoped `relink --apply`, and task cancellation are post-spec hardening, not additional spec phases.

The v1.0 acceptance matrix is tracked in `docs/v1.0-acceptance.md`.

Basic ingest for Phase 1:

```powershell
uv run segretario ingest raw/articles/example.md --auto
```

Start the local operator console:

```powershell
uv run segretario start
```

Run one direct interaction without manually handling task IDs:

```powershell
uv run segretario chat --once "search privacy projection"
uv run segretario chat --once "work"
```

Run a bounded local work cycle:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
uv run segretario work --limit 3
```

Fetch and ingest a public link for Phase 4:

```powershell
uv run segretario link "https://example.com/article" --ingest
```

Prepare a privacy-safe web query from private context:

```powershell
uv run segretario web "private-context query" --private-context --projection "privacy-safe query"
```

Extract rich raw sources in local staging:

```powershell
uv run segretario extract plan
uv run segretario extract queue --kind pdf --limit 1
uv run segretario agents run --limit 1
```

PDFs with embedded text are extracted with PyMuPDF. Image-only PDFs are marked `status: needs_ocr` and can be queued for local OCR:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
uv run segretario ocr queue --limit 1
uv run segretario agents run --limit 1
```

`pytesseract` and `Pillow` are Python dependencies, but the Tesseract executable is a local system dependency. Install Tesseract separately or expose it through `TESSERACT_CMD`; do not store OCR output in `knowledge/` until the extracted marker has been reviewed or ingested through the normal vault flow.

High-risk Gmail and Calendar operations use a confirmation runner:

```powershell
uv run segretario mail archive <MESSAGE_ID>
uv run segretario calendar modify <EVENT_ID> --summary "Updated title"
uv run segretario tasks --limit 5
uv run segretario task run <TASK_ID>
uv run segretario approve <TASK_ID>
uv run segretario task run <TASK_ID>
uv run segretario mail send <TASK_ID>
uv run segretario task show <TASK_ID>
uv run segretario audit verify
```

Expected flow:

```text
waiting_confirmation -> approve -> queued -> task run -> completed
```

## Safety Model

- Vault-private work uses local tools and local models.
- `self/` and `meta/privacy_map.local.json` are no-export paths.
- Gmail send/archive/delete and Calendar modify/delete require taskboard confirmation.
- Approved high-risk tasks run from local payload files under `state/task_payloads/`; `task show` exposes short `input_ref` and `output_ref` values, not raw payloads.
- Phase 5 Google commands use local safe interfaces unless real OAuth API usage is explicitly requested.
- Phase 6 scheduler runs are bounded `run-once` cycles; `--execute` leases and completes safe local jobs without starting a daemon loop.
- External answers are filtered by the output guard: public/cloud-safe pages can be shared, local-only pages require a projection, and no-export paths are blocked.
- Audit events are append-only JSONL records linked by an audit hash chain.
- Google credentials, OAuth tokens, local state, and private dev vault content are gitignored.

## Stop Conditions

Stop and ask before continuing if a requested change would require guessing product behavior, deleting or overwriting user vault content, sending raw private context to the web, writing to `self/profile/` without explicit confirmation, or running a high-risk operation without a taskboard confirmation path.
