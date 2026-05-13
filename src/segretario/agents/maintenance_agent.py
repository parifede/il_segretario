from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from segretario.agents.base import BaseAgent
from segretario.vault.health import lint_vault, vault_stats
from segretario.vault.relink import relink_apply, relink_dry_run


class MaintenanceAgent(BaseAgent):
    allowed_actions = frozenset({"stats", "lint.wiki", "relink.dry_run", "relink.apply"})
    allowed_tools = frozenset({"MarkdownTool", "SearchTool", "VaultTool"})

    def run(self, request: object) -> dict[str, Any]:
        payload = self.payload(request)
        action = self.require_allowed_action(self.command(request, payload))

        if action == "stats":
            return asdict(vault_stats(self.require_vault_path(payload)))

        if action == "lint.wiki":
            today = payload.get("today")
            if today is not None and not isinstance(today, date):
                raise ValueError("today must be a date")
            report = lint_vault(self.require_vault_path(payload), today=today)
            return {"path": report.path, "report_path": report.path, "issues": report.issues}

        if action == "relink.dry_run":
            today = payload.get("today")
            if today is not None and not isinstance(today, date):
                raise ValueError("today must be a date")
            report = relink_dry_run(
                self.require_vault_path(payload),
                source_scope=_source_scope(payload),
                today=today,
            )
            return {
                "path": report.path,
                "report_path": report.path,
                "suggestions": report.suggestions,
            }

        if action == "relink.apply":
            today = payload.get("today")
            if today is not None and not isinstance(today, date):
                raise ValueError("today must be a date")
            report = relink_apply(
                self.require_vault_path(payload),
                source_scope=_source_scope(payload),
                today=today,
            )
            return {
                "path": report.path,
                "report_path": report.path,
                "suggestions": report.suggestions,
            }

        raise ValueError(f"unsupported maintenance action: {action}")


def _source_scope(payload: dict[str, Any]) -> str | None:
    value = payload.get("source_scope")
    if value is None:
        return None
    return str(value)
