from __future__ import annotations

from dataclasses import asdict
from typing import Any

from segretario.agents.base import BaseAgent
from segretario.tools.search_tool import search_vault


class SearchMatches(list[dict[str, Any]]):
    def __getitem__(self, key: int | slice | str) -> Any:
        if key == "matches":
            return self
        return super().__getitem__(key)


class SearchAgent(BaseAgent):
    allowed_actions = frozenset({"search"})
    allowed_tools = frozenset({"SearchTool"})

    def run(self, request: object) -> SearchMatches:
        payload = self.payload(request)
        self.require_allowed_action(self.command(request, payload))
        results = search_vault(
            self.require_vault_path(payload),
            str(payload["query"]),
            include_self=bool(payload.get("include_self", False)),
            include_raw=bool(payload.get("include_raw", False)),
            skip_paths=_skip_paths(payload),
        )
        return SearchMatches(asdict(result) for result in results)


def _skip_paths(payload: dict[str, Any]) -> list[str]:
    value = payload.get("skip_paths")
    if isinstance(value, list):
        return [str(item) for item in value]
    return []
