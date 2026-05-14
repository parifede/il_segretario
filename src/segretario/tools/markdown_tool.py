from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from pathlib import Path

import yaml

from segretario.vault.frontmatter import parse_frontmatter, render_frontmatter
from segretario.vault.index_log import KNOWLEDGE_HEADING, append_log, ensure_meta_index
from segretario.vault.paths import classify_vault_path


class ConfirmationNeededError(Exception):
    """Raised when ingest would touch personal-looking content."""


@dataclass(frozen=True)
class IngestResult:
    path: str
    title: str
    updated: bool


class MarkdownTool:
    """Markdown and text ingest side-effect tool."""

    def ingest_article(
        self,
        vault_path: Path | str,
        source_path: Path | str,
        *,
        auto: bool = False,
    ) -> IngestResult:
        return ingest_article(vault_path, source_path, auto=auto)


def ingest_article(vault_path: Path | str, source_path: Path | str, *, auto: bool = False) -> IngestResult:
    vault = Path(vault_path)
    relative_source = _normalize_source(source_path)
    source = vault / relative_source
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_symlink():
        raise ValueError("ingest source cannot be a symlink")

    raw = _read_source_text(source).lstrip("\ufeff")
    if _looks_personal(raw):
        raise ConfirmationNeededError("personal-looking content requires confirmation")

    source_metadata, source_body = _split_frontmatter(raw)
    title = str(source_metadata.get("title") or _extract_title(source_body, source.stem))
    slug = _slugify(title)
    target_relative = f"knowledge/{slug}.md"
    target = vault / target_relative
    updated = target.exists()

    body = _body_without_title(source_body)
    body = _convert_markdown_links_to_wikilinks(body)
    body = _add_outbound_links(vault, body, title)
    frontmatter = {
        "title": title,
        "source_path": relative_source,
        "content_class": "knowledge",
        "status": "active",
        "privacy": "private",
        "cloud_ok": False,
        "updated": date.today().isoformat(),
    }
    key_points = _extract_key_points(body)
    if key_points:
        frontmatter["key_points"] = key_points

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render_knowledge_page(frontmatter, title, body), encoding="utf-8")
    _update_index(vault, title)
    _append_log(vault, relative_source, target_relative)
    _add_inbound_links(vault, title, target_relative)

    return IngestResult(path=target_relative, title=title, updated=updated)


def _normalize_source(source_path: Path | str) -> str:
    relative = Path(source_path).as_posix().strip("/")
    parts = tuple(Path(relative).parts)
    if ".." in parts:
        raise ValueError("source path cannot contain parent traversal")
    if parts[:1] != ("raw",) or classify_vault_path(relative).skip:
        raise ValueError("ingest source must be under raw and outside skipped paths")
    if Path(relative).suffix.lower() not in {".md", ".txt"}:
        raise ValueError("ingest source must be markdown or text")
    return relative


def _read_source_text(source: Path) -> str:
    data = source.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")

    sample = data[:200]
    if b"\x00" in sample:
        even_nulls = sample[0::2].count(0)
        odd_nulls = sample[1::2].count(0)
        if odd_nulls > even_nulls and odd_nulls >= max(2, len(sample) // 8):
            return data.decode("utf-16-le", errors="replace")
        if even_nulls > odd_nulls and even_nulls >= max(2, len(sample) // 8):
            return data.decode("utf-16-be", errors="replace")

    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() != "---":
            continue
        metadata_text = "\n".join(lines[1:index])
        body = "\n".join(lines[index + 1 :])
        metadata = yaml.safe_load(metadata_text) or {}
        if not isinstance(metadata, dict):
            return {}, body
        return metadata, body

    return {}, text


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
    lines = text.lstrip().splitlines()
    if lines and (lines[0].startswith("# ") or lines[0].strip()):
        return "\n".join(lines[1:]).strip()
    return text.strip()


def _convert_markdown_links_to_wikilinks(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        target = Path(match.group(2)).stem.strip()
        return f"[[{target or label}]]"

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace, text)


def _extract_key_points(body: str) -> list[str]:
    points: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip().strip("-* ")
        if not line or line.startswith("#") or line.startswith("[["):
            continue
        sentence = re.split(r"(?<=[.!?])\s+", line, maxsplit=1)[0].strip()
        if sentence and sentence not in points:
            points.append(sentence)
        if len(points) == 3:
            break
    return points


def _add_outbound_links(vault: Path, body: str, title: str) -> str:
    linked = body
    for related_title in _existing_knowledge_titles(vault, exclude_title=title)[:2]:
        pattern = rf"(?<!\[\[)\b{re.escape(related_title)}\b(?!\]\])"
        updated = re.sub(pattern, f"[[{related_title}]]", linked, count=1, flags=re.IGNORECASE)
        linked = updated
    return linked


def _existing_knowledge_titles(vault: Path, *, exclude_title: str) -> list[str]:
    knowledge_dir = vault / "knowledge"
    if not knowledge_dir.exists():
        return []

    titles: list[str] = []
    for page in sorted(knowledge_dir.rglob("*.md")):
        text = page.read_text(encoding="utf-8", errors="replace")
        metadata, body = parse_frontmatter(text)
        candidate = str(metadata.get("title") or _extract_title(body, page.stem))
        if candidate.casefold() != exclude_title.casefold() and candidate not in titles:
            titles.append(candidate)
    return titles


def _add_inbound_links(vault: Path, title: str, target_relative: str) -> None:
    knowledge_dir = vault / "knowledge"
    if not knowledge_dir.exists():
        return
    pattern = rf"(?<!\[\[)\b{re.escape(title)}\b(?!\]\])"
    for page in sorted(knowledge_dir.rglob("*.md")):
        relative = page.relative_to(vault).as_posix()
        if relative == target_relative:
            continue
        text = page.read_text(encoding="utf-8", errors="replace")
        metadata, body = parse_frontmatter(text)
        updated_body = re.sub(pattern, f"[[{title}]]", body, count=1, flags=re.IGNORECASE)
        if updated_body != body:
            page.write_text(render_frontmatter(metadata, updated_body), encoding="utf-8")


def _render_knowledge_page(frontmatter: dict[str, object], title: str, body: str) -> str:
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False)
    content = body.strip()
    if content:
        content = f"\n\n{content}"
    return f"---\n{yaml_text}---\n\n# {title}{content}\n"


def _update_index(vault: Path, title: str) -> None:
    index_path = ensure_meta_index(vault)
    index = index_path.read_text(encoding="utf-8")

    entry = f"- [[{title}]]"
    if entry not in index.splitlines():
        index = _insert_under_knowledge(index, entry)
        index_path.write_text(index, encoding="utf-8")


def _insert_under_knowledge(index: str, entry: str) -> str:
    lines = index.splitlines()
    try:
        heading_index = lines.index(KNOWLEDGE_HEADING)
    except ValueError:
        lines.append(KNOWLEDGE_HEADING)
        heading_index = len(lines) - 1

    insert_at = heading_index + 1
    while insert_at < len(lines) and not lines[insert_at].startswith("## "):
        insert_at += 1
    lines.insert(insert_at, entry)
    return "\n".join(lines).rstrip() + "\n"


def _append_log(vault: Path, source: str, target: str) -> None:
    log_path = vault / "meta" / "log.md"
    if not log_path.exists():
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("# Log\n", encoding="utf-8")
    append_log(vault, f"- {date.today().isoformat()} ingest {source} -> {target}")


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    return slug or "untitled"
