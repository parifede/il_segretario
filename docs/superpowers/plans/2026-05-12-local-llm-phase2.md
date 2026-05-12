# Local LLM Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add local-only Ollama-backed query support over allowed vault pages.

**Architecture:** Keep the LLM backend behind a small generic local client interface and use Ollama only as one provider. Query behavior first searches allowed vault pages, then sends a constrained prompt to the local model; if no pages match, it refuses to answer from generic model knowledge.

**Tech Stack:** Python 3.11+, httpx, Typer, pytest, existing local search and config modules.

---

## File Structure

- `src/segretario/connectors/ollama_client.py`: local Ollama HTTP client using `/api/generate` with `stream: false`.
- `src/segretario/tools/ollama_tool.py`: small tool wrapper around local model generation and clear unavailable errors.
- `src/segretario/app/query.py`: vault query orchestration, local context selection, prompt construction, citation normalization.
- `src/segretario/cli.py`: add `query` command.
- `tests/test_ollama_client.py`: request/response and graceful failure behavior.
- `tests/test_query_local.py`: query refuses without pages, excludes `self/` and `raw/elaborati`, sends only allowed context, cites pages.
- `tests/test_cli_query.py`: CLI smoke tests.

## Tasks

### Task 1: Ollama Client

**Files:**
- Create: `src/segretario/connectors/ollama_client.py`
- Test: `tests/test_ollama_client.py`

- [ ] Write failing tests for non-streaming payload, response parsing, and unreachable host errors.
- [ ] Run scoped tests and confirm failures.
- [ ] Implement `OllamaClient.generate(prompt, system=None)` with injected `httpx.Client`.
- [ ] Run scoped tests and confirm pass.

### Task 2: Query Service

**Files:**
- Create: `src/segretario/app/query.py`
- Test: `tests/test_query_local.py`

- [ ] Write failing tests for no-results refusal, allowed-context-only prompt, and wikilink citations.
- [ ] Run scoped tests and confirm failures.
- [ ] Implement `query_vault(...)` using `search_vault`, page reads, and a local LLM protocol.
- [ ] Run scoped tests and confirm pass.

### Task 3: CLI Query

**Files:**
- Modify: `src/segretario/cli.py`
- Test: `tests/test_cli_query.py`
- Modify: `README.md`

- [ ] Write failing CLI tests for no local pages and injected fake local model.
- [ ] Run scoped tests and confirm failures.
- [ ] Add `uv run segretario query "question"` command and README note.
- [ ] Run scoped tests and confirm pass.

### Task 4: Verification

**Files:**
- No production edits unless verification exposes a bug.

- [ ] Run `uv run pytest -q -p no:cacheprovider --basetemp=.tmp\pytest`.
- [ ] Run `uv run ruff check .`.
- [ ] Run `uv run segretario status`.
- [ ] Run code integrity auditor and prune scan.

## References

- Ollama API generate docs: `https://docs.ollama.com/api/generate`
- Ollama streaming docs: `https://docs.ollama.com/api/streaming`

## Spec Coverage

- Covers Phase 2: generic local model config, Ollama client, query command, graceful failure if Ollama unavailable, no model-specific names in business logic.
- Defers: prompt templates for ingest classification, richer summaries, real autonomous agent routing, web/Gmail/Calendar.
