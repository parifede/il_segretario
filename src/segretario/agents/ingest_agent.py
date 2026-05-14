from __future__ import annotations

from segretario.agents.base import BaseAgent
from segretario.tools.markdown_tool import (
    ConfirmationNeededError,
    IngestResult,
    MarkdownTool,
    ingest_article,
)


class IngestAgent(BaseAgent):
    allowed_actions = frozenset({"ingest"})
    allowed_tools = frozenset({"MarkdownTool", "VaultTool"})

    def run(self, request: object) -> dict[str, object]:
        payload = self.payload(request)
        self.require_allowed_action(self.command(request, payload))
        result = MarkdownTool().ingest_article(
            self.require_vault_path(payload),
            payload.get("source_path", payload.get("source")),
            auto=bool(payload.get("auto", False)),
        )
        return {"path": result.path, "title": result.title, "updated": result.updated}


__all__ = [
    "ConfirmationNeededError",
    "IngestAgent",
    "IngestResult",
    "ingest_article",
]
