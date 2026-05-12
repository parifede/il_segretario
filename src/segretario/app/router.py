from __future__ import annotations

from typing import Protocol

from segretario.app.models import TaskRequest


class Agent(Protocol):
    def run(self, request: TaskRequest):
        """Run a normalized task request."""


class TaskRouter:
    def __init__(self, agents: dict[str, Agent]) -> None:
        self._agents = dict(agents)

    def agent_for(self, command: str) -> Agent:
        try:
            return self._agents[command]
        except KeyError as exc:
            raise KeyError(f"unknown command: {command}") from exc
