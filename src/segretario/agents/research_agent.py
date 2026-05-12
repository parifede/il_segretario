from __future__ import annotations

from segretario.agents.base import BaseAgent
from segretario.connectors.web_client import WebConnector
from segretario.tools.web_tool import fetch_link


class ResearchAgent(BaseAgent):
    def run(self, request: object) -> dict[str, object]:
        payload = self.payload(request)
        action = self.command(request, payload)

        if action == "web.query":
            return WebConnector().prepare_query(
                str(payload["query"]),
                context_privacy=str(payload.get("context_privacy", "public")),
                projection=payload.get("projection"),
            )

        result = fetch_link(
            self.require_vault_path(payload),
            str(payload["url"]),
            save_dir=str(payload.get("save_dir", "raw/articles")),
        )
        return {
            "path": result.path,
            "title": result.title,
            "source_url": result.source_url,
        }
