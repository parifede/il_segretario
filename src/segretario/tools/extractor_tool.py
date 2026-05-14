from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from segretario.vault.paths import classify_vault_path, matches_configured_skip_path
from segretario.vault.repair import _processed_raw_sources


@dataclass(frozen=True)
class ExtractPlanReport:
    path: str
    items: list[str]


class ExtractorTool:
    """Plan safe local extraction work for rich raw sources."""

    def plan(
        self,
        vault_path: Path | str,
        *,
        today: date | None = None,
        skip_paths: list[str] | tuple[str, ...] | None = None,
    ) -> ExtractPlanReport:
        return plan_extraction(vault_path, today=today, skip_paths=skip_paths)


def plan_extraction(
    vault_path: Path | str,
    *,
    today: date | None = None,
    skip_paths: list[str] | tuple[str, ...] | None = None,
) -> ExtractPlanReport:
    vault = Path(vault_path)
    report_date = today or date.today()
    items = _extract_plan_items(vault, skip_paths=skip_paths)
    relative_report = f"output/extract-plan-{report_date.isoformat()}.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Extract Plan {report_date.isoformat()}", ""]
    if items:
        lines.extend(items)
    else:
        lines.append("- no extraction planning needed")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return ExtractPlanReport(path=relative_report, items=items)


def _extract_plan_items(
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
        if not path.is_file() or path.name == ".gitkeep":
            continue
        relative = path.relative_to(vault).as_posix()
        if classify_vault_path(relative).skip or matches_configured_skip_path(relative, skip_paths):
            continue
        if relative in processed:
            continue
        proposal = _extract_plan_decision(relative)
        if proposal is None:
            continue
        kind, reason = proposal
        items.append(f"- {relative} -> {kind}: {reason}")
    return items


def _extract_plan_decision(relative: str) -> tuple[str, str] | None:
    suffix = Path(relative).suffix.casefold()
    if suffix in {".md", ".txt"}:
        return None
    if suffix == ".pdf":
        return ("extract_candidate", "pdf text extraction candidate")
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}:
        return ("extract_candidate", "image OCR or metadata extraction candidate")
    if suffix in {".xlsx", ".xls", ".ods", ".csv", ".tsv"}:
        return ("extract_candidate", "spreadsheet/table extraction candidate")
    if suffix in {".pptx", ".ppt", ".odp"}:
        return ("extract_candidate", "presentation text extraction candidate")
    if suffix in {".docx", ".doc", ".odt", ".rtf"}:
        return ("extract_candidate", "document text extraction candidate")
    if suffix in {".patch", ".diff"}:
        return ("extract_candidate", "patch text extraction candidate")
    if suffix in {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar"}:
        return ("review_before_extract", "archive/bundle requires explicit expansion policy")
    if suffix:
        return ("leave_in_raw", f"unsupported {suffix.removeprefix('.')} source")
    return ("leave_in_raw", "unsupported source")
