from __future__ import annotations

from segretario.agents.base import BaseAgent
from segretario.tools.web_tool import fetch_link


class ResearchAgent(BaseAgent):
    def run(self, request: object) -> dict[str, object]:
        payload = self.payload(request)
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
