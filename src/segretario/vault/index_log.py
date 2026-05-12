from __future__ import annotations

from pathlib import Path


KNOWLEDGE_HEADING = "## Knowledge"


def ensure_meta_index(vault_root: str | Path) -> Path:
    index_path = Path(vault_root) / "meta" / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    if not index_path.exists():
        index_path.write_text("# Index\n\n## Knowledge\n", encoding="utf-8")
        return index_path

    text = index_path.read_text(encoding="utf-8")
    if KNOWLEDGE_HEADING not in text.splitlines():
        separator = "" if text.endswith("\n") else "\n"
        index_path.write_text(f"{text}{separator}\n{KNOWLEDGE_HEADING}\n", encoding="utf-8")
    return index_path


def append_log(vault_root: str | Path, entry: str) -> Path:
    log_path = Path(vault_root) / "meta" / "log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    line = entry if entry.endswith("\n") else f"{entry}\n"
    with log_path.open("a", encoding="utf-8") as file:
        file.write(line)
    return log_path
