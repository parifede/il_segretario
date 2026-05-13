# Relink Dry-Run Post-Spec Relink Hardening Implementation Plan

**Goal:** Add the MVP `relink --dry-run` command from the spec so the Segretario can inspect the Obsidian graph and propose missing wikilinks without editing pages.

**Architecture:** The relink analyzer scans allowed markdown pages, skips `raw/elaborati/`, derives page titles from frontmatter/H1/stem, and writes a report to `output/relink-YYYY-MM-DD.md`. It only proposes unambiguous links: duplicate target titles are skipped to avoid noisy or unsafe suggestions. CLI execution goes through `SegretarioCore`, `TaskboardStore`, and audit.

## File Structure

- `src/segretario/vault/relink.py`: dry-run graph analyzer and report renderer.
- `src/segretario/agents/maintenance_agent.py`: maintenance action wrapper for `relink.dry_run`.
- `src/segretario/cli.py`: `uv run segretario relink --dry-run`.
- `tests/test_relink_post_spec_relink.py`: dry-run, skip path, ambiguity, and CLI routing tests.

## Tasks

- [x] Write failing tests for relink dry-run.
- [x] Implement analyzer without mutating pages.
- [x] Skip `raw/elaborati/`.
- [x] Skip ambiguous duplicate titles.
- [x] Route CLI through Core/Taskboard/Audit.
- [x] Verify with full test suite, lint, `vault_dev`, and real `E:\vault` report write.

## Safety Boundaries

- Dry-run writes only the report file.
- Source pages are not edited.
- `raw/elaborati/` is never scanned.
- Duplicate target titles are skipped instead of guessed.
