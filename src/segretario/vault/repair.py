from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re

from segretario.vault.frontmatter import parse_frontmatter
from segretario.vault.index_log import append_log, ensure_meta_index
from segretario.vault.paths import classify_vault_path, matches_configured_skip_path
from segretario.vault.wikilinks import extract_wikilink_references


@dataclass(frozen=True)
class RepairIndexReport:
    path: str
    entries: list[str]


@dataclass(frozen=True)
class RepairRawPlanReport:
    path: str
    items: list[str]


def repair_index_dry_run(
    vault_path: str | Path,
    *,
    today: date | None = None,
    skip_paths: list[str] | tuple[str, ...] | None = None,
) -> RepairIndexReport:
    vault = Path(vault_path)
    report_date = today or date.today()
    entries = _missing_index_entries(vault, skip_paths=skip_paths)
    relative_report = f"output/repair-index-{report_date.isoformat()}.md"
    _write_report(vault, relative_report, "Repair Index dry-run", report_date, entries)
    return RepairIndexReport(path=relative_report, entries=entries)


def repair_raw_plan(
    vault_path: str | Path,
    *,
    today: date | None = None,
    skip_paths: list[str] | tuple[str, ...] | None = None,
) -> RepairRawPlanReport:
    vault = Path(vault_path)
    report_date = today or date.today()
    items = _raw_plan_items(vault, skip_paths=skip_paths)
    relative_report = f"output/repair-raw-plan-{report_date.isoformat()}.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Repair Raw Plan {report_date.isoformat()}", ""]
    if items:
        lines.extend(items)
    else:
        lines.append("- no raw planning needed")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return RepairRawPlanReport(path=relative_report, items=items)


def repair_index_apply(
    vault_path: str | Path,
    *,
    today: date | None = None,
    skip_paths: list[str] | tuple[str, ...] | None = None,
) -> RepairIndexReport:
    vault = Path(vault_path)
    report_date = today or date.today()
    entries = _missing_index_entries(vault, skip_paths=skip_paths)
    relative_report = f"output/repair-index-apply-{report_date.isoformat()}.md"

    index_path = ensure_meta_index(vault)
    index_text = index_path.read_text(encoding="utf-8")
    normalized_index = _remove_redundant_plain_title_entries(index_text)
    if entries:
        normalized_index = _append_knowledge_entries(normalized_index, entries)
    if normalized_index != index_text:
        index_path.write_text(normalized_index, encoding="utf-8")

    _write_report(vault, relative_report, "Repair Index apply", report_date, entries)
    append_log(vault, f"- {report_date.isoformat()} repair index -> {relative_report}")
    return RepairIndexReport(path=relative_report, entries=entries)


def _raw_plan_items(
    vault: Path,
    *,
    skip_paths: list[str] | tuple[str, ...] | None,
) -> list[str]:
    raw_dir = vault / "raw"
    if not raw_dir.exists():
        return []
    processed = _processed_raw_sources(vault)
    items: list[str] = []
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == ".gitkeep":
            continue
        relative = path.relative_to(vault).as_posix()
        if classify_vault_path(relative).skip or matches_configured_skip_path(relative, skip_paths):
            continue
        if relative in processed:
            continue
        proposal, reason = _raw_plan_decision(relative)
        items.append(f"- {relative} -> {proposal}: {reason}")
    return items


def _processed_raw_sources(vault: Path) -> set[str]:
    sources: set[str] = set()
    knowledge = vault / "knowledge"
    if knowledge.exists():
        for page in sorted(knowledge.rglob("*.md")):
            metadata, _body = parse_frontmatter(page.read_text(encoding="utf-8", errors="replace"))
            source_path = metadata.get("source_path")
            if isinstance(source_path, str) and source_path.strip():
                sources.add(source_path.strip().replace("\\", "/"))

    log_path = vault / "meta" / "log.md"
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        sources.update(_processed_raw_sources_from_log(log_text))
    return sources


def _processed_raw_sources_from_log(log_text: str) -> set[str]:
    sources: set[str] = set()
    for match in re.finditer(r"\bingest\s+(raw/[^\r\n]+?)\s+->\s+knowledge/", log_text):
        sources.add(match.group(1).strip().replace("\\", "/"))
    for match in re.finditer(r"\bingest_missing\s+\|\s+(raw/[^\r\n]+)", log_text):
        sources.add(match.group(1).strip().replace("\\", "/"))
    return sources


def _raw_plan_decision(relative: str) -> tuple[str, str]:
    suffix = Path(relative).suffix.casefold()
    if _looks_private_raw_path(relative):
        return "review_before_ingest", "private-looking path"
    if suffix in {".md", ".txt"}:
        return "ingest_candidate", "markdown/text source"
    if suffix == ".pdf":
        return "leave_in_raw", "unsupported pdf source"
    if suffix:
        return "leave_in_raw", f"unsupported {suffix.removeprefix('.')} source"
    return "leave_in_raw", "unsupported source"


def _looks_private_raw_path(relative: str) -> bool:
    lowered = relative.casefold()
    private_markers = (
        "whatsapp",
        "telegram",
        "chat",
        "conversazione",
        "adhd",
        "crush",
        "amica",
        "personale",
        "privat",
    )
    return any(marker in lowered for marker in private_markers)


def _missing_index_entries(
    vault: Path,
    *,
    skip_paths: list[str] | tuple[str, ...] | None,
) -> list[str]:
    index_path = vault / "meta" / "index.md"
    index_text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    linked_references = extract_wikilink_references(index_text)
    page_titles = [(page, _title_for_page(page)) for page in _knowledge_pages(vault, skip_paths=skip_paths)]
    title_counts = Counter(title.casefold() for _page, title in page_titles)
    entries: list[str] = []
    for page, title in page_titles:
        if title_counts[title.casefold()] > 1:
            continue
        relative = page.relative_to(vault).as_posix()
        if _is_indexed(title, relative, linked_references):
            continue
        entry = f"- [[{title}]]"
        if entry not in entries:
            entries.append(entry)
    return entries


def _knowledge_pages(
    vault: Path,
    *,
    skip_paths: list[str] | tuple[str, ...] | None,
) -> list[Path]:
    knowledge = vault / "knowledge"
    if not knowledge.exists():
        return []
    pages: list[Path] = []
    for page in sorted(knowledge.rglob("*.md")):
        relative = page.relative_to(vault).as_posix()
        if classify_vault_path(relative).skip or matches_configured_skip_path(relative, skip_paths):
            continue
        pages.append(page)
    return pages


def _is_indexed(title: str, relative: str, references: set[str]) -> bool:
    return (
        title in references
        or relative in references
        or relative.removesuffix(".md") in references
    )


def _title_for_page(page: Path) -> str:
    text = page.read_text(encoding="utf-8", errors="replace")
    metadata, body = parse_frontmatter(text)
    title = metadata.get("title")
    if isinstance(title, str) and title.strip():
        return _clean_title(title)
    for line in body.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return _clean_title(match.group(1))
    return _clean_title(page.stem.replace("-", " ").replace("_", " ").title())


def _clean_title(title: str) -> str:
    cleaned = re.sub(r"\[\[([^\]#|]+)(?:\|[^\]]+)?\]\]", r"\1", title)
    return re.sub(r"\s+", " ", cleaned).strip()


def _append_knowledge_entries(index_text: str, entries: list[str]) -> str:
    if "## Knowledge" not in index_text:
        index_text = index_text.rstrip() + "\n\n## Knowledge\n"
    lines = index_text.splitlines()
    output: list[str] = []
    inserted = False
    for index, line in enumerate(lines):
        if not inserted and index > 0 and line.startswith("## ") and lines[index - 1] != "## Knowledge":
            output.extend(entries)
            inserted = True
        output.append(line)
        if line == "## Knowledge":
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            if next_line.startswith("## "):
                output.extend(entries)
                inserted = True
    if not inserted:
        output.extend(entries)
    return "\n".join(_dedupe_preserving_order(output)).rstrip() + "\n"


def _remove_redundant_plain_title_entries(index_text: str) -> str:
    alias_titles = {
        alias.strip()
        for _target, alias in re.findall(r"\[\[([^|\]]+)\|([^\]]+)\]\]", index_text)
        if alias.strip()
    }
    if not alias_titles:
        return index_text
    lines: list[str] = []
    for line in index_text.splitlines():
        plain = re.fullmatch(r"- \[\[([^\]|#]+)\]\]", line.strip())
        if plain and plain.group(1).strip() in alias_titles:
            continue
        lines.append(line)
    return "\n".join(lines).rstrip() + "\n"


def _dedupe_preserving_order(lines: list[str]) -> list[str]:
    seen_entries: set[str] = set()
    output: list[str] = []
    for line in lines:
        if line.startswith("- [["):
            if line in seen_entries:
                continue
            seen_entries.add(line)
        output.append(line)
    return output


def _write_report(
    vault: Path,
    relative_report: str,
    title: str,
    report_date: date,
    entries: list[str],
) -> None:
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title} {report_date.isoformat()}", ""]
    if entries:
        lines.extend(entries)
    else:
        lines.append("- no index repairs needed")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
