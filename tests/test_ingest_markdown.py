from pathlib import Path

import pytest

from segretario.agents.ingest_agent import ConfirmationNeededError, ingest_article


def test_ingest_markdown_creates_knowledge_page_index_and_log(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Source Topic\n\nAlpha beta topic.\n\nRelated: [[Existing]]\n", encoding="utf-8")

    result = ingest_article(vault, "raw/articles/source.md", auto=True)

    target = vault / "knowledge" / "source-topic.md"
    assert result.path == "knowledge/source-topic.md"
    assert target.exists()
    written = target.read_text(encoding="utf-8")
    assert written.startswith("---\n")
    assert "title: Source Topic\n" in written
    assert "source_path: raw/articles/source.md\n" in written
    assert "[[Existing]]" in written
    assert "- [[Source Topic]]" in (vault / "meta" / "index.md").read_text(encoding="utf-8")
    assert "ingest raw/articles/source.md -> knowledge/source-topic.md" in (
        vault / "meta" / "log.md"
    ).read_text(encoding="utf-8")


def test_ingest_extracts_key_points_into_frontmatter(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "# Source Topic\n\nFirst important point.\n\nSecond important point.\n",
        encoding="utf-8",
    )

    ingest_article(vault, "raw/articles/source.md", auto=True)

    written = (vault / "knowledge" / "source-topic.md").read_text(encoding="utf-8")
    assert "key_points:\n" in written
    assert "- First important point." in written
    assert "- Second important point." in written


def test_ingest_classifies_plain_source_as_knowledge(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Knowledge Source\n\nOperational note.\n", encoding="utf-8")

    ingest_article(vault, "raw/articles/source.md", auto=True)

    written = (vault / "knowledge" / "knowledge-source.md").read_text(encoding="utf-8")
    assert "content_class: knowledge" in written


def test_ingest_adds_inbound_wikilink_from_related_knowledge_page(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "source.md"
    related = vault / "knowledge" / "related.md"
    source.parent.mkdir(parents=True)
    related.parent.mkdir(parents=True)
    source.write_text("# Source Topic\n\nAlpha beta topic.\n", encoding="utf-8")
    related.write_text("# Related\n\nThis page mentions Source Topic plainly.\n", encoding="utf-8")

    ingest_article(vault, "raw/articles/source.md", auto=True)

    assert "[[Source Topic]]" in related.read_text(encoding="utf-8")


def test_ingest_does_not_modify_raw_source(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "source.md"
    source.parent.mkdir(parents=True)
    original = "# Source Topic\n\nAlpha beta topic.\n"
    source.write_text(original, encoding="utf-8")

    ingest_article(vault, "raw/articles/source.md", auto=True)

    assert source.read_text(encoding="utf-8") == original


def test_ingest_strips_utf8_bom_from_title_and_body(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "bom.md"
    source.parent.mkdir(parents=True)
    source.write_text("\ufeff# BOM Title\n\nBody.\n", encoding="utf-8")

    ingest_article(vault, "raw/articles/bom.md", auto=True)

    written = (vault / "knowledge" / "bom-title.md").read_text(encoding="utf-8")
    index = (vault / "meta" / "index.md").read_text(encoding="utf-8")
    assert "\ufeff" not in written
    assert "\ufeff" not in index
    assert "title: BOM Title\n" in written
    assert "- [[BOM Title]]" in index


def test_ingest_text_creates_wikilinks_from_markdown_links(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "plain.txt"
    source.parent.mkdir(parents=True)
    source.write_text(
        "Plain Title\n\nSee [Existing Note](https://example.invalid/Existing Note.md).",
        encoding="utf-8",
    )

    ingest_article(vault, "raw/articles/plain.txt", auto=True)

    written = (vault / "knowledge" / "plain-title.md").read_text(encoding="utf-8")
    assert "[[Existing Note]]" in written


def test_ingest_updates_existing_knowledge_page_without_duplicate_index_or_log_header(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Source Topic\n\nFirst version.\n", encoding="utf-8")

    ingest_article(vault, "raw/articles/source.md", auto=True)
    source.write_text("# Source Topic\n\nSecond version.\n", encoding="utf-8")
    ingest_article(vault, "raw/articles/source.md", auto=True)

    assert "Second version." in (vault / "knowledge" / "source-topic.md").read_text(
        encoding="utf-8"
    )
    index = (vault / "meta" / "index.md").read_text(encoding="utf-8")
    assert index.count("- [[Source Topic]]") == 1
    log = (vault / "meta" / "log.md").read_text(encoding="utf-8")
    assert log.count("# Log\n") == 1


def test_ingest_appends_log_without_rewriting_existing_entries(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Source Topic\n\nBody.\n", encoding="utf-8")
    log = vault / "meta" / "log.md"
    log.parent.mkdir(parents=True)
    log.write_text("# Log\n- keep me\n", encoding="utf-8")

    ingest_article(vault, "raw/articles/source.md", auto=True)

    assert log.read_text(encoding="utf-8").startswith("# Log\n- keep me\n")


def test_personal_looking_ingest_requires_confirmation_and_does_not_write_self(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "diary.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Diary\n\nMy phone number is 555-123-4567.\n", encoding="utf-8")

    with pytest.raises(ConfirmationNeededError):
        ingest_article(vault, "raw/articles/diary.md", auto=True)

    assert not (vault / "self").exists()
    assert not (vault / "knowledge" / "diary.md").exists()


def test_ingest_rejects_symlink_source(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "linked.md"
    outside = tmp_path / "outside.md"
    source.parent.mkdir(parents=True)
    outside.write_text("# Outside\n\nsecret\n", encoding="utf-8")
    try:
        source.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is not available in this environment")

    with pytest.raises(ValueError, match="symlink"):
        ingest_article(vault, "raw/articles/linked.md", auto=True)
