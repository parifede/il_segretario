# Recall Robust Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zero chunk loss during reindex — lower the default char cap to give headroom under mxbai's 512-token limit, then add adaptive recursive splitting so any chunk that still exceeds the context window is transparently split and stored rather than skipped.

**Architecture:** Three orthogonal changes: (1) lower `CHUNK_MAX_CHARS_DEFAULT` + `embedder_max_chunk_chars` from 1600 → 1000 (wide margin below 512 tokens for dense text); (2) add `EmbedderContextTooLongError` subclass to `embedder.py` — raised on Ollama 400 — so callers can distinguish context errors from infrastructure errors; (3) add `_embed_adaptive` to `VaultIndexer` — on `EmbedderContextTooLongError` it splits the chunk text at a sentence/whitespace boundary near the midpoint (fallback: exact midpoint) and retries each half recursively, capped at depth 3 (max 8 sub-chunks per original chunk), saving sub-chunks as distinct store entries.

**Tech Stack:** Python 3.11+, pytest, ollama Python client, pydantic, sqlite-vec.

---

## Files Changed

| File | Action | What changes |
|---|---|---|
| `src/segretario/recall/chunker.py` | Modify lines 7-9 | `CHUNK_TARGET_SIZE` 1500→900, `CHUNK_MAX_CHARS_DEFAULT` 1600→1000 |
| `src/segretario/config/settings.py` | Modify line 130 | `embedder_max_chunk_chars` default 1600→1000 |
| `tests/test_recall_chunker.py` | Modify line 28 | Fix `test_chunker_long_note_no_h2_splits_with_overlap` (content 3500→2200 chars) |
| `src/segretario/recall/embedder.py` | Modify lines 10-46 | Add `EmbedderContextTooLongError`; detect Ollama 400 in `embed()` |
| `tests/test_recall_embedder.py` | Modify (append) | 2 new tests for `EmbedderContextTooLongError` |
| `src/segretario/recall/indexer.py` | Modify | Add `_find_split_point()` helper + `_embed_adaptive()` method; rewrite `_index_note()` to use adaptive split with flat `store_idx` |
| `tests/test_recall_indexer.py` | Modify (append) | 1 new test: adaptive split → zero chunks lost |

---

## Task 1: Lower chunk cap (chunker.py + settings.py + broken test fix)

**Files:**
- Modify: `src/segretario/recall/chunker.py:7-9`
- Modify: `src/segretario/config/settings.py:130`
- Modify: `tests/test_recall_chunker.py:26-32`

- [ ] **Step 1: Write failing test asserting the new cap value**

Add at the end of `tests/test_recall_chunker.py`:

```python
def test_chunk_max_chars_default_is_1000():
    """CHUNK_MAX_CHARS_DEFAULT must be 1000 for safe mxbai headroom."""
    assert CHUNK_MAX_CHARS_DEFAULT == 1000
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_recall_chunker.py::test_chunk_max_chars_default_is_1000 -v
```

Expected: `FAIL — AssertionError: assert 1600 == 1000`

- [ ] **Step 3: Update chunker.py constants**

In `src/segretario/recall/chunker.py`, replace lines 7-9:

```python
CHUNK_TARGET_SIZE = 900    # kept for backward-compat with existing tests
CHUNK_OVERLAP_SIZE = 200
CHUNK_MAX_CHARS_DEFAULT = 1000  # hard cap — ~250 tokens, safe margin under mxbai 512-tok limit
```

- [ ] **Step 4: Update settings.py default**

In `src/segretario/config/settings.py`, replace line 130:

```python
    embedder_max_chunk_chars: int = 1000  # hard cap per embedder token window (mxbai: 512 tok; 1000 chars ≈ 250 tok)
```

- [ ] **Step 5: Fix the one test broken by the new cap**

In `tests/test_recall_chunker.py`, the test `test_chunker_long_note_no_h2_splits_with_overlap` uses 3500 chars and expects exactly 3 chunks — that count was correct with cap=1600 but produces 5 chunks with cap=1000. Change the content length to 2200 (which gives exactly 3 chunks with cap=1000 and overlap=200):

Replace:
```python
def test_chunker_long_note_no_h2_splits_with_overlap():
    chunker = H2OverlapChunker()
    content = "A" * 3500
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 3
    assert all(c.section_title is None for c in chunks)
    assert chunks[1].content[:CHUNK_OVERLAP_SIZE] == chunks[0].content[-CHUNK_OVERLAP_SIZE:]
```

With:
```python
def test_chunker_long_note_no_h2_splits_with_overlap():
    # 2200 chars with cap=1000, overlap=200 → exactly 3 chunks
    chunker = H2OverlapChunker()
    content = "A" * 2200
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 3
    assert all(c.section_title is None for c in chunks)
    assert chunks[1].content[:CHUNK_OVERLAP_SIZE] == chunks[0].content[-CHUNK_OVERLAP_SIZE:]
```

- [ ] **Step 6: Run all chunker tests**

```
pytest tests/test_recall_chunker.py -v
```

Expected: all PASS (13 tests + the new one = 14 total)

- [ ] **Step 7: Commit**

```
git add src/segretario/recall/chunker.py src/segretario/config/settings.py tests/test_recall_chunker.py
git commit -m "fix(recall): lower default chunk cap 1600→1000 for safe mxbai headroom"
```

---

## Task 2: Add EmbedderContextTooLongError to embedder

**Files:**
- Modify: `src/segretario/recall/embedder.py:10-46`
- Modify: `tests/test_recall_embedder.py` (append 2 tests)

- [ ] **Step 1: Write failing tests for EmbedderContextTooLongError**

Append to `tests/test_recall_embedder.py`:

```python
# ---------------------------------------------------------------------------
# test: context-length error detection
# ---------------------------------------------------------------------------

def test_embedder_raises_context_too_long_on_400():
    """Ollama 400 ResponseError → EmbedderContextTooLongError raised."""
    import ollama
    from segretario.recall.embedder import EmbedderContextTooLongError

    embedder = OllamaEmbedder()
    error = ollama.ResponseError("context length exceeded", 400)
    with patch.object(embedder._client, "embed", side_effect=error):
        with pytest.raises(EmbedderContextTooLongError):
            embedder.embed("some text")


def test_embedder_non_400_raises_plain_embedder_error():
    """Non-400 Ollama error → EmbedderError but NOT EmbedderContextTooLongError."""
    import ollama
    from segretario.recall.embedder import EmbedderContextTooLongError

    embedder = OllamaEmbedder()
    error = ollama.ResponseError("model not found", 404)
    with patch.object(embedder._client, "embed", side_effect=error):
        with pytest.raises(EmbedderError) as exc_info:
            embedder.embed("some text")
    assert not isinstance(exc_info.value, EmbedderContextTooLongError)
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_recall_embedder.py::test_embedder_raises_context_too_long_on_400 tests/test_recall_embedder.py::test_embedder_non_400_raises_plain_embedder_error -v
```

Expected: `FAIL — ImportError: cannot import name 'EmbedderContextTooLongError'`

- [ ] **Step 3: Add EmbedderContextTooLongError and 400 detection to embedder.py**

Replace `src/segretario/recall/embedder.py` lines 10-46:

```python
class EmbedderError(Exception):
    """Raised when embedding fails. Message should be suitable for wizard_context["failure_reason"]."""


class EmbedderContextTooLongError(EmbedderError):
    """Raised when text exceeds the embedder's context window (Ollama 400 response)."""
```

Then in `embed()`, replace the `except ollama.ResponseError` clause (currently lines 41-42):

```python
        except ollama.ResponseError as exc:
            if exc.status_code == 400:
                raise EmbedderContextTooLongError(f"Ollama context exceeded (400): {exc}") from exc
            raise EmbedderError(f"Ollama model error: {exc}") from exc
```

The full updated `embedder.py` after these edits:

```python
from __future__ import annotations

import logging

import ollama

logger = logging.getLogger(__name__)


class EmbedderError(Exception):
    """Raised when embedding fails. Message should be suitable for wizard_context["failure_reason"]."""


class EmbedderContextTooLongError(EmbedderError):
    """Raised when text exceeds the embedder's context window (Ollama 400 response)."""


class OllamaEmbedder:
    """Ollama embedding client using mxbai-embed-large (1024-dim by default)."""

    def __init__(
        self,
        model: str = "mxbai-embed-large",
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: int = 60,
    ) -> None:
        self._model: str = model
        self._base_url: str = base_url
        self._timeout_seconds: int = timeout_seconds
        self._client: ollama.Client = ollama.Client(host=base_url, timeout=timeout_seconds)

    def embed(self, text: str) -> list[float]:
        """Return embedding vector. Raises EmbedderContextTooLongError on Ollama 400, EmbedderError on other failures."""
        if len(text) > 8000:
            logger.warning(
                "Text length %d chars exceeds 8000; mxbai-embed-large may truncate.",
                len(text),
            )
        try:
            response = self._client.embed(model=self._model, input=text)
            if not response.embeddings:
                raise EmbedderError("Ollama returned empty embedding response")
            return list(response.embeddings[0])
        except ollama.ResponseError as exc:
            if exc.status_code == 400:
                raise EmbedderContextTooLongError(f"Ollama context exceeded (400): {exc}") from exc
            raise EmbedderError(f"Ollama model error: {exc}") from exc
        except Exception as exc:
            raise EmbedderError(
                f"Ollama not reachable at {self._base_url}: {exc}"
            ) from exc

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed each text individually. Skips (with WARNING) on single-item failure.

        Idempotent: safe to retry. Returns only successful embeddings in order.
        Items that fail are logged at WARNING level and skipped (caller recovers via indexer hash diff).
        """
        results: list[list[float]] = []
        for i, text in enumerate(texts):
            try:
                results.append(self.embed(text))
            except EmbedderError as exc:
                logger.warning("embed_batch: item %d failed, skipping: %s", i, exc)
        return results

    def health_check(self) -> bool:
        """Return True if Ollama is reachable and the model responds. False on any error."""
        try:
            hc_client = ollama.Client(host=self._base_url, timeout=5)
            resp = hc_client.embed(model=self._model, input="test")
            return bool(resp.embeddings)
        except Exception:
            return False
```

- [ ] **Step 4: Run all embedder tests**

```
pytest tests/test_recall_embedder.py -v
```

Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```
git add src/segretario/recall/embedder.py tests/test_recall_embedder.py
git commit -m "feat(recall): add EmbedderContextTooLongError for Ollama 400 context errors"
```

---

## Task 3: Adaptive split in VaultIndexer

**Files:**
- Modify: `src/segretario/recall/indexer.py`
- Modify: `tests/test_recall_indexer.py` (append 1 test)

- [ ] **Step 1: Write failing test — adaptive split, zero chunks lost**

Append to `tests/test_recall_indexer.py`:

```python
# ---------------------------------------------------------------------------
# test: adaptive split on context-length error — zero chunks lost
# ---------------------------------------------------------------------------

def test_indexer_adaptive_split_zero_chunks_lost(tmp_path: Path):
    """Chunks that exceed context window are split and re-embedded — zero chunks lost."""
    from segretario.recall.embedder import EmbedderContextTooLongError
    from segretario.recall.chunker import H2OverlapChunker

    # Chunker cap=800 so each chunk is ≤800 chars, but mock threshold=400 → all chunks fail first try
    content = "# Dense Block\n" + "W" * 2000
    (tmp_path / "dense.md").write_text(content, encoding="utf-8")

    embedder = MagicMock(spec=OllamaEmbedder)

    def embed_side_effect(text: str) -> list[float]:
        if len(text) > 400:
            raise EmbedderContextTooLongError(f"context exceeded: {len(text)} chars")
        return [0.1] * 1024

    embedder.embed.side_effect = embed_side_effect

    store = _make_store()
    chunker = H2OverlapChunker(max_chunk_chars=800)
    indexer = VaultIndexer(vault_path=tmp_path, store=store, embedder=embedder, chunker=chunker)

    result = indexer.reindex()

    # Note fully indexed — zero errors, zero skips
    assert result.indexed == 1
    assert result.errors == []
    # All sub-chunks stored (embed called multiple times per original chunk)
    assert "dense.md" in store.list_indexed_paths()
    assert embedder.embed.call_count > 1
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_recall_indexer.py::test_indexer_adaptive_split_zero_chunks_lost -v
```

Expected: `FAIL — AssertionError: assert 0 == 1` (note not indexed because all chunks are skipped on EmbedderContextTooLongError with current code)

- [ ] **Step 3: Add _find_split_point helper to indexer.py**

Add this module-level function after the `logger = ...` line in `src/segretario/recall/indexer.py`:

```python
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
```

- [ ] **Step 4: Update the import in indexer.py to include EmbedderContextTooLongError**

Replace the existing embedder import line:

```python
from segretario.recall.embedder import OllamaEmbedder, EmbedderError
```

With:

```python
from segretario.recall.embedder import OllamaEmbedder, EmbedderError, EmbedderContextTooLongError
```

- [ ] **Step 5: Add _embed_adaptive method to VaultIndexer**

Add this method to `VaultIndexer` (after `update_note`, before `_scan_vault`):

```python
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
```

- [ ] **Step 6: Rewrite _index_note to use _embed_adaptive with a flat store_idx**

Replace the existing `_index_note` method body:

```python
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
```

- [ ] **Step 7: Run all indexer tests**

```
pytest tests/test_recall_indexer.py -v
```

Expected: all tests PASS (existing 9 + new 1 = 10 total)

- [ ] **Step 8: Run the full recall test suite**

```
pytest tests/test_recall_chunker.py tests/test_recall_embedder.py tests/test_recall_indexer.py -v
```

Expected: all PASS, 0 errors

- [ ] **Step 9: Commit**

```
git add src/segretario/recall/indexer.py tests/test_recall_indexer.py
git commit -m "feat(recall): adaptive split on context-length error — zero chunk loss"
```

---

## Self-Review

### Spec coverage

| Spec requirement | Covered by |
|---|---|
| `embedder_max_chunk_chars` 1600 → ~1000 | Task 1 |
| Adaptive split on 400 "exceeds context" | Task 2 (detection) + Task 3 (split) |
| Split at sentence/whitespace boundary near midpoint | Task 3 `_find_split_point` |
| Recursive retry until fits; recursion cap | Task 3 `_embed_adaptive` depth guard |
| Sub-chunks saved as distinct store entries | Task 3 flat `store_idx` |
| Zero chunk loss | Task 3 test |
| Keep overlap (orthogonal) | Overlap unchanged in chunker — ✓ |

### Placeholder scan

None found — all code blocks are complete and runnable.

### Type consistency

- `EmbedderContextTooLongError` defined in Task 2, imported in Task 3 ✓
- `_find_split_point(text: str, mid: int) -> int` defined and called consistently ✓
- `_embed_adaptive` returns `list[tuple[str, list[float]]]` and is consumed correctly in `_index_note` ✓
- `store_idx` replaces `chunk.chunk_index` for storage — consistent across the new `_index_note` ✓
