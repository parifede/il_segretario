# Vault Core Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Phase 1 local vault core: vault validation, markdown/frontmatter helpers, index/log maintenance, local search, stats, basic lint, and markdown/text ingest.

**Architecture:** Keep all file side effects inside vault-facing modules, with CLI commands delegating to small service functions. The vault code must preserve local-first privacy rules, skip `raw/elaborati`, reject traversal, avoid scanning `self/` for normal search, and append rather than rewrite historical logs.

**Tech Stack:** Python 3.11+, Typer, Pydantic settings, PyYAML, standard-library filesystem and datetime utilities, pytest.

---

## File Structure

- `src/segretario/vault/adapter.py`: vault root checks, safe relative path resolution, file listing.
- `src/segretario/vault/frontmatter.py`: minimal YAML frontmatter parse/render helpers.
- `src/segretario/vault/wikilinks.py`: wikilink extraction and slug/title helpers.
- `src/segretario/vault/index_log.py`: ensure/update `meta/index.md`, append `meta/log.md`.
- `src/segretario/vault/health.py`: vault check, stats, lint report.
- `src/segretario/tools/search_tool.py`: local text search over allowed vault markdown/text files.
- `src/segretario/agents/ingest_agent.py`: basic markdown/text ingest into `knowledge/`.
- `src/segretario/cli.py`: add `vault check`, `search`, `stats`, `lint wiki`, and `ingest`.
- `tests/test_frontmatter.py`: frontmatter behavior.
- `tests/test_index_log.py`: index/log append behavior.
- `tests/test_search_tool.py`: search excludes `raw/elaborati` and `self`.
- `tests/test_vault_health.py`: vault check/stats/lint behavior.
- `tests/test_ingest_markdown.py`: ingest creates knowledge page and updates index/log.
- `tests/test_cli_vault_phase1.py`: CLI command smoke tests.

## Tasks

### Task 1: Vault Adapter And Frontmatter

**Files:**
- Create: `src/segretario/vault/adapter.py`
- Create: `src/segretario/vault/frontmatter.py`
- Test: `tests/test_frontmatter.py`
- Test: extend `tests/test_vault_paths.py`

- [ ] Write failing tests for parsing frontmatter, rendering frontmatter, safe path resolution, and traversal rejection.
- [ ] Run scoped tests and confirm failures are missing modules/functions.
- [ ] Implement `VaultAdapter.resolve_relative`, `VaultAdapter.iter_files`, `parse_markdown`, and `render_markdown`.
- [ ] Run scoped tests and confirm pass.

### Task 2: Index, Log, Wikilinks

**Files:**
- Create: `src/segretario/vault/index_log.py`
- Create: `src/segretario/vault/wikilinks.py`
- Test: `tests/test_index_log.py`
- Test: extend `tests/test_wikilinks.py` or create it.

- [ ] Write failing tests for ensuring `meta/index.md`, appending `meta/log.md`, avoiding duplicate index headings, and extracting `[[wikilinks]]`.
- [ ] Run scoped tests and confirm failures.
- [ ] Implement minimal index/log helpers and wikilink extraction.
- [ ] Run scoped tests and confirm pass.

### Task 3: Search, Stats, Lint

**Files:**
- Create: `src/segretario/tools/search_tool.py`
- Create: `src/segretario/vault/health.py`
- Test: `tests/test_search_tool.py`
- Test: `tests/test_vault_health.py`

- [ ] Write failing tests for allowed local search, `raw/elaborati` skip, `self/` skip by default, stats counts, missing meta files, duplicate index headings, and lint report writing.
- [ ] Run scoped tests and confirm failures.
- [ ] Implement search, stats, vault check, and lint basics.
- [ ] Run scoped tests and confirm pass.

### Task 4: Basic Ingest

**Files:**
- Create: `src/segretario/agents/ingest_agent.py`
- Test: `tests/test_ingest_markdown.py`

- [ ] Write failing tests for ingesting `.md` and `.txt` from `raw/articles`, creating a `knowledge/` page, writing frontmatter, adding at least one source link note, updating index, and appending log.
- [ ] Run scoped tests and confirm failures.
- [ ] Implement conservative knowledge-only ingest for Phase 1. If content appears personal, raise a confirmation-needed error instead of writing `self/`.
- [ ] Run scoped tests and confirm pass.

### Task 5: CLI Integration

**Files:**
- Modify: `src/segretario/cli.py`
- Test: `tests/test_cli_vault_phase1.py`
- Modify: `README.md`

- [ ] Write failing CLI smoke tests for `vault check`, `search`, `stats`, `lint wiki`, and `ingest`.
- [ ] Run CLI scoped tests and confirm failures.
- [ ] Add Typer command groups and wire them to Phase 1 services.
- [ ] Update README first commands from planned to implemented where applicable.
- [ ] Run CLI scoped tests and confirm pass.

### Task 6: Verification

**Files:**
- No production edits unless a verification failure exposes a bug.

- [ ] Run `uv run pytest -q -p no:cacheprovider --basetemp=.tmp\pytest`.
- [ ] Run `uv run ruff check .`.
- [ ] Run `uv run segretario status`.
- [ ] Run code integrity auditor.
- [ ] Run prune candidate scan and keep any candidates that are intentional Phase 1 scaffolding or test mirrors.

## Spec Coverage

- Covers Phase 1: VaultAdapter, path classification usage, markdown/frontmatter parser, index/log helpers, basic search, basic stats, basic lint, ingest markdown/text.
- Defers Phase 2 and later: real LLM query, WebConnector, Gmail, Calendar, scheduler/watcher.
- Preserves Phase 0 safety boundaries: no raw private export, no `raw/elaborati` scan, high-risk task lifecycle stays enforced by TaskboardStore.
