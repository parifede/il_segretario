from __future__ import annotations

from pathlib import Path


CANONICAL_HEADINGS = ("## Self", "## Knowledge", "## Output")
KNOWLEDGE_HEADING = "## Knowledge"


def ensure_meta_index(vault_root: str | Path) -> Path:
    index_path = Path(vault_root) / "meta" / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    if not index_path.exists():
        index_path.write_text(_default_index(), encoding="utf-8")
        return index_path

    raw_text = index_path.read_text(encoding="utf-8")
    text = raw_text.replace("\ufeff", "")
    lines = text.splitlines()
    missing = [heading for heading in CANONICAL_HEADINGS if heading not in lines]
    if missing or text != raw_text:
        separator = "" if text.endswith("\n") else "\n"
        additions = "\n".join(missing)
        suffix = f"{separator}\n{additions}\n" if missing else ""
        index_path.write_text(f"{text}{suffix}", encoding="utf-8")
    return index_path


def _default_index() -> str:
    return "# Index\n\n## Self\n\n## Knowledge\n\n## Output\n"


def append_log(vault_root: str | Path, entry: str) -> Path:
    log_path = Path(vault_root) / "meta" / "log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    line = entry if entry.endswith("\n") else f"{entry}\n"
    with log_path.open("a", encoding="utf-8") as file:
        file.write(line)
    return log_path
