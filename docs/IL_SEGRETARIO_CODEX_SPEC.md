# il_segretario — Local Vault Secretary Implementation Spec

> **Target user:** local-first Obsidian / LLM Wiki maintainer.  
> **Target coding agent:** Codex or compatible coding agent.  
> **Project root:** `E:\il_segretario\`  
> **Vault path:** configurable. The real vault will be placed/selected by the user after bootstrap.  
> **Runtime style:** local-first, CLI-first, Obsidian-compatible, Ollama-backed, privacy-preserving.  
> **Status:** implementation plan, not yet code.  
>
> **Hard rule for the coding agent:** do not invent missing product decisions. If a requirement is ambiguous, stop and ask. Prefer a smaller correct implementation over a broad speculative one.

---

## 0. Non-negotiable decisions from the design discussion

This project is **not** part of any other orchestrator. Do not depend on existing bot/app/orchestrator code. Treat this as a separate local project.

The system is called:

```text
il_segretario
```

The Segretario is not a generic chatbot. It is the **local custodian of an Obsidian / LLM Wiki vault**. It receives tasks from a CLI, manages markdown files, maintains the wiki, coordinates fixed agents, and can operate local connectors such as web fetching, Gmail, and Google Calendar under strict permissions.

Confirmed decisions:

1. The user already has Obsidian and a markdown-folder vault.
2. The initial interface must be CLI-first.
3. Commands should be runnable like:
   ```bash
   uv run segretario status
   ```
4. The project should live under a new Windows directory:
   ```text
   E:\il_segretario\
   ```
5. The real vault path must be configurable. Do not hardcode a final vault path.
6. The user will later place or point the real vault where instructed.
7. The LLM backend must be generic, not hardcoded to one model. Today it may be Qwen via Ollama; tomorrow it may be another local model.
8. Use only local LLMs for vault-private work.
9. Web access is allowed through a **local controlled WebConnector**, not by giving raw private context to external services.
10. Gmail and Google Calendar must use local Google API OAuth. The user already has credentials.
11. Gmail policy:
    - read: allowed
    - draft: allowed
    - send: confirmation required
    - archive/delete: confirmation required
12. Calendar policy:
    - read: allowed
    - create: supported, confirm when needed
    - modify: confirmation required
    - delete: confirmation required
    - scheduling: supported, audited
13. The system must have a paranoid audit log.
14. The system should use a machine taskboard even if the user does not care to read it.
15. The system must support autonomous maintenance, but not uncontrolled loops.
16. Fixed agents are preferred over fully dynamic agent creation.
17. The implementation must respect the user’s existing vault rules, especially privacy, raw immutability, index/log maintenance, and Obsidian wikilink conventions.
18. When in doubt, stop and ask rather than inventing.

---

## 1. Product definition

`il_segretario` is a local command-line system that acts as the operational custodian of a personal LLM Wiki.

The LLM Wiki pattern is:

```text
raw immutable sources -> persistent markdown wiki -> user reads/explores in Obsidian
```

The system should not behave like a plain RAG chatbot that re-derives knowledge at query time. It should maintain a persistent, compounding wiki:

- ingest sources once;
- write/update markdown pages;
- maintain cross-links;
- update `meta/index.md`;
- append to `meta/log.md`;
- detect contradictions;
- flag stale or orphan pages;
- save useful outputs back into `output/`;
- preserve the vault as the source of truth.

The user uses Obsidian as the IDE/browser of the wiki. `il_segretario` is the local maintainer/programmer of that wiki.

---

## 2. High-level architecture

```text
User
  ↓
CLI: uv run segretario <command>
  ↓
SegretarioCLI
  ↓
SegretarioCore
  ↓
TaskRouter
  ↓
RiskClassifier + PermissionKernel
  ↓
TaskBoard
  ↓
Fixed Agents
  ↓
Controlled Tools / Connectors
  ↓
Vault markdown + Gmail + Calendar + Web + Audit
```

Important separation:

```text
LLM backend = reasoning engine
Tool layer  = only place where real side effects happen
PermissionKernel = decides if side effects are allowed
Audit = records what happened
TaskBoard = stores task state and confirmations
```

The LLM must never directly write files, send mail, modify calendar, delete anything, or browse with raw private context. It can propose actions. The executor validates and performs actions through tools.

---

## 3. Directory structure

Create this project structure:

```text
E:\il_segretario\
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── segretario.yaml.example
├── src/
│   └── segretario/
│       ├── __init__.py
│       ├── cli.py
│       ├── app/
│       │   ├── __init__.py
│       │   ├── core.py
│       │   ├── router.py
│       │   ├── models.py
│       │   ├── errors.py
│       │   └── runtime.py
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── ingest_agent.py
│       │   ├── wiki_maintainer_agent.py
│       │   ├── search_agent.py
│       │   ├── research_agent.py
│       │   ├── mail_agent.py
│       │   ├── calendar_agent.py
│       │   ├── maintenance_agent.py
│       │   └── security_agent.py
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── vault_tool.py
│       │   ├── markdown_tool.py
│       │   ├── search_tool.py
│       │   ├── web_tool.py
│       │   ├── gmail_tool.py
│       │   ├── calendar_tool.py
│       │   ├── filesystem_tool.py
│       │   └── ollama_tool.py
│       ├── vault/
│       │   ├── __init__.py
│       │   ├── adapter.py
│       │   ├── paths.py
│       │   ├── frontmatter.py
│       │   ├── wikilinks.py
│       │   ├── index_log.py
│       │   ├── classifier.py
│       │   └── health.py
│       ├── policies/
│       │   ├── __init__.py
│       │   ├── privacy.py
│       │   ├── permissions.py
│       │   ├── risk.py
│       │   ├── confirmation.py
│       │   └── output_guard.py
│       ├── taskboard/
│       │   ├── __init__.py
│       │   ├── store.py
│       │   ├── models.py
│       │   ├── lease.py
│       │   └── renderer.py
│       ├── audit/
│       │   ├── __init__.py
│       │   ├── store.py
│       │   ├── hash_chain.py
│       │   └── redact.py
│       ├── connectors/
│       │   ├── __init__.py
│       │   ├── ollama_client.py
│       │   ├── google_oauth.py
│       │   ├── gmail_client.py
│       │   ├── calendar_client.py
│       │   └── web_client.py
│       ├── scheduler/
│       │   ├── __init__.py
│       │   ├── jobs.py
│       │   ├── watcher.py
│       │   └── budgets.py
│       └── config/
│           ├── __init__.py
│           ├── settings.py
│           └── loader.py
└── tests/
    ├── test_cli_status.py
    ├── test_config.py
    ├── test_vault_paths.py
    ├── test_privacy_policy.py
    ├── test_permission_kernel.py
    ├── test_audit_hash_chain.py
    ├── test_taskboard.py
    ├── test_ingest_markdown.py
    ├── test_wikilinks.py
    ├── test_index_log.py
    ├── test_gmail_policy.py
    ├── test_calendar_policy.py
    └── test_web_privacy.py
```

Do not create the user’s real vault inside the package automatically. Instead, support configuration:

```yaml
vault_path: "E:\\path\\to\\real_vault"
```

A good default for first-run development may be:

```text
E:\il_segretario\vault_dev\
```

But the real vault must be user-configurable.

---

## 4. Configuration

Create `segretario.yaml.example`:

```yaml
project_name: il_segretario

vault:
  path: "E:\\il_segretario\\vault_dev"
  require_agents_md: true
  require_meta_index: true
  require_meta_log: true
  skip_paths:
    - "raw/elaborati"

llm:
  provider: ollama
  model: "local-model-name"
  base_url: "http://127.0.0.1:11434"
  temperature: 0.2
  timeout_seconds: 120

cli:
  default_output: text
  require_confirmation_for_high_risk: true

taskboard:
  sqlite_path: "E:\\il_segretario\\state\\taskboard.sqlite"
  human_mirror_path: "E:\\il_segretario\\state\\bacheca.md"
  lease_minutes: 15
  max_retries: 3

audit:
  events_path: "E:\\il_segretario\\state\\audit\\events.jsonl"
  hash_chain_path: "E:\\il_segretario\\state\\audit\\hash_chain.jsonl"
  redact_sensitive_payloads: true

web:
  enabled: true
  save_dir: "raw/articles"
  user_link_auto_fetch: true
  autonomous_research_enabled: true
  require_projection_for_personal_context: true

google:
  enabled: true
  credentials_path: "E:\\il_segretario\\secrets\\google\\credentials.json"
  token_path: "E:\\il_segretario\\secrets\\google\\token.json"
  gmail_enabled: true
  calendar_enabled: true

scheduler:
  enabled: false
  raw_watcher_enabled: false
  inbox_watcher_enabled: false
  daily_digest_enabled: false
  maintenance_budget_minutes: 10
```

Also support environment variable override:

```text
SEGRETARIO_CONFIG
SEGRETARIO_VAULT_PATH
SEGRETARIO_OLLAMA_MODEL
SEGRETARIO_OLLAMA_BASE_URL
```

Priority order:

```text
CLI args > env vars > config file > defaults
```

---

## 5. CLI commands

Use Typer or Click. Prefer Typer unless a conflict appears.

Minimum commands for MVP:

```bash
uv run segretario status
uv run segretario config show
uv run segretario vault check
uv run segretario search "query"
uv run segretario ingest raw/articles/file.md --auto
uv run segretario query "question"
uv run segretario lint wiki
uv run segretario relink knowledge/ --dry-run
uv run segretario stats
uv run segretario tasks
uv run segretario task show <task_id>
uv run segretario approve <task_id>
uv run segretario deny <task_id>
```

Later commands:

```bash
uv run segretario link "https://example.com/article"
uv run segretario web "topic to research"
uv run segretario mail read --query "from:..."
uv run segretario mail draft "write an email to..."
uv run segretario mail send <task_id>
uv run segretario calendar list --today
uv run segretario calendar create "tomorrow 15:00 dentist"
uv run segretario calendar modify <event_ref>
uv run segretario calendar delete <event_ref>
uv run segretario run-maintenance
uv run segretario watch
```

`status` must be the first implemented command.

Expected `status` output:

```text
il_segretario status
────────────────────────────
Project:      il_segretario
Config:       E:\il_segretario\segretario.yaml
Vault:        E:\...
Vault check:  ok | missing | partial
LLM:          ollama / <configured model>
Ollama:       reachable | unreachable
Taskboard:    ok | missing
Audit:        ok | missing
Google:       configured | not configured
Web:          enabled | disabled
Scheduler:    enabled | disabled
────────────────────────────
```

Do not fail the whole status command just because Ollama or Google is unavailable. Show partial status.

---

## 6. Vault compatibility rules

The vault is an Obsidian-compatible markdown directory. The system must preserve Obsidian wikilinks.

Expected vault structure, configurable but assumed by default:

```text
vault/
├── raw/
│   ├── articles/
│   ├── books/
│   ├── notes/
│   ├── media/
│   ├── assets/
│   └── elaborati/
├── self/
│   ├── profile/
│   ├── interests/
│   ├── character/
│   ├── skills/
│   ├── thoughts/
│   └── wellness/
├── knowledge/
├── output/
│   ├── cloud_research/
│   └── personal_reports/
├── meta/
│   ├── index.md
│   ├── log.md
│   ├── bookmarks.md
│   ├── privacy_policy.md
│   ├── privacy_rules.md
│   └── privacy_map.local.json
└── AGENTS.md
```

Hard rules:

1. `raw/` contains immutable sources. Do not modify raw files except moving processed files to `raw/elaborati/` after explicit confirmation.
2. `raw/elaborati/` is a dead archive. Never scan it, never suggest re-ingesting it, never include it in maintenance scans.
3. `self/` is private local-only content.
4. `self/profile/` is protected. Never write to it unless the user explicitly uses an `update profile:` style command and confirms.
5. `knowledge/` is local-only by default unless a page has both:
   ```yaml
   privacy: public
   cloud_ok: true
   ```
6. `output/` is local by default.
7. `meta/index.md` must be updated after every ingest or structural move.
8. `meta/log.md` is append-only. Never rewrite old entries.
9. Internal wiki links must use Obsidian wikilinks, not relative markdown links.
10. Avoid creating duplicate `## Self`, `## Knowledge`, or `## Output` sections in `meta/index.md`.

---

## 7. Privacy policy implementation

The system must implement a local-first privacy boundary.

Core rule:

```text
Real vault data stays local.
The local Ollama model and local tools are the only custodians of real private context.
External services, web, remote APIs, screenshots, remote logs, and copied prompts receive only privacy projections.
```

Absolute no-export paths:

```text
self/
meta/privacy_map.local.json
```

Never upload, quote, summarize, screenshot, paste, or log raw contents from those paths to remote systems.

Projection rules:

- exact age -> age band
- exact income -> income band
- exact location -> useful geographic area
- exact job -> role or sector band
- health details -> broad category only when needed
- names -> `PERSON_TOKEN_A`
- emails -> `EMAIL_TOKEN_A`
- phones -> `PHONE_TOKEN_A`
- tax/document/account IDs -> `ID_TOKEN_A`
- IBAN/payment data -> `BANK_TOKEN_A`
- license plates/vehicle IDs -> `VEHICLE_TOKEN_A`
- sensitive employer/client/company -> `ORG_TOKEN_A`

Addresses are generalized geographically rather than tokenized by default.

### Important updated design rule for this project

Older vault rules may say the local agent never makes outbound network requests. For `il_segretario`, implement this more precisely:

```text
The LLM itself does not browse.
The local Segretario process may use a controlled WebConnector.
The WebConnector must not receive raw private context.
If a web query depends on private vault context, first create a privacy projection.
The fetched public result is saved into raw/articles/ and then processed locally.
```

This allows local autonomous web research while preserving the privacy boundary.

---

## 8. Permission and risk model

Implement `RiskClassifier` and `PermissionKernel` early.

Risk levels:

```text
low
medium
high
critical
```

Default action policy:

| Action | Default |
|---|---|
| read vault non-protected paths | allow |
| search vault | allow |
| write `knowledge/` | allow after validation |
| write `output/` | allow |
| update `meta/index.md` | allow when part of valid operation |
| append `meta/log.md` | allow |
| write `self/interests`, `self/character`, `self/skills`, `self/thoughts`, `self/wellness` | require announcement and allow user chance to decline |
| write `self/profile/` | explicit command + confirmation required |
| read `meta/privacy_map.local.json` | local-only, only if token mapping is explicitly needed |
| export private content | deny unless projected |
| web with public query | allow |
| web query derived from private context | require privacy projection |
| Gmail read | allow |
| Gmail draft | allow |
| Gmail send | confirmation required |
| Gmail archive/delete | confirmation required |
| Calendar read | allow |
| Calendar create private low-risk reminder | allow or configurable |
| Calendar create with attendees | confirmation required |
| Calendar modify/delete | confirmation required |
| shell execution | deny by default |
| delete files | confirmation required, preferably disabled in MVP |
| modify policy/config | confirmation required |

Confirmation must create or update a task in the taskboard. Do not implement confirmations only as ephemeral CLI prompts for high-risk actions.

---

## 9. Taskboard

The user may not care to read the bacheca, but the system requires a machine taskboard.

Use SQLite for machine state:

```text
E:\il_segretario\state\taskboard.sqlite
```

Optionally render a human mirror:

```text
E:\il_segretario\state\bacheca.md
```

Task model:

```yaml
id: task_YYYYMMDD_HHMMSS_xxxxxx
source: cli | watcher | scheduler | agent
requested_by: owner | system
command: ingest | query | mail.send | calendar.create | lint | relink | web | maintenance
status: queued | running | waiting_confirmation | completed | failed | denied | cancelled
risk: low | medium | high | critical
assigned_agent: IngestAgent | WikiMaintainerAgent | MailAgent | CalendarAgent | MaintenanceAgent | ResearchAgent | SecurityAgent
requires_confirmation: true | false
confirmation_reason: string | null
input_ref: string | null
output_ref: string | null
audit_ref: string | null
created_at: ISO datetime
updated_at: ISO datetime
lease_owner: string | null
lease_expires_at: ISO datetime | null
retries: integer
last_error: string | null
```

Rules:

1. Every non-trivial operation gets a task record.
2. Every high-risk operation must enter `waiting_confirmation`.
3. A task waiting for confirmation must be approved with:
   ```bash
   uv run segretario approve <task_id>
   ```
4. Deny with:
   ```bash
   uv run segretario deny <task_id>
   ```
5. Long-running/autonomous tasks need leases.
6. Failed tasks should have retry counts and cooldowns.
7. Do not allow infinite retries.

---

## 10. Audit log

Implement paranoid append-only audit.

Files:

```text
E:\il_segretario\state\audit\events.jsonl
E:\il_segretario\state\audit\hash_chain.jsonl
```

Each audit event:

```json
{
  "event_id": "audit_000001",
  "timestamp": "2026-05-11T22:40:00+02:00",
  "actor": "MailAgent",
  "task_id": "task_...",
  "action": "gmail.create_draft",
  "risk": "medium",
  "permission_decision": "allowed",
  "confirmation_required": false,
  "input_hash": "sha256:...",
  "output_hash": "sha256:...",
  "redactions_applied": true,
  "prev_hash": "sha256:...",
  "hash": "sha256:..."
}
```

Rules:

1. Append-only. Never edit previous audit entries.
2. Hash-chain every event.
3. Store hashes for sensitive payloads instead of raw payloads.
4. Never store full `self/` content in audit.
5. Never store secrets, OAuth tokens, email bodies containing private content, or full protected file contents.
6. Provide `uv run segretario audit verify` later.
7. Tests must detect tampering.

Separate logs:

```text
meta/log.md          = wiki chronological log, human-facing
state/audit/*.jsonl  = technical security/audit log
state/taskboard.sqlite = machine task state
```

Do not collapse these into one file.

---

## 11. Fixed agents

Implement fixed agents as classes with explicit responsibilities and allowed tools. Do not implement unconstrained autonomous agent spawning.

### 11.1 SegretarioCore

Responsibilities:

- receives normalized tasks;
- routes to agents;
- calls risk/permission checks;
- records taskboard state;
- records audit;
- ensures output guard;
- coordinates confirmations.

### 11.2 IngestAgent

Responsibilities:

- ingest markdown/text sources;
- later support PDFs and other formats;
- classify content as `self/` vs `knowledge/` vs ambiguous;
- extract key points;
- update or create wiki pages;
- trigger cross-linking;
- update `meta/index.md` and append `meta/log.md`.

MVP: markdown `.md` and `.txt` only. Add PDF later unless already easy.

### 11.3 WikiMaintainerAgent

Responsibilities:

- maintain page structure;
- maintain frontmatter;
- maintain `meta/index.md`;
- append `meta/log.md`;
- enforce wikilinks;
- avoid duplicate pages;
- merge duplicate sections in index if detected.

### 11.4 SearchAgent

Responsibilities:

- search `meta/index.md`;
- search frontmatter;
- use local full-text search;
- later support SQLite FTS5 or qmd integration.

MVP search stack:

```text
index.md + frontmatter scan + ripgrep-like text search in Python
```

### 11.5 ResearchAgent

Responsibilities:

- handle web/link tasks;
- build privacy-safe queries when private context is involved;
- use WebConnector;
- save fetched content to `raw/articles/`;
- hand saved source to IngestAgent.

The WebConnector may browse, but the LLM must not send raw private context to the web.

### 11.6 MailAgent

Responsibilities:

- Gmail search/read;
- Gmail draft creation;
- Gmail send only after confirmation;
- Gmail archive/delete only after confirmation.

MVP can implement abstract interface plus tests before real Google calls.

### 11.7 CalendarAgent

Responsibilities:

- list events;
- read event details;
- create events;
- modify events;
- delete events;
- schedule with constraints.

Confirmation required for modification/deletion and for events involving other attendees.

### 11.8 MaintenanceAgent

Responsibilities:

- `lint wiki`;
- `relink`;
- `stats`;
- detect stale stubs;
- detect orphan pages;
- detect index mismatch;
- detect unprocessed files;
- schedule maintenance tasks with budget.

### 11.9 SecurityAgent

Responsibilities:

- enforce privacy rules;
- classify paths;
- block no-export paths;
- validate web projections;
- validate output redaction;
- validate high-risk operations.

SecurityAgent is not optional.

---

## 12. Tool layer

Tools are the only components allowed to do side effects.

Required tools:

```text
VaultTool
MarkdownTool
SearchTool
WebTool
GmailTool
CalendarTool
FilesystemTool
OllamaTool
```

### Tool execution rule

Before any side effect:

```text
Tool request -> PermissionKernel -> Audit pre-event -> execute -> Audit post-event -> TaskBoard update
```

Do not allow agent classes to directly call `Path.write_text`, Google APIs, HTTP clients, or destructive operations. Route through tools.

---

## 13. LLM backend abstraction

Do not hardcode Qwen 3.5.

Implement generic local model config:

```yaml
llm:
  provider: ollama
  model: "qwen3.5:latest"   # example only; user can change
  base_url: "http://127.0.0.1:11434"
```

Use names like:

```python
LocalLLMClient
OllamaClient
LocalModelConfig
```

Avoid names like:

```python
QwenClient
QwenAgent
```

unless only used in example config.

The runtime should report:

```text
LLM: ollama / <configured model>
```

The model can be changed later without changing business logic.

MVP behavior if Ollama is unreachable:

- `status` should show unreachable but not crash;
- pure file checks should still work;
- LLM-dependent commands should fail with a clear actionable error.

---

## 14. Wiki command behavior

The vault already defines command-like behaviors. These are not shell commands. They are behavioral operations implemented by `il_segretario`.

Implement these progressively:

```text
ingest
query
search
relate
relink
review
lint wiki
reorganize
export
summarize session
grow
stats
thread
merge
draft
web
bookmark/bookmarks
```

MVP must implement:

```text
status
vault check
search
ingest markdown/text
query basic
lint basic
relink dry-run
stats basic
tasks
approve/deny
```

### Ingest MVP

Input:

```bash
uv run segretario ingest raw/articles/file.md --auto
```

Behavior:

1. Validate vault path.
2. Read policy files if present.
3. Ensure `raw/elaborati/` is skipped.
4. Read source file.
5. Classify content:
   - personal -> `self/` candidate;
   - independent knowledge -> `knowledge/` candidate;
   - ambiguous -> ask / create waiting confirmation task.
6. Search existing pages for overlap.
7. If overlap is high, update existing page instead of creating duplicate.
8. If new page, write proper frontmatter.
9. Add at least 2 outbound wikilinks where possible.
10. Add inbound links from related pages where possible.
11. Update `meta/index.md`.
12. Append `meta/log.md`.
13. Record task and audit.
14. Report created/updated pages.

### Query MVP

Behavior:

1. Read `meta/index.md`.
2. Search relevant pages.
3. Read relevant pages within allowed scope.
4. Ask local LLM to synthesize answer.
5. Cite wiki pages using `[[page-name]]` style in output.
6. Offer or support saving to `output/` later.
7. If no relevant pages exist, say that no pages were found and suggest ingesting sources. Do not answer from generic training data for vault queries.

### Lint MVP

Checks:

- missing `meta/index.md`;
- missing `meta/log.md`;
- duplicate index sections;
- orphan pages;
- missing status in frontmatter;
- stale stubs by date if dates exist;
- files in `raw/elaborati/` accidentally scanned;
- personal-looking content in `knowledge/` flagged, not moved automatically.

Save report to:

```text
output/lint-YYYY-MM-DD.md
```

Append to `meta/log.md`.

---

## 15. Web/link workflow

Command:

```bash
uv run segretario link "https://example.com/article"
```

Behavior:

1. Validate URL.
2. Fetch with WebConnector.
3. Convert to markdown.
4. Save to:
   ```text
   raw/articles/<slug>.md
   ```
5. Append metadata/frontmatter about source URL and fetched date.
6. Trigger ingest automatically if configured or if user passes `--ingest`.
7. Record task and audit.

Command:

```bash
uv run segretario web "query"
```

Behavior:

1. If query is public/generic, search web.
2. If query includes or depends on private vault context, generate a privacy projection first.
3. Return top results.
4. In autonomous mode, pick best result only if confidence is high; otherwise ask.
5. Save selected result to `raw/articles/`.
6. Ingest locally.

Do not implement a remote browsing system that sends private vault text to an external API.

---

## 16. Gmail workflow

Use local Google API OAuth.

Expected local files:

```text
E:\il_segretario\secrets\google\credentials.json
E:\il_segretario\secrets\google\token.json
```

These must be gitignored.

Commands:

```bash
uv run segretario mail read --query "from:example@example.com newer_than:7d"
uv run segretario mail draft "write a reply to ..."
uv run segretario mail send <task_id>
uv run segretario mail archive <message_ref>
uv run segretario mail delete <message_ref>
```

Policy:

- read: allowed;
- draft: allowed;
- send: create waiting confirmation task;
- archive/delete: create waiting confirmation task;
- never log full sensitive email bodies in audit;
- do not train or store email content in wiki unless explicitly asked;
- if saving email-derived knowledge, classify carefully as `self/` or `knowledge/`.

MVP may stub real Gmail API if needed, but must preserve interfaces and tests.

---

## 17. Calendar workflow

Use local Google API OAuth.

Commands:

```bash
uv run segretario calendar list --today
uv run segretario calendar list --from 2026-05-11 --to 2026-05-18
uv run segretario calendar create "tomorrow 15:00 dentist"
uv run segretario calendar modify <event_ref>
uv run segretario calendar delete <event_ref>
```

Policy:

- read: allowed;
- create private low-risk reminders: configurable;
- create with attendees: confirmation required;
- modify/delete: confirmation required;
- accept/decline invitations: confirmation required unless later trusted rules are added;
- never expose precise personal calendar details to web/external systems.

MVP may stub real Calendar API if needed, but must preserve interfaces and tests.

---

## 18. Scheduler and watcher

The user wants the vault to be alive:

- periodic checks;
- watch folders;
- digest;
- autonomous task assignment;
- maintenance.

But no uncontrolled loops.

Implement scheduler/watcher after MVP core.

Watcher targets:

```text
vault/raw/
vault/inbox/       # optional if created
```

Never watch or scan:

```text
vault/raw/elaborati/
```

Scheduler jobs:

```text
daily digest
weekly lint
periodic stats
raw inbox scan
bookmark review
stale stub review
orphan page review
```

Budget rules:

```yaml
scheduler:
  maintenance_budget_minutes: 10
  max_tasks_per_cycle: 5
  cooldown_minutes_after_failure: 60
  no_user_notification_unless_useful: true
```

Autonomy rules:

1. Create tasks; do not execute high-risk actions silently.
2. Respect leases and cooldowns.
3. Avoid recursive task creation loops.
4. Summarize useful results.
5. Do not notify for low-value maintenance unless requested.

---

## 19. Output guard

Before printing user-facing output:

- remove stack traces unless debug mode;
- remove raw OAuth tokens;
- remove private absolute paths unless useful and local;
- do not dump tool JSON;
- do not expose `meta/privacy_map.local.json` contents;
- do not print full `self/` contents unless explicitly requested locally;
- for sensitive summaries, abstract details.

For CLI debug logs, still do not print secrets.

---

## 20. Testing requirements

Use pytest.

The first implementation must be test-driven enough to avoid privacy/path mistakes.

Required tests:

### Config/status

- `uv run segretario status` works with default config.
- Missing vault path produces clear warning, not crash.
- Ollama unreachable produces partial status, not crash.
- Environment variables override config.

### Vault paths

- `raw/elaborati/` is skipped in scans.
- `self/` is classified local-only.
- `meta/privacy_map.local.json` is no-export.
- `knowledge/` defaults to local unless frontmatter says `privacy: public` and `cloud_ok: true`.

### Permission kernel

- Gmail send requires confirmation.
- Gmail delete/archive requires confirmation.
- Calendar modify/delete requires confirmation.
- `self/profile/` write requires explicit profile update + confirmation.
- Web query using private context requires projection.
- Shell execution denied by default.

### Audit

- Audit events append.
- Hash chain verifies.
- Tampering is detected.
- Sensitive payloads are hashed/redacted.

### Taskboard

- Task creation works.
- Waiting confirmation tasks can be approved/denied.
- Lease expiry works.
- Retry limit works.

### Wiki

- Ingest markdown creates/updates page.
- `meta/index.md` updated.
- `meta/log.md` appended, not rewritten.
- Wikilinks are Obsidian style.
- Duplicate index sections are detected.
- Orphan pages are flagged by lint.

### Web

- Public link fetch saves to `raw/articles/`.
- Private context is not sent to WebConnector raw.
- `self/` content is never passed into web query payload.

### Gmail/Calendar

- Read/draft allowed.
- Send/delete/modify/create-with-attendees creates confirmation task.
- OAuth token paths are gitignored and never logged.

---

## 21. Implementation phases

### Phase 0 — Bootstrap

Deliver:

- project structure;
- `pyproject.toml`;
- Typer CLI;
- config loader;
- `status` command;
- basic vault path validation;
- base audit store;
- base taskboard store;
- tests.

Definition of done:

```bash
uv run segretario status
python -m pytest -q
```

works.

### Phase 1 — Vault core

Deliver:

- VaultAdapter;
- path classification;
- markdown/frontmatter parser;
- index/log helpers;
- basic search;
- basic stats;
- lint basic;
- ingest markdown/text.

### Phase 2 — LLM integration

Deliver:

- generic Ollama client;
- model config;
- LLM prompt templates for classification, summary, query;
- graceful failure when Ollama unavailable;
- no model-specific names in business logic.

### Phase 3 — Task routing and agents

Deliver:

- SegretarioCore;
- TaskRouter;
- BaseAgent;
- IngestAgent;
- WikiMaintainerAgent;
- SearchAgent;
- MaintenanceAgent;
- SecurityAgent.

### Phase 4 — Web/link

Deliver:

- WebConnector;
- link fetch;
- save to raw/articles;
- privacy projection checks;
- link -> ingest workflow.

### Phase 5 — Google connectors

Deliver:

- Google OAuth local connector;
- GmailTool;
- CalendarTool;
- read/draft/list/create interfaces;
- confirmation enforcement.

### Phase 6 — Watcher/scheduler

Deliver:

- raw watcher;
- inbox watcher if useful;
- daily digest;
- maintenance cycle;
- budgets/cooldowns/leases.

Do not jump to later phases before Phase 0 and Phase 1 are stable.

---

## 22. Suggested dependencies

Use conservative dependencies.

Suggested `pyproject.toml` dependencies:

```toml
[project]
name = "il-segretario"
version = "0.1.0"
description = "Local-first Obsidian LLM Wiki secretary"
requires-python = ">=3.11"
dependencies = [
  "typer>=0.12",
  "pydantic>=2",
  "pydantic-settings>=2",
  "pyyaml>=6",
  "httpx>=0.27",
  "python-frontmatter>=1.1",
  "watchdog>=4",
  "rich>=13",
  "google-api-python-client>=2",
  "google-auth>=2",
  "google-auth-oauthlib>=1",
]

[project.scripts]
segretario = "segretario.cli:app"

[dependency-groups]
dev = [
  "pytest>=8",
  "pytest-cov>=5",
  "ruff>=0.6",
  "mypy>=1.10",
]
```

SQLite is from the standard library.

If a dependency creates friction, stop and explain. Do not replace the architecture with a speculative framework.

---

## 23. Gitignore requirements

Create `.gitignore` that excludes:

```gitignore
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.mypy_cache/
*.pyc

# local state
state/
logs/

# secrets
secrets/
.env
*.token
credentials.json
token.json

# optional local dev vault content
vault_dev/raw/
vault_dev/self/
vault_dev/output/
vault_dev/knowledge/**/*.md
vault_dev/meta/privacy_map.local.json
```

Do not accidentally commit Google tokens, real vault data, private wiki content, or audit payloads.

---

## 24. README requirements

Create a README with:

```bash
cd E:\il_segretario
uv sync
uv run segretario status
```

Explain how to configure the real vault:

```yaml
vault:
  path: "E:\\YOUR_REAL_VAULT"
```

Explain that the user can later copy/place their actual Obsidian vault and update config.

Explain first useful commands:

```bash
uv run segretario vault check
uv run segretario ingest raw/articles/example.md --auto
uv run segretario search "topic"
uv run segretario lint wiki
uv run segretario stats
```

Explain safety:

- local-first;
- no-export paths;
- Gmail send confirmation;
- Calendar destructive confirmation;
- audit hash chain.

---

## 25. Stop conditions

The coding agent must stop and ask if:

1. The vault structure differs so much that safe path classification is impossible.
2. `AGENTS.md`, `meta/index.md`, or `meta/log.md` contain conflicting instructions that change privacy behavior.
3. Implementing web would require sending raw private context externally.
4. Gmail/Calendar OAuth files are missing and a real API call is requested.
5. A requested operation would write to `self/profile/` without explicit profile-update confirmation.
6. A high-risk operation lacks a taskboard confirmation path.
7. The model/tool interface would require hardcoding a specific model name.
8. The implementation would need to delete or overwrite user vault content.
9. The task requires guessing product behavior not specified here.

Do not invent. Stop and ask.

---

## 26. First coding task prompt

Start with Phase 0 only.

Build:

- project skeleton;
- `pyproject.toml`;
- Typer CLI entrypoint;
- config loader;
- `status` command;
- VaultPath validator;
- TaskBoard SQLite initialization;
- Audit append-only/hash-chain skeleton;
- PermissionKernel constants;
- tests for the above.

Do not implement Gmail, Calendar, web, scheduler, or full LLM workflows in Phase 0.

Acceptance:

```bash
cd E:\il_segretario
uv sync
uv run segretario status
uv run pytest -q
```

Expected: tests pass and status prints a partial but useful local system report.
