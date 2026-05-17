from __future__ import annotations
from pathlib import Path
from typing import Protocol


class Chunk:
    """A piece of text to embed. Today always the full note content."""
    def __init__(self, text: str, source_path: str) -> None:
        self.text = text
        self.source_path = source_path


class Chunker(Protocol):
    def chunk(self, path: Path, content: str) -> list[Chunk]:
        """Split content into chunks. Protocol allows future strategies."""
        ...


class WholeNoteChunker:
    """Returns the entire note as a single chunk. One note = one vector."""

    def chunk(self, path: Path, content: str) -> list[Chunk]:
        return [Chunk(text=content, source_path=str(path))]
