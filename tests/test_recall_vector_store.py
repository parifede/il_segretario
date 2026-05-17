"""Tests for segretario.recall.sqlite_vec_store (SqliteVecStore)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

from segretario.recall.sqlite_vec_store import SqliteVecStore


def _make_store() -> SqliteVecStore:
    return SqliteVecStore(Path(":memory:"))


def _vec(dim: int = 1024, hot_index: int = 0) -> list[float]:
    v = [0.0] * dim
    v[hot_index] = 1.0
    return v


# ---------------------------------------------------------------------------
# test 5
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_upsert_chunk_and_query():
    """3 orthogonal vectors; query nearest → top hit is correct."""
    store = _make_store()
    v1 = _vec(hot_index=0)
    v2 = _vec(hot_index=1)
    v3 = _vec(hot_index=2)
    query = _vec(hot_index=0)  # should match v1

    store.upsert_chunk("note1.md", 0, None, v1, "chash1", "nhash1")
    store.upsert_chunk("note2.md", 0, None, v2, "chash2", "nhash2")
    store.upsert_chunk("note3.md", 0, None, v3, "chash3", "nhash3")

    hits = store.query(query, k=1)
    assert len(hits) == 1
    assert hits[0].note_path == "note1.md"
    assert hits[0].chunk_index == 0


# ---------------------------------------------------------------------------
# test 6
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_upsert_chunk_idempotent():
    """Upsert same (note_path, chunk_index) twice → exactly 1 record in indexed_chunks."""
    store = _make_store()
    v = _vec(hot_index=0)

    store.upsert_chunk("note.md", 0, None, v, "chash1", "nhash1")
    store.upsert_chunk("note.md", 0, None, v, "chash2", "nhash2")  # second upsert same pk

    count = store._conn.execute(
        "SELECT COUNT(*) FROM indexed_chunks WHERE note_path = ? AND chunk_index = ?",
        ("note.md", 0),
    ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# test 7
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_delete_note():
    """Upsert then delete_note → all chunks gone from indexed_chunks."""
    store = _make_store()
    v0 = _vec(hot_index=0)
    v1 = _vec(hot_index=1)

    store.upsert_chunk("note.md", 0, None, v0, "chash0", "nhash")
    store.upsert_chunk("note.md", 1, "Section A", v1, "chash1", "nhash")
    store.delete_note("note.md")

    row = store._conn.execute(
        "SELECT * FROM indexed_chunks WHERE note_path = ?", ("note.md",)
    ).fetchone()
    assert row is None

    # Also verify the vectors are gone
    hits = store.query(v0, k=5)
    assert all(h.note_path != "note.md" for h in hits)


# ---------------------------------------------------------------------------
# test 8
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_health_check():
    """Real in-memory db → health_check() returns True."""
    store = _make_store()
    assert store.health_check() is True


# ---------------------------------------------------------------------------
# test: section_title is stored and returned in VectorHit
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_section_title_in_hit():
    """upsert_chunk with section_title → query returns it in VectorHit."""
    store = _make_store()
    v = _vec(hot_index=5)
    store.upsert_chunk("note.md", 2, "My Section", v, "ch", "nh")

    hits = store.query(v, k=1)
    assert len(hits) == 1
    assert hits[0].section_title == "My Section"
    assert hits[0].chunk_index == 2


# ---------------------------------------------------------------------------
# test: get_indexed_note_hash
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_get_indexed_note_hash():
    """get_indexed_note_hash returns note_hash, not content_hash."""
    store = _make_store()
    v = _vec(hot_index=3)
    store.upsert_chunk("note.md", 0, None, v, "content_hash_abc", "note_hash_xyz")

    assert store.get_indexed_note_hash("note.md") == "note_hash_xyz"
    assert store.get_indexed_note_hash("missing.md") is None


# ---------------------------------------------------------------------------
# test: list_indexed_paths returns DISTINCT note paths
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_list_indexed_paths():
    """list_indexed_paths returns each note_path once even with multiple chunks."""
    store = _make_store()
    v0 = _vec(hot_index=0)
    v1 = _vec(hot_index=1)
    store.upsert_chunk("note_a.md", 0, None, v0, "ch0", "nh_a")
    store.upsert_chunk("note_a.md", 1, None, v1, "ch1", "nh_a")
    store.upsert_chunk("note_b.md", 0, None, v0, "ch2", "nh_b")

    paths = store.list_indexed_paths()
    assert paths == {"note_a.md", "note_b.md"}


# ---------------------------------------------------------------------------
# test: old schema migration
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_migrates_old_schema(tmp_path: Path):
    """Creating a store on a DB with old indexed_notes table triggers migration."""
    db_path = tmp_path / "test.db"

    # Create old schema manually
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indexed_notes (
            path TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            indexed_at TEXT NOT NULL,
            chunk_count INTEGER NOT NULL,
            embedding_model TEXT NOT NULL
        )
    """)
    conn.execute("INSERT INTO indexed_notes VALUES ('old.md', 'hash', '2024-01-01', 1, 'model')")
    conn.commit()
    conn.close()

    # Opening with SqliteVecStore should trigger migration (no crash)
    store = SqliteVecStore(db_path)

    # Old data should be gone, new schema present
    assert store.get_indexed_note_hash("old.md") is None
    assert store.health_check() is True

    # New schema tables should exist
    tables = {row[0] for row in store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "indexed_chunks" in tables
    assert "indexed_notes" not in tables


# ---------------------------------------------------------------------------
# test: score is similarity (not distance)
# ---------------------------------------------------------------------------

def test_vector_store_query_returns_similarity_not_distance(tmp_path: Path):
    """score is similarity (higher=better), not raw distance."""
    store = SqliteVecStore(tmp_path / "test.db")
    # Create unit vectors (normalized, so cosine similarity is well-defined)
    # very_similar: same direction as query → similarity ~1.0
    very_similar = [1.0] + [0.0] * 1023
    # very_different: opposite direction → similarity ~-1.0
    very_different = [-1.0] + [0.0] * 1023
    query = [1.0] + [0.0] * 1023

    store.upsert_chunk("similar.md", 0, None, very_similar, "h1", "n1")
    store.upsert_chunk("different.md", 0, None, very_different, "h2", "n2")

    hits = store.query(query, k=2)

    assert len(hits) == 2
    # First hit must be "similar" (highest similarity)
    assert hits[0].note_path == "similar.md"
    # Score must be very high (near 1.0 for identical direction)
    assert hits[0].score > 0.9
    # Different vector must have lower score
    assert hits[0].score > hits[1].score


# ---------------------------------------------------------------------------
# test: results ordered by similarity descending
# ---------------------------------------------------------------------------

def test_vector_store_query_orders_by_similarity_descending(tmp_path: Path):
    """Results are ordered highest similarity first."""
    import math

    store = SqliteVecStore(tmp_path / "test.db")
    query = [1.0] + [0.0] * 1023
    # Three vectors: identical, 45 degrees, 90 degrees
    vec_identical = [1.0] + [0.0] * 1023
    vec_45 = [math.cos(math.pi / 4), math.sin(math.pi / 4)] + [0.0] * 1022
    vec_90 = [0.0, 1.0] + [0.0] * 1022

    store.upsert_chunk("identical.md", 0, None, vec_identical, "h1", "n1")
    store.upsert_chunk("45deg.md", 0, None, vec_45, "h2", "n2")
    store.upsert_chunk("90deg.md", 0, None, vec_90, "h3", "n3")

    hits = store.query(query, k=3)

    # Scores must be non-increasing (descending)
    for i in range(len(hits) - 1):
        assert hits[i].score >= hits[i + 1].score
    # All scores in valid cosine similarity range
    for hit in hits:
        assert -1.0 <= hit.score <= 1.0


# ---------------------------------------------------------------------------
# test: score never exceeds 1.0
# ---------------------------------------------------------------------------

def test_vector_store_score_never_exceeds_one(tmp_path: Path):
    """No score should be > 1.0 (would indicate raw distance leaked through)."""
    import random

    store = SqliteVecStore(tmp_path / "test.db")
    rng = random.Random(42)
    for i in range(5):
        vec = [rng.gauss(0, 1) for _ in range(1024)]
        norm = sum(x * x for x in vec) ** 0.5
        vec = [x / norm for x in vec]
        store.upsert_chunk(f"note{i}.md", 0, None, vec, f"h{i}", f"n{i}")

    query = [rng.gauss(0, 1) for _ in range(1024)]
    norm = sum(x * x for x in query) ** 0.5
    query = [x / norm for x in query]

    hits = store.query(query, k=5)
    for hit in hits:
        assert hit.score <= 1.0, f"Score {hit.score} > 1.0 — raw distance leaked through"


# ---------------------------------------------------------------------------
# test: migration from non-cosine chunk_vectors
# ---------------------------------------------------------------------------

def test_sqlite_vec_store_migrates_non_cosine_chunk_vectors(tmp_path: Path):
    """chunk_vectors created without cosine metric is dropped and recreated."""
    db_path = tmp_path / "test.db"

    # Create schema manually WITHOUT cosine metric (simulating old store)
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indexed_chunks (
            note_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            section_title TEXT,
            content_hash TEXT NOT NULL,
            note_hash TEXT NOT NULL,
            indexed_at TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            PRIMARY KEY (note_path, chunk_index)
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
            note_path TEXT,
            chunk_index INTEGER,
            embedding FLOAT[1024]
        )
    """)
    conn.commit()
    conn.close()

    # Opening with SqliteVecStore should trigger migration (no crash)
    store = SqliteVecStore(db_path)
    assert store.health_check() is True

    # Verify chunk_vectors was recreated with cosine metric
    row = store._conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='chunk_vectors'"
    ).fetchone()
    # The new DDL should contain distance_metric=cosine
    assert row is not None
    assert "distance_metric=cosine" in (row[0] or "")
