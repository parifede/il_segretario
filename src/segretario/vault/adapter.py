from __future__ import annotations

from pathlib import Path
from typing import Iterable


class VaultAdapter:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def resolve(self, path: str | Path) -> Path:
        candidate = Path(path)
        if ".." in candidate.parts:
            raise ValueError("vault path cannot contain parent traversal")

        if not candidate.is_absolute():
            candidate = self.root / candidate

        resolved = candidate.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError("path is outside vault root")
        return resolved

    def iter_files(self) -> Iterable[Path]:
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            relative_parts = path.relative_to(self.root).parts
            if relative_parts[:2] == ("raw", "elaborati"):
                continue
            yield path
