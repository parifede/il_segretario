from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from segretario.recall.chunker import H2OverlapChunker
from segretario.recall.embedder import OllamaEmbedder, EmbedderError
from segretario.recall.models import ReindexResult
from segretario.recall.vector_store import VectorStore

logger = logging.getLogger(__name__)


class VaultIndexer:
    def __init__(
        self,
        vault_path: Path,
        store: VectorStore,
        embedder: OllamaEmbedder,
        chunker: H2OverlapChunker | None = None,
        skip_paths: list[str] | None = None,
    ) -> None:
        self._vault_path = vault_path
        self._store = store
        self._embedder = embedder
        self._chunker: H2OverlapChunker = chunker or H2OverlapChunker()
        self._skip_paths: list[str] = skip_paths or ["raw/elaborati"]

    def reindex(self, force: bool = False) -> ReindexResult:
        """Scan vault, embed changed/new notes, delete removed notes.

        Args:
            force: If True, re-embed all notes regardless of hash.
        """
        result = ReindexResult()

        # 1. Scan filesystem
        vault_files = self._scan_vault()

        # 2. Get currently indexed paths for diff
        indexed_paths = self._store.list_indexed_paths()
        scanned_paths: set[str] = set()

        for note_path in vault_files:
            rel_path = str(note_path.relative_to(self._vault_path))
            scanned_paths.add(rel_path)

            try:
                content = note_path.read_text(encoding="utf-8", errors="replace")
                note_hash = _sha256(content)

                if not force:
                    stored_hash = self._store.get_indexed_note_hash(rel_path)
                    if stored_hash == note_hash:
                        result.skipped_unchanged += 1
                        continue

                self._index_note(rel_path, content, note_hash, result)

            except Exception as exc:
                logger.warning("Failed to process %s: %s", rel_path, exc)
                result.errors.append(f"{rel_path}: {exc}")

        # 3. Remove notes that are no longer in the filesystem
        stale_paths = indexed_paths - scanned_paths
        for stale in stale_paths:
            try:
                self._store.delete_note(stale)
                result.deleted += 1
            except Exception as exc:
                logger.warning("Failed to delete stale entry %s: %s", stale, exc)
                result.errors.append(f"{stale} (delete): {exc}")

        return result

    def _index_note(self, rel_path: str, content: str, note_hash: str, result: ReindexResult) -> None:
        """Index all chunks of a note. Clears old chunks first.

        Counts the note as indexed if at least one chunk succeeds.
        Individual chunk EmbedderErrors are logged but do NOT count as errors.
        """
        chunks = self._chunker.chunk(rel_path, content)
        if not chunks:
            return

        # Clear old chunks for this note before inserting new ones
        self._store.delete_note(rel_path)

        any_indexed = False
        for chunk in chunks:
            content_hash = _sha256(chunk.content)
            try:
                embedding = self._embedder.embed(chunk.content)
                self._store.upsert_chunk(
                    note_path=rel_path,
                    chunk_index=chunk.chunk_index,
                    section_title=chunk.section_title,
                    embedding=embedding,
                    content_hash=content_hash,
                    note_hash=note_hash,
                )
                any_indexed = True
            except EmbedderError as exc:
                logger.error(
                    "Failed to embed chunk %d of %s: %s",
                    chunk.chunk_index, rel_path, exc,
                )

        if any_indexed:
            result.indexed += 1

    def update_note(self, note_path: Path) -> bool:
        """Re-index a single note. Called after ingest writes a file.

        Returns True if indexed, False if skipped (unchanged) or failed.
        Raises nothing — failure is logged and returns False.
        """
        try:
            rel_path = str(note_path.relative_to(self._vault_path))
        except ValueError:
            # note_path not under vault_path — skip
            logger.warning("update_note: %s is not under vault %s", note_path, self._vault_path)
            return False

        try:
            content = note_path.read_text(encoding="utf-8", errors="replace")
            note_hash = _sha256(content)
            stored_hash = self._store.get_indexed_note_hash(rel_path)
            if stored_hash == note_hash:
                return False  # unchanged

            result = ReindexResult()
            self._index_note(rel_path, content, note_hash, result)
            return result.indexed > 0
        except Exception as exc:
            logger.warning("update_note failed for %s: %s", note_path, exc)
            return False

    def _scan_vault(self) -> list[Path]:
        """Return all .md files in vault, excluding skip_paths."""
        all_md = sorted(self._vault_path.rglob("*.md"))
        return [
            p for p in all_md
            if not self._is_skipped(p)
        ]

    def _is_skipped(self, path: Path) -> bool:
        rel = str(path.relative_to(self._vault_path)).replace("\\", "/")
        return any(rel == skip or rel.startswith(skip + "/") for skip in self._skip_paths)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
