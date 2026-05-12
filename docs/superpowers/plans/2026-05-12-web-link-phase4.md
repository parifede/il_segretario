# Web Link Phase 4 Implementation Plan

**Goal:** Add a controlled public link workflow that fetches a public URL into `raw/articles/`, optionally ingests the saved source locally, and routes CLI execution through `SegretarioCore`.

**Architecture:** Keep outbound HTTP in the tool layer, expose it through a fixed `ResearchAgent`, and call it from CLI only through Core/TaskRouter/Taskboard/Audit. This phase does not send private vault context to the web.

## File Structure

- `src/segretario/tools/web_tool.py`: validate public HTTP(S) URLs, fetch content, convert basic HTML to markdown, save under configured `web.save_dir`.
- `src/segretario/agents/research_agent.py`: fixed-agent wrapper around `fetch_link`.
- `src/segretario/cli.py`: add `link` command and route it through `SegretarioCore`.
- `tests/test_web_link_phase4.py`: local HTTP server tests for fetch, CLI routing, and optional ingest.

## Tasks

- [x] Write failing tests for public link fetch into `raw/articles/`.
- [x] Implement WebTool link fetch with local path validation.
- [x] Write failing CLI test proving `link` routes through Core and writes audit/taskboard state.
- [x] Implement `ResearchAgent` and CLI `link`.
- [x] Write failing CLI test for `link --ingest`.
- [x] Implement link-to-ingest through a second Core task.
- [x] Run full verification, integrity audit, and a real end-to-end local HTTP smoke test.

## Deferred

- Web search by topic.
- Private-context projection workflow.
- Autonomous research selection.
- Remote browser automation.
