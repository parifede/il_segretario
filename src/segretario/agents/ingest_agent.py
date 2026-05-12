from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from pathlib import Path

import yaml

from segretario.vault.index_log import append_log


class ConfirmationNeededError(Exception):
    """Raised when ingest would touch personal-looking content."""


@dataclass(frozen=True)
class IngestResult:
    path: str
    title: str
    updated: bool


def ingest_article(vault_path: Path | str, source_path: Path | str, *, auto: bool = False) -> IngestResult:
    vault = Path(vault_path)
    relative_source = _normalize_source(source_path)
    source = vault / relative_source
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_symlink():
        raise ValueError("ingest source cannot be a symlink")

    raw = source.read_text(encoding="utf-8")
    if _looks_personal(raw):
        raise ConfirmationNeededError("personal-looking content requires confirmation")

    title = _extract_title(raw, source.stem)
    slug = _slugify(title)
    target_relative = f"knowledge/{slug}.md"
    target = vault / target_relative
    updated = target.exists()

    body = _body_without_title(raw)
    body = _convert_markdown_links_to_wikilinks(body)
    frontmatter = {
        "title": title,
        "source_path": relative_source,
        "privacy": "private",
        "cloud_ok": False,
        "updated": date.today().isoformat(),
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render_knowledge_page(frontmatter, title, body), encoding="utf-8")
    _update_index(vault, title)
    _append_log(vault, relative_source, target_relative)

    return IngestResult(path=target_relative, title=title, updated=updated)


def _normalize_source(source_path: Path | str) -> str:
    relative = Path(source_path).as_posix().strip("/")
    parts = tuple(Path(relative).parts)
    if ".." in parts:
        raise ValueError("source path cannot contain parent traversal")
    if parts[:2] != ("raw", "articles"):
        raise ValueError("ingest source must be under raw/articles")
    if Path(relative).suffix.lower() not in {".md", ".txt"}:
        raise ValueError("ingest source must be markdown or text")
    return relative


def _looks_personal(text: str) -> bool:
    patterns = [
        r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b",
        r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
        r"\bmy\s+(address|phone|password|ssn|social security)\b",
    ]
    lowered = text.casefold()
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in patterns)


def _extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading = re.match(r"^#\s+(.+)$", stripped)
        return heading.group(1).strip() if heading else stripped
    return fallback.replace("-", " ").replace("_", " ").title()


def _body_without_title(text: str) -> str:
    lines = text.splitlines()
    if lines and (lines[0].startswith("# ") or lines[0].strip()):
        return "\n".join(lines[1:]).strip()
    return text.strip()


def _convert_markdown_links_to_wikilinks(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        target = Path(match.group(2)).stem.strip()
        return f"[[{target or label}]]"

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace, text)


def _render_knowledge_page(frontmatter: dict[str, object], title: str, body: str) -> str:
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False)
    content = body.strip()
    if content:
        content = f"\n\n{content}"
    return f"---\n{yaml_text}---\n\n# {title}{content}\n"


def _update_index(vault: Path, title: str) -> None:
    index_path = vault / "meta" / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if index_path.exists():
        index = index_path.read_text(encoding="utf-8")
    else:
        index = "# Index\n"

    entry = f"- [[{title}]]"
    if entry not in index.splitlines():
        index = index.rstrip() + f"\n{entry}\n"
        index_path.write_text(index, encoding="utf-8")
    elif not index_path.exists():
        index_path.write_text(index, encoding="utf-8")


def _append_log(vault: Path, source: str, target: str) -> None:
    log_path = vault / "meta" / "log.md"
    if not log_path.exists():
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("# Log\n", encoding="utf-8")
    append_log(vault, f"- {date.today().isoformat()} ingest {source} -> {target}")


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    return slug or "untitled"
