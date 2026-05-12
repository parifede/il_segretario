from datetime import date
from pathlib import Path

from segretario.vault.health import lint_vault, vault_stats


def test_stats_count_markdown_files_by_top_level_area(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "knowledge" / "projects").mkdir(parents=True)
    (vault / "self").mkdir()
    (vault / "raw" / "articles").mkdir(parents=True)
    (vault / "knowledge" / "projects" / "Alpha.md").write_text("# Alpha\n", encoding="utf-8")
    (vault / "knowledge" / "Beta.md").write_text("# Beta\n", encoding="utf-8")
    (vault / "self" / "profile.md").write_text("# Me\n", encoding="utf-8")
    (vault / "raw" / "articles" / "source.txt").write_text("not markdown\n", encoding="utf-8")

    stats = vault_stats(vault)

    assert stats.markdown_by_area == {"knowledge": 2, "self": 1}
    assert stats.total_markdown == 3


def test_stats_skips_raw_elaborati(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "raw" / "elaborati").mkdir(parents=True)
    (vault / "raw" / "elaborati" / "old.md").write_text("# Old\n", encoding="utf-8")

    stats = vault_stats(vault)

    assert stats.markdown_by_area == {}
    assert stats.total_markdown == 0


def test_lint_detects_missing_meta_files_and_writes_dated_report(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    report = lint_vault(vault, today=date(2026, 5, 11))

    assert report.path == "output/lint-2026-05-11.md"
    assert "meta/index.md: missing" in report.issues
    assert "meta/log.md: missing" in report.issues
    assert (vault / "output" / "lint-2026-05-11.md").read_text(encoding="utf-8").startswith(
        "# Vault lint 2026-05-11\n"
    )


def test_lint_detects_duplicate_index_headings_and_orphan_knowledge_pages(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "meta").mkdir(parents=True)
    (vault / "knowledge").mkdir()
    (vault / "meta" / "index.md").write_text(
        "# Index\n\n## Alpha\n- [[Known]]\n## Alpha\n",
        encoding="utf-8",
    )
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    (vault / "knowledge" / "Known.md").write_text("# Known\n", encoding="utf-8")
    (vault / "knowledge" / "Orphan.md").write_text("# Orphan\n", encoding="utf-8")

    report = lint_vault(vault, today=date(2026, 5, 11))

    assert "meta/index.md: duplicate heading 'Alpha'" in report.issues
    assert "knowledge/Orphan.md: orphan knowledge page" in report.issues
    assert "knowledge/Known.md: orphan knowledge page" not in report.issues
