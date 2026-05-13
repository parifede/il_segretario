from __future__ import annotations

from pathlib import Path

from googleapiclient.discovery import build

from segretario.connectors.google_oauth import GoogleOAuthConnector


class CalendarClient:
    def __init__(self, service) -> None:
        self.service = service

    @classmethod
    def from_token(
        cls,
        *,
        credentials_path: str | Path,
        token_path: str | Path,
    ) -> "CalendarClient":
        credentials = GoogleOAuthConnector(
            credentials_path=credentials_path,
            token_path=token_path,
        ).credentials()
        return cls(build("calendar", "v3", credentials=credentials, cache_discovery=False))

    def list_events(self, *, max_results: int = 10) -> list[dict[str, object]]:
        response = (
            self.service.events()
            .list(
                calendarId="primary",
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return [_event_summary(event) for event in response.get("items", [])]

    def get_event(self, *, event_ref: str) -> dict[str, object]:
        event = (
            self.service.events()
            .get(calendarId="primary", eventId=event_ref)
            .execute()
        )
        return _event_summary(event)

    def delete_event(self, *, event_ref: str) -> dict[str, object]:
        (
            self.service.events()
            .delete(calendarId="primary", eventId=event_ref)
            .execute()
        )
        return {
            "id": event_ref,
            "deleted": True,
        }

    def update_event(self, *, event_ref: str, summary: str) -> dict[str, object]:
        event = (
            self.service.events()
            .patch(
                calendarId="primary",
                eventId=event_ref,
                body={"summary": summary},
            )
            .execute()
        )
        return _event_summary(event)


def _event_summary(event: dict[str, object]) -> dict[str, object]:
    start = event.get("start", {})
    when = ""
    if isinstance(start, dict):
        when = str(start.get("dateTime") or start.get("date") or "")
    return {
        "id": str(event.get("id", "")),
        "summary": str(event.get("summary", "")),
        "when": when,
    }
