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


def test_lint_uses_frontmatter_title_for_orphan_detection(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "meta").mkdir(parents=True)
    (vault / "knowledge").mkdir()
    (vault / "meta" / "index.md").write_text(
        "# Index\n\n## Knowledge\n- [[Alpha Topic]]\n",
        encoding="utf-8",
    )
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    (vault / "knowledge" / "alpha-topic.md").write_text(
        "---\ntitle: Alpha Topic\nstatus: active\n---\n# Alpha Topic\n",
        encoding="utf-8",
    )

    report = lint_vault(vault, today=date(2026, 5, 11))

    assert "knowledge/alpha-topic.md: orphan knowledge page" not in report.issues


def test_lint_treats_obsidian_alias_links_as_indexed(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "meta").mkdir(parents=True)
    (vault / "knowledge" / "nested").mkdir(parents=True)
    (vault / "meta" / "index.md").write_text(
        "# Index\n\n## Knowledge\n"
        "- [[knowledge/nested/alpha|Alpha Topic]] `knowledge/nested/alpha.md`\n",
        encoding="utf-8",
    )
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    (vault / "knowledge" / "nested" / "alpha.md").write_text(
        "---\ntitle: Alpha Topic\nstatus: active\n---\n# Alpha\n",
        encoding="utf-8",
    )

    report = lint_vault(vault, today=date(2026, 5, 11))

    assert "knowledge/nested/alpha.md: orphan knowledge page" not in report.issues


def test_lint_does_not_flag_raw_source_referenced_by_knowledge_frontmatter(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "meta").mkdir(parents=True)
    (vault / "knowledge").mkdir()
    (vault / "raw" / "articles").mkdir(parents=True)
    (vault / "meta" / "index.md").write_text(
        "# Index\n\n## Knowledge\n- [[Processed]]\n",
        encoding="utf-8",
    )
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    (vault / "knowledge" / "processed.md").write_text(
        "---\ntitle: Processed\nstatus: active\nsource_path: raw/articles/source.md\n---\n# Processed\n",
        encoding="utf-8",
    )
    (vault / "raw" / "articles" / "source.md").write_text("# Source\n", encoding="utf-8")

    report = lint_vault(vault, today=date(2026, 5, 11))

    assert "raw/articles/source.md: unprocessed raw file" not in report.issues


def test_lint_detects_missing_status_frontmatter_and_appends_log(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "meta").mkdir(parents=True)
    (vault / "knowledge").mkdir()
    (vault / "meta" / "index.md").write_text(
        "# Index\n\n## Knowledge\n- [[Known]]\n",
        encoding="utf-8",
    )
    log = vault / "meta" / "log.md"
    log.write_text("# Log\n- old entry\n", encoding="utf-8")
    (vault / "knowledge" / "Known.md").write_text(
        "---\ntitle: Known\n---\n# Known\n",
        encoding="utf-8",
    )

    report = lint_vault(vault, today=date(2026, 5, 11))

    assert "knowledge/Known.md: missing status in frontmatter" in report.issues
    log_text = log.read_text(encoding="utf-8")
    assert log_text.startswith("# Log\n- old entry\n")
    assert "- 2026-05-11 lint wiki -> output/lint-2026-05-11.md" in log_text


def test_lint_detects_stale_stubs_unprocessed_raw_and_personal_knowledge(
    tmp_path: Path,
):
    vault = tmp_path / "vault"
    (vault / "meta").mkdir(parents=True)
    (vault / "knowledge").mkdir()
    (vault / "raw" / "articles").mkdir(parents=True)
    (vault / "raw" / "elaborati").mkdir(parents=True)
    (vault / "meta" / "index.md").write_text(
        "# Index\n\n## Knowledge\n- [[Stub]]\n- [[Personal]]\n",
        encoding="utf-8",
    )
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    (vault / "knowledge" / "Stub.md").write_text(
        "---\nstatus: stub\nupdated: '2026-05-01'\n---\n# Stub\nTODO\n",
        encoding="utf-8",
    )
    (vault / "knowledge" / "Personal.md").write_text(
        "# Personal\n\nMy email is person@example.com\n",
        encoding="utf-8",
    )
    (vault / "raw" / "articles" / "fresh.md").write_text("# Fresh\n", encoding="utf-8")
    (vault / "raw" / "elaborati" / "old.md").write_text("# Old\n", encoding="utf-8")

    report = lint_vault(vault, today=date(2026, 5, 14))

    assert "knowledge/Stub.md: stale stub updated 2026-05-01" in report.issues
    assert "raw/articles/fresh.md: unprocessed raw file" in report.issues
    assert "raw/elaborati/old.md" not in "\n".join(report.issues)
    assert "knowledge/Personal.md: personal-looking content in knowledge" in report.issues
