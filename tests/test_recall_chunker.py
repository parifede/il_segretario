from __future__ import annotations
import pytest
from segretario.recall.chunker import H2OverlapChunker, CHUNK_TARGET_SIZE, CHUNK_OVERLAP_SIZE


def test_chunker_empty_note():
    chunker = H2OverlapChunker()
    assert chunker.chunk("test.md", "") == []
    assert chunker.chunk("test.md", "   \n  \n") == []


def test_chunker_short_note_no_h2():
    chunker = H2OverlapChunker()
    chunks = chunker.chunk("test.md", "Una breve nota.")
    assert len(chunks) == 1
    assert chunks[0].content == "Una breve nota."
    assert chunks[0].section_title is None
    assert chunks[0].chunk_index == 0


def test_chunker_long_note_no_h2_splits_with_overlap():
    chunker = H2OverlapChunker()
    content = "A" * 3500
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 3
    assert all(c.section_title is None for c in chunks)
    assert chunks[1].content[:CHUNK_OVERLAP_SIZE] == chunks[0].content[-CHUNK_OVERLAP_SIZE:]


def test_chunker_note_with_h2_sections():
    chunker = H2OverlapChunker()
    content = "## Sezione A\nContenuto A.\n\n## Sezione B\nContenuto B."
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 2
    assert chunks[0].section_title == "Sezione A"
    assert chunks[1].section_title == "Sezione B"


def test_chunker_h2_section_overlap_between_sections():
    chunker = H2OverlapChunker()
    content = (
        "## Sezione A\n" + "Z" * 500 + "FINEUNICA"
        + "\n\n## Sezione B\n" + "Contenuto B normale."
    )
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 2
    assert chunks[1].section_title == "Sezione B"
    assert "FINEUNICA" in chunks[1].content


def test_chunker_preamble_attached_to_first_h2():
    chunker = H2OverlapChunker()
    content = "Preambolo iniziale.\n\n## Prima sezione\nContenuto."
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 1
    assert chunks[0].section_title == "Prima sezione"
    assert "Preambolo iniziale" in chunks[0].content


def test_chunker_long_h2_section_gets_subsplit():
    chunker = H2OverlapChunker()
    content = "## Sezione lunga\n" + "X" * 3500
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) >= 3
    assert all(c.section_title == "Sezione lunga" for c in chunks)
    assert chunks[1].content[:CHUNK_OVERLAP_SIZE] == chunks[0].content[-CHUNK_OVERLAP_SIZE:]


def test_chunker_exact_target_size():
    chunker = H2OverlapChunker()
    content = "B" * CHUNK_TARGET_SIZE
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 1


def test_chunker_one_over_target_size_produces_two_chunks():
    chunker = H2OverlapChunker()
    content = "C" * (CHUNK_TARGET_SIZE + 1)
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 2


def test_chunker_h2_with_empty_section_skipped():
    chunker = H2OverlapChunker()
    content = "## Vuota\n\n## Piena\nContenuto."
    chunks = chunker.chunk("test.md", content)
    section_titles = [c.section_title for c in chunks]
    assert "Piena" in section_titles
    assert "Vuota" not in section_titles


def test_chunker_chunk_indices_are_sequential():
    chunker = H2OverlapChunker()
    content = "A" * 5000  # produces multiple chunks
    chunks = chunker.chunk("test.md", content)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunker_h2_chunk_indices_are_sequential_across_sections():
    chunker = H2OverlapChunker()
    content = "## A\n" + "X" * 3000 + "\n\n## B\n" + "Y" * 3000
    chunks = chunker.chunk("test.md", content)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
