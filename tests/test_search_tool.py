from pathlib import Path

import pytest

from segretario.tools.search_tool import search_vault


def test_search_finds_markdown_and_text_in_allowed_paths(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "notes").mkdir()
    (vault / "knowledge" / "Topic.md").write_text("alpha beta\n", encoding="utf-8")
    (vault / "notes" / "Scratch.txt").write_text("gamma alpha\n", encoding="utf-8")

    results = search_vault(vault, "alpha")

    assert [result.path for result in results] == [
        "knowledge/Topic.md",
        "notes/Scratch.txt",
    ]
    assert results[0].line == 1
    assert results[0].snippet == "alpha beta"


def test_search_skips_raw_elaborati_and_self_by_default(tmp_path: Path):
    vault = tmp_path / "vault"
    for folder in ["raw/articles", "raw/elaborati", "self", "knowledge"]:
        (vault / folder).mkdir(parents=True)
    (vault / "raw" / "articles" / "source.md").write_text("alpha\n", encoding="utf-8")
    (vault / "raw" / "elaborati" / "draft.md").write_text("alpha\n", encoding="utf-8")
    (vault / "self" / "profile.md").write_text("alpha\n", encoding="utf-8")
    (vault / "knowledge" / "Topic.md").write_text("alpha\n", encoding="utf-8")

    results = search_vault(vault, "alpha")

    assert [result.path for result in results] == ["knowledge/Topic.md"]


def test_search_can_include_self_when_explicit(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "self").mkdir(parents=True)
    (vault / "self" / "profile.md").write_text("alpha\n", encoding="utf-8")

    results = search_vault(vault, "alpha", include_self=True)

    assert [result.path for result in results] == ["self/profile.md"]


def test_search_skips_symlinked_files(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("alpha outside\n", encoding="utf-8")
    link = vault / "knowledge" / "linked.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is not available in this environment")

    results = search_vault(vault, "alpha")

    assert results == []
