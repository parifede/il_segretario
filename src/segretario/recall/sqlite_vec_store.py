from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import sqlite_vec

from segretario.recall.vector_store import VectorHit

logger = logging.getLogger(__name__)

# DDL -------------------------------------------------------------------

_DDL_INDEXED_CHUNKS = """
CREATE TABLE IF NOT EXISTS indexed_chunks (
    note_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    section_title TEXT,
    content_hash TEXT NOT NULL,
    note_hash TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    PRIMARY KEY (note_path, chunk_index)
);
"""

_DDL_IDX_NOTE_PATH = """
CREATE INDEX IF NOT EXISTS idx_chunks_note_path ON indexed_chunks(note_path);
"""

_DDL_IDX_NOTE_HASH = """
CREATE INDEX IF NOT EXISTS idx_chunks_note_hash ON indexed_chunks(note_hash);
"""

# chunk_vectors uses vec0 virtual table with cosine distance metric.
# sqlite-vec 0.1.x exposes a `distance` column automatically in KNN queries.
# distance_metric=cosine: distance in [0, 2]; similarity = 1.0 - distance in [-1, 1].
_DDL_CHUNK_VECTORS = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
    note_path TEXT,
    chunk_index INTEGER,
    embedding FLOAT[1024] distance_metric=cosine
);
"""


class SqliteVecStore:
    """SQLite-backed vector store using sqlite-vec 0.1.x with cosine distance metric.

    Stores embeddings at chunk granularity (one row per chunk).

    sqlite-vec API notes (verified against v0.1.9):
    - Virtual table: vec0(note_path TEXT, chunk_index INTEGER, embedding FLOAT[1024] distance_metric=cosine)
    - KNN query: SELECT note_path, chunk_index, distance FROM chunk_vectors
                 WHERE embedding MATCH ? ORDER BY distance ASC LIMIT k
      where ? is a JSON array string (e.g. '[0.1, 0.2, ...]')
    - distance=0 means identical vector (cosine distance in [0, 2], lower is more similar)
    - score = 1.0 - distance: cosine similarity in [-1, 1], higher is more similar
    - UPDATE is not supported on vec0; upsert must be DELETE + INSERT in one txn
    - DELETE by auxiliary column works: DELETE FROM chunk_vectors WHERE note_path = ?
    """

    def __init__(
        self,
        db_path: Path,
        embedding_model: str = "mxbai-embed-large",
    ) -> None:
        self._db_path = db_path
        self._embedding_model = embedding_model
        self._conn = self._open_connection(db_path)
        self._migrate_if_needed()
        self._create_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _open_connection(db_path: Path) -> sqlite3.Connection:
        """Open (or create) the database and load the sqlite-vec extension."""
        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)  # re-disable for security
        return conn

    def _migrate_if_needed(self) -> None:
        """Drop old schema if the legacy indexed_notes table exists.

        Also drops chunk_vectors if it was created without cosine metric,
        forcing a full reindex so scores are correct similarity values.
        """
        row = self._conn.execute(
            "PRAGMA table_info(indexed_notes)"
        ).fetchone()
        if row is not None:
            logger.warning(
                "SqliteVecStore: detected old schema (indexed_notes table). "
                "Dropping all old tables and recreating with chunk-based schema."
            )
            with self._conn:
                # Drop old tables; ignore errors if virtual table already gone
                try:
                    self._conn.execute("DROP TABLE IF EXISTS note_vectors")
                except Exception:
                    pass
                self._conn.execute("DROP TABLE IF EXISTS indexed_notes")

        # Check if chunk_vectors exists but without cosine metric (needs recreation)
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='chunk_vectors'"
        ).fetchone()
        if row is not None and "distance_metric=cosine" not in (row[0] or ""):
            logger.warning(
                "SqliteVecStore: chunk_vectors exists without cosine metric. "
                "Dropping and recreating with cosine. Full reindex required."
            )
            with self._conn:
                try:
                    self._conn.execute("DROP TABLE IF EXISTS chunk_vectors")
                except Exception:
                    pass
                try:
                    self._conn.execute("DELETE FROM indexed_chunks")
                except Exception:
                    pass

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.execute(_DDL_INDEXED_CHUNKS)
            self._conn.execute(_DDL_IDX_NOTE_PATH)
            self._conn.execute(_DDL_IDX_NOTE_HASH)
            self._conn.execute(_DDL_CHUNK_VECTORS)

    # ------------------------------------------------------------------
    # Public interface (satisfies VectorStore protocol)
    # ------------------------------------------------------------------

    def upsert_chunk(
        self,
        note_path: str,
        chunk_index: int,
        section_title: str | None,
        embedding: list[float],
        content_hash: str,
        note_hash: str,
    ) -> None:
        """Insert or update the embedding for a chunk. Atomic + idempotent.

        Uses DELETE + INSERT for chunk_vectors because vec0 virtual tables do
        not support UPDATE. Both tables are updated in a single transaction.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        embedding_json = json.dumps(embedding)
        with self._conn:
            # chunk_vectors: DELETE + INSERT (vec0 does not support UPDATE)
            self._conn.execute(
                "DELETE FROM chunk_vectors WHERE note_path = ? AND chunk_index = ?",
                (note_path, chunk_index),
            )
            self._conn.execute(
                "INSERT INTO chunk_vectors(note_path, chunk_index, embedding) VALUES (?, ?, ?)",
                (note_path, chunk_index, embedding_json),
            )
            # indexed_chunks: standard upsert via INSERT OR REPLACE
            self._conn.execute(
                """
                INSERT OR REPLACE INTO indexed_chunks
                    (note_path, chunk_index, section_title, content_hash, note_hash,
                     indexed_at, embedding_model)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (note_path, chunk_index, section_title, content_hash, note_hash,
                 now_iso, self._embedding_model),
            )

    def delete_note(self, note_path: str) -> None:
        """Remove ALL chunks for a note from both indexed_chunks and chunk_vectors."""
        with self._conn:
            self._conn.execute(
                "DELETE FROM indexed_chunks WHERE note_path = ?",
                (note_path,),
            )
            self._conn.execute(
                "DELETE FROM chunk_vectors WHERE note_path = ?",
                (note_path,),
            )

    def query(self, embedding: list[float], k: int = 5) -> list[VectorHit]:
        """Return top-k hits ordered by descending similarity (highest first).

        sqlite-vec returns cosine distance (range [0, 2], lower=more similar).
        We convert: similarity = 1.0 - distance (range [-1, 1], higher=more similar).
        For normalized embeddings from mxbai-embed-large, practical range is [0, 1].
        ORDER BY distance ASC = ORDER BY similarity DESC.
        """
        embedding_json = json.dumps(embedding)
        rows = self._conn.execute(
            """
            SELECT note_path, chunk_index, distance
            FROM chunk_vectors
            WHERE embedding MATCH ?
            ORDER BY distance ASC
            LIMIT ?
            """,
            (embedding_json, k),
        ).fetchall()

        if not rows:
            return []

        hits: list[VectorHit] = []
        for note_path, chunk_index, distance in rows:
            similarity = 1.0 - distance  # cosine distance → cosine similarity
            section_row = self._conn.execute(
                "SELECT section_title FROM indexed_chunks WHERE note_path = ? AND chunk_index = ?",
                (note_path, chunk_index),
            ).fetchone()
            section_title = section_row[0] if section_row else None
            hits.append(VectorHit(
                note_path=note_path,
                chunk_index=chunk_index,
                section_title=section_title,
                score=similarity,
            ))
        return hits

    def get_indexed_note_hash(self, note_path: str) -> str | None:
        """Return the stored note_hash for a note, or None if not indexed."""
        row = self._conn.execute(
            "SELECT note_hash FROM indexed_chunks WHERE note_path = ? LIMIT 1",
            (note_path,),
        ).fetchone()
        return row[0] if row else None

    def list_indexed_paths(self) -> set[str]:
        """Return the set of all indexed note paths for diff computation."""
        rows = self._conn.execute(
            "SELECT DISTINCT note_path FROM indexed_chunks"
        ).fetchall()
        return {row[0] for row in rows}

    def health_check(self) -> bool:
        """Return True if store is operational (connection + vec extension loaded).

        Never raises; returns False on any exception.
        """
        try:
            self._conn.execute("SELECT vec_version()").fetchone()
            self._conn.execute("SELECT COUNT(*) FROM indexed_chunks LIMIT 1").fetchone()
            return True
        except Exception:
            logger.debug("SqliteVecStore.health_check failed", exc_info=True)
            return False

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()

    def __enter__(self) -> "SqliteVecStore":
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()
