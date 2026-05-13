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
    normalized = _normalize_index_sections(text)
    if normalized != raw_text:
        index_path.write_text(normalized, encoding="utf-8")
    return index_path


def _default_index() -> str:
    return "# Index\n\n## Self\n\n## Knowledge\n\n## Output\n"


def _normalize_index_sections(text: str) -> str:
    lines = text.splitlines()
    prefix: list[str] = []
    canonical_content: dict[str, list[str]] = {heading: [] for heading in CANONICAL_HEADINGS}
    other_sections: list[tuple[str, list[str]]] = []
    current_heading: str | None = None
    current_other: list[str] | None = None

    for line in lines:
        if line.startswith("## "):
            current_heading = line
            if line in canonical_content:
                current_other = None
            else:
                current_other = []
                other_sections.append((line, current_other))
            continue

        if current_heading is None:
            prefix.append(line)
            continue

        if current_heading in canonical_content:
            if line.strip():
                canonical_content[current_heading].append(line)
        elif current_other is not None:
            current_other.append(line)

    output = prefix or ["# Index"]
    while output and not output[-1].strip():
        output.pop()

    for heading in CANONICAL_HEADINGS:
        output.extend(["", heading])
        seen: set[str] = set()
        for line in canonical_content[heading]:
            if line not in seen:
                output.append(line)
                seen.add(line)

    for heading, content in other_sections:
        output.extend(["", heading])
        output.extend(content)

    return "\n".join(output).rstrip() + "\n"


def append_log(vault_root: str | Path, entry: str) -> Path:
    log_path = Path(vault_root) / "meta" / "log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    line = entry if entry.endswith("\n") else f"{entry}\n"
    with log_path.open("a", encoding="utf-8") as file:
        file.write(line)
    return log_path
