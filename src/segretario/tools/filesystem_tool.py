from __future__ import annotations

from pathlib import Path


class FilesystemTool:
    """Narrow filesystem side-effect wrapper for local project writes."""

    def write_text(self, path: str | Path, content: str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def append_text(self, path: str | Path, content: str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as file:
            file.write(content)
        return target

    def ensure_dir(self, path: str | Path) -> Path:
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        return target
