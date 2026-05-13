from __future__ import annotations

from segretario.agents.base import BaseAgent
from segretario.connectors.calendar_client import CalendarClient
from segretario.tools.calendar_tool import CalendarTool


class CalendarAgent(BaseAgent):
    allowed_actions = frozenset(
        {"calendar.list", "calendar.create", "calendar.modify", "calendar.delete"}
    )
    allowed_tools = frozenset({"CalendarTool"})

    def run(self, request: object) -> object:
        payload = self.payload(request)
        action = self.require_allowed_action(self.command(request, payload))
        tool = CalendarTool(
            state_dir=payload["state_dir"],
            calendar_client=_calendar_client_from_payload(payload),
        )

        if action == "calendar.list":
            return tool.list_events()

        if action == "calendar.create":
            return tool.create_event(
                summary=str(payload["summary"]),
                when=str(payload.get("when", payload["summary"])),
                attendees=list(payload.get("attendees", [])),
            )

        if action == "calendar.modify":
            return tool.update_event(
                event_ref=str(payload["event_ref"]),
                summary=str(payload["summary"]),
            )

        if action == "calendar.delete":
            return tool.delete_event(event_ref=str(payload["event_ref"]))

        raise ValueError(f"unsupported calendar action: {action}")


def _calendar_client_from_payload(payload):
    if not payload.get("use_google"):
        return None
    return CalendarClient.from_token(
        credentials_path=payload["credentials_path"],
        token_path=payload["token_path"],
    )
