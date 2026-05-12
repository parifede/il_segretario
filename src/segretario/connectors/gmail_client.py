from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path

from googleapiclient.discovery import build

from segretario.connectors.google_oauth import GoogleOAuthConnector


class GmailClient:
    def __init__(self, service) -> None:
        self.service = service

    @classmethod
    def from_token(cls, *, credentials_path: str | Path, token_path: str | Path) -> "GmailClient":
        credentials = GoogleOAuthConnector(
            credentials_path=credentials_path,
            token_path=token_path,
        ).credentials()
        return cls(build("gmail", "v1", credentials=credentials, cache_discovery=False))

    def search_messages(self, *, query: str, max_results: int = 10) -> list[dict[str, str]]:
        response = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = []
        for item in response.get("messages", []):
            message = (
                self.service.users()
                .messages()
                .get(
                    userId="me",
                    id=item["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject"],
                )
                .execute()
            )
            messages.append(_message_summary(message))
        return messages

    def create_draft(self, *, to: str, subject: str, body: str) -> dict[str, str]:
        email = EmailMessage()
        email["To"] = to
        email["Subject"] = subject
        email.set_content(body)
        raw = base64.urlsafe_b64encode(email.as_bytes()).decode("utf-8")
        draft = (
            self.service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )
        return {
            "id": str(draft["id"]),
            "to": to,
            "subject": subject,
        }

    def send_draft(self, *, draft_id: str) -> dict[str, str]:
        sent = (
            self.service.users()
            .drafts()
            .send(userId="me", body={"id": draft_id})
            .execute()
        )
        return {
            "id": str(sent.get("id", "")),
            "draft_id": draft_id,
        }


def _message_summary(message: dict[str, object]) -> dict[str, str]:
    headers = {
        str(header.get("name", "")).casefold(): str(header.get("value", ""))
        for header in message.get("payload", {}).get("headers", [])
        if isinstance(header, dict)
    }
    return {
        "id": str(message.get("id", "")),
        "from": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "snippet": str(message.get("snippet", "")),
    }
