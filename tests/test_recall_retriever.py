"""Tests for segretario.recall.embedding_retriever (EmbeddingRetriever)."""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from segretario.recall.embedding_retriever import EmbeddingRetriever
from segretario.recall.embedder import OllamaEmbedder
from segretario.recall.sqlite_vec_store import SqliteVecStore
from segretario.recall.vector_store import VectorHit


def _make_embedder(return_vec: list[float] | None = None) -> MagicMock:
    mock = MagicMock(spec=OllamaEmbedder)
    mock.embed.return_value = return_vec or ([0.1] * 1024)
    return mock


def _make_store_with_notes(vault_path: Path, n: int) -> SqliteVecStore:
    store = SqliteVecStore(Path(":memory:"))
    for i in range(n):
        note_file = vault_path / f"note{i}.md"
        note_file.write_text(f"# Note {i}\nContent of note {i}.\n", encoding="utf-8")
        vec = [0.0] * 1024
        vec[i % 1024] = 1.0
        store.upsert_chunk(f"note{i}.md", 0, None, vec, f"chash{i}", f"nhash{i}")
    return store


# ---------------------------------------------------------------------------
# test 16
# ---------------------------------------------------------------------------

def test_embedding_retriever_search_returns_top_k(tmp_path: Path):
    """Store with 10 notes, k=3 → returns 3 hits."""
    n = 10
    store = _make_store_with_notes(tmp_path, n)
    embedder = _make_embedder()
    # Use a query vector that matches note0 (vec[0]=1.0)
    query_vec = [0.0] * 1024
    query_vec[0] = 1.0
    embedder.embed.return_value = query_vec

    retriever = EmbeddingRetriever(vault_path=tmp_path, store=store, embedder=embedder)
    hits = retriever.search("some query", k=3)

    assert len(hits) == 3


# ---------------------------------------------------------------------------
# test 17
# ---------------------------------------------------------------------------

def test_embedding_retriever_skips_missing_files(tmp_path: Path, caplog):
    """Vector hit for nonexistent file → skip + log WARNING."""
    store = SqliteVecStore(Path(":memory:"))
    # Insert a vector for a path that doesn't exist on disk
    vec = [1.0] + [0.0] * 1023
    store.upsert_chunk("ghost.md", 0, None, vec, "hashX", "nhashX")

    embedder = _make_embedder(return_vec=[1.0] + [0.0] * 1023)

    retriever = EmbeddingRetriever(vault_path=tmp_path, store=store, embedder=embedder)

    with caplog.at_level(logging.WARNING):
        hits = retriever.search("query")

    assert len(hits) == 0
    assert any("ghost.md" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# test: RecallHit has chunk_index and section_title fields
# ---------------------------------------------------------------------------

def test_embedding_retriever_hit_has_chunk_fields(tmp_path: Path):
    """RecallHit returned by search has chunk_index and section_title populated."""
    store = SqliteVecStore(Path(":memory:"))
    note_file = tmp_path / "sectioned.md"
    note_file.write_text("## My Section\nSome content here.\n", encoding="utf-8")
    vec = [1.0] + [0.0] * 1023
    store.upsert_chunk("sectioned.md", 0, "My Section", vec, "ch", "nh")

    embedder = _make_embedder(return_vec=[1.0] + [0.0] * 1023)
    retriever = EmbeddingRetriever(vault_path=tmp_path, store=store, embedder=embedder)

    hits = retriever.search("query", k=1)

    assert len(hits) == 1
    assert hits[0].chunk_index == 0
    assert hits[0].section_title == "My Section"
    assert hits[0].note_path == "sectioned.md"


# ---------------------------------------------------------------------------
# test: drift — chunk_index out of range → skip with warning
# ---------------------------------------------------------------------------

def test_embedding_retriever_skips_drifted_chunk_index(tmp_path: Path, caplog):
    """If chunk_index in store is beyond current chunks, skip with WARNING."""
    store = SqliteVecStore(Path(":memory:"))
    # Note has short content → 1 chunk (index 0)
    note_file = tmp_path / "short.md"
    note_file.write_text("Short note.", encoding="utf-8")
    vec = [1.0] + [0.0] * 1023
    # Store chunk_index=5 (which won't exist after re-chunking)
    store.upsert_chunk("short.md", 5, None, vec, "ch", "nh")

    embedder = _make_embedder(return_vec=[1.0] + [0.0] * 1023)
    retriever = EmbeddingRetriever(vault_path=tmp_path, store=store, embedder=embedder)

    with caplog.at_level(logging.WARNING):
        hits = retriever.search("query")

    assert len(hits) == 0
    assert any("drift" in record.message.lower() or "out of range" in record.message for record in caplog.records)
