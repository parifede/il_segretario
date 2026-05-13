from __future__ import annotations

from collections.abc import Mapping
from typing import Any


Payload = Mapping[str, Any]


class AgentPayloadError(ValueError):
    """Raised when an agent request does not contain a mapping payload."""


class BaseAgent:
    """Base class for fixed operation wrappers."""

    allowed_actions: frozenset[str] = frozenset()
    allowed_tools: frozenset[str] = frozenset()

    def __init__(self, vault_path: object | None = None) -> None:
        self.vault_path = vault_path

    def payload(self, request: object) -> Payload:
        if isinstance(request, Mapping):
            return request

        payload = getattr(request, "payload", None)
        if isinstance(payload, Mapping):
            return payload

        raise AgentPayloadError("agent request must be a mapping or expose mapping payload")

    def command(self, request: object, payload: Payload) -> str | None:
        command = payload.get("action") or payload.get("command")
        if command is not None:
            return str(command)

        request_command = getattr(request, "command", None)
        return str(request_command) if request_command is not None else None

    def require_allowed_action(self, action: str | None) -> str:
        if action is None:
            raise AgentPayloadError(f"{type(self).__name__} requires an action")
        if self.allowed_actions and action not in self.allowed_actions:
            raise ValueError(f"{type(self).__name__} cannot handle action: {action}")
        return action

    def require_vault_path(self, payload: Payload) -> object:
        vault_path = payload.get("vault_path", self.vault_path)
        if vault_path is None:
            raise AgentPayloadError("agent request requires vault_path")
        return vault_path
