from __future__ import annotations

from segretario.agents.base import BaseAgent
from segretario.agents.ingest_agent import ingest_article
from segretario.connectors.web_client import WebConnector
from segretario.tools.web_tool import fetch_link


class ResearchAgent(BaseAgent):
    allowed_actions = frozenset({"link", "web.query"})
    allowed_tools = frozenset({"WebTool", "IngestAgent"})

    def run(self, request: object) -> dict[str, object]:
        payload = self.payload(request)
        action = self.require_allowed_action(self.command(request, payload))

        if action == "web.query":
            return WebConnector().prepare_query(
                str(payload["query"]),
                context_privacy=str(payload.get("context_privacy", "public")),
                projection=payload.get("projection"),
            )

        vault_path = self.require_vault_path(payload)
        result = fetch_link(
            vault_path,
            str(payload["url"]),
            save_dir=str(payload.get("save_dir", "raw/articles")),
        )
        output = {
            "path": result.path,
            "title": result.title,
            "source_url": result.source_url,
        }
        if payload.get("ingest"):
            ingest_result = ingest_article(vault_path, result.path, auto=True)
            output["ingested_path"] = ingest_result.path
            output["ingested_title"] = ingest_result.title
            output["ingested_updated"] = ingest_result.updated
        return output
