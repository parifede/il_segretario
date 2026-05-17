"""Tests for segretario.recall.sqlite_vec_store (SqliteVecStore)."""
from __future__ import annotations

from pathlib import Path

import pytest

from segretario.recall.sqlite_vec_store import SqliteVecStore


def _make_store() -> SqliteVecStore:
    return SqliteVecStore(Path(":memory:"))


# ---------------------------------------------------------------------------
# test 5
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_upsert_and_query():
    """3 orthogonal vectors; query nearest → top hit is correct."""
    store = _make_store()
    v1 = [1.0] + [0.0] * 1023
    v2 = [0.0, 1.0] + [0.0] * 1022
    v3 = [0.0, 0.0, 1.0] + [0.0] * 1021
    query = [1.0] + [0.0] * 1023  # should match v1

    store.upsert("note1.md", v1, "hash1")
    store.upsert("note2.md", v2, "hash2")
    store.upsert("note3.md", v3, "hash3")

    hits = store.query(query, k=1)
    assert len(hits) == 1
    assert hits[0].note_path == "note1.md"


# ---------------------------------------------------------------------------
# test 6
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_upsert_idempotent():
    """Upsert same path twice → exactly 1 record in indexed_notes."""
    store = _make_store()
    v = [1.0] + [0.0] * 1023

    store.upsert("note.md", v, "hash1")
    store.upsert("note.md", v, "hash2")  # second upsert same path

    count = store._conn.execute(
        "SELECT COUNT(*) FROM indexed_notes WHERE path = ?", ("note.md",)
    ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# test 7
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_delete():
    """Upsert then delete → note is gone from indexed_notes."""
    store = _make_store()
    v = [1.0] + [0.0] * 1023

    store.upsert("note.md", v, "hash1")
    store.delete("note.md")

    row = store._conn.execute(
        "SELECT * FROM indexed_notes WHERE path = ?", ("note.md",)
    ).fetchone()
    assert row is None

    # Also verify the vector is gone
    hits = store.query(v, k=5)
    assert all(h.note_path != "note.md" for h in hits)


# ---------------------------------------------------------------------------
# test 8
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_health_check():
    """Real in-memory db → health_check() returns True."""
    store = _make_store()
    assert store.health_check() is True
