from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
import re
from pathlib import Path

from segretario.vault.frontmatter import parse_frontmatter, render_frontmatter
from segretario.vault.paths import classify_vault_path
from segretario.vault.wikilinks import extract_wikilink_targets


@dataclass(frozen=True)
class RelinkReport:
    path: str
    suggestions: list[str]


@dataclass(frozen=True)
class WikiPage:
    relative_path: str
    title: str
    body: str
    links: set[str]


@dataclass(frozen=True)
class RelinkSuggestion:
    source_path: str
    target_title: str

    def render(self) -> str:
        return f"{self.source_path} -> [[{self.target_title}]]"


def relink_dry_run(vault_path: str | Path, *, today: date | None = None) -> RelinkReport:
    vault = Path(vault_path)
    report_date = today or date.today()
    suggestions = [suggestion.render() for suggestion in _find_suggestions(vault)]

    relative_report = f"output/relink-{report_date.isoformat()}.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(report_date, suggestions), encoding="utf-8")
    return RelinkReport(path=relative_report, suggestions=suggestions)


def relink_apply(vault_path: str | Path, *, today: date | None = None) -> RelinkReport:
    vault = Path(vault_path)
    report_date = today or date.today()
    applied: list[str] = []

    for suggestion in _find_suggestions(vault):
        if not suggestion.source_path.startswith("knowledge/"):
            continue
        source_path = vault / suggestion.source_path
        text = source_path.read_text(encoding="utf-8", errors="replace")
        metadata, body = parse_frontmatter(text)
        updated_body = _replace_first_title(body, suggestion.target_title)
        if updated_body == body:
            continue
        source_path.write_text(render_frontmatter(metadata, updated_body), encoding="utf-8")
        applied.append(suggestion.render())

    relative_report = f"output/relink-apply-{report_date.isoformat()}.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_apply_report(report_date, applied), encoding="utf-8")
    return RelinkReport(path=relative_report, suggestions=applied)


def _find_suggestions(vault: Path) -> list[RelinkSuggestion]:
    pages = _collect_pages(vault)
    title_counts = Counter(page.title.casefold() for page in pages)
    suggestions: list[RelinkSuggestion] = []
    seen_suggestions: set[str] = set()

    for page in pages:
        for target in pages:
            if page.relative_path == target.relative_path:
                continue
            if title_counts[target.title.casefold()] > 1:
                continue
            if _already_links(page, target):
                continue
            if _mentions_title(page.body, target.title):
                suggestion = RelinkSuggestion(
                    source_path=page.relative_path,
                    target_title=target.title,
                )
                rendered = suggestion.render()
                if rendered not in seen_suggestions:
                    suggestions.append(suggestion)
                    seen_suggestions.add(rendered)
    return suggestions


def _collect_pages(vault: Path) -> list[WikiPage]:
    pages: list[WikiPage] = []
    for path in sorted(vault.rglob("*.md")):
        relative = path.relative_to(vault).as_posix()
        policy = classify_vault_path(relative)
        if policy.skip:
            continue
        parts = relative.split("/")
        if parts[:1] not in (["knowledge"], ["meta"], ["output"]):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        metadata, body = parse_frontmatter(text)
        title = _title_for(path, metadata, body)
        pages.append(
            WikiPage(
                relative_path=relative,
                title=title,
                body=body,
                links=set(extract_wikilink_targets(body)),
            )
        )
    return pages


def _title_for(path: Path, metadata: dict[str, object], body: str) -> str:
    title = metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    for line in body.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return path.stem.replace("-", " ").replace("_", " ").title()


def _already_links(page: WikiPage, target: WikiPage) -> bool:
    target_aliases = {
        target.title,
        target.relative_path.removesuffix(".md"),
        Path(target.relative_path).stem,
    }
    return bool(page.links & target_aliases)


def _mentions_title(body: str, title: str) -> bool:
    if not title.strip():
        return False
    pattern = rf"(?<!\[\[)\b{re.escape(title)}\b(?!\]\])"
    return re.search(pattern, body, flags=re.IGNORECASE) is not None


def _replace_first_title(body: str, title: str) -> str:
    pattern = rf"(?<!\[\[)\b{re.escape(title)}\b(?!\]\])"
    return re.sub(pattern, f"[[{title}]]", body, count=1, flags=re.IGNORECASE)


def _render_report(report_date: date, suggestions: list[str]) -> str:
    lines = [f"# Relink dry-run {report_date.isoformat()}", ""]
    if suggestions:
        lines.extend(f"- {suggestion}" for suggestion in suggestions)
    else:
        lines.append("- no missing links found")
    lines.append("")
    return "\n".join(lines)


def _render_apply_report(report_date: date, applied: list[str]) -> str:
    lines = [f"# Relink apply {report_date.isoformat()}", ""]
    if applied:
        lines.extend(f"- {suggestion}" for suggestion in applied)
    else:
        lines.append("- no links applied")
    lines.append("")
    return "\n".join(lines)
