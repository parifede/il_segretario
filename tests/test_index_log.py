from segretario.vault.adapter import VaultAdapter
from segretario.vault.index_log import append_log, ensure_meta_index


def test_resolve_rejects_parent_traversal_and_outside_absolute_path(tmp_path):
    adapter = VaultAdapter(tmp_path)

    for unsafe in ("../secret.md", "knowledge/../secret.md", tmp_path.parent / "secret.md"):
        try:
            adapter.resolve(unsafe)
        except ValueError as exc:
            assert "outside vault" in str(exc) or "parent traversal" in str(exc)
        else:
            raise AssertionError(f"expected ValueError for {unsafe}")


def test_resolve_accepts_vault_relative_and_inside_absolute_paths(tmp_path):
    adapter = VaultAdapter(tmp_path)
    inside = tmp_path / "knowledge" / "note.md"

    assert adapter.resolve("knowledge/note.md") == inside
    assert adapter.resolve(inside) == inside


def test_iter_files_skips_raw_elaborati(tmp_path):
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "raw" / "elaborati").mkdir(parents=True)
    keep = tmp_path / "knowledge" / "note.md"
    skip = tmp_path / "raw" / "elaborati" / "draft.md"
    keep.write_text("keep", encoding="utf-8")
    skip.write_text("skip", encoding="utf-8")

    files = list(VaultAdapter(tmp_path).iter_files())

    assert files == [keep]


def test_ensure_meta_index_creates_index_with_single_knowledge_heading(tmp_path):
    first = ensure_meta_index(tmp_path)
    second = ensure_meta_index(tmp_path)

    assert first == tmp_path / "meta" / "index.md"
    assert second == first
    text = first.read_text(encoding="utf-8")
    assert text.count("## Self") == 1
    assert first.read_text(encoding="utf-8").count("## Knowledge") == 1
    assert text.count("## Output") == 1


def test_ensure_meta_index_does_not_duplicate_existing_canonical_headings(tmp_path):
    index = tmp_path / "meta" / "index.md"
    index.parent.mkdir()
    index.write_text(
        "# Index\n\n## Self\n\n## Knowledge\n\n- Existing\n\n## Output\n",
        encoding="utf-8",
    )

    ensure_meta_index(tmp_path)

    text = index.read_text(encoding="utf-8")
    assert text.count("## Self") == 1
    assert text.count("## Knowledge") == 1
    assert text.count("## Output") == 1


def test_ensure_meta_index_strips_utf8_bom(tmp_path):
    index = tmp_path / "meta" / "index.md"
    index.parent.mkdir()
    index.write_text("\ufeff# Index\n\n## Knowledge\n\n- [[\ufeffBad Title]]\n", encoding="utf-8")

    ensure_meta_index(tmp_path)

    assert "\ufeff" not in index.read_text(encoding="utf-8")


def test_append_log_appends_without_rewriting_existing_entries(tmp_path):
    log = tmp_path / "meta" / "log.md"
    log.parent.mkdir()
    log.write_text("first\n", encoding="utf-8")

    append_log(tmp_path, "second")
    append_log(tmp_path, "third\n")

    assert log.read_text(encoding="utf-8") == "first\nsecond\nthird\n"
