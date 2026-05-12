# Web Link Phase 4 Implementation Plan

**Goal:** Add a controlled public link workflow that fetches a public URL into `raw/articles/`, optionally ingests the saved source locally, enforces privacy projection checks for web queries, and routes CLI execution through `SegretarioCore`.

**Architecture:** Keep outbound HTTP in a controlled WebConnector/tool layer, expose it through a fixed `ResearchAgent`, and call it from CLI only through Core/TaskRouter/Taskboard/Audit. Private-context web queries must provide a projection; raw private context is not passed to the connector.

## File Structure

- `src/segretario/connectors/web_client.py`: controlled WebConnector for HTTP(S) fetches and privacy-safe query payload preparation.
- `src/segretario/tools/web_tool.py`: validate public HTTP(S) URLs, fetch content, convert basic HTML to markdown, save under configured `web.save_dir`.
- `src/segretario/agents/research_agent.py`: fixed-agent wrapper around `fetch_link` and privacy-safe web query preparation.
- `src/segretario/cli.py`: add `link` and `web` commands and route them through `SegretarioCore`.
- `tests/test_web_link_phase4.py`: local HTTP server tests for fetch, CLI routing, and optional ingest.
- `tests/test_web_privacy_phase4.py`: privacy projection checks for connector and CLI.

## Tasks

- [x] Write failing tests for public link fetch into `raw/articles/`.
- [x] Implement WebTool link fetch with local path validation.
- [x] Write failing CLI test proving `link` routes through Core and writes audit/taskboard state.
- [x] Implement `ResearchAgent` and CLI `link`.
- [x] Write failing CLI test for `link --ingest`.
- [x] Implement link-to-ingest through a second Core task.
- [x] Write failing tests for private-context web query projection checks.
- [x] Implement controlled WebConnector and CLI `web` projection flow.
- [x] Run full verification, integrity audit, and a real end-to-end local HTTP/privacy smoke test.

## Deferred

- Web search by topic.
- Autonomous research selection.
- Remote browser automation.
