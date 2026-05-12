from __future__ import annotations

from segretario.agents.base import BaseAgent
from segretario.connectors.gmail_client import GmailClient
from segretario.tools.gmail_tool import GmailTool


class MailAgent(BaseAgent):
    def run(self, request: object) -> object:
        payload = self.payload(request)
        action = self.command(request, payload)
        tool = GmailTool(
            state_dir=payload["state_dir"],
            google_client=_gmail_client_from_payload(payload),
        )

        if action == "mail.read":
            return tool.read(query=str(payload.get("query", "")))

        if action == "mail.draft":
            return tool.create_draft(
                to=str(payload["to"]),
                subject=str(payload["subject"]),
                body=str(payload["body"]),
            )

        if action == "mail.send":
            return tool.send_draft(draft_id=str(payload["draft_id"]))

        if action == "mail.archive":
            return tool.archive_message(message_ref=str(payload["message_ref"]))

        if action == "mail.delete":
            return tool.delete_message(message_ref=str(payload["message_ref"]))

        raise ValueError(f"unsupported mail action: {action}")


def _gmail_client_from_payload(payload):
    if not payload.get("use_google"):
        return None
    return GmailClient.from_token(
        credentials_path=payload["credentials_path"],
        token_path=payload["token_path"],
    )
