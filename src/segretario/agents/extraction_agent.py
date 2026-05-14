from __future__ import annotations

from datetime import date
from typing import Any

from segretario.agents.base import BaseAgent
from segretario.tools.extractor_tool import ExtractorTool


class ExtractionAgent(BaseAgent):
    allowed_actions = frozenset({"extract.plan", "extract.pdf", "ocr.pdf"})
    allowed_tools = frozenset({"ExtractorTool", "VaultTool"})

    def run(self, request: object) -> dict[str, Any]:
        payload = self.payload(request)
        action = self.require_allowed_action(self.command(request, payload))
        if action == "extract.plan":
            today = payload.get("today")
            if today is not None and not isinstance(today, date):
                raise ValueError("today must be a date")
            report = ExtractorTool().plan(
                self.require_vault_path(payload),
                today=today,
                skip_paths=_skip_paths(payload),
            )
            return {"path": report.path, "report_path": report.path, "items": report.items}
        if action == "extract.pdf":
            source_path = payload.get("source_path")
            if source_path is None:
                raise ValueError("extract.pdf requires source_path")
            return ExtractorTool().extract_pdf(
                self.require_vault_path(payload),
                source_path,
                skip_paths=_skip_paths(payload),
            )
        if action == "ocr.pdf":
            marker_path = payload.get("marker_path")
            if marker_path is None:
                raise ValueError("ocr.pdf requires marker_path")
            return ExtractorTool().ocr_pdf(
                self.require_vault_path(payload),
                marker_path,
                skip_paths=_skip_paths(payload),
            )
        raise ValueError(f"unsupported extraction action: {action}")


def _skip_paths(payload: dict[str, Any]) -> list[str]:
    value = payload.get("skip_paths")
    if isinstance(value, list):
        return [str(item) for item in value]
    return []
