from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from segretario.agents.base import BaseAgent
from segretario.vault.health import lint_vault, vault_stats


class MaintenanceAgent(BaseAgent):
    def run(self, request: object) -> dict[str, Any]:
        payload = self.payload(request)
        action = self.command(request, payload)

        if action == "stats":
            return asdict(vault_stats(self.require_vault_path(payload)))

        if action == "lint.wiki":
            today = payload.get("today")
            if today is not None and not isinstance(today, date):
                raise ValueError("today must be a date")
            report = lint_vault(self.require_vault_path(payload), today=today)
            return {"path": report.path, "report_path": report.path, "issues": report.issues}

        raise ValueError(f"unsupported maintenance action: {action}")
