from __future__ import annotations

from segretario.agents.base import BaseAgent
from segretario.tools.gmail_tool import GmailTool


class MailAgent(BaseAgent):
    def run(self, request: object) -> object:
        payload = self.payload(request)
        action = self.command(request, payload)
        tool = GmailTool(state_dir=payload["state_dir"])

        if action == "mail.read":
            return tool.read(query=str(payload.get("query", "")))

        if action == "mail.draft":
            return tool.create_draft(
                to=str(payload["to"]),
                subject=str(payload["subject"]),
                body=str(payload["body"]),
            )

        raise ValueError(f"unsupported mail action: {action}")
