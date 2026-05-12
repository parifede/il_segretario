from __future__ import annotations

from segretario.agents.base import BaseAgent
from segretario.tools.calendar_tool import CalendarTool


class CalendarAgent(BaseAgent):
    def run(self, request: object) -> object:
        payload = self.payload(request)
        action = self.command(request, payload)
        tool = CalendarTool(state_dir=payload["state_dir"])

        if action == "calendar.list":
            return tool.list_events()

        if action == "calendar.create":
            return tool.create_event(
                summary=str(payload["summary"]),
                when=str(payload.get("when", payload["summary"])),
                attendees=list(payload.get("attendees", [])),
            )

        raise ValueError(f"unsupported calendar action: {action}")
