from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
import re
from pathlib import Path

from segretario.vault.paths import classify_vault_path


@dataclass(frozen=True)
class VaultStats:
    markdown_by_area: dict[str, int]
    total_markdown: int


@dataclass(frozen=True)
class LintReport:
    path: str
    issues: list[str]


def vault_stats(vault_path: Path | str) -> VaultStats:
    vault = Path(vault_path)
    counts: Counter[str] = Counter()

    for file_path in sorted(vault.rglob("*.md")):
        relative = file_path.relative_to(vault)
        if classify_vault_path(relative.as_posix()).skip:
            continue
        if relative.parts:
            counts[relative.parts[0]] += 1

    markdown_by_area = dict(sorted(counts.items()))
    return VaultStats(
        markdown_by_area=markdown_by_area,
        total_markdown=sum(markdown_by_area.values()),
    )


def lint_vault(vault_path: Path | str, *, today: date | None = None) -> LintReport:
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
        issues.extend(_orphan_knowledge_issues(vault, index_text))

    relative_report = f"output/lint-{report_date.isoformat()}.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(report_date, issues), encoding="utf-8")

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


def _orphan_knowledge_issues(vault: Path, index_text: str) -> list[str]:
    linked_titles = {match.strip() for match in re.findall(r"\[\[([^\]#|]+)", index_text)}
    issues: list[str] = []
    knowledge_dir = vault / "knowledge"
    if not knowledge_dir.exists():
        return issues

    for page in sorted(knowledge_dir.rglob("*.md")):
        relative = page.relative_to(vault).as_posix()
        title = page.stem
        if title not in linked_titles:
            issues.append(f"{relative}: orphan knowledge page")
    return issues


def _render_report(report_date: date, issues: list[str]) -> str:
    lines = [f"# Vault lint {report_date.isoformat()}", ""]
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- ok")
    lines.append("")
    return "\n".join(lines)
