from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlparse

import yaml

from segretario.connectors.web_client import WebConnector
from segretario.vault.adapter import VaultAdapter


@dataclass(frozen=True)
class LinkFetchResult:
    path: str
    title: str
    source_url: str


class WebTool:
    """Public web fetch side-effect tool."""

    def fetch_link(
        self,
        vault_path: Path | str,
        url: str,
        *,
        save_dir: str = "raw/articles",
        timeout_seconds: float = 20.0,
        connector: WebConnector | None = None,
    ) -> LinkFetchResult:
        return fetch_link(
            vault_path,
            url,
            save_dir=save_dir,
            timeout_seconds=timeout_seconds,
            connector=connector,
        )


def fetch_link(
    vault_path: Path | str,
    url: str,
    *,
    save_dir: str = "raw/articles",
    timeout_seconds: float = 20.0,
    connector: WebConnector | None = None,
) -> LinkFetchResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("link fetch only supports http and https URLs")

    vault = VaultAdapter(vault_path)
    save_root = vault.resolve(save_dir)
    relative_save_dir = Path(save_dir).as_posix().strip("/")
    if relative_save_dir == "raw/elaborati" or relative_save_dir.startswith("raw/elaborati/"):
        raise ValueError("link fetch cannot save into raw/elaborati")

    connector = connector or WebConnector()
    response = connector.fetch_url(url, timeout_seconds=timeout_seconds)

    content_type = response.content_type
    markdown = _to_markdown(response.text, content_type=content_type)
    title = _extract_title(markdown, parsed.path)
    slug = _slugify(title)
    target = _unique_path(save_root, f"{slug}.md")
    relative_path = Path(relative_save_dir) / target.name

    frontmatter = {
        "title": title,
        "source_url": url,
        "fetched_at": datetime.now(UTC).isoformat(),
        "privacy": "private",
        "cloud_ok": False,
    }
    rendered = _render_source(frontmatter, title, markdown)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")

    return LinkFetchResult(
        path=relative_path.as_posix(),
        title=title,
        source_url=url,
    )


def _to_markdown(text: str, *, content_type: str) -> str:
    text = text.lstrip("\ufeff")
    if "html" not in content_type.casefold() and not _looks_like_html(text):
        return text.strip()

    parser = _HTMLToMarkdown()
    parser.feed(text)
    return parser.markdown().strip()


def _looks_like_html(text: str) -> bool:
    return bool(re.search(r"<(?:html|body|h1|p|title)\b", text, flags=re.IGNORECASE))


def _extract_title(markdown: str, fallback_path: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped:
            return stripped.strip("# ").strip()

    fallback = Path(fallback_path).stem or "web-link"
    return fallback.replace("-", " ").replace("_", " ").title()


def _render_source(frontmatter: dict[str, object], title: str, markdown: str) -> str:
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False)
    body = markdown.strip()
    if not body.startswith("# "):
        body = f"# {title}\n\n{body}" if body else f"# {title}"
    return f"---\n{yaml_text}---\n\n{body}\n"


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    return slug or "web-link"


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


class _HTMLToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._title_parts: list[str] = []
        self._active_heading: str | None = None
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in {"h1", "h2", "h3"}:
            self._active_heading = tag
            self._parts.append("\n")
        elif tag in {"p", "br", "li"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in {"h1", "h2", "h3", "p", "li"}:
            self._active_heading = None
            self._parts.append("\n")

    def handle_data(self, data: str):
        if self._skip_depth:
            return

        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self._title_parts.append(text)
            return
        if self._active_heading:
            level = {"h1": "#", "h2": "##", "h3": "###"}[self._active_heading]
            self._parts.append(f"{level} {text}")
        else:
            self._parts.append(text)

    def markdown(self) -> str:
        body = "\n".join(line.strip() for line in "".join(self._parts).splitlines())
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        if body:
            return body
        title = " ".join(self._title_parts).strip()
        return f"# {title}" if title else ""
