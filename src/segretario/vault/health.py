from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
import re
from pathlib import Path

from segretario.vault.frontmatter import parse_frontmatter
from segretario.vault.index_log import append_log
from segretario.vault.paths import classify_vault_path, matches_configured_skip_path
from segretario.vault.wikilinks import extract_wikilink_references


@dataclass(frozen=True)
class VaultStats:
    markdown_by_area: dict[str, int]
    total_markdown: int


@dataclass(frozen=True)
class LintReport:
    path: str
    issues: list[str]


def vault_stats(
    vault_path: Path | str,
    *,
    skip_paths: list[str] | tuple[str, ...] | None = None,
) -> VaultStats:
    vault = Path(vault_path)
    counts: Counter[str] = Counter()

    for file_path in sorted(vault.rglob("*.md")):
        relative = file_path.relative_to(vault)
        relative_text = relative.as_posix()
        if _should_skip(relative_text, skip_paths):
            continue
        if relative.parts:
            counts[relative.parts[0]] += 1

    markdown_by_area = dict(sorted(counts.items()))
    return VaultStats(
        markdown_by_area=markdown_by_area,
        total_markdown=sum(markdown_by_area.values()),
    )


def lint_vault(
    vault_path: Path | str,
    *,
    today: date | None = None,
    skip_paths: list[str] | tuple[str, ...] | None = None,
) -> LintReport:
    vault = Path(vault_path)
    report_date = today or date.today()
    issues: list[str] = []

    index_path = vault / "meta" / "index.md"
    log_path = vault / "meta" / "log.md"
    if not index_path.exists():
        issues.append("meta/index.md: missing")
    if not log_path.exists():
        issues.append("meta/log.md: missing")

    if index_path.exists():
        index_text = index_path.read_text(encoding="utf-8")
        issues.extend(_duplicate_heading_issues(index_text))
        issues.extend(_orphan_knowledge_issues(vault, index_text, skip_paths=skip_paths))
    issues.extend(_missing_status_issues(vault, skip_paths=skip_paths))
    issues.extend(_stale_stub_issues(vault, report_date, skip_paths=skip_paths))
    issues.extend(_unprocessed_raw_issues(vault, skip_paths=skip_paths))
    issues.extend(_personal_knowledge_issues(vault, skip_paths=skip_paths))

    relative_report = f"output/lint-{report_date.isoformat()}.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(report_date, issues), encoding="utf-8")
    _append_lint_log(vault, report_date, relative_report)

    return LintReport(path=relative_report, issues=issues)


def _duplicate_heading_issues(index_text: str) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*$", index_text, flags=re.MULTILINE):
        normalized = heading.strip()
        if normalized in seen and normalized not in duplicates:
            duplicates.append(normalized)
        seen.add(normalized)
    return [f"meta/index.md: duplicate heading '{heading}'" for heading in duplicates]


def _orphan_knowledge_issues(
    vault: Path,
    index_text: str,
    *,
    skip_paths: list[str] | tuple[str, ...] | None,
) -> list[str]:
    linked_references = extract_wikilink_references(index_text)
    issues: list[str] = []
    knowledge_dir = vault / "knowledge"
    if not knowledge_dir.exists():
        return issues

    for page in sorted(knowledge_dir.rglob("*.md")):
        relative = page.relative_to(vault).as_posix()
        if _should_skip(relative, skip_paths):
            continue
        text = page.read_text(encoding="utf-8", errors="replace")
        metadata, body = parse_frontmatter(text)
        title = str(metadata.get("title") or _extract_title(body, page.stem))
        path_reference = relative.removesuffix(".md")
        if title not in linked_references and relative not in linked_references and path_reference not in linked_references:
            issues.append(f"{relative}: orphan knowledge page")
    return issues


def _missing_status_issues(
    vault: Path,
    *,
    skip_paths: list[str] | tuple[str, ...] | None,
) -> list[str]:
    knowledge_dir = vault / "knowledge"
    if not knowledge_dir.exists():
        return []
    issues: list[str] = []
    for page in sorted(knowledge_dir.rglob("*.md")):
        relative = page.relative_to(vault).as_posix()
        if _should_skip(relative, skip_paths):
            continue
        text = page.read_text(encoding="utf-8", errors="replace")
        metadata, _body = parse_frontmatter(text)
        if not str(metadata.get("status", "")).strip():
            issues.append(f"{relative}: missing status in frontmatter")
    return issues


def _stale_stub_issues(
    vault: Path,
    report_date: date,
    *,
    skip_paths: list[str] | tuple[str, ...] | None,
) -> list[str]:
    issues: list[str] = []
    knowledge_dir = vault / "knowledge"
    if not knowledge_dir.exists():
        return issues

    for page in sorted(knowledge_dir.rglob("*.md")):
        relative = page.relative_to(vault).as_posix()
        if _should_skip(relative, skip_paths):
            continue
        text = page.read_text(encoding="utf-8", errors="replace")
        metadata, body = parse_frontmatter(text)
        if str(metadata.get("status", "")).casefold() != "stub":
            continue
        updated = _parse_date(metadata.get("updated"))
        if updated is None or (report_date - updated).days >= 7:
            details = f" updated {updated.isoformat()}" if updated else ""
            issues.append(f"{relative}: stale stub{details}")
        elif "todo" in body.casefold():
            issues.append(f"{relative}: stale stub")
    return issues


def _unprocessed_raw_issues(
    vault: Path,
    *,
    skip_paths: list[str] | tuple[str, ...] | None,
) -> list[str]:
    raw_dir = vault / "raw"
    if not raw_dir.exists():
        return []
    processed_sources = _processed_raw_sources(vault)
    issues: list[str] = []
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        relative = path.relative_to(vault).as_posix()
        if _should_skip(relative, skip_paths):
            continue
        if relative in processed_sources:
            continue
        issues.append(f"{relative}: unprocessed raw file")
    return issues


def _processed_raw_sources(vault: Path) -> set[str]:
    knowledge_dir = vault / "knowledge"
    if not knowledge_dir.exists():
        return set()
    sources: set[str] = set()
    for page in sorted(knowledge_dir.rglob("*.md")):
        text = page.read_text(encoding="utf-8", errors="replace")
        metadata, _body = parse_frontmatter(text)
        source_path = metadata.get("source_path")
        if isinstance(source_path, str) and source_path:
            sources.add(Path(source_path).as_posix().strip("/"))
    return sources


def _personal_knowledge_issues(
    vault: Path,
    *,
    skip_paths: list[str] | tuple[str, ...] | None,
) -> list[str]:
    knowledge_dir = vault / "knowledge"
    if not knowledge_dir.exists():
        return []
    issues: list[str] = []
    for page in sorted(knowledge_dir.rglob("*.md")):
        relative = page.relative_to(vault).as_posix()
        if _should_skip(relative, skip_paths):
            continue
        text = page.read_text(encoding="utf-8", errors="replace")
        if _looks_personal(text):
            issues.append(f"{relative}: personal-looking content in knowledge")
    return issues


def _parse_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _looks_personal(text: str) -> bool:
    patterns = [
        r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
        r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b",
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
        return heading.group(1).strip() if heading else fallback
    return fallback


def _render_report(report_date: date, issues: list[str]) -> str:
    lines = [f"# Vault lint {report_date.isoformat()}", ""]
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- ok")
    lines.append("")
    return "\n".join(lines)


def _append_lint_log(vault: Path, report_date: date, relative_report: str) -> None:
    log_path = vault / "meta" / "log.md"
    if not log_path.exists():
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("# Log\n", encoding="utf-8")
    append_log(vault, f"- {report_date.isoformat()} lint wiki -> {relative_report}")


def _should_skip(
    relative: str,
    skip_paths: list[str] | tuple[str, ...] | None,
) -> bool:
    return classify_vault_path(relative).skip or matches_configured_skip_path(
        relative,
        skip_paths,
    )
