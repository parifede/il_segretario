from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from segretario.recall.chunker import H2OverlapChunker
from segretario.recall.embedder import OllamaEmbedder, EmbedderError, EmbedderContextTooLongError
from segretario.recall.models import ReindexResult
from segretario.recall.vector_store import VectorStore

logger = logging.getLogger(__name__)

_ADAPTIVE_SPLIT_MAX_DEPTH = 3  # max 2^3 = 8 sub-chunks per original chunk


def _find_split_point(text: str, mid: int) -> int:
    """Return index of a sentence/whitespace boundary at or before mid (within 200-char window).

    Priority: sentence end (. ! ? newline) > whitespace > exact mid.
    """
    mid = min(mid, max(0, len(text) - 1))
    window = min(200, mid)
    search_start = max(0, mid - window)
    # Sentence boundary: split after the punctuation/newline
    for i in range(mid, search_start - 1, -1):
        if text[i] in '.!?\n' and (i + 1 >= len(text) or text[i + 1].isspace()):
            return i + 1
    # Whitespace: split after the space
    for i in range(mid, search_start - 1, -1):
        if text[i].isspace():
            return i + 1
    return mid


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

        Counts the note as indexed if at least one chunk (or sub-chunk) succeeds.
        EmbedderContextTooLongError triggers adaptive recursive splitting — no chunk is skipped.
        Other EmbedderErrors are logged as WARNING and the chunk is skipped.
        """
        chunks = self._chunker.chunk(rel_path, content)
        if not chunks:
            return

        self._store.delete_note(rel_path)

        any_indexed = False
        store_idx = 0  # flat counter across all chunks + sub-chunks

        for chunk in chunks:
            try:
                pairs = self._embed_adaptive(rel_path, chunk.content, depth=0)
            except EmbedderError as exc:
                logger.warning(
                    "Failed to embed chunk %d of %s: %s — skipping chunk",
                    chunk.chunk_index, rel_path, exc,
                )
                continue

            for sub_text, embedding in pairs:
                content_hash = _sha256(sub_text)
                self._store.upsert_chunk(
                    note_path=rel_path,
                    chunk_index=store_idx,
                    section_title=chunk.section_title,
                    embedding=embedding,
                    content_hash=content_hash,
                    note_hash=note_hash,
                )
                store_idx += 1
                any_indexed = True

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

    def _embed_adaptive(self, note_path: str, text: str, depth: int) -> list[tuple[str, list[float]]]:
        """Embed text, recursively splitting on context-length errors.

        Returns list of (sub_text, embedding) pairs — may be >1 if splitting occurred.
        Raises EmbedderError (non-context) so _index_note can log and skip.
        """
        try:
            return [(text, self._embedder.embed(text))]
        except EmbedderContextTooLongError as exc:
            if depth >= _ADAPTIVE_SPLIT_MAX_DEPTH:
                logger.warning(
                    "Adaptive split depth %d reached for %s — skipping sub-chunk: %s",
                    depth, note_path, exc,
                )
                return []
            mid = len(text) // 2
            split_pt = _find_split_point(text, mid)
            left = text[:split_pt].strip()
            right = text[split_pt:].strip()
            if not left or not right:
                logger.warning(
                    "Cannot split chunk further in %s — skipping: %s", note_path, exc
                )
                return []
            return (
                self._embed_adaptive(note_path, left, depth + 1)
                + self._embed_adaptive(note_path, right, depth + 1)
            )

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
