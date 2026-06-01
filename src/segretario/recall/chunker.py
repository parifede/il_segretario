from __future__ import annotations
import re

from segretario.recall.models import Chunk


CHUNK_TARGET_SIZE = 1500   # kept for backward-compat with existing tests
CHUNK_OVERLAP_SIZE = 200
CHUNK_MAX_CHARS_DEFAULT = 1600  # hard cap ≈ 450/512 mxbai-embed-large tokens (conservative)

H2_PATTERN = re.compile(r'^##\s+(.+?)\s*$', re.MULTILINE)


class H2OverlapChunker:
    """Chunker che divide note per sezioni H2 con overlap.

    Logica:
    - Note senza H2 e <= max_chunk_chars: 1 chunk = nota intera
    - Note senza H2 e > max_chunk_chars: split per blocchi di ~max_chunk_chars
      con overlap di CHUNK_OVERLAP_SIZE
    - Note con H2: ogni sezione H2 e' un chunk (preceduta da overlap della sezione
      precedente). Se una sezione supera max_chunk_chars, viene a sua volta
      splittata internamente con stessa logica.
    """

    def __init__(self, max_chunk_chars: int = CHUNK_MAX_CHARS_DEFAULT) -> None:
        self.max_chunk_chars = max_chunk_chars

    def chunk(self, note_path: str, content: str) -> list[Chunk]:
        if not content.strip():
            return []

        sections = self._split_by_h2(content)

        if not sections:
            return self._chunk_plain_text(note_path, content, section_title=None)

        chunks: list[Chunk] = []
        previous_tail = ""

        for section_title, section_content in sections:
            content_with_overlap = (previous_tail + section_content).strip()
            section_chunks = self._chunk_plain_text(
                note_path,
                content_with_overlap,
                section_title=section_title,
                start_index=len(chunks),
            )
            chunks.extend(section_chunks)
            previous_tail = section_content[-CHUNK_OVERLAP_SIZE:] if len(section_content) > CHUNK_OVERLAP_SIZE else section_content

        return chunks

    def _split_by_h2(self, content: str) -> list[tuple[str, str]]:
        matches = list(H2_PATTERN.finditer(content))
        if not matches:
            return []

        sections: list[tuple[str, str]] = []
        preamble = content[:matches[0].start()].strip()

        for i, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            section_content = content[start:end].strip()
            if i == 0 and preamble:
                section_content = preamble + "\n\n" + section_content
            sections.append((title, section_content))

        return sections

    def _chunk_plain_text(
        self,
        note_path: str,
        text: str,
        section_title: str | None,
        start_index: int = 0,
    ) -> list[Chunk]:
        if not text.strip():
            return []

        cap = self.max_chunk_chars
        if len(text) <= cap:
            return [Chunk(
                note_path=note_path,
                chunk_index=start_index,
                section_title=section_title,
                content=text,
                char_count=len(text),
            )]

        chunks: list[Chunk] = []
        idx = start_index
        pos = 0

        while pos < len(text):
            end = min(pos + cap, len(text))
            chunk_content = text[pos:end]
            chunks.append(Chunk(
                note_path=note_path,
                chunk_index=idx,
                section_title=section_title,
                content=chunk_content,
                char_count=len(chunk_content),
            ))
            idx += 1
            if end >= len(text):
                break
            # Advance with overlap; max(..., pos+1) guarantees forward progress
            # even if CHUNK_OVERLAP_SIZE >= cap (shouldn't happen in production).
            pos = max(pos + 1, end - CHUNK_OVERLAP_SIZE)

        return chunks
