"""Tests for segretario.recall.indexer (VaultIndexer)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from segretario.recall.embedder import EmbedderError, OllamaEmbedder
from segretario.recall.indexer import VaultIndexer
from segretario.recall.sqlite_vec_store import SqliteVecStore


def _make_embedder(dims: int = 1024) -> MagicMock:
    mock = MagicMock(spec=OllamaEmbedder)
    mock.embed.return_value = [0.1] * dims
    mock.embed.side_effect = None
    return mock


def _make_store() -> SqliteVecStore:
    return SqliteVecStore(Path(":memory:"))


def _make_indexer(vault_path: Path, embedder=None, store=None, skip_paths=None) -> VaultIndexer:
    if embedder is None:
        embedder = _make_embedder()
    if store is None:
        store = _make_store()
    return VaultIndexer(
        vault_path=vault_path,
        store=store,
        embedder=embedder,
        skip_paths=skip_paths or ["raw/elaborati"],
    )


# ---------------------------------------------------------------------------
# test 9
# ---------------------------------------------------------------------------

def test_indexer_reindex_new_vault(tmp_path: Path):
    """3 .md files in tmp_path, mock embedder, in-memory store → indexed=3."""
    (tmp_path / "a.md").write_text("# A\ncontent a\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\ncontent b\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("# C\ncontent c\n", encoding="utf-8")

    indexer = _make_indexer(tmp_path)
    result = indexer.reindex()

    assert result.indexed == 3
    assert result.errors == []


# ---------------------------------------------------------------------------
# test 10
# ---------------------------------------------------------------------------

def test_indexer_reindex_skips_unchanged(tmp_path: Path):
    """Run reindex twice, same files → second run: skipped_unchanged=3, indexed=0."""
    (tmp_path / "a.md").write_text("# A\ncontent a\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\ncontent b\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("# C\ncontent c\n", encoding="utf-8")

    embedder = _make_embedder()
    store = _make_store()
    indexer = VaultIndexer(vault_path=tmp_path, store=store, embedder=embedder)

    first = indexer.reindex()
    assert first.indexed == 3

    second = indexer.reindex()
    assert second.skipped_unchanged == 3
    assert second.indexed == 0


# ---------------------------------------------------------------------------
# test 11
# ---------------------------------------------------------------------------

def test_indexer_reindex_detects_modified(tmp_path: Path):
    """Reindex, modify 1 file content, reindex again → indexed=1."""
    note = tmp_path / "a.md"
    note.write_text("# A\noriginal content\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\ncontent b\n", encoding="utf-8")

    embedder = _make_embedder()
    store = _make_store()
    indexer = VaultIndexer(vault_path=tmp_path, store=store, embedder=embedder)

    indexer.reindex()

    # Modify one file
    note.write_text("# A\nmodified content\n", encoding="utf-8")

    second = indexer.reindex()
    assert second.indexed == 1
    assert second.skipped_unchanged == 1


# ---------------------------------------------------------------------------
# test 12
# ---------------------------------------------------------------------------

def test_indexer_reindex_detects_deleted(tmp_path: Path):
    """Reindex, delete 1 file, reindex → deleted=1."""
    note_a = tmp_path / "a.md"
    note_a.write_text("# A\ncontent a\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\ncontent b\n", encoding="utf-8")

    embedder = _make_embedder()
    store = _make_store()
    indexer = VaultIndexer(vault_path=tmp_path, store=store, embedder=embedder)

    indexer.reindex()

    note_a.unlink()

    second = indexer.reindex()
    assert second.deleted == 1


# ---------------------------------------------------------------------------
# test 13
# ---------------------------------------------------------------------------

def test_indexer_respects_skip_paths(tmp_path: Path):
    """File in raw/elaborati/ → NOT indexed."""
    skip_dir = tmp_path / "raw" / "elaborati"
    skip_dir.mkdir(parents=True)
    (skip_dir / "secret.md").write_text("# Secret\ncontent\n", encoding="utf-8")
    # Also add a non-skipped file
    (tmp_path / "visible.md").write_text("# Visible\n", encoding="utf-8")

    embedder = _make_embedder()
    store = _make_store()
    indexer = VaultIndexer(
        vault_path=tmp_path,
        store=store,
        embedder=embedder,
        skip_paths=["raw/elaborati"],
    )

    result = indexer.reindex()

    assert result.indexed == 1  # only visible.md
    # Verify the secret file was not indexed
    paths = store.list_indexed_paths()
    assert not any("secret" in p for p in paths)


# ---------------------------------------------------------------------------
# test 14
# ---------------------------------------------------------------------------

def test_indexer_indexes_self_directory(tmp_path: Path):
    """File in self/ → INDEXED (not in skip_paths by default in indexer)."""
    self_dir = tmp_path / "self"
    self_dir.mkdir(parents=True)
    (self_dir / "profile.md").write_text("# Profile\ncontent\n", encoding="utf-8")

    embedder = _make_embedder()
    store = _make_store()
    # Default skip_paths = ["raw/elaborati"], so self/ is not skipped
    indexer = VaultIndexer(
        vault_path=tmp_path,
        store=store,
        embedder=embedder,
        skip_paths=["raw/elaborati"],
    )

    result = indexer.reindex()

    assert result.indexed == 1
    paths = store.list_indexed_paths()
    assert any("profile" in p for p in paths)


# ---------------------------------------------------------------------------
# test 15
# ---------------------------------------------------------------------------

def test_indexer_handles_single_note_embed_failure(tmp_path: Path):
    """Mock embedder raises EmbedderError for 1 note → that note in errors, others indexed."""
    (tmp_path / "good1.md").write_text("# Good1\ncontent\n", encoding="utf-8")
    (tmp_path / "bad.md").write_text("# Bad\ncontent\n", encoding="utf-8")
    (tmp_path / "good2.md").write_text("# Good2\ncontent\n", encoding="utf-8")

    embedder = MagicMock(spec=OllamaEmbedder)

    def embed_side_effect(text: str) -> list[float]:
        if "Bad" in text:
            raise EmbedderError("simulated embed failure")
        return [0.1] * 1024

    embedder.embed.side_effect = embed_side_effect

    store = _make_store()
    indexer = VaultIndexer(vault_path=tmp_path, store=store, embedder=embedder)

    result = indexer.reindex()

    assert result.indexed == 2
    assert len(result.errors) == 1
    assert "bad.md" in result.errors[0]
