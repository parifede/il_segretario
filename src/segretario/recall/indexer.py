from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from segretario.recall.chunker import Chunker, WholeNoteChunker
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
        chunker: Chunker | None = None,
        skip_paths: list[str] | None = None,
    ) -> None:
        self._vault_path = vault_path
        self._store = store
        self._embedder = embedder
        self._chunker: Chunker = chunker or WholeNoteChunker()
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
                content_hash = _sha256(content)

                if not force:
                    stored_hash = self._store.get_indexed_hash(rel_path)
                    if stored_hash == content_hash:
                        result.skipped_unchanged += 1
                        continue

                # Embed and store
                chunks = self._chunker.chunk(note_path, content)
                if not chunks:
                    continue
                # WholeNoteChunker: always 1 chunk. Use first chunk's text.
                embedding = self._embedder.embed(chunks[0].text)
                self._store.upsert(rel_path, embedding, content_hash)
                result.indexed += 1

            except EmbedderError as exc:
                logger.warning("Failed to embed %s: %s", rel_path, exc)
                result.errors.append(f"{rel_path}: {exc}")
            except Exception as exc:
                logger.warning("Failed to process %s: %s", rel_path, exc)
                result.errors.append(f"{rel_path}: {exc}")

        # 3. Remove notes that are no longer in the filesystem
        stale_paths = indexed_paths - scanned_paths
        for stale in stale_paths:
            try:
                self._store.delete(stale)
                result.deleted += 1
            except Exception as exc:
                logger.warning("Failed to delete stale entry %s: %s", stale, exc)
                result.errors.append(f"{stale} (delete): {exc}")

        return result

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
            content_hash = _sha256(content)
            stored_hash = self._store.get_indexed_hash(rel_path)
            if stored_hash == content_hash:
                return False  # unchanged

            chunks = self._chunker.chunk(note_path, content)
            if not chunks:
                return False
            embedding = self._embedder.embed(chunks[0].text)
            self._store.upsert(rel_path, embedding, content_hash)
            return True
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
