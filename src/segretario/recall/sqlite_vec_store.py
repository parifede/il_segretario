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

_DDL_INDEXED_NOTES = """
CREATE TABLE IF NOT EXISTS indexed_notes (
    path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    embedding_model TEXT NOT NULL
);
"""

# note_vectors uses vec0 virtual table with cosine distance metric.
# sqlite-vec 0.1.x exposes a `distance` column automatically in KNN queries.
# Syntax: SELECT note_path, distance FROM note_vectors
#         WHERE embedding MATCH <json_array_string> ORDER BY distance LIMIT k
_DDL_NOTE_VECTORS = """
CREATE VIRTUAL TABLE IF NOT EXISTS note_vectors USING vec0(
    note_path TEXT,
    embedding FLOAT[1024] distance_metric=cosine
);
"""

_DDL_INDEX = """
CREATE INDEX IF NOT EXISTS idx_indexed_notes_hash ON indexed_notes(content_hash);
"""


class SqliteVecStore:
    """SQLite-backed vector store using sqlite-vec 0.1.x with cosine distance.

    Single connection, single DB file.  Thread safety is the caller's concern.

    sqlite-vec API notes (verified against v0.1.9):
    - Virtual table: vec0(note_path TEXT, embedding FLOAT[1024] distance_metric=cosine)
    - KNN query: SELECT note_path, distance FROM note_vectors
                 WHERE embedding MATCH ? ORDER BY distance LIMIT k
      where ? is a JSON array string (e.g. '[0.1, 0.2, ...]')
    - distance=0 means identical vector (cosine distance, lower is more similar)
    - UPDATE is not supported on vec0; upsert must be DELETE + INSERT in one txn
    - DELETE by auxiliary column works: DELETE FROM note_vectors WHERE note_path = ?
    """

    def __init__(
        self,
        db_path: Path,
        embedding_model: str = "mxbai-embed-large",
    ) -> None:
        self._db_path = db_path
        self._embedding_model = embedding_model
        self._conn = self._open_connection(db_path)
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

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.execute(_DDL_INDEXED_NOTES)
            self._conn.execute(_DDL_NOTE_VECTORS)
            self._conn.execute(_DDL_INDEX)

    # ------------------------------------------------------------------
    # Public interface (satisfies VectorStore protocol)
    # ------------------------------------------------------------------

    def upsert(self, note_path: str, embedding: list[float], content_hash: str) -> None:
        """Insert or update the embedding for a note.  Atomic + idempotent.

        Uses DELETE + INSERT for note_vectors because vec0 virtual tables do
        not support UPDATE.  Both tables are updated in a single transaction.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        embedding_json = json.dumps(embedding)
        with self._conn:
            # indexed_notes: standard upsert via INSERT OR REPLACE
            self._conn.execute(
                """
                INSERT OR REPLACE INTO indexed_notes
                    (path, content_hash, indexed_at, chunk_count, embedding_model)
                VALUES (?, ?, ?, ?, ?)
                """,
                (note_path, content_hash, now_iso, 1, self._embedding_model),
            )
            # note_vectors: DELETE + INSERT (vec0 does not support UPDATE)
            self._conn.execute(
                "DELETE FROM note_vectors WHERE note_path = ?",
                (note_path,),
            )
            self._conn.execute(
                "INSERT INTO note_vectors(note_path, embedding) VALUES (?, ?)",
                (note_path, embedding_json),
            )

    def delete(self, note_path: str) -> None:
        """Remove note from both indexed_notes and note_vectors."""
        with self._conn:
            self._conn.execute(
                "DELETE FROM indexed_notes WHERE path = ?",
                (note_path,),
            )
            self._conn.execute(
                "DELETE FROM note_vectors WHERE note_path = ?",
                (note_path,),
            )

    def query(self, embedding: list[float], k: int = 5) -> list[VectorHit]:
        """Return top-k hits by cosine similarity.  Lower score = more similar.

        sqlite-vec KNN syntax (v0.1.9):
            SELECT note_path, distance
            FROM note_vectors
            WHERE embedding MATCH <json_array_string>
            ORDER BY distance
            LIMIT k
        The `distance` column is the cosine distance (0 = identical).
        """
        embedding_json = json.dumps(embedding)
        rows = self._conn.execute(
            """
            SELECT note_path, distance
            FROM note_vectors
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            (embedding_json, k),
        ).fetchall()
        return [VectorHit(note_path=row[0], score=row[1]) for row in rows]

    def get_indexed_hash(self, note_path: str) -> str | None:
        """Return the stored content_hash for a note, or None if not indexed."""
        row = self._conn.execute(
            "SELECT content_hash FROM indexed_notes WHERE path = ?",
            (note_path,),
        ).fetchone()
        return row[0] if row else None

    def list_indexed_paths(self) -> set[str]:
        """Return the set of all indexed note paths for diff computation."""
        rows = self._conn.execute("SELECT path FROM indexed_notes").fetchall()
        return {row[0] for row in rows}

    def health_check(self) -> bool:
        """Return True if store is operational (connection + vec extension loaded).

        Never raises; returns False on any exception.
        """
        try:
            self._conn.execute("SELECT vec_version()").fetchone()
            self._conn.execute("SELECT COUNT(*) FROM indexed_notes").fetchone()
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
